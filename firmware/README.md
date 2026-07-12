# Firmware

## Preparations

To install ESP32 support:

```sh
arduino-cli core install esp32:esp32
```

To generate `compile_commands.json` for IDE support:

```sh
arduino-cli compile firmware --fqbn esp32:esp32:esp32 --build-path ./build --only-compilation-database
```

## Workflows

To compile and flash the firmware:

```sh
arduino-cli compile firmware --fqbn esp32:esp32:esp32 --build-path ./build --port <device> --upload
```
