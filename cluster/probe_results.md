# Cluster probe results — Rogues Gallery (rg-login)

Raw output:
[probe_rg_run2.txt](probe_rg_run2.txt) (2026-11-08 22:47 EST, login shell — **use this one**) ·
[probe_rg_run1.txt](probe_rg_run1.txt) (22:43, non-login shell; SLURM wasn't
on PATH, so only the host/IPMI/lscpu parts are meaningful).

SLURM lives in `/opt/slurm/current/bin`, which only lands on PATH via the
login profile — hence `bash -l` for run 2. pho has not been probed yet.

## Interpretation

| Question | Answer | Evidence |
|---|---|---|
| Host / cluster | `rg-login.crnch.gatech.edu` (Ubuntu, kernel 5.15). SLURM `ClusterName = cluster` | `hostname -f`, `scontrol show config` |
| SLURM version | **25.05.5** → plugin doc re-checked against tag `slurm-25-05-5-1` | `scontrol --version` |
| Partitions | `rg-dev*` (crush only, 25 h max), `rg-nextgen-hpc` (29 nodes, 24 h), `rg-violet` (12 h), `rg-neuro`, `rg-fpga`. No partition named high-mem. | `sinfo -s` |
| High-mem nodes | **x86 ≥ 512 GB: only `crush`** (rg-dev, 1,030,000 MB ≈ 1 TB, 80 CPUs = 4×10×2, idle). aarch64 ≥ 512 GB: `kingpin1-2` (514 GB), `rg-uwing-1-2` (587 GB, Grace+H200). Just under 512 GB at 510,000 MB: `dash1-4`, `flubber8-10`, `violet1-2`, `instinct`. | `sinfo -N -o '%N %P %c %m %f'` |
| Energy plugin & frequency | **Not enabled.** `AcctGatherEnergyType = (null)`, `AcctGatherNodeFreq = 0`. `energy` *is* in `AccountingStorageTRES`, but nothing feeds it. No `/etc/slurm/acct_gather.conf`. | `scontrol show config` |
| ConsumedEnergy populated? | **No** (and couldn't be, with no plugin). `sacct -a` over 7 days returned **zero rows** even though nodes are allocated — most likely `PrivateData=jobs` hides other users' jobs and I have none; not confirmed. | `sacct -S now-7days -a` |
| Energy profiling (hdf5)? | **No.** `AcctGatherProfileType = (null)` → `--profile=energy` / `sh5util` won't work. | `scontrol show config` |
| PrologFlags=Contain? | **Yes** (`Alloc,Contain,X11`). If energy were enabled, whole-job energy would sit on the `extern` step. | `scontrol show config` |
| Can I submit, where? | **Unclear — probably not yet.** `sacctmgr show assoc user=ylee880` returned **nothing** (no association). QOSes exist: `normal`, `single-node`, `single-chassis`, `two-chassis`, `four-chassis`. Partitions allow ALL groups/accounts/QOS, so whether I can submit depends on `AccountingStorageEnforce`, which the probe didn't capture. | `sacctmgr show assoc`, `scontrol show partition` |
| Nodes shared or exclusive? | **Shared at core granularity.** `select/cons_tres` + `CR_CORE`, `OverSubscribe=NO`, `ExclusiveUser=NO` on every partition → different jobs can run on one node at once (many nodes are `mixed`). Whole-node BMC power must be split → `cpu_share` attribution; validation runs need `--exclusive`. | `scontrol show config/partition`, `sinfo` |
| IPMI without sudo? | **No.** `/dev/ipmi0` is `crw------- root root`. Both `ipmitool` calls failed once (exit 1) and were not retried. (The "No such file or directory" text refers to `/dev/ipmidev/0`, the last path ipmitool tries; the real failure on `/dev/ipmi0` is permission.) ipmitool + FreeIPMI are installed. | `ls -l /dev/ipmi*`, `ipmitool` |
| HPL / BLAS / MPI available? | **None found.** `module` (Lmod) works but `module avail` has no hpl/blas/mkl/mpi/aocl/blis entry; no `xhpl`; nothing in `/opt` or `/usr/local`. Would need a build in `$HOME` (and MPI built with SLURM PMI support for `srun`). | `module avail`, `which xhpl` |
| Login node CPU | 2× Xeon E5-2650 v4 (Broadwell, AVX2+FMA, no AVX-512), 24 cores / 48 threads, 2 NUMA nodes, 251 GB. **Not representative** — compute nodes range from RISC-V to Grace. | `lscpu`, `free -g` |
| My groups | `gtperson`, `coc-rg-login`, other CoC course/lab groups; nothing IPMI/admin-related | `id` |

## What this means for the project

1. **SLURM won't give us energy numbers.** No energy plugin, no profiling, so
   `sacct ConsumedEnergy` is empty — there's nothing to compare against unless
   an admin enables `acct_gather_energy/ipmi`. Our calculator has to be the
   source of truth, fed by Jal's collector.
2. **Power readings need privileged BMC access.** In-band needs root on each
   node; out-of-band needs BMC network credentials. Either way that's an
   admin decision, and it decides how Jal's collector must run.
3. **Shared nodes are normal here**, so `--attribution cpu_share` is the
   relevant mode for real jobs; validation needs `--exclusive`.
4. **HPL validation target: `crush`** (rg-dev). Blocked on (1)–(2), a missing
   association, and an HPL build — see [hpl_validation.md](hpl_validation.md).

## Still unknown

* `AccountingStorageEnforce` and `PrivateData` (not in the grep).
* `scontrol show node crush`: exact CPU model, real core count, and whether
  the node's BMC supports DCMI power reading.
* Everything about pho.

## How to rerun

Run it on the cluster so the output is written there as UTF-8 (PowerShell's
`>` saves UTF-16 and wraps ssh's banner in error records), then copy it back:

```bash
scp cluster/probe.sh rg:~/ipmi-energy-cluster/probe.sh
ssh rg 'bash -l ~/ipmi-energy-cluster/probe.sh > ~/probe_rg.txt 2>&1'
scp rg:~/probe_rg.txt cluster/probe_rg_runN.txt
```

Use `pho` in place of `rg` for the pho login node.
