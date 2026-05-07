import asyncio
import json
import logging
import os
import threading
from functools import partial
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from models import Draft
from pipeline import generate_story, apply_user_tweak, PipelineCancelled
from utils import estimate_reading_time


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


HERE = Path(__file__).parent
FRONTEND_DIR = HERE.parent / "frontend"

# Single user-facing error string. Real exception details are logged
# server-side (see _safe_runner) but never echoed to the browser.
GENERIC_ERROR = "The storyteller hit a snag — please try again in a moment."

app = FastAPI(title="Bedtime")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Unique end-of-stream sentinel. Using an object() rather than a string like
# "_done" means it can't ever collide with a payload type emitted by the
# pipeline, even by accident.
_STREAM_DONE = object()


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


class GenerateIn(BaseModel):
    input: str = Field(min_length=1, max_length=2000)


class TweakIn(BaseModel):
    # 6000 chars is comfortably above the largest expected story (~750 words
    # ≈ 4500 chars) but small enough to limit prompt-injection surface.
    story: str = Field(min_length=1, max_length=6000)
    request: str = Field(min_length=1, max_length=2000)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _emit_factory(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
    """Build an `on_event` callback that the (sync) pipeline can call from a
    worker thread. Crosses the thread boundary via call_soon_threadsafe."""

    def emit(stage: str, payload: dict) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "stage", "stage": stage, "payload": payload},
        )

    return emit


RunnerFn = Callable[[asyncio.Queue, threading.Event], Awaitable[None]]


async def _stream(runner: RunnerFn) -> AsyncIterator[str]:
    """Run `runner` as a background task; yield queued events as SSE.

    On consumer disconnect (StreamingResponse cancels this generator), we set
    the cancel event and cancel the task. The pipeline cooperates by checking
    the cancel flag between LLM calls, so further calls don't start.
    """
    queue: asyncio.Queue = asyncio.Queue()
    cancel_event = threading.Event()
    task = asyncio.create_task(runner(queue, cancel_event))

    try:
        while True:
            msg = await queue.get()
            if msg is _STREAM_DONE:
                break
            yield _sse(msg)
    finally:
        cancel_event.set()
        task.cancel()


async def _safe_runner(
    work_label: str,
    coro_factory: Callable[[], Awaitable[dict]],
    queue: asyncio.Queue,
) -> None:
    """Run `coro_factory()` and put the resulting payload on the queue.

    Translates exceptions:
      - PipelineCancelled / CancelledError → silent (client gone)
      - anything else → logged in full, generic message sent to client
    Always emits the `_done` sentinel.
    """
    try:
        payload = await coro_factory()
        await queue.put(payload)
    except (PipelineCancelled, asyncio.CancelledError):
        pass
    except Exception:
        logger.exception("%s failed", work_label)
        await queue.put({"type": "error", "message": GENERIC_ERROR})
    finally:
        await queue.put(_STREAM_DONE)


async def _generate_runner(
    user_input: str, queue: asyncio.Queue, cancel_event: threading.Event,
) -> None:
    loop = asyncio.get_running_loop()
    emit = _emit_factory(loop, queue)

    async def work() -> dict:
        draft, report, _req = await asyncio.to_thread(
            generate_story,
            user_input,
            on_event=emit,
            is_cancelled=cancel_event.is_set,
        )
        return {
            "type": "story",
            "text": draft.text,
            "reading_time": estimate_reading_time(draft.text),
            "iterations": draft.iteration,
            "passed": report.passing(),
        }

    await _safe_runner("generate_story", work, queue)


async def _tweak_runner(
    story: str,
    user_request: str,
    queue: asyncio.Queue,
    cancel_event: threading.Event,
) -> None:
    loop = asyncio.get_running_loop()
    emit = _emit_factory(loop, queue)

    async def work() -> dict:
        new_draft, report = await asyncio.to_thread(
            apply_user_tweak,
            Draft(text=story),
            user_request,
            on_event=emit,
            is_cancelled=cancel_event.is_set,
        )
        return {
            "type": "story",
            "text": new_draft.text,
            "reading_time": estimate_reading_time(new_draft.text),
            "iterations": new_draft.iteration,
            "passed": report.passing(),
        }

    await _safe_runner("apply_user_tweak", work, queue)


@app.post("/api/generate")
async def api_generate(payload: GenerateIn) -> StreamingResponse:
    return StreamingResponse(
        _stream(partial(_generate_runner, payload.input)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/tweak")
async def api_tweak(payload: TweakIn) -> StreamingResponse:
    return StreamingResponse(
        _stream(partial(_tweak_runner, payload.story, payload.request)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def run() -> None:
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    run()
