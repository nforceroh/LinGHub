"""Command-line entry point for LinGHub."""

import argparse
import asyncio
import sys
import time

from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusFastError

from . import config as config_module
from .discovery.detector import Detection, detect
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage G502 hardware profiles via ratbagd.")
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

    if args.command == "ui":
        from .ui.app import main as ui_main

        return ui_main()

    if args.command == "detect":
        return _detect_watch(args) if args.watch else _detect_once(args)

    if args.command == "run":
        return _run_daemon(args)

    try:
        asyncio.run(_run_hardware(args))
    except (RuntimeError, OSError, DBusFastError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
