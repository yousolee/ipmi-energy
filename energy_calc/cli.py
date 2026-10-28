"""Command line: ``python -m energy_calc --samples s.csv --jobs j.csv``."""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Sequence

from .io import InputError, load_idle, load_jobs, load_samples
from .jobs import ATTRIBUTIONS, job_energy
from .series import METHODS

RESULT_COLS = ("jobid", "nodes", "start", "end", "duration_s", "method", "attribution",
               "share", "total_J", "total_kWh", "avg_W", "dynamic_J", "complete", "warnings")
NODE_COLS = ("jobid", "node", "energy_J", "avg_W", "dynamic_J", "n_samples",
             "coverage", "max_gap_s")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="energy_calc",
                                description="Per-job energy from IPMI power samples.")
    p.add_argument("--samples", required=True, help="CSV: timestamp,node,watts")
    p.add_argument("--jobs", required=True,
                   help="CSV: jobid,nodes,start,end,alloc_cpus,total_cpus")
    p.add_argument("--idle", help="CSV: node,idle_watts (enables dynamic_J)")
    p.add_argument("--method", choices=METHODS, default="trapezoid")
    p.add_argument("--attribution", choices=ATTRIBUTIONS, default="exclusive")
    p.add_argument("--max-gap", type=float, default=None,
                   help="warn when samples are further apart than this many seconds")
    p.add_argument("--out", help="write per-job results CSV here (default: stdout)")
    p.add_argument("--per-node-out", help="also write a per-node breakdown CSV")
    return p


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}" if abs(value) < 1e6 else f"{value:.1f}"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def _row(result: dict) -> dict:
    row = {k: _fmt(result[k]) for k in RESULT_COLS if k != "warnings"}
    row["warnings"] = "; ".join(result["warnings"])
    return row


def _node_rows(result: dict):
    for node, e in result["per_node"].items():
        yield {"jobid": result["jobid"], "node": node,
               **{k: _fmt(e[k]) for k in NODE_COLS[2:]}}


def _write(rows, cols, path: str | None) -> None:
    fh = open(path, "w", newline="", encoding="utf-8") if path else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if path:
            fh.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        samples = load_samples(args.samples)
        jobs = load_jobs(args.jobs)
        idle = load_idle(args.idle) if args.idle else None
    except (OSError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results = [job_energy(j, samples, idle, args.attribution, args.method, args.max_gap)
               for j in jobs]
    _write((_row(r) for r in results), RESULT_COLS, args.out)
    if args.per_node_out:
        _write((row for r in results for row in _node_rows(r)), NODE_COLS,
               args.per_node_out)

    incomplete = [r["jobid"] for r in results if not r["complete"]]
    if incomplete:
        print(f"warning: {len(incomplete)} job(s) incomplete: {', '.join(incomplete)}",
              file=sys.stderr)
    if args.out:
        print(f"wrote {len(results)} job(s) to {args.out}", file=sys.stderr)
    return 0
