from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.camera_support import CameraInitializationError, create_hand_tracker


def fake_mediapipe(hands_factory: Mock, module_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        __file__=module_file,
        solutions=SimpleNamespace(
            hands=SimpleNamespace(Hands=hands_factory),
        ),
    )


class HandTrackerInitializationTests(unittest.TestCase):
    def test_creates_hand_tracker_with_expected_settings(self) -> None:
        tracker = object()
        hands_factory = Mock(return_value=tracker)
        mediapipe = fake_mediapipe(
            hands_factory,
            "C:/venvs/gcsc/Lib/site-packages/mediapipe/__init__.py",
        )

        self.assertIs(create_hand_tracker(mediapipe), tracker)
        hands_factory.assert_called_once_with(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

    def test_non_ascii_windows_installation_has_actionable_error(self) -> None:
        hands_factory = Mock(
            side_effect=FileNotFoundError("hand_landmark_tracking_cpu.binarypb")
        )
        mediapipe = fake_mediapipe(
            hands_factory,
            "C:/Users/张越扬/project/.venv/Lib/site-packages/mediapipe/__init__.py",
        )

        with patch("tools.camera_support.os.name", "nt"):
            with self.assertRaisesRegex(
                CameraInitializationError,
                "ASCII-only directory",
            ) as caught:
                create_hand_tracker(mediapipe)

        self.assertIn("UV_PROJECT_ENVIRONMENT", str(caught.exception))

    def test_missing_model_on_ascii_path_preserves_original_detail(self) -> None:
        hands_factory = Mock(side_effect=FileNotFoundError("missing.binarypb"))
        mediapipe = fake_mediapipe(
            hands_factory,
            "C:/venvs/gcsc/Lib/site-packages/mediapipe/__init__.py",
        )

        with self.assertRaisesRegex(
            CameraInitializationError,
            "missing.binarypb",
        ):
            create_hand_tracker(mediapipe)

    def test_other_initialization_error_is_wrapped(self) -> None:
        hands_factory = Mock(side_effect=ValueError("invalid graph"))
        mediapipe = fake_mediapipe(
            hands_factory,
            "C:/venvs/gcsc/Lib/site-packages/mediapipe/__init__.py",
        )

        with self.assertRaisesRegex(
            CameraInitializationError,
            "invalid graph",
        ):
            create_hand_tracker(mediapipe)


if __name__ == "__main__":
    unittest.main()
