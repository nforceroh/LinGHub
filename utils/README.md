# Legacy scripts

These predate LinGHub and are kept for reference only. They will be removed.

| File | What it does |
| --- | --- |
| `g502-apply-profile.py` | Applies a profile from `g502-profiles.json` via `ratbagctl` |
| `g502-profiles.json` | The old profile format — **not** the format LinGHub reads |
| `g502-reset-profile.sh` | Resets the mouse to a known profile |

**Do not treat `g502-profiles.json` as configuration for LinGHub.** LinGHub reads
a single config file (see ADR-0004) with a different schema. Editing the file
here has no effect on LinGHub, and the two can disagree about what is loaded on
the mouse.

These scripts also shell out to `ratbagctl`, which LinGHub deliberately avoids in
favour of the D-Bus API.
