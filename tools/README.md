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
