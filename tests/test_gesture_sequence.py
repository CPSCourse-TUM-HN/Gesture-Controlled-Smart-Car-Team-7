from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.controller import CommandSender
from tools.gesture_config import GestureTemplate
from tools.gesture_sequence import ActionSequenceRunner


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def gesture(actions: tuple[str, ...]) -> GestureTemplate:
    return GestureTemplate(
        id="route",
        name="Route",
        handedness="Right",
        features=(0.0,) * 42,
        match_threshold=0.2,
        actions=actions,
    )


class ActionSequenceRunnerTests(unittest.TestCase):
    def test_sequence_uses_uniform_steps_and_stops_at_end(self) -> None:
        clock = FakeClock()
        sender = CommandSender(
            min_interval_seconds=0.2,
            reversal_stop_seconds=0.3,
            clock=clock,
            sleeper=clock.sleep,
        )
        runner = ActionSequenceRunner(1.0, clock=clock)
        runner.start(gesture(("F", "F", "L", "S")))

        with patch("tools.controller.send_command") as send:
            self.assertTrue(runner.tick("connection", sender))
            self.assertEqual(runner.status.action_name, "Forward")

            clock.now = 0.9
            self.assertFalse(runner.tick("connection", sender))

            clock.now = 1.0
            self.assertTrue(runner.tick("connection", sender))

            clock.now = 2.0
            self.assertFalse(runner.tick("connection", sender))
            self.assertEqual(clock.now, 2.0)

            clock.now = 2.3
            self.assertTrue(runner.tick("connection", sender))

            clock.now = 3.3
            self.assertTrue(runner.tick("connection", sender))

            clock.now = 4.3
            self.assertTrue(runner.tick("connection", sender))

        self.assertFalse(runner.active)
        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            ["F", "S", "L", "S", "S"],
        )

    def test_cancel_forces_stop_and_clears_sequence(self) -> None:
        clock = FakeClock()
        sender = CommandSender(
            min_interval_seconds=0,
            clock=clock,
            sleeper=clock.sleep,
        )
        runner = ActionSequenceRunner(1.0, clock=clock)
        runner.start(gesture(("B", "D")))

        with patch("tools.controller.send_command") as send:
            runner.tick("connection", sender)
            was_active = runner.cancel("connection", sender)

        self.assertTrue(was_active)
        self.assertFalse(runner.active)
        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            ["B", "S"],
        )

    def test_new_sequence_cannot_replace_active_sequence(self) -> None:
        runner = ActionSequenceRunner(1.0)
        runner.start(gesture(("F",)))

        with self.assertRaisesRegex(RuntimeError, "already running"):
            runner.start(gesture(("B",)))


if __name__ == "__main__":
    unittest.main()
