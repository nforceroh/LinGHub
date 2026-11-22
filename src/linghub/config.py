"""Load the LinGHub config file.

One file holds every profile plus application settings (ADR-0004). The daemon
is its only writer; this module only reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .domain.profile import Binding, Game, Profile
from .hardware import mapping


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
        try:
            binding = Binding(type=value["type"], value=value.get("value"))
            # The encoder is the authority on what the mouse can take. A
            # binding it rejects used to load fine and crash the daemon on its
            # first write, and since the config still loaded, systemd
            # restarted it into the same crash (#8).
            mapping.encode(binding)
        except ValueError as exc:
            raise ConfigError(f"binding {key!r} is invalid: {exc}") from exc
        bindings[index] = binding
    return bindings


LED_MODES = ("off", "on", "cycle", "breathing")


def validate_led(entry: dict) -> dict:
    """Validate one LED settings dict, returning a normalised copy."""
    return _parse_leds([entry])[0]


def _parse_leds(raw: list) -> tuple[dict, ...]:
    """Validate LED settings at load time.

    These values go straight to the hardware, so a bad one would otherwise
    fail deep inside the writer or silently do nothing.
    """
    leds = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ConfigError("each led must be an object")
        if "index" not in entry:
            raise ConfigError("led is missing an 'index'")
        try:
            index = int(entry["index"])
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"led index {entry['index']!r} is not a number") from exc

        led: dict = {"index": index}

        if "mode" in entry:
            mode = entry["mode"]
            if mode not in LED_MODES:
                raise ConfigError(
                    f"led {index} has unknown mode {mode!r}; expected one of {LED_MODES}"
                )
            led["mode"] = mode

        if "brightness" in entry:
            brightness = entry["brightness"]
            if not isinstance(brightness, int) or not 0 <= brightness <= 255:
                raise ConfigError(
                    f"led {index} brightness must be 0-255, got {brightness!r}"
                )
            led["brightness"] = brightness

        if "duration" in entry:
            duration = entry["duration"]
            if not isinstance(duration, int) or duration < 0:
                raise ConfigError(
                    f"led {index} duration must be a non-negative integer, got {duration!r}"
                )
            led["duration"] = duration

        if "color" in entry:
            color = entry["color"]
            if not isinstance(color, (list, tuple)) or len(color) != 3:
                raise ConfigError(
                    f"led {index} color must be three channels, got {color!r}"
                )
            channels = []
            for channel in color:
                if not isinstance(channel, int) or not 0 <= channel <= 255:
                    raise ConfigError(
                        f"led {index} color channels must be 0-255, got {color!r}"
                    )
                channels.append(channel)
            led["color"] = channels

        leds.append(led)
    return tuple(leds)


def factory_default() -> Config:
    """The config a fresh install starts with: one desktop profile.

    The values are the G502's own defaults, not a copy of whatever the mouse
    happens to hold. Reading the mouse instead would need a decode path that
    does not exist, and would make the first run depend on the device being
    plugged in. The consequence is deliberate: the daemon's first tick loads
    this profile into slot 0, replacing what was there.

    Only the desktop profile is created. A gaming profile with no game bound
    to it would never be selected, so the user adds those as they need them.
    """
    desktop = Profile(
        name="desktop",
        report_rate=1000,
        resolutions=(
            {"dpi": 400},
            {"dpi": 800, "active": True, "default": True},
            {"dpi": 1000},
        ),
        bindings={
            0: Binding("button", 1),
            1: Binding("button", 2),
            2: Binding("button", 3),
            3: Binding("button", 4),
            4: Binding("button", 5),
            6: Binding("special", "resolution-down"),
            7: Binding("special", "resolution-up"),
        },
        leds=(
            {"index": 0, "mode": "cycle", "duration": 8000},
            {"index": 1, "mode": "cycle", "duration": 8000},
        ),
    )
    return Config(profiles=[desktop], desktop_profile="desktop", poll_interval=2.0)


def write_default(path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    """Write the factory default config, creating its directory.

    An existing file is never replaced, whatever state it is in: a broken
    config must still fail loudly at daemon start rather than be silently
    replaced, which would destroy the user's profiles.
    """
    path = Path(path)
    if path.exists():
        raise ConfigError(f"config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, factory_default())


def _parse_game(raw) -> Game:
    """One game entry, in either shape the config accepts.

    A bare string is a game with no name, which is what every config written
    before names existed holds. The object form carries the name. Accepting
    both means no migration step for a field that is purely cosmetic.
    """
    if isinstance(raw, str):
        return Game(executable=raw)
    if isinstance(raw, dict):
        executable = raw.get("executable")
        if not isinstance(executable, str):
            raise ConfigError(f"game entry needs an executable: {raw!r}")
        name = raw.get("name", "")
        if not isinstance(name, str):
            raise ConfigError(f"game name must be a string: {raw!r}")
        return Game(executable=executable, name=name)
    raise ConfigError(f"game entry must be a string or an object: {raw!r}")


def _parse_profile(name: str, raw: dict) -> Profile:
    games = tuple(_parse_game(g) for g in raw.get("games", []))
    return Profile(
        name=name,
        games=games,
        report_rate=raw.get("report_rate"),
        resolutions=tuple(raw.get("resolutions", [])),
        bindings=_parse_bindings(raw.get("bindings", {})),
        leds=_parse_leds(raw.get("leds", [])),
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


def _binding_to_raw(binding: Binding) -> dict:
    raw = {"type": binding.type}
    if binding.value is not None:
        raw["value"] = binding.value
    return raw


def _profile_to_raw(profile: Profile) -> dict:
    """Serialize the parts of a profile the model understands."""
    raw: dict = {}
    if profile.games:
        # The object form always, even for a nameless game: one shape written
        # is easier to reason about than two, and the reader takes both.
        raw["games"] = [
            {"executable": game.executable, "name": game.name}
            for game in profile.games
        ]
    if profile.report_rate is not None:
        raw["report_rate"] = profile.report_rate
    if profile.resolutions:
        raw["resolutions"] = list(profile.resolutions)
    if profile.bindings:
        raw["bindings"] = {
            str(index): _binding_to_raw(binding)
            for index, binding in sorted(profile.bindings.items())
        }
    if profile.leds:
        raw["leds"] = list(profile.leds)
    return raw


def save(path: Path | str, config: Config) -> None:
    """Write the config back, then validate it by loading it again.

    Unknown keys in the file are preserved: this module only models the parts
    it understands, and silently dropping a hand-written key would be worse
    than refusing to save. The new file is validated before it replaces the
    old one, so a bug here cannot leave the user without a working config.
    """
    path = Path(path)
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        original = {}
    except json.JSONDecodeError as exc:
        raise ConfigError(f"refusing to overwrite a corrupt config: {exc}") from exc

    if not isinstance(original, dict):
        raise ConfigError("config root must be an object")

    raw_profiles = original.get("profiles")
    if not isinstance(raw_profiles, dict):
        raw_profiles = {}

    rebuilt: dict = dict(original)
    rebuilt["version"] = SUPPORTED_VERSION

    settings = dict(original.get("settings") or {})
    settings["desktop_profile"] = config.desktop_profile
    if config.poll_interval is not None:
        settings["poll_interval"] = config.poll_interval
    rebuilt["settings"] = settings

    profiles: dict = {}
    for profile in config.profiles:
        # Start from what was already there so keys this model does not know
        # about (and hand-written comments-as-keys) survive.
        existing = raw_profiles.get(profile.name)
        entry = dict(existing) if isinstance(existing, dict) else {}
        fresh = _profile_to_raw(profile)
        # Drop keys the model owns but no longer has a value for.
        for owned in ("games", "report_rate", "resolutions", "bindings", "leds"):
            if owned not in fresh:
                entry.pop(owned, None)
        entry.update(fresh)
        profiles[profile.name] = entry
    rebuilt["profiles"] = profiles

    serialized = json.dumps(rebuilt, indent=2) + "\n"
    _validate_text(serialized, path)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialized, encoding="utf-8")
    tmp.replace(path)


def _validate_text(serialized: str, path: Path) -> None:
    """Parse the bytes we are about to write, so a bug cannot land on disk."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        handle.write(serialized)
        probe = Path(handle.name)
    try:
        load(probe)
    except ConfigError as exc:
        raise ConfigError(f"refusing to write an invalid config: {exc}") from exc
    finally:
        probe.unlink(missing_ok=True)
