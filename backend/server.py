import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from models import Draft
from pipeline import generate_story, apply_user_tweak
from utils import estimate_reading_time


HERE = Path(__file__).parent
FRONTEND_DIR = HERE.parent / "frontend"

app = FastAPI(title="Bedtime")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


class GenerateIn(BaseModel):
    input: str = Field(min_length=1, max_length=2000)


class TweakIn(BaseModel):
    story: str = Field(min_length=1, max_length=20000)
    request: str = Field(min_length=1, max_length=2000)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _generate_stream(user_input: str) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(stage: str, payload: dict) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "stage", "stage": stage, "payload": payload}
        )

    async def runner() -> None:
        try:
            draft, report, _req = await asyncio.to_thread(
                generate_story, user_input, emit
            )
            await queue.put(
                {
                    "type": "story",
                    "text": draft.text,
                    "reading_time": estimate_reading_time(draft.text),
                    "iterations": draft.iteration,
                    "passed": report.passing(),
                }
            )
        except Exception as e:
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put({"type": "_done"})

    asyncio.create_task(runner())

    while True:
        msg = await queue.get()
        if msg.get("type") == "_done":
            break
        yield _sse(msg)


async def _tweak_stream(story: str, user_request: str) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()

    async def runner() -> None:
        try:
            await queue.put({"type": "stage", "stage": "tweak_start", "payload": {}})
            new_draft = await asyncio.to_thread(
                apply_user_tweak, Draft(text=story), user_request
            )
            await queue.put(
                {
                    "type": "story",
                    "text": new_draft.text,
                    "reading_time": estimate_reading_time(new_draft.text),
                }
            )
        except Exception as e:
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put({"type": "_done"})

    asyncio.create_task(runner())

    while True:
        msg = await queue.get()
        if msg.get("type") == "_done":
            break
        yield _sse(msg)


@app.post("/api/generate")
async def api_generate(payload: GenerateIn) -> StreamingResponse:
    return StreamingResponse(
        _generate_stream(payload.input),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/tweak")
async def api_tweak(payload: TweakIn) -> StreamingResponse:
    return StreamingResponse(
        _tweak_stream(payload.story, payload.request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def run() -> None:
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    run()
