from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CONFIG_VERSION = 1
DEFAULT_STEP_DURATION_SECONDS = 1.0
MIN_STEP_DURATION_SECONDS = 0.1
MAX_STEP_DURATION_SECONDS = 10.0
FEATURE_COUNT = 42
HANDEDNESSES = frozenset({"Left", "Right"})

ACTION_NAMES = {
    "F": "Forward",
    "B": "Backward",
    "L": "Steer Left",
    "R": "Steer Right",
    "A": "Spin Left",
    "D": "Spin Right",
    "S": "Stop",
}
ALLOWED_ACTIONS = frozenset(ACTION_NAMES)


class GestureConfigError(RuntimeError):
    """Raised when a gesture configuration cannot be loaded or validated."""


def default_config_path() -> Path:
    return Path.home() / ".gcsc" / "gesture-config.json"


DEFAULT_CONFIG_PATH = default_config_path()


@dataclass(frozen=True)
class GestureTemplate:
    id: str
    name: str
    handedness: str
    features: tuple[float, ...]
    match_threshold: float
    actions: tuple[str, ...]


@dataclass(frozen=True)
class GestureConfig:
    version: int = CONFIG_VERSION
    step_duration_seconds: float = DEFAULT_STEP_DURATION_SECONDS
    gestures: tuple[GestureTemplate, ...] = field(default_factory=tuple)


def _as_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GestureConfigError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise GestureConfigError(f"{field_name} must be finite")
    return number


def _parse_template(data: Any, index: int) -> GestureTemplate:
    field_prefix = f"gestures[{index}]"
    if not isinstance(data, dict):
        raise GestureConfigError(f"{field_prefix} must be an object")

    gesture_id = data.get("id")
    if not isinstance(gesture_id, str) or not gesture_id.strip():
        raise GestureConfigError(f"{field_prefix}.id must be a non-empty string")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise GestureConfigError(f"{field_prefix}.name must be a non-empty string")

    handedness = data.get("handedness")
    if handedness not in HANDEDNESSES:
        raise GestureConfigError(
            f"{field_prefix}.handedness must be Left or Right"
        )

    raw_features = data.get("features")
    if not isinstance(raw_features, list) or len(raw_features) != FEATURE_COUNT:
        raise GestureConfigError(
            f"{field_prefix}.features must contain {FEATURE_COUNT} numbers"
        )
    features = tuple(
        _as_number(value, f"{field_prefix}.features[{feature_index}]")
        for feature_index, value in enumerate(raw_features)
    )

    threshold = _as_number(
        data.get("match_threshold"),
        f"{field_prefix}.match_threshold",
    )
    if threshold <= 0 or threshold > 1:
        raise GestureConfigError(
            f"{field_prefix}.match_threshold must be greater than 0 and at most 1"
        )

    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise GestureConfigError(f"{field_prefix}.actions must not be empty")
    actions: list[str] = []
    for action_index, action in enumerate(raw_actions):
        if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
            raise GestureConfigError(
                f"{field_prefix}.actions[{action_index}] is not a supported action"
            )
        actions.append(action)

    return GestureTemplate(
        id=gesture_id.strip(),
        name=name.strip(),
        handedness=handedness,
        features=features,
        match_threshold=threshold,
        actions=tuple(actions),
    )


def config_from_dict(data: Any) -> GestureConfig:
    if not isinstance(data, dict):
        raise GestureConfigError("configuration root must be an object")

    version = data.get("version")
    if version != CONFIG_VERSION:
        raise GestureConfigError(
            f"unsupported gesture configuration version {version!r}; "
            f"expected {CONFIG_VERSION}"
        )

    step_duration = _as_number(
        data.get("step_duration_seconds"),
        "step_duration_seconds",
    )
    if not MIN_STEP_DURATION_SECONDS <= step_duration <= MAX_STEP_DURATION_SECONDS:
        raise GestureConfigError(
            "step_duration_seconds must be between "
            f"{MIN_STEP_DURATION_SECONDS} and {MAX_STEP_DURATION_SECONDS}"
        )

    raw_gestures = data.get("gestures")
    if not isinstance(raw_gestures, list):
        raise GestureConfigError("gestures must be an array")
    gestures = tuple(
        _parse_template(raw_template, index)
        for index, raw_template in enumerate(raw_gestures)
    )

    ids: set[str] = set()
    names: set[str] = set()
    for gesture in gestures:
        if gesture.id in ids:
            raise GestureConfigError(f"duplicate gesture id: {gesture.id}")
        ids.add(gesture.id)

        normalized_name = gesture.name.casefold()
        if normalized_name in names:
            raise GestureConfigError(f"duplicate gesture name: {gesture.name}")
        names.add(normalized_name)

    return GestureConfig(
        version=CONFIG_VERSION,
        step_duration_seconds=step_duration,
        gestures=gestures,
    )


def config_to_dict(config: GestureConfig) -> dict[str, Any]:
    validated = config_from_dict(
        {
            "version": config.version,
            "step_duration_seconds": config.step_duration_seconds,
            "gestures": [
                {
                    "id": gesture.id,
                    "name": gesture.name,
                    "handedness": gesture.handedness,
                    "features": list(gesture.features),
                    "match_threshold": gesture.match_threshold,
                    "actions": list(gesture.actions),
                }
                for gesture in config.gestures
            ],
        }
    )
    return {
        "version": validated.version,
        "step_duration_seconds": validated.step_duration_seconds,
        "gestures": [
            {
                "id": gesture.id,
                "name": gesture.name,
                "handedness": gesture.handedness,
                "features": list(gesture.features),
                "match_threshold": gesture.match_threshold,
                "actions": list(gesture.actions),
            }
            for gesture in validated.gestures
        ],
    }


def load_config(path: str | os.PathLike[str] = DEFAULT_CONFIG_PATH) -> GestureConfig:
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return GestureConfig()

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GestureConfigError(
            f"could not read gesture configuration {config_path}: {exc}"
        ) from exc

    try:
        return config_from_dict(data)
    except GestureConfigError as exc:
        raise GestureConfigError(
            f"invalid gesture configuration {config_path}: {exc}"
        ) from exc


def save_config(
    config: GestureConfig,
    path: str | os.PathLike[str] = DEFAULT_CONFIG_PATH,
) -> None:
    data = config_to_dict(config)
    config_path = Path(path).expanduser()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            dir=config_path.parent,
            text=True,
        )
    except OSError as exc:
        raise GestureConfigError(
            f"could not prepare gesture configuration {config_path}: {exc}"
        ) from exc

    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, config_path)
    except OSError as exc:
        raise GestureConfigError(
            f"could not save gesture configuration {config_path}: {exc}"
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def make_config(
    gestures: Iterable[GestureTemplate],
    step_duration_seconds: float = DEFAULT_STEP_DURATION_SECONDS,
) -> GestureConfig:
    return config_from_dict(
        {
            "version": CONFIG_VERSION,
            "step_duration_seconds": step_duration_seconds,
            "gestures": [
                {
                    "id": gesture.id,
                    "name": gesture.name,
                    "handedness": gesture.handedness,
                    "features": list(gesture.features),
                    "match_threshold": gesture.match_threshold,
                    "actions": list(gesture.actions),
                }
                for gesture in gestures
            ],
        }
    )
