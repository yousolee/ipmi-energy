# ipmi-energy

Per-SLURM-job energy from IPMI/BMC power readings — Rogues Gallery VIP,
Telemetry team, IPMI subteam. Consumes the power samples and job records
produced by the SLURM telemetry collector (Jal's scripts) and reports
energy per job: total J / kWh, average W, dynamic (above-idle) J, and a
per-node breakdown. No Redfish; target clusters are pho and Rogues Gallery,
starting with high-mem nodes.

| Path | What |
|---|---|
| `energy_calc/` | the calculator package + CLI |
| `tests/` | pytest suite (synthetic data, exact answers) |
| `docs/slurm_ipmi_plugin.md` | how SLURM's `acct_gather_energy/ipmi` actually computes `ConsumedEnergy`, with source line refs |
| `docs/energy_math.md` | integration rules, idle subtraction, shared-node split, edge cases, accuracy limits, sampling-error findings |
| `analysis/` | sampling-interval error study (`sampling_error.py` → `.png`, `.md`, `.csv`) |
| `cluster/` | read-only cluster probe, probe results, HPL validation plan and (unsubmitted) sbatch |
| `examples/` | small example inputs |

## Input formats (for the collector)

CSV with a header row; extra columns are ignored; column order doesn't matter.

**Samples** — one row per reading:

```csv
timestamp,node,watts
1793000120,hm01,612
1793000125,hm01,598
```

**Jobs** — one row per job (or step). `nodes` is comma-separated inside quotes.
`alloc_cpus` / `total_cpus` are **summed over the job's nodes**
(`total_cpus` = sum of `CPUTot` of those nodes); they're only used for
`--attribution cpu_share`.

```csv
jobid,nodes,start,end,alloc_cpus,total_cpus
1001,"hm01,hm02",2026-10-26T09:02:00,2026-10-26T09:22:00,128,128
1002,hm03,1793000300,1793000900,16,64
```

**Idle baseline** (optional) — enables `dynamic_J`:

```csv
node,idle_watts
hm01,180
```

**Timestamps:** Unix seconds (int or float — preferred) or ISO 8601. ISO
strings **without an offset are treated as UTC**. Note that `sacct` prints
*local* time without an offset — either use `sacct -o ...,Start,End` with
`SLURM_TIME_FORMAT=%s` (Unix seconds) or add the offset. Samples and jobs
must agree.

**Node names** must match exactly between samples and jobs (use short
hostnames, as `sacct NodeList` expanded with `scontrol show hostnames`).

## Running

Python ≥ 3.10 with numpy (matplotlib only for the analysis plot; pandas is
not used).

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
python -m venv .venv && .venv/bin/pip install -r requirements.txt       # Linux
```

```bash
python -m energy_calc --samples examples/samples.csv --jobs examples/jobs.csv --idle examples/idle.csv --attribution cpu_share --out results.csv --per-node-out nodes.csv
```

Options: `--method trapezoid|rectangle` (default trapezoid, same as SLURM),
`--attribution exclusive|cpu_share` (default exclusive = whole-node energy,
same as SLURM), `--max-gap S` (warn on sample gaps longer than S seconds).
Omit `--out` to print to stdout. Exit code 2 on bad input, with file and line
in the message.

Output columns: `jobid, nodes, start, end, duration_s, method, attribution,
share, total_J, total_kWh, avg_W, dynamic_J, complete, warnings`.
`complete=False` means a node had no samples, samples didn't cover ≥ 99 % of
the job window, a gap exceeded `--max-gap`, or an idle baseline was missing —
see `warnings`.

From Python:

```python
from energy_calc import load_samples, load_jobs, job_energy, energy
samples = load_samples("samples.csv")
r = job_energy(load_jobs("jobs.csv")[0], samples, idle={"hm01": 180.0})
energy(samples["hm01"], t_start, t_end, method="trapezoid")   # joules
```

Tests and analysis:

```bash
python -m pytest
python analysis/sampling_error.py
```

## Key findings so far

* SLURM's IPMI plugin integrates with the **trapezoid** rule between polls
  (default every 30 s), in integer watts and whole seconds; on shared nodes
  every job is charged the **whole** node's energy. Details:
  `docs/slurm_ipmi_plugin.md`.
* On a synthetic HPL-like trace, energy error is driven by job edges:
  ≤ 0.4 % for a 1 h job even at 60 s polling, but 10–40 % mean error for
  jobs ≤ 2 min at 30–60 s polling. Trapezoid beats rectangle by 1.3–1.6×
  at ≥ 10 s intervals. Details: `docs/energy_math.md`.

## Open questions for the prof

From the Rogues Gallery probe on 2026-11-08 (`cluster/probe_results.md`;
pho not probed yet):

1. **Power data access (the main blocker).** `/dev/ipmi0` is root-only and
   SLURM's energy plugin is off, so nothing we can run reads node power.
   Will Jal's collector read BMCs in-band (needs root / a udev group on
   `/dev/ipmi0`) or out-of-band (needs BMC credentials + network)? Who
   grants that, and which sensor is "node input power" on these BMCs
   (DCMI vs. a PSU SDR sensor)?
2. **SLURM energy accounting.** `AcctGatherEnergyType` and
   `AcctGatherProfileType` are both `(null)`, so `sacct ConsumedEnergy` is
   always empty. Would the admins enable `acct_gather_energy/ipmi` (even on
   one node, e.g. `crush`) so we have a reference to validate against? With
   which `EnergyIPMIFrequency`?
3. **Job submission.** `sacctmgr show assoc user=ylee880` returns nothing.
   Which account / QOS should I use (QOSes: `normal`, `single-node`,
   `single-chassis`, …), and who adds the association?
4. **Which "high-mem" node.** The only x86 node ≥ 512 GB is `crush`
   (`rg-dev`, ~1 TB, 40 cores). Is it OK to hold it **exclusively** for
   ~45 min for the HPL run (`cluster/hpl_job.sbatch`)? Or do the 500 GB
   `dash`/`violet`/`flubber8-10` nodes, or aarch64 `kingpin`/`rg-uwing`,
   count as the high-mem target?
5. **Node sharing.** Nodes are shared per core (`select/cons_tres` +
   `CR_CORE`, no `OverSubscribe`/`ExclusiveUser`). Is the CPU-share split
   (`--attribution cpu_share`) acceptable as an estimate, or should we
   report whole-node energy like SLURM would?
6. **HPL stack.** No HPL / MPI / BLAS module exists. Is there a preferred
   build, or should I build OpenBLAS + OpenMPI + HPL in `$HOME` on `crush`?
7. **Idle baselines.** Can we get a few minutes of idle time per target node
   to measure `idle_watts`, or is there historical BMC data?
8. **pho.** Same questions — I haven't probed it yet.
