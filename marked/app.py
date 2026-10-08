"""FastAPI app: JSON API under /api, take audio under /takes, frontend at /."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from marked import config, pipeline, takes
from marked.config import Settings
from marked.stt import audio_leaves_machine, get_transcriber

log = logging.getLogger("marked")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Marked", docs_url="/api/docs", redoc_url=None)


def _parse_settings(raw: str | None) -> Settings:
    if not raw:
        return Settings()
    try:
        return Settings.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f"bad settings: {exc}") from exc


@app.on_event("startup")
async def _warm() -> None:
    # Load the local model in the background so the first take doesn't pay for it.
    import asyncio

    async def _load() -> None:
        try:
            await run_in_threadpool(get_transcriber().load)  # type: ignore[attr-defined]
            log.info("STT ready: %s", get_transcriber().describe())
        except Exception as exc:
            log.warning("STT warm-up failed: %s", exc)

    asyncio.create_task(_load())


@app.get("/api/health")
async def health() -> dict:
    from marked.llm import llm_status
    return {
        "stt": get_transcriber().describe(),
        "audio_leaves_machine": audio_leaves_machine(),
        "llm": llm_status(),
        "defaults": Settings().model_dump(),
    }


@app.get("/api/sample")
async def sample() -> dict:
    return {"text": config.SAMPLE_SCRIPT.read_text(encoding="utf-8")}


@app.post("/api/takes")
async def create_take(audio: UploadFile = File(...), script: str = Form(...), settings: str | None = Form(None),
                      label: str = Form("")) -> dict:
    st = _parse_settings(settings)
    if not script.strip():
        raise HTTPException(400, "script is empty")
    suffix = Path(audio.filename or "").suffix or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = Path(tmp.name)
    try:
        return await run_in_threadpool(pipeline.run_take, tmp_path, script, st, label, audio.filename or "")
    except Exception as exc:
        log.exception("take failed")
        raise HTTPException(500, f"analysis failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


class ReanalyzeBody(BaseModel):
    script: str
    settings: Settings = Settings()
    label: str | None = None


@app.post("/api/takes/{take_id}/reanalyze")
async def reanalyze_take(take_id: str, body: ReanalyzeBody) -> dict:
    try:
        tdir = takes.take_path(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if not (tdir / "transcript.json").exists():
        raise HTTPException(404, "take not found")
    return await run_in_threadpool(pipeline.reanalyze, take_id, body.script, body.settings, body.label)


@app.get("/api/takes")
async def list_takes() -> list[dict]:
    return takes.list_takes()


@app.get("/api/takes/{take_id}")
async def get_take(take_id: str) -> dict:
    try:
        data = takes.load_take(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if data is None:
        raise HTTPException(404, "take not found")
    return data


@app.get("/takes/{take_id}/audio.wav")
async def take_audio(take_id: str) -> FileResponse:
    try:
        p = takes.take_path(take_id) / "audio.wav"
    except ValueError:
        raise HTTPException(400, "bad take id")
    if not p.exists():
        raise HTTPException(404, "audio not found")
    return FileResponse(p, media_type="audio/wav")


@app.post("/api/takes/{take_id}/coach")
async def coach_take(take_id: str) -> dict:
    from marked.coaching import coach
    from marked.llm import get_llm
    try:
        data = takes.load_take(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if data is None:
        raise HTTPException(404, "take not found")
    earlier = [a for a in takes.takes_with_same_script(take_id) if a.get("take_id") != take_id]
    data["coaching"] = await run_in_threadpool(coach, data, get_llm(), earlier)
    takes.save_json(takes.take_path(take_id) / "analysis.json", data)
    return data


@app.get("/api/compare")
async def compare(take_id: str) -> dict:
    from marked.compare import compare_takes
    try:
        group = takes.takes_with_same_script(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if not group:
        raise HTTPException(404, "take not found")
    result = compare_takes(group)
    result["takes_info"] = [{"take_id": a["take_id"], "created_at": a.get("created_at"), "label": a.get("label", "")} for a in group]
    return result


# ---- LLM features ------------------------------------------------------------
from marked.suggest import router as suggest_router  # noqa: E402

app.include_router(suggest_router)


# ---- frontend ------------------------------------------------------------------
if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    async def _no_frontend() -> str:
        return ("<h1>Marked API is running</h1><p>The frontend has not been built. Run "
                "<code>./run.ps1</code> (or <code>./run.sh</code>), which builds it, "
                "or <code>cd frontend && npm run build</code>.</p><p>API docs: <a href='/api/docs'>/api/docs</a></p>")


@app.exception_handler(404)
async def _not_found(_, exc):  # type: ignore[no-untyped-def]
    return JSONResponse({"detail": getattr(exc, "detail", "not found")}, status_code=404)
