from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(order=True)
class Event:
    t: float
    kind: str = field(compare=False)
    data: dict[str, Any] = field(default_factory=dict, compare=False)


class EventLoop:
    def __init__(self) -> None:
        self._queue: list[Event] = []
        self._time = 0.0

    @property
    def now(self) -> float:
        return self._time

    def schedule(self, event: Event) -> None:
        heapq.heappush(self._queue, event)

    def run(self) -> Iterator[Event]:
        while self._queue:
            event = heapq.heappop(self._queue)
            self._time = event.t
            yield event
