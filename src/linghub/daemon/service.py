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
from ..hardware.ratbag import RatbagClient
from ..hardware.writer import ProfileWriter, WriteError
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
        self._manual_override: str | None = None
        self._detected_game: str | None = None

    async def _connect(self) -> None:
        self._bus = await asyncio.wait_for(
            MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5
        )
        client = RatbagClient(self._bus)
        device = await client.find_device()
        self._writer = ProfileWriter(client, device)
        logger.info("using device %s at %s", device.name, device.path)

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

    async def _apply_target(self) -> None:
        """Load the target profile if it differs from what is loaded."""
        assert self._state is not None and self._writer is not None

        if not self._state.needs_write:
            return

        target = self._state.target_profile
        slot = DESKTOP_SLOT if target.is_desktop else GAMING_SLOT

        try:
            result = await self._writer.apply(target, slot)
        except WriteError as exc:
            logger.error("failed to load profile %r: %s", target.name, exc)
            self._pending = target.name
            return

        self._state.mark_loaded(target.name)
        self._pending = None
        logger.info("loaded profile %r into slot %d (%d changes)", target.name, slot, len(result.changed))

        if self._interface is not None:
            self._interface.ProfileChanged(target.name)

    async def _tick(self) -> None:
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

        await self._connect()
        await self._export_interface()
        interval = self._poll_interval or self._state.config.poll_interval

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
