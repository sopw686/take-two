"""Script import: PowerPoint speaker notes -> script text. Mounted at /api/import.

Nothing is stored: the client puts the returned text into the Script editor, where the
speaker reviews it and fills in budgets.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from take_two import pptx_import

router = APIRouter(prefix="/api/import")


@router.post("/pptx")
async def import_pptx(file: UploadFile = File(...)) -> dict:
    """{text: script with one `## Slide N: title` section per slide, slides: slide count}."""
    limit = pptx_import.MAX_UPLOAD_BYTES
    if file.size is not None and file.size > limit:
        raise HTTPException(400, pptx_import.too_large_message())
    data = await file.read(limit + 1)  # never more than the limit in memory
    if len(data) > limit:
        raise HTTPException(400, pptx_import.too_large_message())
    try:
        text, slides = await run_in_threadpool(pptx_import.notes_to_script, data)
    except pptx_import.PptxError as exc:
        raise HTTPException(400, exc.message) from exc
    return {"text": text, "slides": slides}
