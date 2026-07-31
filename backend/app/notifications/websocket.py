"""In-process broadcaster for WebSocket fan-out (C.4-C.6).

WebSocket clients subscribe to channels (e.g. ``org:{org_id}``,
``user:{user_id}``). Code anywhere in the app calls ``broadcast(channel,
event)`` to push events to subscribers.

Single-replica: in-process dict {channel: [queues]}.
Multi-replica: stub here — production would back this with Redis pub/sub
(``broadcaster`` library or raw ``redis.asyncio``).

Event format sent over the wire:
    {"event": "task.created", "task": {...}, "channel": "org:abc"}
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, AsyncIterator


logger = logging.getLogger(__name__)


class Broadcaster:
    """In-process pub/sub for WebSocket fan-out."""

    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        """Async-iterate over events on ``channel``.

        Yields one event dict per ``broadcast()`` call. The subscriber
        is automatically unsubscribed when the generator is closed.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._channels[channel].add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                self._channels[channel].discard(queue)
                if not self._channels[channel]:
                    self._channels.pop(channel, None)

    async def broadcast(self, channel: str, event: dict[str, Any]) -> int:
        """Push an event to every subscriber on ``channel``.

        Returns the number of subscribers that received the event.
        """
        delivered = 0
        async with self._lock:
            queues = list(self._channels.get(channel, set()))
        for q in queues:
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Slow subscriber — drop the event for them
                logger.warning("Dropping event for slow subscriber on %s", channel)
        return delivered

    async def channel_size(self, channel: str) -> int:
        async with self._lock:
            return len(self._channels.get(channel, set()))


# Module-level singleton
_broadcaster: Broadcaster | None = None


def get_broadcaster() -> Broadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = Broadcaster()
    return _broadcaster


def reset_for_tests() -> None:
    global _broadcaster
    _broadcaster = None


def serialize_event(event: dict[str, Any]) -> str:
    """JSON-encode an event for WebSocket transmission."""
    return json.dumps(event, default=str)