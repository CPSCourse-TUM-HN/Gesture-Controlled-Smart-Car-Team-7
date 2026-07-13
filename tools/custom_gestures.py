from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

from tools.gesture_config import GestureTemplate

WRIST = 0
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_PIP = 14
RING_TIP = 16
PINKY_PIP = 18
PINKY_TIP = 20
LANDMARK_COUNT = 21
FINGER_FOLDED_RATIO = 1.08

CAPTURE_FRAME_COUNT = 30
MIN_MATCH_THRESHOLD = 0.12
MAX_MATCH_THRESHOLD = 0.35
THRESHOLD_VARIATION_MULTIPLIER = 2.0
DEFAULT_STABLE_SECONDS = 0.4
DEFAULT_REARM_SECONDS = 0.3


class Landmark(Protocol):
    x: float
    y: float


LandmarkLike = Landmark | Sequence[float]


@dataclass(frozen=True)
class GestureMatch:
    gesture: GestureTemplate
    distance: float


def _coordinates(point: LandmarkLike) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    if isinstance(point, Sequence) and len(point) >= 2:
        return float(point[0]), float(point[1])
    raise ValueError("landmark must provide x and y coordinates")


def _distance(first: LandmarkLike, second: LandmarkLike) -> float:
    first_x, first_y = _coordinates(first)
    second_x, second_y = _coordinates(second)
    return math.hypot(first_x - second_x, first_y - second_y)


def normalize_landmarks(landmarks: Iterable[LandmarkLike]) -> tuple[float, ...]:
    points = list(landmarks)
    if len(points) < LANDMARK_COUNT:
        raise ValueError(f"expected {LANDMARK_COUNT} hand landmarks")

    wrist_x, wrist_y = _coordinates(points[WRIST])
    middle_x, middle_y = _coordinates(points[MIDDLE_MCP])
    scale = math.hypot(middle_x - wrist_x, middle_y - wrist_y)
    if not math.isfinite(scale) or scale <= 1e-6:
        raise ValueError("palm scale is too small")

    features: list[float] = []
    for point in points[:LANDMARK_COUNT]:
        x, y = _coordinates(point)
        normalized_x = (x - wrist_x) / scale
        normalized_y = (y - wrist_y) / scale
        if not math.isfinite(normalized_x) or not math.isfinite(normalized_y):
            raise ValueError("landmark coordinates must be finite")
        features.extend((normalized_x, normalized_y))
    return tuple(features)


def feature_distance(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != len(second) or len(first) % 2:
        raise ValueError("gesture feature vectors must have equal even lengths")
    if not first:
        raise ValueError("gesture feature vectors must not be empty")

    squared_distance = sum(
        (first[index] - second[index]) ** 2
        + (first[index + 1] - second[index + 1]) ** 2
        for index in range(0, len(first), 2)
    )
    return math.sqrt(squared_distance / (len(first) // 2))


def is_fist_pose(landmarks: Iterable[LandmarkLike]) -> bool:
    points = list(landmarks)
    if len(points) < LANDMARK_COUNT:
        return False
    for pip_index, tip_index in (
        (INDEX_PIP, INDEX_TIP),
        (MIDDLE_PIP, MIDDLE_TIP),
        (RING_PIP, RING_TIP),
        (PINKY_PIP, PINKY_TIP),
    ):
        if _distance(points[WRIST], points[tip_index]) > (
            _distance(points[WRIST], points[pip_index]) * FINGER_FOLDED_RATIO
        ):
            return False
    return True


def _percentile_95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def build_template(
    name: str,
    handedness: str,
    actions: Iterable[str],
    samples: Iterable[Iterable[LandmarkLike]],
    *,
    gesture_id: str | None = None,
) -> GestureTemplate:
    raw_samples = [list(sample) for sample in samples]
    if len(raw_samples) < CAPTURE_FRAME_COUNT:
        raise ValueError(
            f"at least {CAPTURE_FRAME_COUNT} valid frames are required"
        )
    if sum(is_fist_pose(sample) for sample in raw_samples) / len(raw_samples) >= 0.8:
        raise ValueError("the fist pose is reserved for emergency stop")

    feature_samples = [normalize_landmarks(sample) for sample in raw_samples]
    centroid = tuple(
        sum(sample[index] for sample in feature_samples) / len(feature_samples)
        for index in range(len(feature_samples[0]))
    )
    variations = [feature_distance(sample, centroid) for sample in feature_samples]
    threshold = min(
        MAX_MATCH_THRESHOLD,
        max(
            MIN_MATCH_THRESHOLD,
            _percentile_95(variations) * THRESHOLD_VARIATION_MULTIPLIER,
        ),
    )

    return GestureTemplate(
        id=gesture_id or str(uuid.uuid4()),
        name=name,
        handedness=handedness,
        features=centroid,
        match_threshold=threshold,
        actions=tuple(actions),
    )


def find_matching_gesture(
    features: Sequence[float],
    handedness: str,
    gestures: Iterable[GestureTemplate],
) -> GestureMatch | None:
    best_match: GestureMatch | None = None
    best_ratio = math.inf
    for gesture in gestures:
        if gesture.handedness != handedness:
            continue
        distance = feature_distance(features, gesture.features)
        ratio = distance / gesture.match_threshold
        if distance <= gesture.match_threshold and ratio < best_ratio:
            best_match = GestureMatch(gesture=gesture, distance=distance)
            best_ratio = ratio
    return best_match


def find_template_conflict(
    candidate: GestureTemplate,
    existing: Iterable[GestureTemplate],
) -> GestureTemplate | None:
    for gesture in existing:
        if gesture.id == candidate.id or gesture.handedness != candidate.handedness:
            continue
        if feature_distance(candidate.features, gesture.features) <= max(
            candidate.match_threshold,
            gesture.match_threshold,
        ):
            return gesture
    return None


class GestureTrigger:
    def __init__(
        self,
        stable_seconds: float = DEFAULT_STABLE_SECONDS,
        rearm_seconds: float = DEFAULT_REARM_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._stable_seconds = stable_seconds
        self._rearm_seconds = rearm_seconds
        self._clock = clock
        self._armed = True
        self._candidate_id: str | None = None
        self._candidate_since: float | None = None
        self._absent_since: float | None = None

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def candidate_id(self) -> str | None:
        return self._candidate_id

    def update(self, gesture_id: str | None, now: float | None = None) -> str | None:
        current_time = self._clock() if now is None else now

        if gesture_id is None:
            self._candidate_id = None
            self._candidate_since = None
            if not self._armed:
                if self._absent_since is None:
                    self._absent_since = current_time
                elif (
                    current_time - self._absent_since + 1e-9
                    >= self._rearm_seconds
                ):
                    self._armed = True
                    self._absent_since = None
            return None

        self._absent_since = None
        if not self._armed:
            return None

        if gesture_id != self._candidate_id:
            self._candidate_id = gesture_id
            self._candidate_since = current_time
            return None

        if (
            self._candidate_since is not None
            and current_time - self._candidate_since + 1e-9
            >= self._stable_seconds
        ):
            self._armed = False
            self._candidate_id = None
            self._candidate_since = None
            return gesture_id
        return None
