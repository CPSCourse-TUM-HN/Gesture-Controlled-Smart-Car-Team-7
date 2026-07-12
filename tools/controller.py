from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping

import serial

MACOS_DEFAULT_PORT = "/dev/cu.roboS"
DEFAULT_PORT_ENV_VAR = "GCSC_PORT"
BAUD_RATE = 115200
CONNECT_DELAY_SECONDS = 2.0
WRITE_TIMEOUT_SECONDS = 1.0
MIN_COMMAND_INTERVAL_SECONDS = 0.2
REVERSAL_STOP_SECONDS = 0.3
MOVEMENT_COMMANDS = frozenset({"F", "B", "L", "R", "A", "D"})


def default_port(
    os_name: str = os.name,
    environ: Mapping[str, str] = os.environ,
) -> str:
    configured_port = environ.get(DEFAULT_PORT_ENV_VAR)
    if configured_port:
        return configured_port

    return MACOS_DEFAULT_PORT


DEFAULT_PORT = default_port()

KEY_COMMANDS = {
    "w": ("F", "forward"),
    "s": ("B", "backward"),
    "a": ("L", "arc left"),
    "d": ("R", "arc right"),
    "q": ("A", "spin left"),
    "e": ("D", "spin right"),
    "x": ("S", "stop"),
    " ": ("S", "stop"),
}


class CommandSender:
    def __init__(
        self,
        min_interval_seconds: float = MIN_COMMAND_INTERVAL_SECONDS,
        reversal_stop_seconds: float = REVERSAL_STOP_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._reversal_stop_seconds = reversal_stop_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._last_sent_at: float | None = None
        self._last_command: str | None = None

    def send(
        self,
        connection: serial.Serial,
        command: str,
        *,
        force: bool = False,
    ) -> bool:
        if command == self._last_command and not force:
            return False

        if self._is_movement_change(command) and not force:
            self._wait_until_allowed()
            self._send_now(connection, "S")
            self._sleeper(self._reversal_stop_seconds)
            self._send_now(connection, command)
            return True

        if not force and not self._can_send_now():
            return False

        if force:
            self._wait_until_allowed()

        self._send_now(connection, command)
        return True

    def _is_movement_change(self, command: str) -> bool:
        return (
            command in MOVEMENT_COMMANDS
            and self._last_command in MOVEMENT_COMMANDS
            and command != self._last_command
        )

    def _can_send_now(self) -> bool:
        if self._last_sent_at is None:
            return True
        return self._clock() - self._last_sent_at >= self._min_interval_seconds

    def _wait_until_allowed(self) -> None:
        if self._last_sent_at is None:
            return

        elapsed = self._clock() - self._last_sent_at
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            self._sleeper(remaining)

    def _send_now(self, connection: serial.Serial, command: str) -> None:
        send_command(connection, command)
        self._last_sent_at = self._clock()
        self._last_command = command


CommandLimiter = CommandSender


class Keyboard:
    def __enter__(self) -> Keyboard:
        if os.name == "nt":
            import msvcrt

            self._msvcrt = msvcrt
            return self

        import termios
        import tty

        self._termios = termios
        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)
        return self

    def __exit__(self, *_: object) -> None:
        if os.name != "nt":
            self._termios.tcsetattr(
                self._fd,
                self._termios.TCSADRAIN,
                self._old_settings,
            )

    def read(self) -> str:
        if os.name == "nt":
            key = self._msvcrt.getwch()
            if key in {"\x00", "\xe0"}:
                self._msvcrt.getwch()
                return ""
            return key

        return sys.stdin.read(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Control the ESP32 car over a serial Bluetooth connection.",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"serial port to open (default: {DEFAULT_PORT})",
    )
    return parser.parse_args()


def send_command(connection: serial.Serial, command: str) -> None:
    if is_disconnected(connection):
        raise serial.SerialException("serial port disconnected")

    payload = command.encode("ascii")
    written = connection.write(payload)
    if written != len(payload):
        raise serial.SerialException("serial write incomplete")

    if is_disconnected(connection):
        raise serial.SerialException("serial port disconnected")


send = send_command


def is_disconnected(connection: serial.Serial) -> bool:
    if os.name == "nt":
        return False

    import select

    poller = select.poll()
    try:
        poller.register(
            connection.fileno(),
            select.POLLERR | select.POLLHUP | select.POLLNVAL,
        )
        return bool(poller.poll(0))
    except (OSError, ValueError, serial.SerialException):
        return True


def print_controls() -> None:
    print(
        "\n".join(
            [
                "Controls:",
                "  w/s       forward/backward",
                "  a/d       arc left/arc right",
                "  q/e       spin left/spin right",
                "  x/space   stop",
                "  Esc/C-c   stop and exit",
                "",
            ]
        )
    )


def run(port: str) -> None:
    print(f"Opening {port} at {BAUD_RATE} baud...")
    with serial.Serial(
        port,
        BAUD_RATE,
        timeout=1,
        write_timeout=WRITE_TIMEOUT_SECONDS,
    ) as connection:
        time.sleep(CONNECT_DELAY_SECONDS)
        print_controls()
        sender = CommandSender()

        with Keyboard() as keyboard:
            while True:
                key = keyboard.read()
                if key in {"\x03", "\x1b"}:
                    sender.send(connection, "S", force=True)
                    print("\nSent stop.")
                    return

                action = KEY_COMMANDS.get(key.lower())
                if action is None:
                    continue

                command, name = action
                if sender.send(connection, command, force=command == "S"):
                    print(f"{name:<10} -> {command}")


def main() -> int:
    args = parse_args()

    try:
        run(args.port)
        return 0
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
