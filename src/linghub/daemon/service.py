"""The LinGHub daemon: watch for games and load the matching profile.

Runs as a user service. It needs no privileges because ratbagd already owns
the privileged hardware path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from .. import config as config_module
from ..discovery.detector import detect
from ..discovery.gamemode import GameModeClient
from dbus_fast import DBusError as DBusFastError

from ..hardware.ratbag import DeviceNotFound, RatbagClient
from ..hardware.writer import ProfileWriter, WriteError
from ..domain.profile import Binding
from .dbus_service import PATH, SERVICE, ManagerInterface
from .snapshot import StateSnapshot
from .state import DaemonState
from .watcher import ConfigWatcher


GAMING_SLOT = 1
DESKTOP_SLOT = 0

logger = logging.getLogger("linghub.daemon")


class ConfigStartupError(RuntimeError):
    """The config is missing or invalid, so the daemon cannot start.

    Distinct from a transient failure: systemd should not restart on this.
    """


class Daemon:
    def __init__(
        self,
        config_path: Path | str = config_module.DEFAULT_CONFIG_PATH,
        poll_interval: float | None = None,
    ):
        self._config_path = Path(config_path)
        self._poll_interval = poll_interval
        self._state: DaemonState | None = None
        self._writer: ProfileWriter | None = None
        self._bus: MessageBus | None = None
        self._pending: str | None = None
        self._watcher = ConfigWatcher(self._config_path)
        self._wakeup = asyncio.Event()
        self._gamemode: GameModeClient | None = None
        self._session_bus: MessageBus | None = None
        self._interface: ManagerInterface | None = None
        self._report_rates: list[int] = []
        self._manual_override: str | None = None
        self._detected_game: str | None = None

    async def _connect(self) -> None:
        self._bus = await asyncio.wait_for(
            MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5
        )
        client = RatbagClient(self._bus)
        device = await client.find_device()
        self._writer = ProfileWriter(client, device)
        # A missing capability must not stop the daemon: an empty list just
        # means the UI offers no rate choices.
        self._report_rates = await client.report_rates(device)
        logger.info(
            "using device %s at %s (report rates %s)",
            device.name, device.path, self._report_rates,
        )

    async def _connect_with_retry(self, interval: float) -> None:
        """Wait for the device to appear rather than exiting.

        A missing device is usually transient: the mouse may be unplugged, or
        a stale Wine process may be holding a deleted hidraw node. Exiting
        would mean the service stays dead until someone notices, so retry and
        log the diagnosis once.
        """
        reported = False
        while True:
            try:
                await self._connect()
                return
            except DeviceNotFound as exc:
                if not reported:
                    logger.error("%s", exc)
                    logger.info("retrying every %ss until the device appears", interval)
                    reported = True
                await asyncio.sleep(interval)

    async def _export_interface(self) -> None:
        """Publish the manager interface on the session bus.

        Failure here is not fatal: the daemon still switches profiles, it just
        cannot be controlled by the UI.
        """
        try:
            self._session_bus = await asyncio.wait_for(
                MessageBus(bus_type=BusType.SESSION).connect(), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as exc:
            logger.warning("cannot publish D-Bus interface: %s", exc)
            return

        self._interface = ManagerInterface(
            on_load_profile=self._request_profile,
            on_reload=self._request_reload,
            get_state=self._snapshot,
            get_bindings=self._get_bindings,
            on_set_binding=self._request_set_binding,
            get_leds=self._get_leds,
            on_set_leds=self._request_set_leds,
            get_resolutions=self._get_resolutions,
            get_report_rate=self._get_report_rate,
            get_report_rates=self._get_report_rates,
            on_set_resolution=self._request_set_resolution,
            on_set_report_rate=self._request_set_report_rate,
        )
        self._session_bus.export(PATH, self._interface)
        await self._session_bus.request_name(SERVICE)
        logger.info("published %s on the session bus", SERVICE)

    def _snapshot(self) -> StateSnapshot:
        assert self._state is not None
        return StateSnapshot(
            profile_names=tuple(p.name for p in self._state.config.profiles),
            loaded_profile=self._state.loaded_profile,
            detected_game=self._detected_game,
            desktop_profile=self._state.config.desktop_profile,
        )

    def _request_profile(self, name: str) -> bool:
        """Handle a manual profile request from the UI.

        The override is cleared as soon as the detected game changes, so a
        manual choice does not fight detection indefinitely.
        """
        assert self._state is not None
        if self._state.config.profile_named(name) is None:
            logger.warning("LoadProfile(%r): no such profile", name)
            return False
        self._manual_override = name
        self._wake()
        return True

    def _request_reload(self) -> bool:
        self._watcher.reset()
        self._wake()
        return True

    def _get_bindings(self, profile_name: str) -> dict[int, tuple[str, object]]:
        """Every binding in a profile, as plain values for D-Bus."""
        if self._state is None:
            return {}
        profile = self._state.config.profile_named(profile_name)
        if profile is None:
            return {}
        return {
            index: (binding.type, binding.value)
            for index, binding in profile.bindings.items()
        }

    def _request_set_binding(
        self, profile_name: str, index: int, kind: str, value: object
    ) -> bool:
        """Change one binding, persist it, and let the next tick push it.

        The config is updated in memory first so the UI sees the change
        immediately; if saving fails the in-memory change is rolled back, so
        the running state never disagrees with the file.
        """
        assert self._state is not None

        if kind not in Binding.VALID_TYPES:
            logger.warning("SetBinding: unknown binding type %r", kind)
            return False
        try:
            binding = Binding(type=kind, value=value)
        except ValueError as exc:
            logger.warning("SetBinding: %s", exc)
            return False

        previous = self._state.config
        if not self._state.set_binding(profile_name, index, binding):
            logger.warning("SetBinding(%r): no such profile", profile_name)
            return False

        if not self._save_config():
            self._state.config = previous
            return False

        logger.info(
            "binding %d of %r is now %s(%r)", index, profile_name, kind, value
        )
        self._wake()
        return True

    def _get_leds(self, profile_name: str) -> dict[int, dict]:
        """A profile's LED zones, keyed by index."""
        if self._state is None:
            return {}
        profile = self._state.config.profile_named(profile_name)
        if profile is None:
            return {}
        return {int(entry["index"]): dict(entry) for entry in profile.leds}

    def _request_set_leds(self, profile_name: str, settings: dict) -> bool:
        """Change a profile's lighting, persist it, and let the next tick push it.

        Same rollback rule as a binding change: the in-memory config is only
        kept if saving succeeds, so the running state never disagrees with the
        file.
        """
        assert self._state is not None

        try:
            # Reuse the config validator so the ranges cannot drift from what
            # a hand-written file is allowed to contain.
            config_module.validate_led(dict(settings, index=0))
        except config_module.ConfigError as exc:
            logger.warning("SetLeds: %s", exc)
            return False

        previous = self._state.config
        if not self._state.set_leds(profile_name, settings):
            logger.warning("SetLeds(%r): no such profile", profile_name)
            return False

        if not self._save_config():
            self._state.config = previous
            return False

        logger.info("leds of %r are now %r", profile_name, settings)
        self._wake()
        return True

    def _get_resolutions(self, profile_name: str) -> tuple:
        """A profile's DPI slots as (dpi, is_default, is_disabled) in order."""
        if self._state is None:
            return ()
        profile = self._state.config.profile_named(profile_name)
        if profile is None:
            return ()
        return tuple(
            (
                int(slot.get("dpi", 0)),
                bool(slot.get("default")),
                bool(slot.get("disabled")),
            )
            for slot in profile.resolutions
        )

    def _get_report_rate(self, profile_name: str) -> int:
        if self._state is None:
            return 0
        profile = self._state.config.profile_named(profile_name)
        return int(profile.report_rate or 0) if profile else 0

    def _get_report_rates(self, profile_name: str) -> tuple:
        """The rates the device accepts, cached from the last connect.

        Read from the device rather than hard-coded, so a variant offering a
        different set is not presented with the wrong choices.
        """
        return tuple(self._report_rates)

    def _request_set_resolution(
        self, profile_name: str, index: int, dpi: int, make_default: bool, disabled: bool
    ) -> bool:
        return self._apply_and_save(
            lambda: self._state.set_resolution(
                profile_name, index, dpi,
                make_default=make_default, disabled=disabled,
            ),
            f"SetResolution({profile_name!r}, {index}, {dpi})",
        )

    def _request_set_report_rate(self, profile_name: str, rate: int) -> bool:
        return self._apply_and_save(
            lambda: self._state.set_report_rate(profile_name, rate),
            f"SetReportRate({profile_name!r}, {rate})",
        )

    def _apply_and_save(self, change, description: str) -> bool:
        """Run a config change, persist it, and roll back if saving fails.

        Every write path needs the same rule: the running config must never
        disagree with the file, so a failed save restores the previous config.
        """
        assert self._state is not None
        previous = self._state.config
        if not change():
            logger.warning("%s: rejected", description)
            return False
        if not self._save_config():
            self._state.config = previous
            return False
        logger.info("%s applied", description)
        self._wake()
        return True

    def _save_config(self) -> bool:
        assert self._state is not None
        try:
            config_module.save(self._config_path, self._state.config)
        except (config_module.ConfigError, OSError) as exc:
            logger.error("cannot save config: %s", exc)
            return False
        # The file we just wrote is the daemon's own change, not an external
        # edit. resync() accepts the new stat signature without reporting a
        # change; reset() would do the opposite and force a reload.
        self._watcher.resync()
        return True

    def _reload_config(self) -> bool:
        try:
            config = config_module.load(self._config_path)
        except config_module.ConfigError as exc:
            logger.error("config error: %s", exc)
            return False
        if self._state is None:
            self._state = DaemonState(config=config)
        else:
            self._state.config = config
        return True

    def _reload_if_changed(self) -> None:
        """Reload the config when the file changes, keeping the old one on error.

        A broken edit must not take the daemon down: the previous config stays
        in force and the error is logged, so the user can fix the file and the
        next change is picked up.
        """
        if not self._watcher.changed():
            return

        try:
            config = config_module.load(self._config_path)
        except config_module.ConfigError as exc:
            logger.error("config reload failed, keeping the previous config: %s", exc)
            return

        assert self._state is not None
        self._state.config = config
        logger.info("reloaded config: %d profile(s)", len(config.profiles))

    async def _reconnect(self, attempts: int = 3, delay: float = 1.0) -> None:
        """Try to reconnect to the device after it disappeared.

        Bounded rather than looping until the device returns: blocking here
        would stop the tick loop, so games would stop being detected while the
        mouse is unplugged. A few quick attempts handle a KVM flick; a longer
        absence is picked up by the next tick.
        """
        self._writer = None
        for attempt in range(attempts):
            try:
                await self._connect()
                if attempt:
                    logger.info("device is back")
                return
            except DeviceNotFound as exc:
                if attempt == 0:
                    logger.warning("%s; will retry", exc)
                await asyncio.sleep(delay * (attempt + 1))
        logger.warning("device still absent; detection continues without it")

    async def _apply_target(self) -> None:
        """Load the target profile if it differs from what is loaded."""
        assert self._state is not None
        if self._writer is None:
            await self._reconnect()
        if self._writer is None:
            # Still absent: nothing to write to. Detection keeps running and
            # the next tick tries again.
            return

        if not self._state.needs_write:
            return

        target = self._state.target_profile
        slot = DESKTOP_SLOT if target.is_desktop else GAMING_SLOT

        try:
            result = await self._writer.apply(target, slot)
        except WriteError as exc:
            # A refused write is not a missing device: keep the writer and
            # retry on the next tick.
            logger.error("failed to load profile %r: %s", target.name, exc)
            self._pending = target.name
            return
        except (RuntimeError, OSError, DBusFastError) as exc:
            # The device object is gone: a KVM switch, an unplugged cable, a
            # flat battery. The writer is stale, so drop it and reconnect
            # rather than letting this escape and killing the daemon.
            logger.warning("lost the device while writing: %s", exc)
            self._writer = None
            self._pending = target.name
            return

        self._state.mark_loaded(target.name)
        self._pending = None
        logger.info("loaded profile %r into slot %d (%d changes)", target.name, slot, len(result.changed))

        if self._interface is not None:
            self._interface.ProfileChanged(target.name)

    async def _tick(self) -> None:
        assert self._state is not None
        try:
            await self._tick_once()
        except (RuntimeError, OSError, DBusFastError) as exc:
            # One bad tick must not take the daemon down: systemd would restart
            # it, losing state and the manual override.
            logger.error("tick failed: %s", exc)

    async def _tick_once(self) -> None:
        assert self._state is not None
        self._reload_if_changed()
        detection = detect(self._state.config.profiles)

        previous_game = self._detected_game
        self._state.observe(detection)
        self._detected_game = detection.game.profile.name if detection.game else None

        # A manual choice lasts until the detected game changes, then detection
        # takes over again.
        if self._detected_game != previous_game:
            self._manual_override = None
            if self._interface is not None:
                if self._detected_game is not None:
                    self._interface.GameDetected(self._detected_game)
                elif previous_game is not None:
                    self._interface.GameExited(previous_game)

        if self._manual_override is not None:
            self._state.stack = [self._manual_override]

        await self._apply_target()

    async def run(self) -> None:
        if not self._reload_config():
            # A bad config is not transient: restarting will not fix it, so
            # exit non-zero and let systemd's RestartPreventExitStatus stop
            # the unit rather than looping.
            raise ConfigStartupError("cannot start without a valid config")

        interval = self._poll_interval or self._state.config.poll_interval
        await self._connect_with_retry(interval)
        await self._export_interface()

        # GameMode is an accelerator: when it fires, run a tick immediately
        # instead of waiting for the next poll. When it is absent the poll
        # loop still detects every game, just less promptly.
        self._gamemode = GameModeClient(on_change=self._wake)
        if await self._gamemode.connect():
            if self._gamemode.available:
                logger.info("watching for games every %ss, with GameMode signals", interval)
            else:
                logger.info("watching for games every %ss (GameMode not running)", interval)
        else:
            logger.info("watching for games every %ss (GameMode not available)", interval)

        try:
            while True:
                await self._tick()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
                self._wakeup.clear()
        finally:
            self._gamemode.disconnect()
            if self._session_bus is not None:
                self._session_bus.disconnect()
            if self._bus is not None:
                self._bus.disconnect()

    def _wake(self) -> None:
        """Ask the run loop to tick now rather than at the next interval."""
        self._wakeup.set()
