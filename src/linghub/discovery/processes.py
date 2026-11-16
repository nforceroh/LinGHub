"""Read and filter processes from /proc.

Ported from the reference implementation (MIT, TheLioN25) and translated to
English. The matching rules are unchanged; see docs/adr/0006.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROC_DIR = Path("/proc")

# Kernel threads and init. These never match a game.
IGNORED_NAMES = frozenset({
    "systemd",
    "kthreadd",
    "kworker",
    "ksoftirqd",
    "migration",
    "rcu_preempt",
    "watchdog",
    "idle_inject",
})

# Wine and Proton helper processes. They share the game's prefix but are not
# the game, and matching them would switch profiles before the game starts.
IGNORED_COMMAND_PARTS = frozenset({
    "steamwebhelper",
    "pressure-vessel",
    "srt-bwrap",
    "wineserver",
    "winedevice.exe",
    "plugplay.exe",
    "services.exe",
    "explorer.exe",
    "rpcss.exe",
})


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    executable_path: str
    real_executable_path: str
    command: str

    @property
    def executable_name(self) -> str:
        """Basename of argv[0], handling both Linux and Wine paths.

        Wine processes report a Windows path such as
        `C:\\Games\\World_of_Tanks_NA\\win64\\WorldOfTanks.exe`, so backslashes
        are normalised before splitting.
        """
        path = self.executable_path
        if path == "/proc/self/exe":
            path = self.real_executable_path
        return path.replace("\\", "/").rsplit("/", maxsplit=1)[-1]


def read_process(pid_path: Path) -> ProcessInfo | None:
    """Read one process, or return None if it vanished or is unreadable."""
    try:
        pid = int(pid_path.name)
        name = (pid_path / "comm").read_text(encoding="utf-8", errors="replace").strip()
        raw_cmdline = (pid_path / "cmdline").read_bytes()
        real_executable_path = str((pid_path / "exe").resolve())
    except (ValueError, FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None

    arguments = raw_cmdline.split(b"\x00")
    if arguments and arguments[-1] == b"":
        arguments.pop()
    if not arguments or not name:
        return None

    executable_path = arguments[0].decode("utf-8", errors="replace")
    command = raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    if not command:
        return None

    return ProcessInfo(
        pid=pid,
        name=name,
        executable_path=executable_path,
        real_executable_path=real_executable_path,
        command=command,
    )


def should_ignore(process: ProcessInfo) -> bool:
    if process.name.casefold() in IGNORED_NAMES:
        return True
    command = process.command.casefold()
    return any(part in command for part in IGNORED_COMMAND_PARTS)


def discover_processes(proc_dir: Path = PROC_DIR) -> list[ProcessInfo]:
    """Return every readable, non-ignored process."""
    try:
        entries = list(proc_dir.iterdir())
    except OSError:
        return []

    processes = []
    for pid_path in entries:
        if not pid_path.name.isdigit():
            continue
        process = read_process(pid_path)
        if process is not None and not should_ignore(process):
            processes.append(process)
    return processes


def deduplicate(processes: list[ProcessInfo]) -> list[ProcessInfo]:
    """Collapse processes that share a name and command line."""
    unique: dict[tuple[str, str], ProcessInfo] = {}
    for process in processes:
        unique.setdefault((process.name.casefold(), process.command.casefold()), process)
    return list(unique.values())
