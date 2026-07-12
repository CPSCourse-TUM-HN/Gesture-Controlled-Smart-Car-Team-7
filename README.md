# Gesture-Controlled Smart Car

## Content

- `firmware`: firmware for the ESP32 chip.
- `tools`: scripts for debugging and development.

## Development

It is recommended to use [mise](https://mise.jdx.dev/) for reproducible environment and [direnv](https://direnv.net/) for better developer experience.

```sh
mise trust
direnv allow
```

Note that we use [uv](https://docs.astral.sh/uv/) for python dependency management.
