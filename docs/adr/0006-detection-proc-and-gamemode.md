# Detect games with /proc scanning and GameMode signals, not window classes

Game detection combines two signals: a `/proc` scan for known game executables,
and a subscription to GameMode's `GameRegistered`/`GameUnregistered` signals on
the session bus. Window-class detection was rejected.

KWin window classes are useless for Wine and Proton games: World of Tanks
reports `resourceClass: "steam_app_default"`, which is generic to every Proton
game. The process, by contrast, is precise — `/proc/<pid>/cmdline` contains
`C:\Games\World_of_Tanks_NA\win64\WorldOfTanks.exe`. Window-class detection is
also KWin-specific and would not work on GNOME.

GameMode is not sufficient on its own either. It fires only for games launched
through `gamemoderun` or with `libgamemodeauto` preloaded. Of the three target
games, only World of Tanks registers today; Star Citizen launches through a
plain Wine script and DCS through Proton shortcuts.

## Consequences

- `/proc` scanning is the path that must work for every game; GameMode is an
  optimisation that makes detection immediate when available.
- Detection is heuristic, so the CLI needs an `--explain` mode that shows why a
  process did or did not match.
- No dependency on KWin scripting, so the same code works on KDE and GNOME.
