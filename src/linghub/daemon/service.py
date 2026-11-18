"""The LinGHub daemon: watch for games and load the matching profile.

Runs as a user service. It needs no privileges because ratbagd already owns
the privileged hardware path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Protocol

from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from .. import config as config_module
from ..discovery.detector import Detection, detect
from ..discovery.gamemode import GameModeClient
from dbus_fast import DBusError as DBusFastError

from ..domain.profile import Profile
from ..hardware.ratbag import DeviceNotFound
from ..hardware.writer import RatbagConnector, WriteError, WriteResult
from ..notify import Notifier, profile_message
from . import slots
from .dbus_service import PATH, SERVICE, BusAnnouncer, ManagerInterface
from .snapshot import StateSnapshot
from .state import DaemonState
from .watcher import ConfigWatcher
from .writes import Bindings, ConfigWrites, DeviceSettings, ProfileLifecycle


logger = logging.getLogger("linghub.daemon")


class ConfigStartupError(RuntimeError):
    """The config is missing or invalid, so the daemon cannot start.

    Distinct from a transient failure: systemd should not restart on this.
    """


class Mouse(Protocol):
    """What the daemon needs from a connected mouse.

    `apply` raises WriteError when the mouse refused a write; any other error
    means the mouse is gone and must be reconnected.
    """

    async def apply(self, profile: Profile, slot: int) -> WriteResult: ...

    async def active_slot(self) -> int | None: ...

    async def report_rates(self) -> list[int]: ...


class MouseConnector(Protocol):
    """Connects to the mouse; `connect` raises DeviceNotFound when it is absent."""

    async def connect(self) -> Mouse: ...

    def disconnect(self) -> None: ...


class Announcer(Protocol):
    """Who the daemon tells about what it did, so clients need not poll."""

    def profile_loaded(self, name: str) -> None: ...

    def game_started(self, name: str) -> None: ...

    def game_stopped(self, name: str) -> None: ...

    def config_changed(self) -> None: ...


class Daemon:
    def __init__(
        self,
        config_path: Path | str = config_module.DEFAULT_CONFIG_PATH,
        poll_interval: float | None = None,
        detector: Callable[[list], Detection] = detect,
        mouse: MouseConnector | None = None,
        announce: Announcer | None = None,
        reconnect_delay: float = 1.0,
    ):
        self._config_path = Path(config_path)
        self._poll_interval = poll_interval
        # Detection and the mouse are injected so a test can say what is
        # running and what the hardware does without a bus or a device.
        self._detector = detector
        self._mouse = mouse if mouse is not None else RatbagConnector()
        self._bus_announcer = BusAnnouncer()
        self._announce = announce if announce is not None else self._bus_announcer
        self._reconnect_delay = reconnect_delay
        self._state: DaemonState | None = None
        self._writer: Mouse | None = None
        self._watcher = ConfigWatcher(self._config_path)
        self._wakeup = asyncio.Event()
        self._gamemode: GameModeClient | None = None
        self._session_bus: MessageBus | None = None
        self._interface: ManagerInterface | None = None
        self._report_rates: list[int] = []
        self._notifier: Notifier | None = None

        # The three collaborators the D-Bus adapter calls. They hold the config
        # edits; this class keeps the run loop and the device. Which profile
        # should be on the mouse is DaemonState's decision.
        writes = ConfigWrites(
            state=lambda: self._state,
            save=self._save_config,
            wake=self._wake,
            announce=self._announce.config_changed,
        )
        self.profiles = ProfileLifecycle(
            state=lambda: self._state,
            writes=writes,
            request_load=self._request_load,
            request_reload=self._request_reload,
        )
        self.bindings = Bindings(state=lambda: self._state, writes=writes)
        self.settings = DeviceSettings(
            state=lambda: self._state,
            writes=writes,
            report_rates=lambda: tuple(self._report_rates),
        )

    def _request_load(self, name: str) -> bool:
        """Load a named profile, overriding detection until the game changes."""
        if self._state is None or not self._state.request(name):
            return False
        self._wake()
        return True

    def _request_reload(self) -> bool:
        self._watcher.reset()
        self._wake()
        return True

    async def _connect(self) -> None:
        mouse = await self._mouse.connect()
        # A missing capability must not stop the daemon: an empty list just
        # means the UI offers no rate choices.
        self._report_rates = await mouse.report_rates()
        self._writer = mouse
        logger.info("using the mouse (report rates %s)", self._report_rates)

    async def _start_notifications(self) -> None:
        """Attach to the notification daemon, if there is one.

        Failure is not fatal: a headless machine has no notifications and must
        still switch profiles.
        """
        self._notifier = Notifier()
        await self._notifier.connect()

    async def _notify_switch(self, profile_name: str) -> None:
        """Tell the user which profile was loaded."""
        if self._notifier is None or not self._notifier.available:
            return
        summary, body = profile_message(profile_name, self._state.current_game if self._state else None)
        await self._notifier.notify(summary, body, tag="profile")

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
            profiles=self.profiles,
            bindings=self.bindings,
            settings=self.settings,
            get_state=self.snapshot,
        )
        self._session_bus.export(PATH, self._interface)
        self._bus_announcer.attach(self._interface)
        await self._session_bus.request_name(SERVICE)
        logger.info("published %s on the session bus", SERVICE)

    def snapshot(self) -> StateSnapshot:
        """What the daemon believes now, as the D-Bus adapter reports it."""
        assert self._state is not None
        return StateSnapshot(
            profile_names=tuple(p.name for p in self._state.config.profiles),
            loaded_profile=self._state.loaded_profile,
            detected_game=self._state.current_game,
            desktop_profile=self._state.config.desktop_profile,
        )

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

    def load_config(self) -> bool:
        """Read the config file; False, keeping any previous config, if it is invalid."""
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
        self._announce.config_changed()

    async def _reconnect(self, attempts: int = 3) -> None:
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
                await asyncio.sleep(self._reconnect_delay * (attempt + 1))
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
        slot = slots.slot_for(target)

        try:
            result = await self._writer.apply(target, slot)
        except WriteError as exc:
            # A refused write is not a missing device: keep the writer and
            # retry on the next tick. The retry needs no queue: mark_loaded
            # was not reached, so the fingerprint still disagrees and
            # needs_write stays true.
            logger.error("failed to load profile %r: %s", target.name, exc)
            return
        except (RuntimeError, OSError, DBusFastError) as exc:
            # The device object is gone: a KVM switch, an unplugged cable, a
            # flat battery. The writer is stale, so drop it and reconnect
            # rather than letting this escape and killing the daemon.
            logger.warning("lost the device while writing: %s", exc)
            self._writer = None
            return

        self._state.mark_loaded(target.name)
        logger.info("loaded profile %r into slot %d (%d changes)", target.name, slot, len(result.changed))

        self._announce.profile_loaded(target.name)
        await self._notify_switch(target.name)

    async def tick(self) -> None:
        """One pass: detect games, check the mouse's slot, write if needed.

        Never raises for a vanished mouse or a failed write: one bad tick must
        not take the daemon down.
        """
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
        detection = self._detector(self._state.config.profiles)

        override = self._state.manual_override
        change = self._state.observe(detection)
        if change is not None:
            if override is not None:
                logger.info("clearing the manual override for %r: the current game changed", override)
            if change.started is not None:
                self._announce.game_started(change.started)
            elif change.stopped is not None:
                self._announce.game_stopped(change.stopped)

        await self._observe_active_slot()
        await self._apply_target()

    async def _observe_active_slot(self) -> None:
        """Ask the hardware which slot is active, so drift is noticed.

        Without this the daemon compares only its own memory: a physical
        profile button, a ratbagctl call, or a KVM reconnect could move the
        active slot and the daemon would never correct it.
        """
        assert self._state is not None
        if self._writer is None:
            return
        try:
            active = await self._writer.active_slot()
        except (RuntimeError, OSError, DBusFastError) as exc:
            logger.debug("cannot read the active slot: %s", exc)
            return

        before = self._state.needs_write
        self._state.observe_active_slot(active)
        if not before and self._state.needs_write:
            logger.info(
                "the mouse is on slot %s but %r belongs in slot %s; reloading",
                active, self._state.loaded_profile, self._state.expected_slot,
            )

    async def run(self) -> None:
        if not self.load_config():
            # A bad config is not transient: restarting will not fix it, so
            # exit non-zero and let systemd's RestartPreventExitStatus stop
            # the unit rather than looping.
            raise ConfigStartupError("cannot start without a valid config")

        interval = self._poll_interval or self._state.config.poll_interval

        # Publish the interface before looking for the device. A mouse that is
        # unplugged, or on the far side of a KVM switch, must not make the
        # daemon invisible to the UI and the tray: they can still read the
        # config and see which profile *would* be loaded.
        await self._export_interface()
        await self._start_notifications()

        # Try once rather than looping here: blocking would stop the tick loop,
        # so games would go undetected for as long as the mouse was absent.
        # _apply_target reconnects on each tick until the device appears.
        try:
            await self._connect()
        except DeviceNotFound as exc:
            logger.warning("%s", exc)
            logger.info("detection will run without the device until it appears")

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
                await self.tick()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
                self._wakeup.clear()
        finally:
            if self._notifier is not None:
                self._notifier.disconnect()
            self._gamemode.disconnect()
            if self._session_bus is not None:
                self._session_bus.disconnect()
            self._mouse.disconnect()

    def _wake(self) -> None:
        """Ask the run loop to tick now rather than at the next interval."""
        self._wakeup.set()
