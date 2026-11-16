"""Diagnose why ratbagd cannot see the mouse.

The common cause is a stale Wine or Proton process still holding a deleted
/dev/hidraw node. The kernel keeps the node alive for that process, so the
device does not reappear until the process exits, even after replugging the
receiver.

Naming the offending process turns a silent "no G502 found" into something
the user can act on.
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


def describe_failure() -> str:
    """A human-readable explanation of why the device is missing."""
    holders = find_deleted_hidraw_holders()
    if not holders:
        return (
            "no G502 found and no stale hidraw holders detected. "
            "Check that the mouse is connected and ratbagd is running."
        )

    lines = [
        "no G502 found: these processes hold deleted /dev/hidraw nodes, "
        "which prevents the device from reappearing:",
    ]
    for holder in holders:
        lines.append(f"  pid {holder.pid}: {holder.command} (holding {holder.node})")
    lines.append("Kill them, then replug the mouse receiver.")
    return "\n".join(lines)
