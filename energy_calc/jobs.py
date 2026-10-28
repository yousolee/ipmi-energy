"""Per-job energy: sum across nodes, optional idle subtraction and CPU share."""

from __future__ import annotations

from typing import Mapping

from .io import Job
from .series import Series, energy_detail, joules_to_kwh

ATTRIBUTIONS = ("exclusive", "cpu_share")

# Below this fraction of the job window covered by samples, a node is flagged.
MIN_COVERAGE = 0.99


def _share(job: Job, attribution: str) -> float:
    if attribution == "exclusive":
        return 1.0
    if attribution == "cpu_share":
        return job.alloc_cpus / job.total_cpus
    raise ValueError(f"attribution must be one of {ATTRIBUTIONS}, got {attribution!r}")


def job_energy(job: Job, samples: Mapping[str, Series],
               idle: Mapping[str, float] | None = None,
               attribution: str = "exclusive",
               method: str = "trapezoid",
               max_gap_s: float | None = None) -> dict:
    """Energy attributed to one job.

    Node energy is integrated over [job.start, job.end] and summed across the
    job's nodes. With ``attribution="cpu_share"`` each node's energy is scaled
    by ``alloc_cpus / total_cpus`` -- an *estimate* for shared nodes, since the
    BMC only sees whole-node power.

    Returns a dict with total_J, total_kWh, avg_W, dynamic_J (None unless
    ``idle`` is given), share, complete, warnings, and a per-node breakdown.
    """
    share = _share(job, attribution)
    warnings: list[str] = []
    per_node: dict[str, dict] = {}
    total = 0.0
    dynamic: float | None = 0.0 if idle is not None else None

    for node in job.nodes:
        series = samples.get(node)
        if series is None or len(series) < 2:
            warnings.append(f"{node}: no samples")
            dynamic = None if idle is not None else dynamic
            continue
        d = energy_detail(series, job.start, job.end, method)
        node_E = d.energy_J * share
        entry = {
            "energy_J": node_E,
            "avg_W": node_E / d.covered_s if d.covered_s > 0 else float("nan"),
            "n_samples": d.n_samples,
            "coverage": d.coverage,
            "max_gap_s": d.max_gap_s,
            "dynamic_J": None,
        }
        if d.coverage < MIN_COVERAGE:
            warnings.append(f"{node}: samples cover {d.coverage:.1%} of the job")
        if max_gap_s is not None and d.max_gap_s > max_gap_s:
            warnings.append(f"{node}: gap of {d.max_gap_s:.0f}s exceeds {max_gap_s:.0f}s")
        if idle is not None:
            if node in idle:
                entry["dynamic_J"] = (d.energy_J - idle[node] * d.covered_s) * share
                if dynamic is not None:
                    dynamic += entry["dynamic_J"]
            else:
                warnings.append(f"{node}: no idle baseline")
                dynamic = None
        per_node[node] = entry
        total += node_E

    return {
        "jobid": job.jobid,
        "nodes": list(job.nodes),
        "start": job.start,
        "end": job.end,
        "duration_s": job.duration,
        "method": method,
        "attribution": attribution,
        "share": share,
        "total_J": total,
        "total_kWh": joules_to_kwh(total),
        "avg_W": total / job.duration,
        "dynamic_J": dynamic,
        "complete": not warnings,
        "warnings": warnings,
        "per_node": per_node,
    }
