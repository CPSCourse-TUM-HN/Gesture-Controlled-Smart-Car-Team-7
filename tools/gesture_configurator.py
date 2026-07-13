from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.custom_gestures import (
    CAPTURE_FRAME_COUNT,
    build_template,
    find_template_conflict,
)
from tools.gesture_config import (
    ACTION_NAMES,
    DEFAULT_CONFIG_PATH,
    MAX_STEP_DURATION_SECONDS,
    MIN_STEP_DURATION_SECONDS,
    GestureConfig,
    GestureConfigError,
    GestureTemplate,
    load_config,
    make_config,
    save_config,
)
from tools.gesture_serial_test import SerialOutputTester

RECORDING_COUNTDOWN_SECONDS = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record custom hand gestures and arrange car action sequences.",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="camera index to open (default: 0)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"gesture configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser.parse_args()


class CameraWorker(QThread):
    frame_ready = Signal(object)
    observation_ready = Signal(object, object, float)
    recording_progress = Signal(int, int)
    recording_complete = Signal(object, str)
    status_changed = Signal(str)
    error = Signal(str)

    def __init__(self, camera_index: int) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._lock = threading.Lock()
        self._recording = False
        self._countdown_until = 0.0
        self._samples: list[list[tuple[float, float]]] = []
        self._recorded_hand: str | None = None
        self._last_status: str | None = None

    def request_recording(self) -> None:
        with self._lock:
            self._recording = True
            self._countdown_until = time.monotonic() + RECORDING_COUNTDOWN_SECONDS
            self._samples = []
            self._recorded_hand = None
        self._set_status("Get ready to hold the new pose.")

    def cancel_recording(self) -> None:
        with self._lock:
            self._recording = False
            self._samples = []
            self._recorded_hand = None
        self._set_status("Recording cancelled.")

    def _set_status(self, message: str) -> None:
        if message != self._last_status:
            self._last_status = message
            self.status_changed.emit(message)

    @staticmethod
    def _handedness(results: object) -> str | None:
        handedness = getattr(results, "multi_handedness", None)
        if not handedness or not handedness[0].classification:
            return None
        label = handedness[0].classification[0].label
        return label if label in {"Left", "Right"} else None

    def _handle_recording(
        self,
        landmarks: list[tuple[float, float]] | None,
        handedness: str | None,
    ) -> tuple[bool, int]:
        with self._lock:
            if not self._recording:
                return False, 0

            remaining = self._countdown_until - time.monotonic()
            if remaining > 0:
                self._set_status(
                    f"Recording starts in {max(1, math.ceil(remaining))}..."
                )
                return True, math.ceil(remaining)

            if landmarks is None or handedness is None:
                if self._samples:
                    self._samples = []
                    self._recorded_hand = None
                    self.recording_progress.emit(0, CAPTURE_FRAME_COUNT)
                self._set_status("Keep one hand fully visible and hold the pose.")
                return True, 0

            if self._recorded_hand is None:
                self._recorded_hand = handedness
            elif self._recorded_hand != handedness:
                self._samples = []
                self._recorded_hand = handedness
                self.recording_progress.emit(0, CAPTURE_FRAME_COUNT)
                self._set_status("Hand changed; restarting the continuous capture.")

            self._samples.append(landmarks)
            count = len(self._samples)
            self.recording_progress.emit(count, CAPTURE_FRAME_COUNT)
            self._set_status(
                f"Hold still: {count}/{CAPTURE_FRAME_COUNT} valid frames"
            )

            if count >= CAPTURE_FRAME_COUNT:
                samples = self._samples
                recorded_hand = self._recorded_hand
                self._recording = False
                self._samples = []
                self._recorded_hand = None
                self.recording_complete.emit(samples, recorded_hand)
                self._set_status("Pose recorded. Save the gesture to keep it.")
            return True, 0

    def run(self) -> None:
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            self.error.emit(f"Camera dependencies are unavailable: {exc}")
            return

        capture = cv2.VideoCapture(self._camera_index)
        if not capture.isOpened():
            self.error.emit(f"Could not open camera {self._camera_index}.")
            return

        hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self._set_status("Camera ready.")
        try:
            while not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok:
                    self.error.emit("Could not read from the camera.")
                    return

                frame = cv2.flip(frame, 1)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = hands.process(rgb_frame)
                landmark_points: list[tuple[float, float]] | None = None
                handedness = None

                if results.multi_hand_landmarks:
                    hand_landmarks = results.multi_hand_landmarks[0]
                    landmark_points = [
                        (float(point.x), float(point.y))
                        for point in hand_landmarks.landmark
                    ]
                    handedness = self._handedness(results)
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame,
                        hand_landmarks,
                        mp.solutions.hands.HAND_CONNECTIONS,
                    )

                recording, countdown = self._handle_recording(
                    landmark_points,
                    handedness,
                )
                self.observation_ready.emit(
                    landmark_points,
                    handedness,
                    time.monotonic(),
                )
                if recording:
                    overlay = (
                        str(countdown)
                        if countdown > 0
                        else "HOLD POSE"
                    )
                    cv2.putText(
                        frame,
                        overlay,
                        (20, 48),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0,
                        (30, 220, 30),
                        2,
                        cv2.LINE_AA,
                    )

                self.frame_ready.emit(frame.copy())
        finally:
            hands.close()
            capture.release()


class GestureConfiguratorWindow(QMainWindow):
    def __init__(
        self,
        config: GestureConfig,
        config_path: Path,
        camera_index: int,
        *,
        start_camera: bool = True,
    ) -> None:
        super().__init__()
        self._config_path = config_path.expanduser()
        self._gestures = list(config.gestures)
        self._editing_id: str | None = None
        self._editing_template: GestureTemplate | None = None
        self._captured_samples: list[list[tuple[float, float]]] | None = None
        self._captured_handedness: str | None = None
        self._config_dirty = False
        self._editor_dirty = False
        self._loading_editor = False
        self._serial_tester: SerialOutputTester | None = None

        self.setWindowTitle("GCSC Custom Gesture Configurator")
        self.resize(1180, 760)

        self._preview = QLabel("Waiting for camera...")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(600, 450)
        self._preview.setStyleSheet("background: #111; color: #ddd;")

        self._gesture_list = QListWidget()
        self._gesture_list.currentRowChanged.connect(self._load_selected_gesture)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Gesture name")
        self._name_edit.textEdited.connect(self._mark_editor_dirty)

        self._hand_label = QLabel("Not recorded")
        self._record_button = QPushButton("Record / Re-record Pose")
        self._record_button.clicked.connect(self._record_pose)

        self._action_combo = QComboBox()
        for command, action_name in ACTION_NAMES.items():
            self._action_combo.addItem(f"{action_name} ({command})", command)
        add_action_button = QPushButton("Add Action")
        add_action_button.clicked.connect(self._add_action)

        self._action_list = QListWidget()
        self._action_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self._action_list.model().rowsMoved.connect(self._mark_editor_dirty)

        remove_action_button = QPushButton("Remove")
        remove_action_button.clicked.connect(self._remove_action)
        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(lambda: self._move_action(-1))
        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(lambda: self._move_action(1))

        self._duration = QDoubleSpinBox()
        self._duration.setRange(
            MIN_STEP_DURATION_SECONDS,
            MAX_STEP_DURATION_SECONDS,
        )
        self._duration.setSingleStep(0.1)
        self._duration.setDecimals(1)
        self._duration.setSuffix(" seconds")
        self._duration.setValue(config.step_duration_seconds)
        self._duration.valueChanged.connect(self._mark_config_dirty)

        new_button = QPushButton("New Gesture")
        new_button.clicked.connect(self._new_gesture)
        save_gesture_button = QPushButton("Save Gesture")
        save_gesture_button.clicked.connect(self._save_gesture)
        delete_button = QPushButton("Delete Gesture")
        delete_button.clicked.connect(self._delete_gesture)
        save_config_button = QPushButton("Save Configuration")
        save_config_button.clicked.connect(self._save_configuration)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self._preview, 1)
        left_layout.addWidget(self._record_button)

        gesture_group = QGroupBox("Gestures")
        gesture_layout = QVBoxLayout(gesture_group)
        gesture_layout.addWidget(self._gesture_list)
        gesture_buttons = QHBoxLayout()
        gesture_buttons.addWidget(new_button)
        gesture_buttons.addWidget(delete_button)
        gesture_layout.addLayout(gesture_buttons)

        details_group = QGroupBox("Gesture Details")
        details_layout = QFormLayout(details_group)
        details_layout.addRow("Name", self._name_edit)
        details_layout.addRow("Recorded hand", self._hand_label)

        sequence_group = QGroupBox("Action Sequence")
        sequence_layout = QVBoxLayout(sequence_group)
        add_action_layout = QHBoxLayout()
        add_action_layout.addWidget(self._action_combo, 1)
        add_action_layout.addWidget(add_action_button)
        sequence_layout.addLayout(add_action_layout)
        sequence_layout.addWidget(self._action_list)
        sequence_buttons = QHBoxLayout()
        sequence_buttons.addWidget(remove_action_button)
        sequence_buttons.addWidget(move_up_button)
        sequence_buttons.addWidget(move_down_button)
        sequence_layout.addLayout(sequence_buttons)

        settings_group = QGroupBox("Sequence Settings")
        settings_layout = QFormLayout(settings_group)
        settings_layout.addRow("Duration per action", self._duration)

        test_group = QGroupBox("Serial Output Test (Dry Run)")
        test_layout = QVBoxLayout(test_group)
        test_explanation = QLabel(
            "Recognize saved custom gestures and show the Bluetooth bytes "
            "without connecting to the car."
        )
        test_explanation.setWordWrap(True)
        self._test_status = QLabel("Test stopped")
        self._test_output = QPlainTextEdit()
        self._test_output.setReadOnly(True)
        self._test_output.setPlaceholderText("Transmitted bytes will appear here.")
        self._test_output.setMaximumBlockCount(500)
        self._test_button = QPushButton("Start Serial Output Test")
        self._test_button.clicked.connect(self._toggle_serial_test)
        clear_test_button = QPushButton("Clear Output")
        clear_test_button.clicked.connect(self._test_output.clear)
        test_buttons = QHBoxLayout()
        test_buttons.addWidget(self._test_button)
        test_buttons.addWidget(clear_test_button)
        test_layout.addWidget(test_explanation)
        test_layout.addWidget(self._test_status)
        test_layout.addWidget(self._test_output)
        test_layout.addLayout(test_buttons)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(gesture_group, 1)
        right_layout.addWidget(details_group)
        right_layout.addWidget(sequence_group, 1)
        right_layout.addWidget(settings_group)
        right_layout.addWidget(test_group, 1)
        right_layout.addWidget(save_gesture_button)
        right_layout.addWidget(save_config_button)
        path_label = QLabel(f"Configuration: {self._config_path}")
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        right_layout.addWidget(path_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        self._refresh_gesture_list()
        self._new_gesture()

        self._camera_worker: CameraWorker | None = None
        if start_camera:
            self._camera_worker = CameraWorker(camera_index)
            self._camera_worker.frame_ready.connect(self._show_frame)
            self._camera_worker.observation_ready.connect(
                self._test_observation
            )
            self._camera_worker.recording_progress.connect(
                self._recording_progress
            )
            self._camera_worker.recording_complete.connect(
                self._recording_complete
            )
            self._camera_worker.status_changed.connect(
                self.statusBar().showMessage
            )
            self._camera_worker.error.connect(self._camera_error)
            self._camera_worker.start()
        else:
            self._record_button.setEnabled(False)
            self._test_button.setEnabled(False)

    def _mark_editor_dirty(self, *_: object) -> None:
        if not self._loading_editor:
            self._editor_dirty = True

    def _mark_config_dirty(self, *_: object) -> None:
        self._config_dirty = True

    def _refresh_gesture_list(self, selected_id: str | None = None) -> None:
        self._gesture_list.blockSignals(True)
        self._gesture_list.clear()
        selected_row = -1
        for index, gesture in enumerate(self._gestures):
            item = QListWidgetItem(f"{gesture.name} [{gesture.handedness}]")
            item.setData(Qt.ItemDataRole.UserRole, gesture.id)
            self._gesture_list.addItem(item)
            if gesture.id == selected_id:
                selected_row = index
        self._gesture_list.blockSignals(False)
        if selected_row >= 0:
            self._gesture_list.setCurrentRow(selected_row)

    def _new_gesture(self) -> None:
        self._loading_editor = True
        self._gesture_list.clearSelection()
        self._gesture_list.setCurrentRow(-1)
        self._editing_id = None
        self._editing_template = None
        self._captured_samples = None
        self._captured_handedness = None
        self._name_edit.clear()
        self._hand_label.setText("Not recorded")
        self._action_list.clear()
        self._loading_editor = False
        self._editor_dirty = False

    def _load_selected_gesture(self, row: int) -> None:
        if row < 0 or row >= len(self._gestures):
            return
        gesture = self._gestures[row]
        self._loading_editor = True
        self._editing_id = gesture.id
        self._editing_template = gesture
        self._captured_samples = None
        self._captured_handedness = None
        self._name_edit.setText(gesture.name)
        self._hand_label.setText(gesture.handedness)
        self._action_list.clear()
        for action in gesture.actions:
            self._append_action(action)
        self._loading_editor = False
        self._editor_dirty = False

    def _append_action(self, command: str) -> None:
        item = QListWidgetItem(f"{ACTION_NAMES[command]} ({command})")
        item.setData(Qt.ItemDataRole.UserRole, command)
        self._action_list.addItem(item)

    def _add_action(self) -> None:
        command = self._action_combo.currentData()
        self._append_action(command)
        self._editor_dirty = True

    def _remove_action(self) -> None:
        row = self._action_list.currentRow()
        if row >= 0:
            self._action_list.takeItem(row)
            self._editor_dirty = True

    def _move_action(self, offset: int) -> None:
        row = self._action_list.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self._action_list.count():
            return
        item = self._action_list.takeItem(row)
        self._action_list.insertItem(target, item)
        self._action_list.setCurrentRow(target)
        self._editor_dirty = True

    def _record_pose(self) -> None:
        if self._camera_worker is None:
            return
        self._record_button.setEnabled(False)
        self._camera_worker.request_recording()

    def _recording_progress(self, current: int, total: int) -> None:
        self._record_button.setText(f"Recording {current}/{total}")

    def _recording_complete(
        self,
        samples: list[list[tuple[float, float]]],
        handedness: str,
    ) -> None:
        self._captured_samples = samples
        self._captured_handedness = handedness
        self._hand_label.setText(handedness)
        self._record_button.setText("Record / Re-record Pose")
        self._record_button.setEnabled(True)
        self._editor_dirty = True

    def _camera_error(self, message: str) -> None:
        self._preview.setText(message)
        self._record_button.setEnabled(False)
        self._test_button.setEnabled(False)
        self.statusBar().showMessage(message)

    def _toggle_serial_test(self) -> None:
        if self._serial_tester is not None:
            self._serial_tester = None
            self._test_button.setText("Start Serial Output Test")
            self._test_status.setText("Test stopped")
            return
        if self._editor_dirty:
            QMessageBox.information(
                self,
                "Unsaved Gesture",
                "Save the current gesture before testing it.",
            )
            return
        if not self._gestures:
            QMessageBox.information(
                self,
                "No Gestures",
                "Create and save at least one custom gesture first.",
            )
            return
        try:
            config = make_config(self._gestures, self._duration.value())
        except GestureConfigError as exc:
            QMessageBox.warning(self, "Cannot Start Test", str(exc))
            return
        self._serial_tester = SerialOutputTester(config)
        self._test_button.setText("Stop Serial Output Test")
        self._test_status.setText("Ready — hold a recorded pose for 0.4 seconds")
        self._test_output.appendPlainText("--- test started (no Bluetooth connection) ---")

    def _test_observation(
        self,
        landmarks: list[tuple[float, float]] | None,
        handedness: str | None,
        observed_at: float,
    ) -> None:
        if self._serial_tester is None:
            return
        update = self._serial_tester.process(
            landmarks,
            handedness,
            observed_at,
        )
        if update.sequence is not None:
            self._test_status.setText(
                f"{update.sequence.gesture_name}: step "
                f"{update.sequence.step_number}/{update.sequence.step_count} "
                f"{update.sequence.action_name}"
            )
        elif not update.armed:
            self._test_status.setText("Sequence complete — release hand to re-arm")
        elif update.match is not None:
            self._test_status.setText(
                f"Matched {update.match.gesture.name} — hold to trigger"
            )
        else:
            self._test_status.setText("Ready — show a recorded pose")

        for payload in update.new_bytes:
            command = payload.decode("ascii")
            self._test_output.appendPlainText(
                f"TX  0x{payload[0]:02X}  '{command}'  {ACTION_NAMES[command]}"
            )

    def _show_frame(self, frame: object) -> None:
        height, width, channels = frame.shape
        image = QImage(
            frame.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_BGR888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(pixmap)

    def _actions_from_editor(self) -> tuple[str, ...]:
        return tuple(
            self._action_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self._action_list.count())
        )

    def _candidate_template(self) -> GestureTemplate:
        name = self._name_edit.text().strip()
        if not name:
            raise ValueError("Enter a gesture name.")
        actions = self._actions_from_editor()
        if not actions:
            raise ValueError("Add at least one action to the sequence.")

        if self._captured_samples is not None:
            return build_template(
                name=name,
                handedness=self._captured_handedness or "",
                actions=actions,
                samples=self._captured_samples,
                gesture_id=self._editing_id,
            )
        if self._editing_template is None:
            raise ValueError("Record a hand pose before saving the gesture.")
        return GestureTemplate(
            id=self._editing_template.id,
            name=name,
            handedness=self._editing_template.handedness,
            features=self._editing_template.features,
            match_threshold=self._editing_template.match_threshold,
            actions=actions,
        )

    def _save_gesture(self) -> bool:
        try:
            candidate = self._candidate_template()
            conflict = find_template_conflict(candidate, self._gestures)
            if conflict is not None:
                raise ValueError(
                    f"This pose is too similar to '{conflict.name}'."
                )

            updated = [
                gesture
                for gesture in self._gestures
                if gesture.id != candidate.id
            ]
            updated.append(candidate)
            validated = make_config(updated, self._duration.value())
        except (ValueError, GestureConfigError) as exc:
            QMessageBox.warning(self, "Cannot Save Gesture", str(exc))
            return False

        self._gestures = list(validated.gestures)
        self._editing_id = candidate.id
        self._editing_template = candidate
        self._captured_samples = None
        self._captured_handedness = None
        self._editor_dirty = False
        self._config_dirty = True
        self._refresh_gesture_list(candidate.id)
        self.statusBar().showMessage(f"Gesture '{candidate.name}' updated.")
        return True

    def _delete_gesture(self) -> None:
        row = self._gesture_list.currentRow()
        if row < 0:
            return
        gesture = self._gestures[row]
        answer = QMessageBox.question(
            self,
            "Delete Gesture",
            f"Delete '{gesture.name}'?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._gestures[row]
        self._config_dirty = True
        self._refresh_gesture_list()
        self._new_gesture()

    def _save_configuration(self) -> bool:
        if self._editor_dirty:
            QMessageBox.information(
                self,
                "Unsaved Gesture",
                "Save or discard the current gesture edits first.",
            )
            return False
        try:
            config = make_config(self._gestures, self._duration.value())
            save_config(config, self._config_path)
        except GestureConfigError as exc:
            QMessageBox.critical(self, "Cannot Save Configuration", str(exc))
            return False
        self._config_dirty = False
        self.statusBar().showMessage(f"Saved {self._config_path}")
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._editor_dirty or self._config_dirty:
            answer = QMessageBox.warning(
                self,
                "Unsaved Changes",
                "Save changes before closing?",
                (
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel
                ),
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                if self._editor_dirty and not self._save_gesture():
                    event.ignore()
                    return
                if not self._save_configuration():
                    event.ignore()
                    return

        if self._camera_worker is not None:
            self._camera_worker.requestInterruption()
            self._camera_worker.wait(3000)
        event.accept()


def main() -> int:
    args = parse_args()
    app = QApplication(sys.argv)
    try:
        config = load_config(args.config)
    except GestureConfigError as exc:
        QMessageBox.critical(None, "Invalid Gesture Configuration", str(exc))
        return 1

    window = GestureConfiguratorWindow(config, args.config, args.camera)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
