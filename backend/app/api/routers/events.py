import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.core.broadcaster import broadcaster

router = APIRouter()

@router.get("/sync")
async def sync_events():
    async def event_generator():
        queue = await broadcaster.subscribe()
        try:
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
