from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tools.gesture_config import GestureConfig
from tools.camera_support import CameraInitializationError
from tools.gesture_configurator import CameraWorker, GestureConfiguratorWindow


class FakeCapture:
    def __init__(self, *, opened: bool = True, read_ok: bool = False) -> None:
        self.opened = opened
        self.read_ok = read_ok
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, object | None]:
        return self.read_ok, None

    def release(self) -> None:
        self.released = True


class FakeHands:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class GestureConfiguratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_action_list_preserves_user_order_and_duplicates(self) -> None:
        window = GestureConfiguratorWindow(
            GestureConfig(),
            Path("unused-test-gestures.json"),
            0,
            start_camera=False,
        )
        window._append_action("F")
        window._append_action("F")
        window._append_action("L")

        self.assertEqual(window._actions_from_editor(), ("F", "F", "L"))
        window._editor_dirty = False
        window.close()

    def test_worker_reports_tracker_startup_error_and_releases_camera(self) -> None:
        capture = FakeCapture()
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=capture))
        worker = CameraWorker(0)
        errors: list[str] = []
        worker.error.connect(errors.append)

        with (
            patch(
                "tools.gesture_configurator.load_camera_dependencies",
                return_value=(cv2, object()),
            ),
            patch(
                "tools.gesture_configurator.create_hand_tracker",
                side_effect=CameraInitializationError("model path failed"),
            ),
        ):
            worker.run()

        self.assertEqual(errors, ["model path failed"])
        self.assertTrue(capture.released)

    def test_worker_closes_tracker_and_releases_camera_on_read_error(self) -> None:
        capture = FakeCapture(read_ok=False)
        hands = FakeHands()
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=capture))
        worker = CameraWorker(0)
        errors: list[str] = []
        worker.error.connect(errors.append)

        with (
            patch(
                "tools.gesture_configurator.load_camera_dependencies",
                return_value=(cv2, object()),
            ),
            patch(
                "tools.gesture_configurator.create_hand_tracker",
                return_value=hands,
            ),
        ):
            worker.run()

        self.assertEqual(errors, ["Could not read from the camera."])
        self.assertTrue(hands.closed)
        self.assertTrue(capture.released)


if __name__ == "__main__":
    unittest.main()
