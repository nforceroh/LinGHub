# LinGHub

A profile manager for the Logitech G502 family on Linux. It edits named profiles
— button bindings, DPI table, LED settings and report rate — and loads the right
one into the mouse when a game starts.

LinGHub talks to [ratbagd](https://github.com/libratbag/libratbag) over the
system D-Bus. It does not use `ratbagctl`, and it does not create virtual input
devices: every binding is written to the mouse's own memory, so games see real
hardware events.

## Status

Early. The hardware client and CLI work; game detection and the UI are in
progress.

## Requirements

- Linux with ratbagd running (Fedora: `libratbag-ratbagd`)
- Python 3.11+
- A G502 variant supported by libratbag

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```bash
linghub list          # list hardware profiles
linghub switch 1      # activate profile 1
linghub detect        # report which configured game is running
linghub run           # run the daemon in the foreground
```

`switch` reports that ratbagd has queued a commit. Commits are asynchronous, so
that message does not confirm the hardware write succeeded.

## Running as a service

```bash
./scripts/install-service.sh     # install and start the user service
./scripts/uninstall-service.sh   # stop and remove it
```

The daemon watches for games and loads the matching profile into slot 1,
restoring the desktop profile into slot 0 when the last game exits. It reloads
its config when the file changes, and keeps the previous config if an edit is
invalid rather than exiting.

```bash
systemctl --user status linghub.service
journalctl --user -u linghub.service -f
```

## Configuration

The daemon reads `~/.config/linghub/config.json`. See
[config.example.json](config.example.json) for the shape. One file holds every
profile plus application settings (ADR-0004).

## Documentation

- [Button map](docs/button-map.md) — manual number, G-name and ratbag index for
  every button, plus the supported variants
- [Glossary](GLOSSARY.md) — the vocabulary this project uses
- [Architecture decisions](docs/adr/) — why the design is the way it is

## Legacy scripts

`utils/` holds the scripts that predate LinGHub. They use `ratbagctl` and their
own `g502-profiles.json`, which is **not** the format LinGHub reads. They are
kept for reference and will be removed.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t .
```
