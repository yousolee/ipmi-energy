"""CSV loading for samples, jobs and idle baselines.

Formats (header row required, extra columns ignored):

* samples: ``timestamp,node,watts``
* jobs:    ``jobid,nodes,start,end,alloc_cpus,total_cpus``
  (``nodes`` comma-separated inside quotes, e.g. ``"hm01,hm02"``)
* idle:    ``node,idle_watts``

Timestamps are Unix seconds (int or float) or ISO 8601. ISO strings without a
UTC offset are interpreted in ``naive_tz`` (default UTC; ``sacct`` prints local
time without an offset, so pass the cluster's zone for sacct-derived files).

Sample rows whose watts field is blank or ``na``/``nan`` (common in IPMI dumps)
are skipped with a logged warning; job rows with an ``Unknown``/``None`` end
(still running) are skipped likewise. Anything else malformed is an error that
names the file and line.
"""

from __future__ import annotations

import csv
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path

from .series import Series, as_series

SAMPLE_COLS = ("timestamp", "node", "watts")
JOB_COLS = ("jobid", "nodes", "start", "end", "alloc_cpus", "total_cpus")
IDLE_COLS = ("node", "idle_watts")
MISSING_READINGS = {"", "na", "n/a", "nan", "none"}
UNFINISHED_END = {"", "unknown", "none"}

log = logging.getLogger(__name__)


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


def parse_timestamp(value: str, naive_tz: tzinfo = timezone.utc) -> float:
    """Unix seconds from a Unix-seconds string or an ISO 8601 string."""
    text = value.strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        if not math.isfinite(number):
            raise ValueError(f"non-finite timestamp {value!r}")
        return number
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unrecognised timestamp {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
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


def load_samples(path: str | Path,
                 naive_tz: tzinfo = timezone.utc) -> dict[str, Series]:
    """Read a samples CSV into ``{node: Series}``."""
    by_node: dict[str, list[tuple[float, float]]] = defaultdict(list)
    skipped = 0
    for lineno, row in _rows(path, SAMPLE_COLS):
        if (row["watts"] or "").strip().lower() in MISSING_READINGS:
            skipped += 1
            continue
        try:
            t = parse_timestamp(row["timestamp"], naive_tz)
            w = float(row["watts"])
        except ValueError as exc:
            raise InputError(f"{path}:{lineno}: {exc}") from exc
        if not math.isfinite(w) or w < 0:
            raise InputError(f"{path}:{lineno}: watts must be finite and >= 0, got {w}")
        node = row["node"].strip()
        if not node:
            raise InputError(f"{path}:{lineno}: empty node name")
        by_node[node].append((t, w))
    if skipped:
        log.warning("%s: skipped %d sample row(s) with no reading", path, skipped)
    try:
        return {node: as_series(pts) for node, pts in by_node.items()}
    except ValueError as exc:
        raise InputError(f"{path}: {exc}") from exc


def load_jobs(path: str | Path, naive_tz: tzinfo = timezone.utc) -> list[Job]:
    jobs = []
    for lineno, row in _rows(path, JOB_COLS):
        if (row["end"] or "").strip().lower() in UNFINISHED_END:
            log.warning("%s:%d: job %s has no end time (still running?); skipped",
                        path, lineno, row["jobid"])
            continue
        try:
            nodes = tuple(n.strip() for n in row["nodes"].split(",") if n.strip())
            job = Job(
                jobid=row["jobid"].strip(),
                nodes=nodes,
                start=parse_timestamp(row["start"], naive_tz),
                end=parse_timestamp(row["end"], naive_tz),
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
        if not math.isfinite(value) or value < 0:
            raise InputError(f"{path}:{lineno}: idle_watts must be finite and >= 0")
        idle[row["node"].strip()] = value
    return idle
