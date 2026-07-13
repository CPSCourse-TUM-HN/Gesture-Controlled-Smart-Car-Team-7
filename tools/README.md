# Tools

## Controller

`gcsc-controller` is a keyboard controller for manually debugging the car over Bluetooth serial.

To use this script, you have to:

1. Pair with the Bluetooth device named `roboS`.
2. Use the serial port exposed by the paired device. The default is
   `/dev/cu.roboS` on all platforms, including Windows. You can override it
   with `--port` or the `GCSC_PORT` environment variable.

```sh
uv run gcsc-controller
```

Instructions are printed when the tool starts.

Note that Windows support is implemented but untested.

## Gesture Controller

`gcsc-gesture-controller` uses MediaPipe Hands and a webcam to control the car
over the same Bluetooth serial connection.

```sh
uv run gcsc-gesture-controller
```

The controller automatically reads custom gestures from
`~/.gcsc/gesture-config.json`. Use `--config PATH` to select another file. A
missing file is valid and leaves the original gesture controls unchanged; an
invalid or unsupported file stops startup before the serial port is opened.

Gesture mapping:

- index finger up: forward
- index finger down: backward
- index finger left in the preview: left
- index finger right in the preview: right
- open palm fingers left in the preview: spin left
- open palm fingers right in the preview: spin right
- fist: stop

If no valid gesture is detected for a short timeout, the controller sends stop.
Use `q` or `Esc` in the preview window to stop and exit.

When a custom pose matches, it takes priority over the ordinary movement
gestures. Hold it for 0.4 seconds to start its configured action sequence. A
held pose runs once and must disappear for 0.3 seconds before it can trigger
again. While a sequence runs, other movement gestures are ignored, but a fist,
`q`, or `Esc` immediately requests stop. Every sequence also stops
automatically after its last step.

## Custom Gesture Configurator

Start the English Qt desktop configurator with:

```sh
uv run gcsc-gesture-configurator
```

Use `--camera INDEX` for another camera and `--config PATH` to edit a different
configuration. The configurator does not connect to Bluetooth.

To create a gesture:

1. Click **New Gesture**, enter a unique name, and click **Record / Re-record
   Pose**.
2. After the three-second countdown, keep one hand and pose steady until 30
   consecutive frames are captured.
3. Add and arrange one or more actions. Available actions are Forward (`F`),
   Backward (`B`), Steer Left/Right (`L`/`R`), Spin Left/Right (`A`/`D`), and
   Stop (`S`).
4. Click **Save Gesture**, then **Save Configuration**.

The step-duration setting applies to every action in every sequence. Duplicate
adjacent actions are allowed and extend a motion for another step. The fist is
reserved for emergency stop, and two templates for the same hand cannot be so
similar that their match ranges overlap. Left- and right-hand recordings are
kept distinct; record a separate gesture to support the other hand.

### Serial output test

The **Serial Output Test (Dry Run)** panel exercises the saved gesture through
the same template matcher, stable trigger, sequence runner, safety transition,
and command scheduler used by the live controller. It displays every byte that
would be written to the Bluetooth serial connection, including inserted stop
bytes and the automatic final stop. Writes go to an in-memory recorder, so the
test never connects to or moves the car.

This verifies host-side output only. The one-byte Bluetooth protocol has no
acknowledgement or telemetry, so it cannot confirm that a physical ESP32
received or executed a byte. Use the keyboard controller and raise the wheels
for physical end-to-end checks.
