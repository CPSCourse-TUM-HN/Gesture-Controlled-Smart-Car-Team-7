from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from tools.controller import CommandSender
from tools.custom_gestures import (
    GestureMatch,
    GestureTrigger,
    LandmarkLike,
    find_matching_gesture,
    is_fist_pose,
    normalize_landmarks,
)
from tools.gesture_config import GestureConfig
from tools.gesture_sequence import ActionSequenceRunner, SequenceStatus


class _TestClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def set(self, now: float) -> None:
        self.now = max(self.now, now)

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass(frozen=True)
class SerialTestUpdate:
    match: GestureMatch | None
    sequence: SequenceStatus | None
    armed: bool
    new_bytes: tuple[bytes, ...]


class SerialOutputTester:
    """Exercise the gesture-to-command pipeline without opening a serial port."""

    def __init__(self, config: GestureConfig) -> None:
        self._config = config
        self._clock = _TestClock()
        self._output: list[bytes] = []
        self._connection = object()
        self._sender = CommandSender(
            clock=self._clock,
            sleeper=self._clock.sleep,
            command_writer=self._record_command,
        )
        self._trigger = GestureTrigger(clock=self._clock)
        self._sequence = ActionSequenceRunner(
            config.step_duration_seconds,
            clock=self._clock,
        )

    @property
    def output(self) -> tuple[bytes, ...]:
        return tuple(self._output)

    def _record_command(self, _connection: object, command: str) -> None:
        self._output.append(command.encode("ascii"))

    def process(
        self,
        landmarks: Iterable[LandmarkLike] | None,
        handedness: str | None,
        now: float,
    ) -> SerialTestUpdate:
        self._clock.set(now)
        output_start = len(self._output)
        points = list(landmarks) if landmarks is not None else None
        match = None

        if points is not None and handedness is not None:
            try:
                features = normalize_landmarks(points)
            except ValueError:
                features = None
            if features is not None:
                match = find_matching_gesture(
                    features,
                    handedness,
                    self._config.gestures,
                )

        emergency_stop = points is not None and is_fist_pose(points)
        if emergency_stop:
            if self._sequence.active:
                self._sequence.cancel(self._connection, self._sender)
            elif self._sender.last_command != "S":
                self._sender.send(self._connection, "S", force=True)
            self._trigger.update(None, self._clock())
        elif self._sequence.active:
            self._trigger.update(
                match.gesture.id if match is not None else None,
                self._clock(),
            )
            self._sequence.tick(self._connection, self._sender, self._clock())
        elif match is not None:
            triggered_id = self._trigger.update(
                match.gesture.id,
                self._clock(),
            )
            if triggered_id is not None:
                self._sequence.start(match.gesture, self._clock())
                self._sequence.tick(
                    self._connection,
                    self._sender,
                    self._clock(),
                )
        else:
            self._trigger.update(None, self._clock())

        return SerialTestUpdate(
            match=match,
            sequence=self._sequence.status,
            armed=self._trigger.armed,
            new_bytes=tuple(self._output[output_start:]),
        )
