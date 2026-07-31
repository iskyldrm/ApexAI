"""WebSocket endpoint for live updates (C.4-C.6)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from app.deps import get_current_user
from app.notifications.websocket import get_broadcaster


logger = logging.getLogger(__name__)


router = APIRouter(tags=["notifications"])


@router.websocket("/ws/tasks")
async def ws_tasks(
    websocket: WebSocket,
    token: str = Query(..., description="JWT for auth"),
    org_id: str | None = Query(None, description="Org to subscribe to"),
) -> None:
    """Live task events. Subscribes to ``org:{org_id}`` + ``user:{user_id}``.

    Authentication: JWT in query string (browsers can't set headers on WS).
    The server validates the token on connect; unauthorized sockets are
    closed with code 1008.
    """
    # Authenticate: decode the JWT manually since WS doesn't use Depends
    try:
        from app.core.security import decode_token

        claims = decode_token(token)
    except Exception as e:
        logger.warning("WS auth failed: %s", e)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = claims.get("sub")
    org_id = org_id or claims.get("active_org_id") or claims.get("org_id")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    broadcaster = get_broadcaster()
    channels = []
    if org_id:
        channels.append(f"org:{org_id}")
    channels.append(f"user:{user_id}")

    # Subscribe to each channel concurrently and forward to the WS
    async def forward(channel: str):
        try:
            async for event in broadcaster.subscribe(channel):
                await websocket.send_json(event)
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.exception("Forwarder for %s failed: %s", channel, e)

    import asyncio

    tasks = [asyncio.create_task(forward(ch)) for ch in channels]
    try:
        # Keep the connection alive until the client disconnects.
        # We block on a future that completes when any forwarder exits.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            t.result()  # raises if the task errored (e.g. WebSocketDisconnect)
    except WebSocketDisconnect:
        logger.info("WS disconnected user=%s", user_id)
    finally:
        for t in tasks:
            t.cancel()