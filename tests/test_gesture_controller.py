from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.camera_support import CameraInitializationError
from tools.controller import CommandSender
from tools.gesture_controller import GestureState, classify_gesture, run, send_if_changed


@dataclass(frozen=True)
class Point:
    x: float
    y: float


class FakeConnection:
    def __init__(self) -> None:
        self.commands: list[bytes] = []

    def write(self, payload: bytes) -> int:
        self.commands.append(payload)
        return len(payload)

    def flush(self) -> None:
        pass


class FakeCapture:
    def __init__(self) -> None:
        self.released = False

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


def hand_with(index_tip: Point, folded: bool = True) -> list[Point]:
    points = [Point(0.5, 0.7) for _ in range(21)]
    index_mcp = Point(0.5, 0.5)
    points[0] = Point(0.5, 0.7)
    points[5] = index_mcp
    points[6] = Point(
        index_mcp.x + (index_tip.x - index_mcp.x) * 0.35,
        index_mcp.y + (index_tip.y - index_mcp.y) * 0.35,
    )
    points[8] = index_tip

    if folded:
        for pip_index, tip_index in ((10, 12), (14, 16), (18, 20)):
            points[pip_index] = Point(0.5, 0.45)
            points[tip_index] = Point(0.5, 0.5)
    else:
        for pip_index, tip_index in ((10, 12), (14, 16), (18, 20)):
            points[pip_index] = Point(0.5, 0.45)
            points[tip_index] = Point(0.5, 0.1)

    return points


def fist() -> list[Point]:
    points = hand_with(Point(0.5, 0.5))
    points[6] = Point(0.5, 0.45)
    points[8] = Point(0.5, 0.5)
    return points


def open_palm(finger_tip: Point) -> list[Point]:
    points = [Point(0.5, 0.7) for _ in range(21)]
    wrist = Point(0.5, 0.7)
    base = Point(0.5, 0.5)
    points[0] = wrist

    for mcp_index, pip_index, tip_index in (
        (5, 6, 8),
        (9, 10, 12),
        (13, 14, 16),
        (17, 18, 20),
    ):
        points[mcp_index] = base
        points[pip_index] = Point(
            base.x + (finger_tip.x - base.x) * 0.35,
            base.y + (finger_tip.y - base.y) * 0.35,
        )
        points[tip_index] = finger_tip

    return points


class GestureClassificationTests(unittest.TestCase):
    def test_index_up_is_forward(self) -> None:
        state = classify_gesture(hand_with(Point(0.5, 0.1)))

        self.assertEqual(state, GestureState("F", "forward"))

    def test_index_down_is_backward(self) -> None:
        state = classify_gesture(hand_with(Point(0.5, 0.95)))

        self.assertEqual(state, GestureState("B", "backward"))

    def test_index_left_is_left(self) -> None:
        state = classify_gesture(hand_with(Point(0.1, 0.5)))

        self.assertEqual(state, GestureState("L", "left"))

    def test_index_right_is_right(self) -> None:
        state = classify_gesture(hand_with(Point(0.9, 0.5)))

        self.assertEqual(state, GestureState("R", "right"))

    def test_open_palm_fingers_left_is_spin_left(self) -> None:
        state = classify_gesture(open_palm(Point(0.1, 0.5)))

        self.assertEqual(state, GestureState("A", "spin left"))

    def test_open_palm_fingers_right_is_spin_right(self) -> None:
        state = classify_gesture(open_palm(Point(0.9, 0.5)))

        self.assertEqual(state, GestureState("D", "spin right"))

    def test_open_palm_fingers_up_is_ignored(self) -> None:
        state = classify_gesture(open_palm(Point(0.5, 0.1)))

        self.assertIsNone(state)

    def test_open_palm_fingers_down_is_ignored(self) -> None:
        state = classify_gesture(open_palm(Point(0.5, 0.95)))

        self.assertIsNone(state)

    def test_fist_is_stop(self) -> None:
        state = classify_gesture(fist())

        self.assertEqual(state, GestureState("S", "stop"))

    def test_other_extended_fingers_are_ignored(self) -> None:
        state = classify_gesture(hand_with(Point(0.5, 0.1), folded=False))

        self.assertIsNone(state)

    def test_incomplete_landmarks_are_ignored(self) -> None:
        state = classify_gesture([Point(0.0, 0.0)])

        self.assertIsNone(state)


class SerialCommandTests(unittest.TestCase):
    def test_send_if_changed_skips_duplicate_command(self) -> None:
        connection = FakeConnection()
        sender = CommandSender(min_interval_seconds=0)

        with patch("tools.controller.send_command") as send, redirect_stdout(StringIO()):
            last_command = send_if_changed(
                connection,
                GestureState("F", "forward"),
                None,
                sender,
            )
            last_command = send_if_changed(
                connection,
                GestureState("F", "forward"),
                last_command,
                sender,
            )
            send_if_changed(
                connection,
                GestureState("S", "stop"),
                last_command,
                sender,
            )

        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            ["F", "S"],
        )

    def test_send_if_changed_stops_before_direction_change(self) -> None:
        connection = FakeConnection()
        sender = CommandSender()

        with patch("tools.controller.send_command") as send, redirect_stdout(StringIO()):
            last_command = send_if_changed(
                connection,
                GestureState("F", "forward"),
                None,
                sender,
            )
            last_command = send_if_changed(
                connection,
                GestureState("L", "left"),
                last_command,
                sender,
            )

        self.assertEqual(last_command, "L")
        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            ["F", "S", "L"],
        )

    def test_send_if_changed_stops_before_opposite_command(self) -> None:
        connection = FakeConnection()
        sender = CommandSender()

        with patch("tools.controller.send_command") as send, redirect_stdout(StringIO()):
            last_command = send_if_changed(
                connection,
                GestureState("F", "forward"),
                None,
                sender,
            )
            last_command = send_if_changed(
                connection,
                GestureState("B", "backward"),
                last_command,
                sender,
            )

        self.assertEqual(last_command, "B")
        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            ["F", "S", "B"],
        )


class GestureControllerStartupTests(unittest.TestCase):
    def test_tracker_startup_error_releases_camera(self) -> None:
        capture = FakeCapture()
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=capture))

        with (
            patch(
                "tools.gesture_controller.load_camera_dependencies",
                return_value=(cv2, object()),
            ),
            patch(
                "tools.gesture_controller.create_hand_tracker",
                side_effect=CameraInitializationError("model path failed"),
            ),
        ):
            with self.assertRaisesRegex(
                CameraInitializationError,
                "model path failed",
            ):
                run(
                    port="unused",
                    camera=0,
                    lost_timeout=0.5,
                    preview=False,
                    config_path=Path("missing-test-config.json"),
                )

        self.assertTrue(capture.released)


if __name__ == "__main__":
    unittest.main()
