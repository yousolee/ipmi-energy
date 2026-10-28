"""How much does the BMC polling interval cost us?

Ground truth: trapezoid integral of a 1 s synthetic HPL-like trace over the
job window. Each case downsamples that trace to every k seconds (with several
poll phases relative to job start and several noise seeds, since a real
poller isn't aligned to the job) and integrates with both methods.

Usage: python analysis/sampling_error.py  (writes results next to this file)
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_calc import energy  # noqa: E402
from energy_calc.synthetic import downsample, hpl_trace  # noqa: E402

INTERVALS_S = (1, 5, 10, 30, 60)
JOB_LENGTHS_S = (30, 60, 120, 300, 600, 1800, 3600)
METHODS = ("trapezoid", "rectangle")
SEEDS = range(5)
N_PHASES = 10
OUT_DIR = Path(__file__).resolve().parent


def run() -> list[dict]:
    rows = []
    for length in JOB_LENGTHS_S:
        traces = [hpl_trace(length, seed=s) for s in SEEDS]
        truths = [energy(tr, a, b) for tr, a, b in traces]
        for k in INTERVALS_S:
            phases = np.unique(np.floor(np.linspace(0, k, N_PHASES, endpoint=False)))
            errs = {m: [] for m in METHODS}
            for (trace, a, b), truth in zip(traces, truths):
                for ph in phases:
                    polled = downsample(trace, k, ph)
                    for m in METHODS:
                        errs[m].append(100 * (energy(polled, a, b, m) - truth) / truth)
            for m in METHODS:
                e = np.asarray(errs[m])
                rows.append({
                    "job_len_s": length, "interval_s": k, "method": m,
                    "mean_err_pct": e.mean(), "mean_abs_err_pct": np.abs(e).mean(),
                    "max_abs_err_pct": np.abs(e).max(), "n_cases": e.size,
                })
    return rows


def write_tables(rows: list[dict]) -> None:
    with open(OUT_DIR / "sampling_error.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()}
                    for r in rows)

    lines = ["Mean |error| % (max |error| %) vs. 1 s ground truth.", "",
             "| job length | method | " + " | ".join(f"{k} s" for k in INTERVALS_S) + " |",
             "|---|---|" + "---|" * len(INTERVALS_S)]
    for length in JOB_LENGTHS_S:
        for m in METHODS:
            cells = []
            for k in INTERVALS_S:
                r = next(r for r in rows if r["job_len_s"] == length
                         and r["interval_s"] == k and r["method"] == m)
                cells.append(f"{r['mean_abs_err_pct']:.2f} ({r['max_abs_err_pct']:.2f})")
            lines.append(f"| {length} s | {m} | " + " | ".join(cells) + " |")
    (OUT_DIR / "sampling_error.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot(rows: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    styles = {"trapezoid": ("#2a6fb0", "-"), "rectangle": ("#c8553d", "--")}

    longest = max(JOB_LENGTHS_S)
    for m, (color, ls) in styles.items():
        sel = [r for r in rows if r["job_len_s"] == longest and r["method"] == m]
        ax1.plot([r["interval_s"] for r in sel], [r["mean_abs_err_pct"] for r in sel],
                 color=color, ls=ls, marker="o", label=f"{m}, mean")
        ax1.plot([r["interval_s"] for r in sel], [r["max_abs_err_pct"] for r in sel],
                 color=color, ls=ls, marker="x", alpha=0.5, label=f"{m}, max")
    ax1.set(xlabel="polling interval (s)", ylabel="|energy error| (%)",
            title=f"{longest // 60} min HPL-like job")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    cmap = plt.get_cmap("viridis")
    for i, k in enumerate(INTERVALS_S[1:]):
        color = cmap(i / (len(INTERVALS_S) - 1))
        for m, (_, ls) in styles.items():
            sel = [r for r in rows if r["interval_s"] == k and r["method"] == m]
            ax2.plot([r["job_len_s"] for r in sel], [r["mean_abs_err_pct"] for r in sel],
                     color=color, ls=ls, marker="o", ms=3,
                     label=f"{k} s" if m == "trapezoid" else None)
    ax2.set(xscale="log", yscale="log", xlabel="job length (s)",
            ylabel="mean |energy error| (%)",
            title="error vs. job length (solid trapezoid, dashed rectangle)")
    ax2.legend(title="interval", fontsize=8)
    ax2.grid(alpha=0.3, which="both")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "sampling_error.png", dpi=130)


def main() -> None:
    rows = run()
    write_tables(rows)
    plot(rows)
    print((OUT_DIR / "sampling_error.md").read_text())


if __name__ == "__main__":
    main()
