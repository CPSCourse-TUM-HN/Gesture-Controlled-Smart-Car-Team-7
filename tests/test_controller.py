from __future__ import annotations

import unittest
from unittest.mock import patch

import serial

from tools.controller import (
    CommandSender,
    KEY_COMMANDS,
    MACOS_DEFAULT_PORT,
    default_port,
    send_command,
)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps.append(seconds)


class FakeConnection:
    def __init__(self, flush_raises: bool = False) -> None:
        self.payloads: list[bytes] = []
        self.flush_raises = flush_raises
        self.flush_called = False

    def write(self, payload: bytes) -> int:
        self.payloads.append(payload)
        return len(payload)

    def flush(self) -> None:
        self.flush_called = True
        if self.flush_raises:
            raise serial.SerialTimeoutException("Write timeout")


class DefaultPortTests(unittest.TestCase):
    def test_non_windows_default_port_is_robos_device(self) -> None:
        self.assertEqual(default_port(os_name="posix", environ={}), MACOS_DEFAULT_PORT)

    def test_windows_default_port_is_robos_device(self) -> None:
        self.assertEqual(default_port(os_name="nt", environ={}), MACOS_DEFAULT_PORT)

    def test_environment_variable_overrides_platform_default(self) -> None:
        self.assertEqual(
            default_port(os_name="nt", environ={"GCSC_PORT": "COM7"}),
            "COM7",
        )


class KeyboardCommandTests(unittest.TestCase):
    def test_s_key_is_backward(self) -> None:
        self.assertEqual(KEY_COMMANDS["s"], ("B", "backward"))


class CommandSenderTests(unittest.TestCase):
    def test_first_command_sends_immediately(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)
        connection = object()

        with patch("tools.controller.send_command") as send:
            sent = sender.send(connection, "F")

        self.assertTrue(sent)
        send.assert_called_once_with(connection, "F")

    def test_duplicate_command_is_skipped(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.2
            self.assertFalse(sender.send("connection", "F"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["F"])

    def test_movement_change_inside_interval_waits_stops_then_sends(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.1
            self.assertTrue(sender.send("connection", "L"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["F", "S", "L"])
        self.assertEqual(clock.now, 0.5)

    def test_movement_change_after_interval_stops_then_sends(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.2
            self.assertTrue(sender.send("connection", "L"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["F", "S", "L"])
        self.assertEqual(clock.now, 0.5)

    def test_opposite_command_stops_before_sending(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.2
            self.assertTrue(sender.send("connection", "B"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["F", "S", "B"])
        self.assertEqual(clock.now, 0.5)

    def test_spin_to_arc_change_stops_before_sending(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "A"))
            clock.now += 0.2
            self.assertTrue(sender.send("connection", "R"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["A", "S", "R"])
        self.assertEqual(clock.now, 0.5)

    def test_movement_after_stop_sends_without_extra_stop(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.2
            self.assertTrue(sender.send("connection", "S", force=True))
            clock.now += 0.2
            self.assertTrue(sender.send("connection", "B"))

        self.assertEqual([call.args[1] for call in send.call_args_list], ["F", "S", "B"])

    def test_forced_stop_inside_interval_waits_and_sends(self) -> None:
        clock = FakeClock()
        sender = CommandSender(clock=clock, sleeper=clock.sleep)

        with patch("tools.controller.send_command") as send:
            self.assertTrue(sender.send("connection", "F"))
            clock.now += 0.1
            self.assertTrue(sender.send("connection", "S", force=True))

        self.assertEqual(clock.now, 0.2)
        self.assertEqual([call.args[1] for call in send.call_args_list], ["F", "S"])


class SerialSendTests(unittest.TestCase):
    def test_send_writes_command_without_flushing(self) -> None:
        connection = FakeConnection()

        with patch("tools.controller.is_disconnected", return_value=False):
            send_command(connection, "F")

        self.assertEqual(connection.payloads, [b"F"])
        self.assertFalse(connection.flush_called)

    def test_send_ignores_flush_timeout_because_flush_is_not_called(self) -> None:
        connection = FakeConnection(flush_raises=True)

        with patch("tools.controller.is_disconnected", return_value=False):
            send_command(connection, "B")

        self.assertEqual(connection.payloads, [b"B"])
        self.assertFalse(connection.flush_called)

    def test_incomplete_write_raises_serial_exception(self) -> None:
        connection = FakeConnection()

        def incomplete_write(payload: bytes) -> int:
            connection.payloads.append(payload)
            return 0

        connection.write = incomplete_write

        with patch("tools.controller.is_disconnected", return_value=False):
            with self.assertRaises(serial.SerialException):
                send_command(connection, "F")


if __name__ == "__main__":
    unittest.main()
