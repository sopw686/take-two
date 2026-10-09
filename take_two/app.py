"""FastAPI app: JSON API under /api, take audio under /takes, frontend at /."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from take_two import config, pipeline, takes
from take_two.config import Settings
from take_two.stt import audio_leaves_machine, get_transcriber

log = logging.getLogger("take_two")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Take Two", docs_url="/api/docs", redoc_url=None)

# The server is local-only. Reject foreign Host headers (DNS rebinding) and cross-site writes:
# a multipart POST needs no CORS preflight, so any web page could otherwise create takes or spend LLM credits.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))


@app.middleware("http")
async def _same_origin_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        host = urlsplit(origin).hostname or ""
        if host not in LOCAL_HOSTS and f"[{host}]" not in LOCAL_HOSTS:
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)


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
    from take_two.llm import llm_status
    return {
        "stt": get_transcriber().describe(),
        "audio_leaves_machine": audio_leaves_machine(),
        "llm": llm_status(),
        "defaults": Settings().model_dump(),
    }


@app.get("/api/sample")
async def sample() -> dict:
    return {"text": config.SAMPLE_SCRIPT.read_text(encoding="utf-8")}


async def _new_script_take(audio: UploadFile, script: str, settings: str | None, label: str) -> tuple[str, Settings]:
    """Validate a script take and create its folder (upload, script, settings) before any processing."""
    st = _parse_settings(settings)
    # Multipart form fields arrive with CRLF; on Windows write_text would turn that into \r\r\n in script.md.
    script = script.replace("\r\n", "\n")
    if not script.strip():
        raise HTTPException(400, "script is empty")
    data = await audio.read()
    if not data:
        raise HTTPException(400, "the recording is empty")
    take_id = takes.new_take("script", upload=data, original_name=audio.filename or "take.webm",
                             settings=st.model_dump(), label=label, script=script)
    return take_id, st


@app.post("/api/takes")
async def create_take(audio: UploadFile = File(...), script: str = Form(...), settings: str | None = Form(None),
                      label: str = Form("")) -> dict:
    take_id, st = await _new_script_take(audio, script, settings, label)
    return await process(take_id, st)


async def process(take_id: str, settings: Settings | None = None) -> dict:
    """Run pipeline.process_take in a worker thread; failures carry the take id so the client can retry."""
    try:
        return await run_in_threadpool(pipeline.process_take, take_id, None, settings)
    except takes.Busy:
        raise HTTPException(409, "this take is already being analyzed")
    except pipeline.TakeFailed as exc:
        raise HTTPException(500, detail={"message": exc.message, "take_id": take_id}) from exc


def _take_dir(take_id: str) -> Path:
    try:
        tdir = takes.take_path(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if not tdir.is_dir():
        raise HTTPException(404, "take not found")
    return tdir


class RetryBody(BaseModel):
    mode: Literal["script", "improv"] | None = None  # only needed for folders that saved neither
    script: str | None = None
    topic: str | None = None
    goal_s: float | None = None
    content: bool = False
    settings: Settings | None = None
    label: str | None = None


@app.post("/api/takes/{take_id}/retry")
async def retry_take(take_id: str, body: RetryBody | None = None) -> dict:
    """Run a failed take again from its saved upload, resuming at the first stage whose output is missing."""
    settings = _prepare_retry(take_id, body)
    return await process(take_id, settings)


def _prepare_retry(take_id: str, body: RetryBody | None) -> Settings | None:
    """Check a take can be retried and save whatever the retry adds (script, topic, settings, label)."""
    tdir = _take_dir(take_id)
    body = body or RetryBody()
    _check_retryable(take_id)
    meta = takes.load_meta(take_id)
    mode = meta.get("mode") or body.mode or ("improv" if body.topic else "script" if body.script else None)
    updates: dict = {"mode": mode}
    if mode == "script":
        if body.script is not None:
            script = body.script.replace("\r\n", "\n")
            if not script.strip():
                raise HTTPException(400, "script is empty")
            (tdir / "script.md").write_text(script, encoding="utf-8")
        elif not (tdir / "script.md").exists():
            raise HTTPException(400, "this take has no saved script; send the script to retry with")
    elif mode == "improv":
        if not (tdir / "improv.json").exists():
            from take_two.improv_routes import check_goal, clean_topic
            takes.save_json(tdir / "improv.json", {"topic": clean_topic(body.topic or ""), "goal_s": check_goal(body.goal_s),
                                                   "content": body.content})
    else:
        raise HTTPException(400, "this take saved neither a script nor a topic; send one to retry with")
    if body.settings is not None:
        updates["settings"] = body.settings.model_dump()
    if body.label is not None:
        updates["label"] = body.label
    takes.update_meta(take_id, **updates)
    return body.settings


def _check_retryable(take_id: str) -> None:
    st = takes.take_status(take_id)
    if st["status"] == "done":
        raise HTTPException(409, "this take is already analyzed")
    if takes.is_busy(take_id) or st["status"] == "processing":
        raise HTTPException(409, "this take is being analyzed right now")
    if not st["retryable"]:
        raise HTTPException(400, "the original recording is missing, so this take can only be deleted")


@app.delete("/api/takes/{take_id}")
async def delete_take(take_id: str) -> dict:
    tdir = _take_dir(take_id)
    if takes.is_busy(take_id):
        raise HTTPException(409, "this take is being analyzed right now")
    if (tdir / "analysis.json").exists():
        raise HTTPException(409, "only unfinished takes can be deleted")
    await run_in_threadpool(takes.delete_take, take_id)
    return {"deleted": take_id}


async def _new_drill(parent_id: str, audio: UploadFile, kind: str, index: int, settings: str | None) -> tuple[str, Settings]:
    _take_dir(parent_id)
    st = _parse_settings(settings)
    data = await audio.read()
    if not data:
        raise HTTPException(400, "the recording is empty")
    try:
        return pipeline.create_drill(parent_id, data, audio.filename or "drill.webm", kind, index, st), st
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/takes/{take_id}/drill")
async def create_drill(take_id: str, audio: UploadFile = File(...), kind: str = Form(...), index: int = Form(...),
                       settings: str | None = Form(None)) -> dict:
    """Record one line or section of a take's script; its rates are judged against that take's median."""
    drill_id, st = await _new_drill(take_id, audio, kind, index, settings)
    return await process(drill_id, st)


class ExampleBody(BaseModel):
    settings: Settings = Settings()


@app.post("/api/examples/{name}")
async def load_example(name: str, body: ExampleBody | None = None) -> dict:
    """A copy of a shipped example take, analyzed from its committed transcript (no microphone, no speech model)."""
    if name not in EXAMPLES:
        raise HTTPException(404, "no such example")
    settings = (body or ExampleBody()).settings
    try:
        return await run_in_threadpool(pipeline.create_example, name, settings)
    except pipeline.TakeFailed as exc:
        raise HTTPException(500, detail={"message": exc.message, "take_id": exc.take_id}) from exc


EXAMPLES = ("coral",)


class ReanalyzeBody(BaseModel):
    script: str | None = None  # None: keep the take's own script (e.g. a settings change)
    settings: Settings = Settings()
    label: str | None = None


@app.post("/api/takes/{take_id}/reanalyze")
async def reanalyze_take(take_id: str, body: ReanalyzeBody) -> dict:
    tdir = _take_dir(take_id)
    if not (tdir / "analysis.json").exists() or not (tdir / "transcript.json").exists():
        raise HTTPException(409, "this take has not been analyzed yet; retry it instead")
    if takes.is_busy(take_id):
        raise HTTPException(409, "this take is being analyzed right now")
    _reject_improv(take_id)
    if body.script is not None and takes.load_meta(take_id).get("kind") == "drill":
        raise HTTPException(400, "a drill keeps its own one-line script; re-analyze the full take instead")
    script = body.script
    if script is None:
        p = tdir / "script.md"
        if not p.exists():
            raise HTTPException(404, "take has no saved script")
        script = p.read_text(encoding="utf-8")
    return await run_in_threadpool(pipeline.reanalyze, take_id, script, body.settings, body.label)


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
    from take_two.coaching import coach
    from take_two.llm import get_llm
    try:
        data = takes.load_take(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if data is None:
        raise HTTPException(404, "take not found")
    _reject_improv(take_id, data)
    earlier = [a for a in takes.takes_with_same_script(take_id) if a.get("take_id") != take_id]
    coaching = await run_in_threadpool(coach, data, get_llm(), earlier)

    def attach(current: dict) -> dict | None:
        # A re-analysis may have finished while the model was answering; its numbers win.
        if current.get("settings") != data.get("settings") or current.get("script_key") != data.get("script_key"):
            return None
        current["coaching"] = coaching
        return current
    return (await run_in_threadpool(takes.update_analysis, take_id, attach)) or data


@app.get("/api/compare")
async def compare(take_id: str) -> dict:
    from take_two.compare import compare_takes
    try:
        _reject_improv(take_id)
        group = takes.takes_with_same_script(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if not group:
        raise HTTPException(404, "take not found")
    result = compare_takes(group)
    result["takes_info"] = [{"take_id": a["take_id"], "created_at": a.get("created_at"), "label": a.get("label", ""),
                             "audio_url": a.get("audio_url") or f"/takes/{a['take_id']}/audio.wav"} for a in group]
    return result


def _reject_improv(take_id: str, data: dict | None = None) -> None:
    """Script-take routes refuse Improvise takes, which have no script or marks."""
    data = data if data is not None else takes.load_take(take_id)
    if data and data.get("mode") == "improv":
        raise HTTPException(400, "this is an Improvise take; use /api/improv")


# ---- background jobs: the same work, with progress -----------------------------
# The synchronous endpoints above stay for scripts and tests; the page uses these and polls.

def _start_job(take_id: str, settings: Settings | None) -> dict:
    from take_two import jobs
    mode = takes.load_meta(take_id).get("mode") or "script"
    try:
        return jobs.submit(take_id, mode, lambda progress: pipeline.process_take(take_id, progress, settings))
    except takes.Busy:
        raise HTTPException(409, "this take is being analyzed right now")


@app.post("/api/jobs/takes")
async def create_take_job(audio: UploadFile = File(...), script: str = Form(...), settings: str | None = Form(None),
                          label: str = Form("")) -> dict:
    take_id, st = await _new_script_take(audio, script, settings, label)
    return _start_job(take_id, st)


@app.post("/api/jobs/improv")
async def create_improv_job(audio: UploadFile = File(...), topic: str = Form(...), goal_s: float | None = Form(None),
                            content: bool = Form(False), settings: str | None = Form(None), label: str = Form("")) -> dict:
    from take_two.improv_routes import new_improv_take
    take_id, st = await new_improv_take(audio, topic, goal_s, content, settings, label)
    return _start_job(take_id, st)


@app.post("/api/jobs/retry/{take_id}")
async def retry_job(take_id: str, body: RetryBody | None = None) -> dict:
    return _start_job(take_id, _prepare_retry(take_id, body))


@app.post("/api/jobs/drill/{take_id}")
async def drill_job(take_id: str, audio: UploadFile = File(...), kind: str = Form(...), index: int = Form(...),
                    settings: str | None = Form(None)) -> dict:
    drill_id, st = await _new_drill(take_id, audio, kind, index, settings)
    return _start_job(drill_id, st)


@app.get("/api/jobs/{take_id}")
async def job_status(take_id: str) -> dict:
    """{take_id, mode, status: queued | running | done | failed, stage, stages, error, result (the analysis, when done)}."""
    from take_two import jobs
    _take_dir(take_id)
    job = jobs.status(take_id)
    if job["status"] == "done":
        job["result"] = takes.load_take(take_id)
    return job


# ---- LLM features ------------------------------------------------------------
from take_two.suggest import router as suggest_router  # noqa: E402

app.include_router(suggest_router)

# ---- Improvise -----------------------------------------------------------------
from take_two.improv_routes import router as improv_router  # noqa: E402

app.include_router(improv_router)


# ---- frontend ------------------------------------------------------------------
if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    async def _no_frontend() -> str:
        return ("<h1>Take Two API is running</h1><p>The frontend has not been built. Run "
                "<code>./run.ps1</code> (or <code>./run.sh</code>), which builds it, "
                "or <code>cd frontend && npm run build</code>.</p><p>API docs: <a href='/api/docs'>/api/docs</a></p>")


@app.exception_handler(404)
async def _not_found(_, exc):  # type: ignore[no-untyped-def]
    return JSONResponse({"detail": getattr(exc, "detail", "not found")}, status_code=404)
