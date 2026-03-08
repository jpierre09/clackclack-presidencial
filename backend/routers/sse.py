"""Server-Sent Events streaming endpoint."""
import json
import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from backend.services.event_bus import event_bus

router = APIRouter(tags=["sse"])


@router.get("/api/events")
async def event_stream():
    """SSE endpoint for real-time updates."""
    async def generate():
        yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"
        async for event in event_bus.subscribe():
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
