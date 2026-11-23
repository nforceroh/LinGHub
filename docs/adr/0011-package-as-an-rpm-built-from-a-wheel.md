# Package as an RPM built from a wheel

LinGHub ran only from a clone, through an editable install, with a service
script that rewrote the unit to point at the clone's virtualenv. That made the
clone load-bearing: moving or deleting it broke the running app, and there was
no way to install LinGHub on a machine that did not have the source.

## Decision

The wheel is the artifact. `scripts/build-rpm.sh` builds it, and
`packaging/linghub.spec` wraps it into one RPM: `linghub`, holding the daemon,
the CLI, the window and the tray. The RPM installs the
wheel's `.dist-info` alongside the code, so a packaged install reports its
build-time version through `importlib.metadata` — the fallback ADR-0009
already described.

An earlier version of this decision split the RPM into `python3-linghub` (daemon
and CLI, GTK-free) and `linghub-ui` (the window and tray), so a headless machine
could run the daemon without a desktop stack. No such install ever happened,
and no user of this project has a mouse plugged into a machine without a
desktop; the split paid two install commands, two names and two upgrade
invocations for a scenario that never arrived. One package needs the GUI
libraries unconditionally, which is what every real install wanted anyway,
and the CLI stays GTK-free in code (the `ui` and `tray` subcommands import
`gi` lazily), so a future split could be recovered from the same wheel if a
headless consumer ever shows up.

A clone install and a packaged install coexist. The clone's unit is
`linghub-dev.service`; the packaged one owns `linghub.service` in
`/usr/lib/systemd/user`. A unit in the user directory shadows one in the
system directory, so the two names must differ or the clone silently wins.

## Considered Options

- **A frozen binary (PyInstaller)** — tried, and it works: an 80 MB one-file
  binary ran `--version`, `list`, `ui` and `tray`. Rejected because it is not
  self-contained (PyGObject is a system library, so GTK4, libadwaita and the
  typelibs still come from the host), it unpacks to `/tmp` on every start, it
  breaks the tray's "Open LinGHub" (which spawns `sys.executable -m
  linghub.cli ui`, and a frozen `sys.executable` is the binary), and Fedora
  rejects bundled binaries, so it could not be packaged for Fedora at all.
- **An AppImage** — the same bundling problem with a larger surface: GTK4
  themes, gschemas and portals all need shipping, and the result is the
  wrong-theme class of bug. It also cannot install a systemd user unit, which
  the daemon needs, and ratbagd is a host package on the system bus either
  way. Flatpak would be the better portable channel if one is ever wanted.
- **A wheel into a fixed-path virtualenv** — no root, but the venv must be
  created with `--system-site-packages` to see `gi`, and it is a mutable
  directory with no upgrade or uninstall path.
- **Two subpackages (`python3-linghub` + `linghub-ui`)** — tried first, and it
  works, but it serves a headless install that nobody has. Reverted in favour
  of one package whose GUI libraries are ordinary requirements.

## Consequences

- `scripts/build-rpm.sh` refuses a version containing `+` or `dirty`: a
  packaged release must come from a tag on a clean tree, or the RPM version
  field would change with every commit.
- The build script smoke-tests the package by unpacking it with `rpm2cpio`
  and importing it, so a `%files` list that misses an asset fails the build.
- The diagram and the placed hotspots ship inside the package
  (`linghub/ui/images/`, `linghub/ui/hotspots.json`), because a packaged
  install has no clone to find them in. `linghub hotspots` writes to
  `~/.local/share/linghub/hotspots.json`, since the package directory is
  read-only.
- `linghub init` writes the factory default config, and the unit runs it with
  `--if-missing` before the daemon. A missing config is handled once; a
  broken one is still left alone so the daemon fails loudly on it.
- The RPMs are published as release artifacts on GitHub rather than through
  COPR. A release is a tag plus two attached files, which needs no Fedora
  account and no extra service; COPR would add a repository to subscribe to,
  and the spec is the same either way. If a `dnf` repository is ever wanted,
  the built RPMs are what it would serve.
