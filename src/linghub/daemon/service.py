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
from ..hardware.ratbag import RatbagClient
from ..hardware.writer import ProfileWriter, WriteError
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

    async def _connect(self) -> None:
        self._bus = await asyncio.wait_for(
            MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5
        )
        client = RatbagClient(self._bus)
        device = await client.find_device()
        self._writer = ProfileWriter(client, device)
        logger.info("using device %s at %s", device.name, device.path)

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

    async def _tick(self) -> None:
        assert self._state is not None
        self._reload_if_changed()
        detection = detect(self._state.config.profiles)
        self._state.observe(detection)
        await self._apply_target()

    async def run(self) -> None:
        if not self._reload_config():
            # A bad config is not transient: restarting will not fix it, so
            # exit non-zero and let systemd's RestartPreventExitStatus stop
            # the unit rather than looping.
            raise ConfigStartupError("cannot start without a valid config")

        await self._connect()
        interval = self._poll_interval or self._state.config.poll_interval
        logger.info("watching for games every %ss", interval)

        try:
            while True:
                await self._tick()
                await asyncio.sleep(interval)
        finally:
            if self._bus is not None:
                self._bus.disconnect()
