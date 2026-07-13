from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gesture_config import (
    CONFIG_VERSION,
    GestureConfig,
    GestureConfigError,
    GestureTemplate,
    config_from_dict,
    load_config,
    save_config,
)


def template(
    *,
    gesture_id: str = "gesture-1",
    name: str = "Wave",
    actions: tuple[str, ...] = ("F", "L", "S"),
) -> GestureTemplate:
    return GestureTemplate(
        id=gesture_id,
        name=name,
        handedness="Right",
        features=tuple(0.01 * index for index in range(42)),
        match_threshold=0.2,
        actions=actions,
    )


class GestureConfigurationTests(unittest.TestCase):
    def test_missing_file_returns_default_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.json")

        self.assertEqual(config, GestureConfig())

    def test_configuration_round_trips_through_json(self) -> None:
        config = GestureConfig(
            step_duration_seconds=1.7,
            gestures=(template(),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "gestures.json"
            save_config(config, path)
            loaded = load_config(path)
            temporary_files = list(path.parent.glob("*.tmp"))

        self.assertEqual(loaded, config)
        self.assertEqual(temporary_files, [])

    def test_unknown_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(GestureConfigError, "unsupported"):
            config_from_dict(
                {
                    "version": CONFIG_VERSION + 1,
                    "step_duration_seconds": 1.0,
                    "gestures": [],
                }
            )

    def test_duplicate_names_are_case_insensitive(self) -> None:
        config = GestureConfig(gestures=(template(), template(
            gesture_id="gesture-2",
            name="wave",
        )))

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(GestureConfigError, "duplicate gesture name"):
                save_config(config, Path(directory) / "gestures.json")

    def test_empty_or_unknown_actions_are_rejected(self) -> None:
        base = {
            "version": CONFIG_VERSION,
            "step_duration_seconds": 1.0,
            "gestures": [
                {
                    "id": "one",
                    "name": "One",
                    "handedness": "Left",
                    "features": [0.0] * 42,
                    "match_threshold": 0.2,
                    "actions": [],
                }
            ],
        }
        with self.assertRaisesRegex(GestureConfigError, "must not be empty"):
            config_from_dict(base)

        base["gestures"][0]["actions"] = ["X"]
        with self.assertRaisesRegex(GestureConfigError, "not a supported action"):
            config_from_dict(base)

    def test_invalid_step_duration_is_rejected(self) -> None:
        with self.assertRaisesRegex(GestureConfigError, "between"):
            config_from_dict(
                {
                    "version": CONFIG_VERSION,
                    "step_duration_seconds": 0.01,
                    "gestures": [],
                }
            )

    def test_malformed_json_reports_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(GestureConfigError, str(path)):
                load_config(path)

    def test_saved_document_has_versioned_public_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gestures.json"
            save_config(GestureConfig(gestures=(template(),)), path)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["version"], CONFIG_VERSION)
        self.assertEqual(data["gestures"][0]["actions"], ["F", "L", "S"])


if __name__ == "__main__":
    unittest.main()
