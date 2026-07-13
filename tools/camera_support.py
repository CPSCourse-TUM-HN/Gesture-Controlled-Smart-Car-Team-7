from __future__ import annotations

import os
from pathlib import Path
from types import ModuleType
from typing import Any


class CameraInitializationError(RuntimeError):
    """A camera or hand-tracker startup failure safe to show to users."""


def load_camera_dependencies() -> tuple[ModuleType, ModuleType]:
    try:
        import cv2
        import mediapipe as mp
    except ImportError as exc:
        raise CameraInitializationError(
            "Camera dependencies are unavailable. Install the project "
            "dependencies with `uv sync --frozen`."
        ) from exc
    return cv2, mp


def _mediapipe_installation_path(mediapipe_module: Any) -> Path | None:
    module_file = getattr(mediapipe_module, "__file__", None)
    if not module_file:
        return None
    return Path(module_file).resolve().parent


def create_hand_tracker(mediapipe_module: Any) -> Any:
    try:
        return mediapipe_module.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
    except FileNotFoundError as exc:
        installation_path = _mediapipe_installation_path(mediapipe_module)
        if (
            os.name == "nt"
            and installation_path is not None
            and not str(installation_path).isascii()
        ):
            raise CameraInitializationError(
                "MediaPipe could not load its hand-tracking models from the "
                f"non-ASCII installation path '{installation_path}'. Recreate "
                "the virtual environment in an ASCII-only directory by "
                "setting UV_PROJECT_ENVIRONMENT, then run `uv sync --frozen`. "
                "See the Windows camera setup in README.md."
            ) from exc
        raise CameraInitializationError(
            f"MediaPipe could not load its hand-tracking models: {exc}"
        ) from exc
    except Exception as exc:
        raise CameraInitializationError(
            f"Could not initialize MediaPipe hand tracking: {exc}"
        ) from exc
