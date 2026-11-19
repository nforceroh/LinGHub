"""Command-line entry point for LinGHub."""

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass

from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusFastError

from . import config as config_module
from . import version
from .discovery.detector import Detection, detect
from .hardware.active_slot import SlotReadings
from .hardware.ratbag import RatbagClient


_UNSET = object()


def _print_detection(detection: Detection, explain: bool) -> None:
    match = detection.game
    if match is None:
        print("no game detected")
    else:
        print(f"{match.game.executable} -> profile {match.profile.name!r} (pid {match.process.pid})")

    if not explain:
        return

    print(f"\nconsidered {detection.considered} process(es)")
    for rejection in detection.rejections:
        print(f"  skip  pid {rejection.process.pid:<7} {rejection.process.executable_name}: {rejection.reason}")
    for match in detection.matches:
        print(f"  match pid {match.process.pid:<7} {match.process.executable_name} -> {match.profile.name}")


def _load_config(args: argparse.Namespace):
    try:
        return config_module.load(args.config)
    except config_module.ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return None


def _detect_once(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1
    _print_detection(detect(config.profiles), args.explain)
    return 0


def _detect_watch(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if config is None:
        return 1

    print(f"watching for games every {config.poll_interval}s (ctrl-c to stop)")
    previous: object = _UNSET
    try:
        while True:
            detection = detect(config.profiles)
            match = detection.game
            current = match.profile.name if match else None
            if current != previous:
                if match is None:
                    print("no game detected")
                else:
                    print(f"{match.game.executable} -> profile {match.profile.name!r} (pid {match.process.pid})")
                if args.explain:
                    _print_detection(detection, explain=True)
                previous = current
            time.sleep(config.poll_interval)
    except KeyboardInterrupt:
        print()
        return 0


def _run_daemon(args: argparse.Namespace) -> int:
    import logging

    from .daemon.service import ConfigStartupError, Daemon

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    daemon = Daemon(config_path=args.config, poll_interval=args.interval)
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        return 0
    except ConfigStartupError as exc:
        # Exit 78 (EX_CONFIG) so the unit can refuse to restart on it.
        print(f"Error: {exc}", file=sys.stderr)
        return 78
    except (RuntimeError, OSError, DBusFastError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_status() -> int:
    """Report what the daemon is doing, then what the mouse itself says (#5).

    The mouse section is read here, not taken from the daemon: it is for
    seeing the truth when the daemon is down or wrong. It never changes the
    exit status, which still says whether the daemon answered.
    """
    from . import daemon_access

    # The hardware code logs disagreements and warnings for the daemon's
    # journal; here they'd be stray lines around the report.
    logging.getLogger("linghub").setLevel(logging.ERROR)

    status = 0
    try:
        state = daemon_access.state()
    except daemon_access.DaemonUnavailable as exc:
        print(
            f"Error: the daemon is not running or not answering ({exc}).",
            file=sys.stderr,
        )
        state, status = None, 1
    except (RuntimeError, OSError) as exc:
        # A failure inside the call is not a missing daemon, so say so.
        print(f"Error: {exc}", file=sys.stderr)
        state, status = None, 1

    if state is not None:
        print(format_status(
            active=state.active_profile,
            detected=state.detected_game or None,
            desktop=state.desktop_profile,
            profiles=state.profiles,
        ))
        names = slot_names(desktop=state.desktop_profile, loaded=state.active_profile or None)
    else:
        names = slot_names(desktop=_desktop_from_config(), loaded=None)

    if state is not None:
        print()
    print(format_mouse(asyncio.run(_read_mouse()), names))
    return status


def _desktop_from_config() -> str | None:
    """The desktop profile's name from the config file, for when the daemon is down."""
    try:
        return config_module.load(config_module.DEFAULT_CONFIG_PATH).desktop_profile
    except (config_module.ConfigError, OSError):
        return None


@dataclass(frozen=True)
class MouseReport:
    """What `status` found when it asked the mouse itself (#5)."""

    name: str | None = None
    node: str | None = None
    readings: "SlotReadings | None" = None
    absent: bool = False
    misconfigured: str | None = None
    holders: tuple = ()


async def _read_mouse() -> MouseReport:
    """Find the G502 and ask it, through the adapter the daemon uses."""
    from .hardware import diagnose
    from .hardware.failures import MouseAbsent, MouseLost, MouseMisconfigured
    from .hardware.mouse import RatbagConnector

    connector = RatbagConnector()
    try:
        mouse = await connector.connect()
        readings = await mouse.slot_readings()
    except (MouseAbsent, MouseLost):
        # Only now are held nodes worth a mention: as a lead, never a cause.
        return MouseReport(absent=True, holders=tuple(diagnose.find_deleted_hidraw_holders()))
    except MouseMisconfigured as exc:
        return MouseReport(misconfigured=str(exc))
    finally:
        connector.disconnect()
    node = "/dev/" + mouse.device.path.rstrip("/").rsplit("/", 1)[-1]
    return MouseReport(name=mouse.device.name, node=node, readings=readings)


def slot_names(*, desktop: str | None, loaded: str | None) -> dict[int, str]:
    """Which profile each slot holds, as far as `status` can know.

    Slot 0 always holds the desktop profile. Slot 1 holds whichever gaming
    profile the daemon last loaded, which only the daemon knows.
    """
    names: dict[int, str] = {}
    if desktop:
        names[0] = desktop
    if loaded and loaded != desktop:
        names[1] = loaded
    return names


def format_mouse(report: MouseReport, names: dict[int, str]) -> str:
    """Render the mouse section of `status`."""
    if report.misconfigured is not None:
        return f"Mouse          : {report.misconfigured}"
    if report.absent or report.readings is None:
        lines = ["Mouse          : not found (KVM, unplugged or asleep)"]
        if report.holders:
            lines.append(
                "Processes holding deleted device nodes (a possible lead, often harmless):"
            )
            lines.extend(f"  pid {h.pid} {h.command} ({h.node})" for h in report.holders)
        return "\n".join(lines)

    def slot(number: int | None) -> str:
        if number is None:
            return "none"
        return f"{number} ({names[number]})" if number in names else str(number)

    r = report.readings
    ratbagd = f"ratbagd says {slot(r.believed)}"
    if r.reason is None:
        value = slot(r.mouse) + ("" if r.mouse == r.believed else f" · {ratbagd}")
    elif r.reason == "no answer":
        value = f"unknown (the mouse did not answer; asleep?) · {ratbagd}"
    elif r.reason == "host mode":
        value = "none (host mode: another tool controls the mouse)"
    elif r.reason == "no permission":
        value = f"{slot(r.believed)} · ratbagd's answer; no permission to read the mouse"
    else:
        value = f"{slot(r.believed)} · ratbagd's answer; the device node could not be confirmed"
    return f"Mouse          : {report.name} on {report.node}\nActive slot    : {value}"


async def _run_hardware(args: argparse.Namespace) -> None:
    bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5)
    try:
        client = RatbagClient(bus)
        device = await client.find_device()
        if args.command == "list":
            print(f"{device.name} ({device.path})")
            for profile in await client.profiles(device):
                status = " (active)" if profile.active else " (disabled)" if profile.disabled else ""
                print(f"  profile {profile.index}{status}")
        elif await client.switch(device, args.index):
            print(f"Profile {args.index} selected; hardware commit queued by ratbagd.")
            print("Commit is asynchronous; the hardware write is not confirmed.")
        else:
            print(f"Profile {args.index} is already active; no changes made.")
    finally:
        bus.disconnect()


def format_status(
    *, active: str, detected: str | None, desktop: str, profiles: tuple[str, ...]
) -> str:
    """Render the running daemon's state as a short report."""
    lines = [
        f"Active profile : {active or 'unknown'}",
        f"Detected game  : {detected or 'no game'}",
        f"Desktop profile: {desktop}",
        f"Profiles       : {len(profiles)} ({', '.join(profiles)})",
    ]
    return "\n".join(lines)


def format_version(own: str, daemon: version.DaemonVersion) -> str:
    """This process's app version, the daemon's, and a note if they differ."""
    line, note = version.describe(own, daemon)
    lines = [f"LinGHub {own}", line]
    if note is not None:
        lines.append(note)
    return "\n".join(lines)


class _VersionAction(argparse.Action):
    """Print the versions and exit, before argparse demands a subcommand."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(format_version(version.current(), _daemon_version()))
        parser.exit()


def _daemon_version() -> version.DaemonVersion:
    """What the running daemon is running, or why we can't say."""
    from . import daemon_access

    async def read(client):
        return await client.daemon_version()

    try:
        return daemon_access.call(read)
    except daemon_access.DaemonUnavailable:
        return version.DaemonVersion.not_running()
    except (RuntimeError, OSError, TimeoutError):
        return version.DaemonVersion.unreadable()


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage G502 hardware profiles via ratbagd.")
    parser.add_argument(
        "--version", action=_VersionAction,
        help="show this version and the running daemon's, then exit",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list hardware profiles")

    switch = commands.add_parser("switch", help="activate a hardware profile")
    switch.add_argument("index", type=int, help="profile index")

    detect_cmd = commands.add_parser("detect", help="report which configured game is running")
    detect_cmd.add_argument("--config", default=config_module.DEFAULT_CONFIG_PATH, help="config file path")
    detect_cmd.add_argument("--watch", action="store_true", help="poll and report changes")
    detect_cmd.add_argument("--explain", action="store_true", help="show why each process did or did not match")

    run_cmd = commands.add_parser("run", help="run the daemon: watch for games and load profiles")
    run_cmd.add_argument("--config", default=config_module.DEFAULT_CONFIG_PATH, help="config file path")
    run_cmd.add_argument("--interval", type=float, default=None, help="override the poll interval")

    commands.add_parser("ui", help="open the graphical interface")

    commands.add_parser(
        "status", help="report what the running daemon is doing"
    )

    commands.add_parser("tray", help="show a tray icon for switching profiles")

    hotspots_cmd = commands.add_parser(
        "hotspots", help="place button hotspots on a mouse image"
    )
    hotspots_cmd.add_argument("--image", default="images/g502_trans.png", help="image to annotate")
    hotspots_cmd.add_argument("--out", default=None, help="where to write the hotspots")

    args = parser.parse_args()

    if args.command == "hotspots":
        from .ui.hotspot_editor import DEFAULT_OUTPUT, main as editor_main

        argv = ["--image", args.image]
        if args.out is not None:
            argv += ["--out", args.out]
        return editor_main(argv)

    if args.command == "status":
        return _run_status()

    if args.command == "tray":
        # Imported lazily: the tray is GTK3 and the rest of the app is GTK4.
        from .tray import main as tray_main

        return tray_main()

    if args.command == "ui":
        from .ui.app import main as ui_main

        return ui_main()

    if args.command == "detect":
        return _detect_watch(args) if args.watch else _detect_once(args)

    if args.command == "run":
        return _run_daemon(args)

    from .hardware.failures import MouseFailure

    try:
        asyncio.run(_run_hardware(args))
    except (MouseFailure, RuntimeError, OSError, DBusFastError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
