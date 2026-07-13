from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Iterable, Protocol

import serial

from tools.camera_support import create_hand_tracker, load_camera_dependencies
from tools.controller import (
    BAUD_RATE,
    CONNECT_DELAY_SECONDS,
    CommandSender,
    DEFAULT_PORT,
    WRITE_TIMEOUT_SECONDS,
    is_disconnected,
)
from tools.custom_gestures import (
    GestureMatch,
    GestureTrigger,
    find_matching_gesture,
    normalize_landmarks,
)
from tools.gesture_config import (
    ACTION_NAMES,
    DEFAULT_CONFIG_PATH,
    load_config,
)
from tools.gesture_sequence import ActionSequenceRunner

WRIST = 0
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_PIP = 14
RING_TIP = 16
PINKY_PIP = 18
PINKY_TIP = 20

FINGER_JOINTS = (
    (INDEX_PIP, INDEX_TIP),
    (MIDDLE_PIP, MIDDLE_TIP),
    (RING_PIP, RING_TIP),
    (PINKY_PIP, PINKY_TIP),
)

GESTURE_COMMANDS = {
    "forward": ("F", "forward"),
    "backward": ("B", "backward"),
    "left": ("L", "left"),
    "right": ("R", "right"),
    "spin_left": ("A", "spin left"),
    "spin_right": ("D", "spin right"),
    "stop": ("S", "stop"),
}

DEFAULT_CAMERA = 0
DEFAULT_LOST_TIMEOUT_SECONDS = 0.5
DEFAULT_MIN_DIRECTION_DELTA = 0.08
FINGER_EXTENDED_RATIO = 1.18
FINGER_FOLDED_RATIO = 1.08


class Landmark(Protocol):
    x: float
    y: float


@dataclass(frozen=True)
class GestureState:
    command: str
    name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Control the ESP32 car with MediaPipe hand gestures.",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"serial port to open (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=DEFAULT_CAMERA,
        help=f"camera index to open (default: {DEFAULT_CAMERA})",
    )
    parser.add_argument(
        "--lost-timeout",
        type=float,
        default=DEFAULT_LOST_TIMEOUT_SECONDS,
        help=(
            "seconds without a valid hand gesture before sending stop "
            f"(default: {DEFAULT_LOST_TIMEOUT_SECONDS})"
        ),
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="disable the camera preview window",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"gesture configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser.parse_args()


def distance(first: Landmark, second: Landmark) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def is_finger_extended(
    landmarks: list[Landmark],
    pip_index: int,
    tip_index: int,
) -> bool:
    wrist = landmarks[WRIST]
    return distance(wrist, landmarks[tip_index]) > (
        distance(wrist, landmarks[pip_index]) * FINGER_EXTENDED_RATIO
    )


def is_finger_folded(
    landmarks: list[Landmark],
    pip_index: int,
    tip_index: int,
) -> bool:
    wrist = landmarks[WRIST]
    return distance(wrist, landmarks[tip_index]) <= (
        distance(wrist, landmarks[pip_index]) * FINGER_FOLDED_RATIO
    )


def classify_gesture(
    landmarks: Iterable[Landmark],
    min_direction_delta: float = DEFAULT_MIN_DIRECTION_DELTA,
) -> GestureState | None:
    points = list(landmarks)
    if len(points) <= PINKY_TIP:
        return None

    folded = [
        is_finger_folded(points, pip_index, tip_index)
        for pip_index, tip_index in FINGER_JOINTS
    ]
    if all(folded):
        command, name = GESTURE_COMMANDS["stop"]
        return GestureState(command, name)

    extended = [
        is_finger_extended(points, pip_index, tip_index)
        for pip_index, tip_index in FINGER_JOINTS
    ]
    if all(extended):
        middle_base = points[MIDDLE_PIP]
        middle_tip = points[MIDDLE_TIP]
        dx = middle_tip.x - middle_base.x
        dy = middle_tip.y - middle_base.y

        if abs(dx) > abs(dy) and abs(dx) >= min_direction_delta:
            gesture = "spin_right" if dx > 0 else "spin_left"
            command, name = GESTURE_COMMANDS[gesture]
            return GestureState(command, name)
        return None

    index_extended = is_finger_extended(points, INDEX_PIP, INDEX_TIP)
    other_fingers_folded = all(folded[1:])
    if not index_extended or not other_fingers_folded:
        return None

    index_base = points[INDEX_MCP]
    index_tip = points[INDEX_TIP]
    dx = index_tip.x - index_base.x
    dy = index_tip.y - index_base.y

    if abs(dx) < min_direction_delta and abs(dy) < min_direction_delta:
        return None

    if abs(dx) > abs(dy):
        gesture = "right" if dx > 0 else "left"
    else:
        gesture = "backward" if dy > 0 else "forward"

    command, name = GESTURE_COMMANDS[gesture]
    return GestureState(command, name)


def print_controls(preview: bool) -> None:
    lines = [
        "Gesture controls:",
        "  index up      forward",
        "  index down    backward",
        "  index left    left",
        "  index right   right",
        "  palm left     spin left",
        "  palm right    spin right",
        "  fist          stop",
        "  no gesture    stop after timeout",
    ]
    if preview:
        lines.append("  q/Esc         stop and exit")
    else:
        lines.append("  C-c           stop and exit")
    lines.append("")
    print("\n".join(lines))


def send_if_changed(
    connection: serial.Serial,
    state: GestureState,
    last_command: str | None,
    sender: CommandSender,
) -> str:
    if state.command == last_command:
        return last_command

    if sender.send(connection, state.command, force=state.command == "S"):
        print(f"{state.name:<10} -> {state.command}")
        return state.command
    return last_command


def handedness_label(results: object) -> str | None:
    multi_handedness = getattr(results, "multi_handedness", None)
    if not multi_handedness:
        return None
    classifications = multi_handedness[0].classification
    if not classifications:
        return None
    label = classifications[0].label
    return label if label in {"Left", "Right"} else None


def draw_status(
    frame: object,
    cv2: object,
    match: GestureMatch | None,
    trigger: GestureTrigger,
    sequence: ActionSequenceRunner,
) -> None:
    lines: list[str] = []
    status = sequence.status
    if status is not None:
        lines.extend(
            [
                f"Custom: {status.gesture_name}",
                (
                    f"Step {status.step_number}/{status.step_count}: "
                    f"{status.action_name}"
                ),
            ]
        )
    elif not trigger.armed:
        lines.append("Release hand to re-arm")
    elif match is not None:
        lines.append(f"Custom: {match.gesture.name} (hold to trigger)")

    for line_index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (16, 32 + line_index * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (24, 220, 24),
            2,
            cv2.LINE_AA,
        )


def run(
    port: str,
    camera: int,
    lost_timeout: float,
    preview: bool,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> None:
    config = load_config(config_path)

    cv2, mp = load_camera_dependencies()

    capture = cv2.VideoCapture(camera)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"could not open camera {camera}")

    try:
        hands = create_hand_tracker(mp)
    except Exception:
        capture.release()
        raise

    print(f"Opening {port} at {BAUD_RATE} baud...")
    last_command: str | None = None
    last_valid_gesture_at = time.monotonic()

    try:
        with serial.Serial(
            port,
            BAUD_RATE,
            timeout=1,
            write_timeout=WRITE_TIMEOUT_SECONDS,
        ) as connection:
            time.sleep(CONNECT_DELAY_SECONDS)
            print_controls(preview)
            sender = CommandSender()
            trigger = GestureTrigger()
            sequence = ActionSequenceRunner(config.step_duration_seconds)

            try:
                while True:
                    if is_disconnected(connection):
                        raise serial.SerialException("serial port disconnected")

                    ok, frame = capture.read()
                    if not ok:
                        raise RuntimeError("could not read from camera")

                    frame = cv2.flip(frame, 1)
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(rgb_frame)
                    state = None
                    match = None

                    if results.multi_hand_landmarks:
                        hand_landmarks = results.multi_hand_landmarks[0]
                        state = classify_gesture(hand_landmarks.landmark)
                        hand_label = handedness_label(results)
                        if hand_label is not None and config.gestures:
                            try:
                                features = normalize_landmarks(
                                    hand_landmarks.landmark
                                )
                            except ValueError:
                                features = None
                            if features is not None:
                                match = find_matching_gesture(
                                    features,
                                    hand_label,
                                    config.gestures,
                                )
                        if preview:
                            mp.solutions.drawing_utils.draw_landmarks(
                                frame,
                                hand_landmarks,
                                mp.solutions.hands.HAND_CONNECTIONS,
                            )

                    now = time.monotonic()
                    is_emergency_stop = state is not None and state.command == "S"

                    if is_emergency_stop:
                        if sequence.active:
                            sequence.cancel(connection, sender)
                            print("emergency stop -> S")
                        else:
                            last_command = send_if_changed(
                                connection,
                                state,
                                sender.last_command,
                                sender,
                            )
                        trigger.update(None, now)
                    elif sequence.active:
                        trigger.update(match.gesture.id if match else None, now)
                        sequence.tick(connection, sender, now)
                    elif match is not None:
                        triggered_id = trigger.update(match.gesture.id, now)
                        if triggered_id is not None:
                            sequence.start(match.gesture, now)
                            sequence.tick(connection, sender, now)
                            print(
                                f"custom {match.gesture.name}: "
                                + " -> ".join(
                                    ACTION_NAMES[action]
                                    for action in match.gesture.actions
                                )
                            )
                    else:
                        trigger.update(None, now)
                        if state is not None:
                            last_valid_gesture_at = now
                            last_command = send_if_changed(
                                connection,
                                state,
                                sender.last_command,
                                sender,
                            )
                        elif now - last_valid_gesture_at >= lost_timeout:
                            stop_state = GestureState("S", "stop")
                            last_command = send_if_changed(
                                connection,
                                stop_state,
                                sender.last_command,
                                sender,
                            )

                    last_command = sender.last_command or last_command

                    if preview:
                        draw_status(frame, cv2, match, trigger, sequence)
                        cv2.imshow("GCSC Gesture Controller", frame)
                        key = cv2.waitKey(1) & 0xFF
                        if key in {27, ord("q")}:
                            print("\nSent stop.")
                            return
            finally:
                try:
                    sender.send(connection, "S", force=True)
                except serial.SerialException:
                    pass

    finally:
        hands.close()
        capture.release()
        if preview:
            cv2.destroyAllWindows()


def main() -> int:
    args = parse_args()

    try:
        run(
            port=args.port,
            camera=args.camera,
            lost_timeout=args.lost_timeout,
            preview=not args.no_preview,
            config_path=args.config,
        )
        return 0
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Gesture controller error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
