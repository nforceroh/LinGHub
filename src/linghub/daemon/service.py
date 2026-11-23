"""The LinGHub daemon: watch for games and load the matching profile.

Runs as a user service. It needs no privileges because ratbagd already owns
the privileged hardware path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Protocol

from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from .. import config as config_module
from .. import version
from ..discovery.detector import Detection, detect
from ..discovery.gamemode import GameModeClient

from ..domain.profile import Profile
from ..hardware.failures import (
    LoadRefused, MouseAbsent, MouseLost, MouseMisconfigured, SlotUnknown,
)
from ..hardware.mouse import Connected, RatbagConnector, WriteResult
from ..notify import Notifier, profile_message, refused_message
from . import slots
from .absence import Absence, Report
from .dbus_service import PATH, SERVICE, BusAnnouncer, ManagerInterface
from .snapshot import View, read_view
from .state import DaemonState
from .watcher import ConfigWatcher
from .writes import build_collaborators


logger = logging.getLogger("linghub.daemon")


class ConfigStartupError(RuntimeError):
    """The config is missing or invalid, so the daemon cannot start.

    Distinct from a transient failure: systemd should not restart on this.
    """


class Mouse(Protocol):
    """What the daemon needs from a connected mouse.

    Failures are reported in the seam's vocabulary (`hardware.failures`), and
    the daemon matches on what they mean (#8):

    - `apply` raises LoadRefused (keep the mouse, don't retry the same load)
      or MouseLost (reconnect).
    - `active_slot` raises SlotUnknown (skip this check) or MouseLost.

    Anything else is a bug: `tick` logs it with its traceback and carries on.
    """

    async def apply(self, profile: Profile, slot: int) -> WriteResult: ...

    async def active_slot(self) -> int | None: ...


class MouseConnector(Protocol):
    """Connects to the mouse.

    `connect` raises MouseAbsent (not found, or ratbagd not answering),
    MouseMisconfigured (retrying won't help until something changes) or
    MouseLost (the mouse vanished before it could be asked).
    """

    async def connect(self) -> Connected: ...

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
        clock: Callable[[], float] = time.monotonic,
        notifier: Notifier | None = None,
    ):
        self._config_path = Path(config_path)
        self._poll_interval = poll_interval
        # Detection and the mouse are injected so a test can say what is
        # running and what the hardware does without a bus or a device.
        self._detector = detector
        self._connector = mouse if mouse is not None else RatbagConnector()
        self._bus_announcer = BusAnnouncer()
        self._announce = announce if announce is not None else self._bus_announcer
        # One absence: from losing the mouse (or not finding it at startup)
        # to the next connection. It sets how much the daemon logs (#4).
        self._absence = Absence(clock)
        self._state: DaemonState | None = None
        self._mouse: Mouse | None = None
        self._watcher = ConfigWatcher(self._config_path)
        self._wakeup = asyncio.Event()
        self._gamemode: GameModeClient | None = None
        self._session_bus: MessageBus | None = None
        self._interface: ManagerInterface | None = None
        self._report_rates: list[int] = []
        # Injected by tests; otherwise made, and connected, at startup.
        self._notifier: Notifier | None = notifier
        # The last unexpected error, so a bug that repeats every check is
        # logged with its traceback once, not every two seconds.
        self._last_bug: tuple[str, str] | None = None
        # Nodes the retrigger helper has already been asked about (#19).
        self._nudged: set[str] = set()

        # The three collaborators the D-Bus adapter calls. They hold the config
        # edits; this class keeps the run loop and the device. Which profile
        # should be on the mouse is DaemonState's decision.
        wired = build_collaborators(
            state=lambda: self._state,
            save=self._save_config,
            wake=self._wake,
            announce=self._announce.config_changed,
            request_load=self._request_load,
            request_reload=self._request_reload,
        )
        self.profiles = wired.profiles
        self.bindings = wired.bindings
        self.settings = wired.settings

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
        """Connect, and leave with a mouse or a connection failure.

        One step: the connector returns the mouse with its capabilities, so
        there is no second await that can fail in a different vocabulary.
        """
        connected = await self._connector.connect()
        self._mouse = connected.mouse
        self._report_rates = connected.report_rates
        logger.info("using the mouse (report rates %s)", self._report_rates)

    async def _start_notifications(self) -> None:
        """Attach to the notification daemon, if there is one.

        Failure is not fatal: a headless machine has no notifications and must
        still switch profiles.
        """
        if self._notifier is None:
            self._notifier = Notifier()
        await self._notifier.connect()

    async def _notify_switch(self, profile_name: str) -> None:
        """Tell the user which profile was loaded."""
        if self._notifier is None or not self._notifier.available:
            return
        summary, body = profile_message(profile_name, self._state.current_game if self._state else None)
        await self._notifier.notify(summary, body, tag="profile")

    async def _notify_refused(self, profile_name: str, reason: str) -> None:
        """Tell the user a load was refused: the mouse is on the wrong profile."""
        if self._notifier is None or not self._notifier.available:
            return
        summary, body = refused_message(profile_name, reason)
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
            get_view=self.view,
            app_version=version.current(),
        )
        self._session_bus.export(PATH, self._interface)
        self._bus_announcer.attach(self._interface)
        await self._session_bus.request_name(SERVICE)
        logger.info("published %s on the session bus", SERVICE)

    def view(self, profile: str = "") -> View:
        """What the daemon believes now, and one profile's sections."""
        assert self._state is not None
        return read_view(self._state, profile, tuple(self._report_rates))

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
            # Before the first write, say the desktop profile is loaded rather
            # than "unknown": that is what slot 0 holds, and the drift check
            # corrects it if something else moved the mouse.
            self._state.assume_desktop_loaded()
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

    async def _reconnect(self) -> None:
        """Look for the mouse once, without waiting.

        One attempt per check, and no sleeping: the search costs a few D-Bus
        calls, and waiting between retries inside a check slowed detection to
        about 8 s and held back GameMode wake-ups while the mouse was on
        another machine (#4). A brief KVM flick is caught by the next check.
        """
        self._mouse = None
        try:
            await self._connect()
        except MouseAbsent as exc:
            self._log(self._absence.search_failed(str(exc)))
            return
        except MouseMisconfigured as exc:
            # Retrying won't help until something changes, but searching is
            # cheap and the condition can go away (one G502 unplugged).
            self._log(self._absence.search_failed(str(exc), level=logging.ERROR))
            await self._nudge_once(exc)
            return
        except MouseLost as exc:
            # The mouse vanished between being found and being asked for its
            # capabilities. At connect time that is a mouse that isn't there.
            self._log(self._absence.search_failed(str(exc)))
            return

        # A new connection may accept a load the last one refused.
        if self._state is not None:
            self._state.clear_refusal()

        self._log(self._absence.found())

    async def _nudge_once(self, exc: MouseMisconfigured) -> None:
        """Ask the retrigger helper to nudge udev, once per node.

        The helper re-presents the node ratbagd missed, which is the only cure
        for an enumeration that ran before the mouse finished initializing
        (#19). Once per node, not once per retry: the check loop runs every
        few seconds, and a helper that is missing or refused must not become
        a log every tick. A nudge that worked shows up as a connection on a
        later check, which is the loop's ordinary path.
        """
        if exc.node is None or exc.node in self._nudged:
            return
        self._nudged.add(exc.node)
        from ..hardware.retrigger import nudge

        await nudge(exc.node)

    def _lose_mouse(self, message: str) -> None:
        """Drop the mouse and start an absence, if one hasn't started."""
        self._mouse = None
        self._log(self._absence.lost(message))

    @staticmethod
    def _log(report: Report | None) -> None:
        """Say what the absence module decided, if it decided anything."""
        if report is not None:
            logger.log(report.level, "%s", report.message)

    async def _apply_target(self) -> None:
        """Load the target profile if it differs from what is loaded."""
        assert self._state is not None
        if self._mouse is None:
            await self._reconnect()
        if self._mouse is None:
            # Still absent: nothing to write to. Detection keeps running and
            # the next tick tries again.
            return

        if not self._state.needs_write:
            return

        target = self._state.target_profile
        slot = slots.slot_for(target)

        try:
            result = await self._mouse.apply(target, slot)
        except LoadRefused as exc:
            # Not a missing mouse: keep it. Retrying the same load would be
            # refused again, flooding the log and maybe rewriting flash, so
            # it waits for the config, the target or the connection to change.
            self._state.mark_refused()
            logger.error("could not load profile %r: %s", target.name, exc)
            await self._notify_refused(target.name, str(exc))
            return
        except MouseLost as exc:
            # A KVM switch, an unplugged cable, a flat battery: drop the
            # stale mouse; the next check looks for it again.
            self._lose_mouse(f"lost the device while writing: {exc}")
            return

        self._state.mark_loaded(target.name)
        logger.info(
            "loaded profile %r into slot %d (%s)",
            target.name, slot, ", ".join(result.changed) or "nothing to change",
        )

        self._announce.profile_loaded(target.name)
        await self._notify_switch(target.name)

    async def tick(self) -> None:
        """One pass: detect games, check the mouse's slot, write if needed.

        Never raises for anything an Exception covers: the mouse's failures
        are handled where they happen, and anything else is a bug, logged
        with its traceback. One bad tick must not take the daemon down:
        systemd would restart it, losing state and the manual override, and a
        bug that repeats would crash-loop it (#8).
        """
        assert self._state is not None
        try:
            await self._tick_once()
        except Exception as exc:  # noqa: BLE001 - the daemon must survive its own bugs
            self._log_bug("tick failed", exc)

    def _log_bug(self, what: str, exc: Exception) -> None:
        """Log an unexpected error with its traceback, once while it repeats."""
        key = (type(exc).__name__, str(exc))
        if key == self._last_bug:
            logger.debug("%s again: %s", what, exc)
            return
        self._last_bug = key
        logger.error("%s: %s", what, exc, exc_info=exc)

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
        if self._mouse is None:
            return
        try:
            active = await self._mouse.active_slot()
        except SlotUnknown as exc:
            # The mouse could not say (asleep, out of range, host mode). Not
            # drift, so no reload, and not lost, so no reconnect: the next
            # check asks again (#2).
            logger.debug("active slot unknown: %s", exc)
            return
        except MouseLost as exc:
            # The path names another device (DeviceReplaced) or nothing at
            # all: after a KVM switch the kernel renumbers hidraw nodes, and
            # ratbagd's paths follow them. With nothing to write this read is
            # the only call that touches the mouse, so drop the stale mouse
            # here; _apply_target reconnects in this same tick. An unreadable
            # slot is not drift, so nothing is rewritten on its account.
            self._lose_mouse(f"lost the device: {exc}")
            return

        before = self._state.needs_write
        self._state.observe_active_slot(active)
        if not before and self._state.needs_write:
            logger.info(
                "the mouse is on slot %s but %r belongs in slot %s; reloading",
                active, self._state.loaded_profile, self._state.expected_slot,
            )

    async def run(self) -> None:
        # Fix the app version now, before anything else: it must describe the
        # code this process loaded, not whatever the clone holds later.
        logger.info("LinGHub %s starting", version.current())
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
        # _apply_target looks again on each tick until the device appears.
        try:
            await self._reconnect()
        except Exception as exc:  # noqa: BLE001 - a bug here must not stop startup
            self._log_bug("first connection failed", exc)

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
            self._connector.disconnect()

    def _wake(self) -> None:
        """Ask the run loop to tick now rather than at the next interval."""
        self._wakeup.set()
