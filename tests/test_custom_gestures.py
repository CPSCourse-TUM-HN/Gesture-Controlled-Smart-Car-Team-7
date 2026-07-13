from __future__ import annotations

import unittest

from tools.custom_gestures import (
    GestureTrigger,
    build_template,
    feature_distance,
    find_matching_gesture,
    find_template_conflict,
    normalize_landmarks,
)
from tools.gesture_config import GestureTemplate


def open_hand() -> list[tuple[float, float]]:
    points = [(0.5, 0.7) for _ in range(21)]
    points[0] = (0.5, 0.82)
    points[1:5] = [(0.43, 0.68), (0.36, 0.62), (0.30, 0.56), (0.24, 0.52)]
    for mcp, pip, dip, tip, x in (
        (5, 6, 7, 8, 0.40),
        (9, 10, 11, 12, 0.48),
        (13, 14, 15, 16, 0.56),
        (17, 18, 19, 20, 0.64),
    ):
        points[mcp] = (x, 0.62)
        points[pip] = (x, 0.46)
        points[dip] = (x, 0.30)
        points[tip] = (x, 0.14)
    return points


def fist() -> list[tuple[float, float]]:
    points = open_hand()
    for pip, dip, tip, x in (
        (6, 7, 8, 0.40),
        (10, 11, 12, 0.48),
        (14, 15, 16, 0.56),
        (18, 19, 20, 0.64),
    ):
        points[pip] = (x, 0.62)
        points[dip] = (x, 0.69)
        points[tip] = (x, 0.73)
    return points


def transformed(
    points: list[tuple[float, float]],
    scale: float,
    x_offset: float,
    y_offset: float,
) -> list[tuple[float, float]]:
    return [
        (x * scale + x_offset, y * scale + y_offset)
        for x, y in points
    ]


class GestureTemplateTests(unittest.TestCase):
    def test_normalization_ignores_position_and_scale(self) -> None:
        original = normalize_landmarks(open_hand())
        moved = normalize_landmarks(transformed(open_hand(), 1.8, -0.4, 0.2))

        self.assertAlmostEqual(feature_distance(original, moved), 0.0)

    def test_normalization_preserves_orientation(self) -> None:
        points = open_hand()
        wrist_x = points[0][0]
        mirrored = [(2 * wrist_x - x, y) for x, y in points]

        distance = feature_distance(
            normalize_landmarks(points),
            normalize_landmarks(mirrored),
        )

        self.assertGreater(distance, 0.2)

    def test_build_template_uses_thirty_frames_and_rejects_fist(self) -> None:
        samples = [open_hand() for _ in range(30)]
        gesture = build_template("Palm", "Right", ("F",), samples)

        self.assertEqual(gesture.name, "Palm")
        self.assertEqual(len(gesture.features), 42)

        with self.assertRaisesRegex(ValueError, "reserved"):
            build_template("Unsafe", "Right", ("F",), [fist() for _ in range(30)])

    def test_match_requires_same_handedness(self) -> None:
        gesture = build_template(
            "Palm",
            "Right",
            ("F",),
            [open_hand() for _ in range(30)],
        )
        features = normalize_landmarks(open_hand())

        self.assertIsNotNone(find_matching_gesture(features, "Right", [gesture]))
        self.assertIsNone(find_matching_gesture(features, "Left", [gesture]))

    def test_nearest_matching_template_wins(self) -> None:
        features = normalize_landmarks(open_hand())
        farther = GestureTemplate(
            id="far",
            name="Far",
            handedness="Right",
            features=tuple(value + 0.05 for value in features),
            match_threshold=0.2,
            actions=("B",),
        )
        exact = GestureTemplate(
            id="exact",
            name="Exact",
            handedness="Right",
            features=features,
            match_threshold=0.2,
            actions=("F",),
        )

        match = find_matching_gesture(features, "Right", [farther, exact])

        self.assertIsNotNone(match)
        self.assertEqual(match.gesture.id, "exact")

    def test_similar_template_conflict_is_reported(self) -> None:
        first = build_template("First", "Right", ("F",), [open_hand()] * 30)
        second = build_template("Second", "Right", ("B",), [open_hand()] * 30)

        self.assertEqual(find_template_conflict(second, [first]), first)


class GestureTriggerTests(unittest.TestCase):
    def test_stable_pose_triggers_once_until_absent_for_rearm_time(self) -> None:
        trigger = GestureTrigger(stable_seconds=0.4, rearm_seconds=0.3)

        self.assertIsNone(trigger.update("one", 0.0))
        self.assertIsNone(trigger.update("one", 0.39))
        self.assertEqual(trigger.update("one", 0.4), "one")
        self.assertIsNone(trigger.update("one", 2.0))
        self.assertFalse(trigger.armed)

        self.assertIsNone(trigger.update(None, 2.1))
        self.assertIsNone(trigger.update(None, 2.39))
        self.assertIsNone(trigger.update(None, 2.4))
        self.assertTrue(trigger.armed)

        self.assertIsNone(trigger.update("one", 2.5))
        self.assertEqual(trigger.update("one", 2.9), "one")

    def test_changing_candidate_restarts_stability_window(self) -> None:
        trigger = GestureTrigger(stable_seconds=0.4)

        trigger.update("one", 0.0)
        trigger.update("two", 0.3)

        self.assertIsNone(trigger.update("two", 0.6))
        self.assertEqual(trigger.update("two", 0.7), "two")


if __name__ == "__main__":
    unittest.main()
