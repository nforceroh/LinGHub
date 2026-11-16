"""Load the LinGHub config file.

One file holds every profile plus application settings (ADR-0004). The daemon
is its only writer; this module only reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .domain.profile import Binding, Game, Profile


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "linghub" / "config.json"
SUPPORTED_VERSION = 1


class ConfigError(RuntimeError):
    """The config file is missing, malformed, or unsupported."""


@dataclass(frozen=True)
class Config:
    profiles: list[Profile]
    desktop_profile: str
    poll_interval: float

    def profile_named(self, name: str) -> Profile | None:
        return next((p for p in self.profiles if p.name == name), None)

    @property
    def desktop(self) -> Profile | None:
        return self.profile_named(self.desktop_profile)


def _parse_bindings(raw: dict) -> dict[int, Binding]:
    bindings = {}
    for key, value in raw.items():
        try:
            index = int(key)
        except ValueError as exc:
            raise ConfigError(f"binding key {key!r} is not a button index") from exc
        if not isinstance(value, dict) or "type" not in value:
            raise ConfigError(f"binding {key!r} must be an object with a 'type'")
        bindings[index] = Binding(type=value["type"], value=value.get("value"))
    return bindings


def _parse_profile(name: str, raw: dict) -> Profile:
    games = tuple(Game(executable=g) for g in raw.get("games", []))
    return Profile(
        name=name,
        games=games,
        report_rate=raw.get("report_rate"),
        resolutions=tuple(raw.get("resolutions", [])),
        bindings=_parse_bindings(raw.get("bindings", {})),
        leds=tuple(raw.get("leds", [])),
    )


def load(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Read and validate the config file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {path}: {exc}") from exc

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise ConfigError(
            f"unsupported config version {version!r}; expected {SUPPORTED_VERSION}"
        )

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ConfigError("config must define at least one profile")

    profiles = [_parse_profile(name, body) for name, body in raw_profiles.items()]

    settings = raw.get("settings", {})
    desktop_profile = settings.get("desktop_profile", "desktop")
    if not any(p.name == desktop_profile for p in profiles):
        raise ConfigError(f"desktop profile {desktop_profile!r} is not defined")

    return Config(
        profiles=profiles,
        desktop_profile=desktop_profile,
        poll_interval=float(settings.get("poll_interval", 2)),
    )
