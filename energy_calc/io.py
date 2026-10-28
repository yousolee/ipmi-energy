"""CSV loading for samples, jobs and idle baselines.

Formats (header row required, extra columns ignored):

* samples: ``timestamp,node,watts``
* jobs:    ``jobid,nodes,start,end,alloc_cpus,total_cpus``
  (``nodes`` comma-separated inside quotes, e.g. ``"hm01,hm02"``)
* idle:    ``node,idle_watts``

Timestamps are Unix seconds (int or float) or ISO 8601. ISO strings without a
UTC offset are interpreted as **UTC**; samples and jobs must use the same
convention.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .series import Series, as_series

SAMPLE_COLS = ("timestamp", "node", "watts")
JOB_COLS = ("jobid", "nodes", "start", "end", "alloc_cpus", "total_cpus")
IDLE_COLS = ("node", "idle_watts")


@dataclass(frozen=True)
class Job:
    """A job window. ``alloc_cpus``/``total_cpus`` are summed over ``nodes``."""

    jobid: str
    nodes: tuple[str, ...]
    start: float
    end: float
    alloc_cpus: int
    total_cpus: int

    @property
    def duration(self) -> float:
        return self.end - self.start


class InputError(ValueError):
    """Raised for malformed input files; message names the file and row."""


def parse_timestamp(value: str) -> float:
    """Unix seconds from a Unix-seconds string or an ISO 8601 string."""
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unrecognised timestamp {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _rows(path: str | Path, required: tuple[str, ...]):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in required if c not in header]
        if missing:
            raise InputError(f"{path}: missing column(s) {missing}; found {header}")
        reader.fieldnames = header
        for lineno, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values()):
                continue
            yield lineno, row


def load_samples(path: str | Path) -> dict[str, Series]:
    """Read a samples CSV into ``{node: Series}``."""
    by_node: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for lineno, row in _rows(path, SAMPLE_COLS):
        try:
            t = parse_timestamp(row["timestamp"])
            w = float(row["watts"])
        except ValueError as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
        node = row["node"].strip()
        if not node:
            raise InputError(f"{path}:{lineno}: empty node name")
        by_node[node].append((t, w))
    try:
        return {node: as_series(pts) for node, pts in by_node.items()}
    except ValueError as exc:
        raise InputError(f"{path}: {exc}") from exc


def load_jobs(path: str | Path) -> list[Job]:
    jobs = []
    for lineno, row in _rows(path, JOB_COLS):
        try:
            nodes = tuple(n.strip() for n in row["nodes"].split(",") if n.strip())
            job = Job(
                jobid=row["jobid"].strip(),
                nodes=nodes,
                start=parse_timestamp(row["start"]),
                end=parse_timestamp(row["end"]),
                alloc_cpus=int(row["alloc_cpus"]),
                total_cpus=int(row["total_cpus"]),
            )
        except ValueError as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
        if not nodes:
            raise InputError(f"{path}:{lineno}: job {job.jobid} has no nodes")
        if job.end <= job.start:
            raise InputError(f"{path}:{lineno}: job {job.jobid} ends before it starts")
        if not 0 < job.alloc_cpus <= job.total_cpus:
            raise InputError(
                f"{path}:{lineno}: job {job.jobid} needs 0 < alloc_cpus <= total_cpus")
        jobs.append(job)
    return jobs


def load_idle(path: str | Path) -> dict[str, float]:
    idle = {}
    for lineno, row in _rows(path, IDLE_COLS):
        try:
            value = float(row["idle_watts"])
        except ValueError as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
        if value < 0:
            raise InputError(f"{path}:{lineno}: idle_watts must be >= 0")
        idle[row["node"].strip()] = value
    return idle
