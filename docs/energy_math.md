# Energy from power samples: the math

We get power readings Pᵢ (watts) at times tᵢ (seconds) from the BMC, one
series per node. Energy is the time integral of power, E = ∫ P(t) dt, which we
can only approximate from samples. Δtᵢ = tᵢ₊₁ − tᵢ.

## Integration rules

**Rectangle / hold-last-value (left Riemann sum)**

    E ≈ Σᵢ Pᵢ · Δtᵢ

Assumes each reading holds until the next. Simple, and it is what you get if
you "add up watts × seconds" naively. For a linear ramp P = a + b·t sampled
every Δ over a span T it is off by exactly −b·T·Δ/2 (it under-reads rising
power, over-reads falling power) — `tests/test_series.py` checks this.

**Trapezoid**

    E ≈ Σᵢ ½ (Pᵢ + Pᵢ₊₁) · Δtᵢ

Assumes power changes linearly between readings. Exact for piecewise-linear
power; error is O(Δ²·P″) rather than O(Δ·P′).

**SLURM uses trapezoid.** `_get_additional_consumption()` in the IPMI plugin
computes `(t1 − t0)·(w1 + w0)/2` per poll interval
(see `docs/slurm_ipmi_plugin.md` §3), in integer watts and whole seconds. The
optional `EnergyIPMICalcAdjustment` adds a rectangle extrapolation from the last
poll to "now". `energy_calc` defaults to trapezoid so its numbers are
comparable to `sacct ConsumedEnergy`.

## Derived quantities

* **Average power:** P̄ = E / (t_end − t_start).
* **Dynamic (job-caused) energy:** E_job ≈ E_total − P_idle · (t_end − t_start),
  where P_idle is the node's measured idle baseline. It removes what the node
  would have burned anyway (fans, PSU losses, DIMM refresh, idle cores). It's
  an approximation: idle power depends on temperature and fan speed, and a hot
  node after a job doesn't return to idle instantly.
* **Shared-node attribution (estimate):** if a job holds `alloc_cpus` of a
  node's `total_cpus`,

      E_job,node ≈ (alloc_cpus / total_cpus) · E_node

  and likewise for dynamic energy. **This is an estimate, not a
  measurement**: the BMC sees one number for the whole node, and a
  memory-bound job on 8 cores can draw more than a sleeping job on 32. SLURM
  itself does *not* split — every job on a shared node is charged the whole
  node delta. In `energy_calc`, `alloc_cpus`/`total_cpus` are totals over the
  job's nodes, and the same share is applied to each node.

## Edge cases

* **Job boundaries between samples.** The window [t_start, t_end] rarely lines
  up with sample times. We add synthetic points at both boundaries — linearly
  interpolated for trapezoid, hold-last-value for rectangle (consistent with
  each method's assumption) — and integrate only inside the window. Without
  this, each edge can be off by up to one full interval of power.
* **Missing / gappy samples.** Integration bridges gaps (linearly for
  trapezoid), which is right if power didn't change much but can be badly
  wrong across a job start/stop. `energy_calc` reports the largest gap per
  node and warns if it exceeds `--max-gap`. Parts of the window outside the
  data range are **not** extrapolated; they reduce `coverage` and produce a
  warning, and the job is marked `complete=False`.
* **Multi-node jobs.** Integrate each node separately, then sum (this is what
  SLURM does too: `jobacctinfo_aggregate` sums per-node energy).
* **Units.** 1 kWh = 3.6 × 10⁶ J; 1 W·s = 1 J. A 600 W node for one hour is
  2.16 MJ = 0.6 kWh.

## What limits accuracy

| Source | Typical size | Effect |
|---|---|---|
| Polling interval | 1–60 s (SLURM default 30 s) | Misses fast changes; edges of short jobs dominate (see below). |
| BMC sensor update rate | often 1–5 s, vendor-specific | Polling faster than the BMC updates just repeats values. |
| Reading resolution | ~1 W (DCMI integer; SLURM also truncates to int) | Negligible for energy (< 0.5% at 200 W), visible in short spikes. |
| DCMI averaging window | vendor-specific, can be several seconds | "Current power" is already a moving average, so sharp edges are smeared and shifted in time. |
| Where it's measured | PSU AC input (usually) | Includes PSU conversion loss, fans, disks, NICs — not just CPU/RAM. Good for "what did the wall see", not for per-component energy. |
| Timestamps | SLURM uses whole seconds; our collector should use sub-second | Δt error of ±1 s per interval at 1 s polling is up to 100%. |
| Shared nodes | — | Any split is an estimate (above). |

## Sampling-rate error analysis

`analysis/sampling_error.py` builds a 1 s synthetic HPL-like trace (idle
180 W → 8 s ramp → noisy ~620 W plateau with periodic 60 W dips every 23 s and
a slow sag → ramp down → idle; see `energy_calc/synthetic.py`), takes the 1 s
trapezoid integral over the job window as ground truth, then downsamples to
1/5/10/30/60 s polling with 10 poll phases × 5 noise seeds per case. Full table:
`analysis/sampling_error.md` / `.csv`; plot: `analysis/sampling_error.png`.

Mean |error| (max |error|), selected cases:

| job length | method | 5 s | 10 s | 30 s | 60 s |
|---|---|---|---|---|---|
| 30 s | trapezoid | 1.45 (3.1) | 4.3 (9.9) | 19.9 (64) | 41.5 (64) |
| 30 s | rectangle | 1.81 (3.9) | 6.3 (11.6) | 32.3 (64) | 48.8 (64) |
| 2 min | trapezoid | 0.43 (1.0) | 0.76 (1.9) | 5.0 (13) | 10.2 (32) |
| 2 min | rectangle | 0.44 (1.2) | 1.14 (2.6) | 6.6 (13) | 15.9 (32) |
| 10 min | trapezoid | 0.14 (0.4) | 0.26 (0.7) | 0.93 (2.8) | 2.1 (6.2) |
| 10 min | rectangle | 0.14 (0.4) | 0.31 (0.9) | 1.24 (3.2) | 3.0 (6.2) |
| 1 h | trapezoid | 0.07 (0.2) | 0.08 (0.3) | 0.20 (0.8) | 0.36 (1.3) |
| 1 h | rectangle | 0.07 (0.2) | 0.09 (0.3) | 0.23 (0.8) | 0.53 (1.4) |

Findings (on synthetic data — to be checked against a real trace):

1. **Error is dominated by the job edges, so it scales roughly as
   interval / job length.** For ≥ 10 min jobs every interval up to 60 s is
   within a few percent; for jobs shorter than ~2× the interval the estimate
   is unreliable (a 30 s job polled every 30–60 s can be off by > 60% — the
   ramp is guessed from idle samples on either side).
2. **SLURM's 30 s default is fine for long HPL runs (< 1% for 1 h) but poor
   for jobs under ~5 min.** For short jobs we want ≤ 5 s polling, and the
   collector should poll at job start/end.
3. **Trapezoid beats rectangle at every interval ≥ 10 s**, by about 1.3–1.6×
   on mean error; at 5 s they're equivalent because noise, not the ramp
   shape, dominates. There's no reason to use rectangle except to mimic a
   tool that does.
4. Going below the BMC's own update rate won't improve real-world numbers the
   way it does here, since the synthetic trace has true 1 s resolution. The
   real floor is set by the BMC (to be measured: poll at 1 s and look for
   repeated values).
