from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tools.gesture_config import GestureConfig
from tools.gesture_configurator import GestureConfiguratorWindow


class GestureConfiguratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_action_list_preserves_user_order_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = GestureConfiguratorWindow(
                GestureConfig(),
                Path(directory) / "gestures.json",
                0,
                start_camera=False,
            )
            window._append_action("F")
            window._append_action("F")
            window._append_action("L")

            self.assertEqual(window._actions_from_editor(), ("F", "F", "L"))
            window.close()


if __name__ == "__main__":
    unittest.main()
