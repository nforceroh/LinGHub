"""Find processes holding a deleted /dev/hidraw node: a possible lead.

When a device goes away while a process has its hidraw node open, the node
lives on, deleted, until that process closes it. Wine does this routinely for
the devices a game uses.

This used to be presented as "the usual cause" of a missing mouse, with
advice to kill the holder. The evidence says otherwise: on 2026-11-19 Wine
held a deleted /dev/hidraw15 for over an hour while the G502 came back on its
own after two KVM switches, each time on a new node number. So the daemon no
longer mentions holders (#3). An on-demand diagnostic may list them as a lead
for when the mouse genuinely will not come back (#5), and should never advise
killing a process, which is usually the game being played.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROC = Path("/proc")


@dataclass(frozen=True)
class HidrawHolder:
    pid: int
    command: str
    node: str


def _read_command(pid: int) -> str:
    try:
        raw = (PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return "?"
    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
    return " ".join(parts) if parts else "?"


def find_deleted_hidraw_holders() -> list[HidrawHolder]:
    """Processes holding a deleted /dev/hidraw node.

    Only processes owned by the current user are visible, which is enough:
    the stale holders are Wine processes running as the user.
    """
    holders: list[HidrawHolder] = []

    try:
        pids = [p for p in PROC.iterdir() if p.name.isdigit()]
    except OSError:
        return holders

    for pid_path in pids:
        fd_dir = pid_path / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue

        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if "hidraw" not in target or "deleted" not in target:
                continue
            node = target.split(" (deleted)")[0]
            holders.append(HidrawHolder(
                pid=int(pid_name := pid_path.name),
                command=_read_command(int(pid_name)),
                node=node,
            ))
            break

    return holders
