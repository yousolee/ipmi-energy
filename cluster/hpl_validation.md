# HPL energy validation plan (one high-mem node)

Goal: run a known, steady, power-hungry workload on one high-mem node, collect
power samples, run `energy_calc`, and compare against SLURM's own
`ConsumedEnergy` (if enabled). Agreement within a few percent validates both
our pipeline and our reading of the SLURM plugin.

Legend: 🟢 I can do it myself · 🟡 needs my submission rights confirmed ·
🔴 needs prof/admin.

**Status:** not started — no cluster access yet. Step 0 fills in every
`CHANGE_ME` below.

## 0. Probe (🟢, read-only)

```bash
bash cluster/probe.sh > probe_$(hostname -s).txt 2>&1
```

Record the results in `cluster/probe_results.md`. Decide from them:

* which partition / node is "high-mem" (`RealMemory`, features),
* whether `AcctGatherEnergyType=acct_gather_energy/ipmi` is set and its
  `EnergyIPMIFrequency`, `EnergyIPMIPowerSensors`, `EnergyIPMICalcAdjustment`,
* whether `AcctGatherProfileType=acct_gather_profile/hdf5` is set (gives us a
  per-sample power series through SLURM, no IPMI rights needed),
* whether IPMI is readable without root (almost certainly not),
* where an HPL binary / BLAS / MPI comes from.

Then `scontrol show node <node>` (🟢) for that node's exact CPU count and
memory — compute nodes may differ from the login node's `lscpu`.

## 1. Pick the node and get permission (🔴)

* Ask the prof which high-mem node we may take **exclusively** for ~45 min,
  and when (an otherwise idle node gives a clean baseline).
* Confirm we have an association on that partition (`sacctmgr show assoc`
  from the probe) — 🟡.

## 2. Power source (🔴 for direct IPMI)

One of, in order of preference:

1. **Jal's collector** running against that node's BMC during the job
   (whatever privileges it uses) → `samples.csv` in our format.
2. **SLURM energy profile**: if hdf5 profiling is enabled, uncomment
   `--profile=energy` / `--acctg-freq=energy=5` in the sbatch, then
   `sh5util -j <jobid> -S -l Node:TimeSeries -s Energy` → convert columns to
   `timestamp,node,watts`. (🟡 — depends on cluster config.)
3. **In-job `ipmitool dcmi power reading`** — the sbatch tries it
   automatically, but it needs read access to `/dev/ipmi0` (🔴, admin).

If none is available we can still compare `sacct ConsumedEnergy` with an
energy estimate from SLURM's own average power, but that's not independent
validation.

## 3. Fill in and submit `hpl_job.sbatch` (🟡, and only after go-ahead)

Fill the `CHANGE_ME` lines (partition, nodelist, ntasks-per-node, module
loads, `XHPL`). The job then:

1. **Idle baseline, 5 min** — node held exclusively, nothing running.
   Its average power is `idle_watts` for this node.
2. **HPL, ~15 min** — `N` = min(80 % of RAM, the size that runs
   `TARGET_HPL_S` = 900 s at ~70 % of a peak estimated from `lscpu`:
   cores × GHz × 16 or 32 DP FLOPs/cycle), rounded to a multiple of
   `NB=192`; P×Q = near-square factorisation of the rank count. Example: a
   2×32-core AVX-512 node at 3 GHz → N ≈ 180 k, ≈ 260 GB, P×Q = 8×8. High-mem
   nodes would take hours if HPL were sized by memory alone, so runtime is
   the limiting term.
3. **Idle tail, 5 min** — shows how long the node takes to return to idle
   (fans, thermals), which affects `dynamic_J`.

It writes `phases.csv` (one jobs-format row per phase) and, if IPMI is
readable, `samples.csv`, under `~/ipmi-energy-runs/<jobid>/`.

Total request: 1 node, exclusive, 45 min.

## 4. Run the calculator (🟢)

```bash
# idle baseline from the idle phase
python -m energy_calc --samples samples.csv --jobs phases.csv --out phases_energy.csv
#   idle_watts = avg_W of the "<jobid>.idle" row  -> idle.csv  (node,idle_watts)
python -m energy_calc --samples samples.csv --jobs phases.csv --idle idle.csv \
    --max-gap 10 --out phases_energy.csv --per-node-out phases_nodes.csv
```

Also run with a whole-job row (`start` of idle → `end` of tail) to compare
with SLURM, which charges the whole allocation.

## 5. Compare with SLURM (🟢, if energy accounting is on)

```bash
sacct -j <jobid> -o JobID,Start,End,Elapsed,ConsumedEnergyRaw -P
```

* Compare `ConsumedEnergyRaw` of the job (and of the `batch` step) with our
  whole-job `total_J`. Expected differences: SLURM polls every
  `EnergyIPMIFrequency` s (default 30) with integer watts/seconds, and without
  `EnergyIPMICalcAdjustment` drops up to one interval at each end — for a
  ~25-min job that's ≲ 1 % from our sampling-error analysis, plus whatever
  sensor differences there are (if SLURM's auto-discovered sensor isn't the
  one DCMI reports, the gap will be larger and constant in watts).
* Re-integrate our samples downsampled to SLURM's interval
  (`energy_calc.synthetic.downsample`) to separate sampling effects from
  sensor effects.

## 6. Report

Idle W, HPL plateau W, HPL GFLOPS (from `hpl.out`), total/dynamic energy,
GFLOPS/W, our total vs SLURM's, and the residual explained.
