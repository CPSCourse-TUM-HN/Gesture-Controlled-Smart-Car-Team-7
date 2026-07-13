from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from tools.gesture_config import ACTION_NAMES, GestureTemplate


class Sender(Protocol):
    @property
    def last_command(self) -> str | None: ...

    def send(self, connection: object, command: str, *, force: bool = False) -> bool: ...

    def send_nonblocking(
        self,
        connection: object,
        command: str,
        *,
        force: bool = False,
    ) -> bool: ...


@dataclass(frozen=True)
class SequenceStatus:
    gesture_name: str
    step_number: int
    step_count: int
    command: str
    action_name: str


class ActionSequenceRunner:
    def __init__(
        self,
        step_duration_seconds: float,
        clock=time.monotonic,
    ) -> None:
        self._step_duration_seconds = step_duration_seconds
        self._clock = clock
        self._gesture: GestureTemplate | None = None
        self._step_index = 0
        self._current_step_index: int | None = None
        self._next_step_at: float | None = None

    @property
    def active(self) -> bool:
        return self._gesture is not None

    @property
    def status(self) -> SequenceStatus | None:
        if self._gesture is None:
            return None
        display_index = self._current_step_index
        if display_index is None:
            display_index = 0
        command = self._gesture.actions[display_index]
        return SequenceStatus(
            gesture_name=self._gesture.name,
            step_number=display_index + 1,
            step_count=len(self._gesture.actions),
            command=command,
            action_name=ACTION_NAMES[command],
        )

    def start(self, gesture: GestureTemplate, now: float | None = None) -> None:
        if self.active:
            raise RuntimeError("an action sequence is already running")
        self._gesture = gesture
        self._step_index = 0
        self._current_step_index = None
        self._next_step_at = self._clock() if now is None else now

    def tick(
        self,
        connection: object,
        sender: Sender,
        now: float | None = None,
    ) -> bool:
        if self._gesture is None:
            return False

        current_time = self._clock() if now is None else now
        if self._next_step_at is not None and current_time < self._next_step_at:
            return False

        if self._step_index >= len(self._gesture.actions):
            sender.send(connection, "S", force=True)
            self._clear()
            return True

        command = self._gesture.actions[self._step_index]
        ready = sender.send_nonblocking(
            connection,
            command,
            force=command == "S",
        )
        if not ready:
            return False

        self._current_step_index = self._step_index
        self._step_index += 1
        self._next_step_at = self._clock() + self._step_duration_seconds
        return True

    def cancel(self, connection: object, sender: Sender) -> bool:
        was_active = self.active
        sender.send(connection, "S", force=True)
        self._clear()
        return was_active

    def _clear(self) -> None:
        self._gesture = None
        self._step_index = 0
        self._current_step_index = None
        self._next_step_at = None
