from __future__ import annotations

import unittest

from tests.test_custom_gestures import fist, open_hand
from tools.custom_gestures import build_template
from tools.gesture_config import GestureConfig
from tools.gesture_serial_test import SerialOutputTester


class SerialOutputTesterTests(unittest.TestCase):
    def make_tester(self) -> SerialOutputTester:
        gesture = build_template(
            "Route",
            "Right",
            ("F", "L", "S"),
            [open_hand() for _ in range(30)],
        )
        return SerialOutputTester(
            GestureConfig(
                step_duration_seconds=0.1,
                gestures=(gesture,),
            )
        )

    def test_recognized_custom_gesture_records_exact_serial_bytes(self) -> None:
        tester = self.make_tester()

        tester.process(open_hand(), "Right", 0.0)
        first = tester.process(open_hand(), "Right", 0.4)
        self.assertEqual(first.new_bytes, (b"F",))

        tester.process(None, None, 0.5)
        turn_stop = tester.process(None, None, 0.6)
        self.assertEqual(turn_stop.new_bytes, (b"S",))
        tester.process(None, None, 0.89)
        turn = tester.process(None, None, 0.9)
        self.assertEqual(turn.new_bytes, (b"L",))

        tester.process(None, None, 1.0)
        explicit_stop = tester.process(None, None, 1.1)
        self.assertEqual(explicit_stop.new_bytes, (b"S",))
        tester.process(None, None, 1.2)
        final_stop = tester.process(None, None, 1.3)
        self.assertEqual(final_stop.new_bytes, (b"S",))

        self.assertEqual(tester.output, (b"F", b"S", b"L", b"S", b"S"))

    def test_wrong_hand_produces_no_serial_output(self) -> None:
        tester = self.make_tester()

        tester.process(open_hand(), "Left", 0.0)
        tester.process(open_hand(), "Left", 1.0)

        self.assertEqual(tester.output, ())

    def test_fist_cancels_sequence_with_stop_byte(self) -> None:
        tester = self.make_tester()
        tester.process(open_hand(), "Right", 0.0)
        tester.process(open_hand(), "Right", 0.4)

        update = tester.process(fist(), "Right", 0.5)

        self.assertEqual(update.new_bytes, (b"S",))
        self.assertIsNone(update.sequence)
        self.assertEqual(tester.output, (b"F", b"S"))


if __name__ == "__main__":
    unittest.main()
