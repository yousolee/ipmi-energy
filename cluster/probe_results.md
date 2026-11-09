# Cluster probe results

## Run 1 — rg-login, 2026-11-08 22:43 EST (partial)

Raw output: [probe_rg_run1.txt](probe_rg_run1.txt)

Ran as `ssh rg 'bash ~/ipmi-energy-cluster/probe.sh'`. That is a
**non-login, non-interactive shell**, so `/etc/profile` was not sourced and
**every SLURM command (`sinfo`, `scontrol`, `sacct`, `sacctmgr`) and `module`
were "command not found"**, and `/etc/slurm/acct_gather.conf` doesn't exist at
that path. That says nothing about whether SLURM runs on this cluster, only
that it wasn't on PATH in that shell. `probe.sh` now sources the login profile
and records PATH / SLURM install locations; run 2 should fill the SLURM rows.

### What run 1 did establish

| Question | Answer | Evidence |
|---|---|---|
| Host | `rg-login.crnch.gatech.edu`, Ubuntu kernel 5.15.0-203 | `hostname -f`, `uname -a` |
| IPMI without sudo? | **No, not on the login node.** `/dev/ipmi0` exists but is `crw------- root root` (owner-only). Both `ipmitool` attempts failed (exit 1). | `ls -l /dev/ipmi*` |
| ipmitool / FreeIPMI installed? | Yes: `/usr/bin/ipmitool`, `/usr/sbin/ipmi-sensors`, `/usr/sbin/ipmi-dcmi` | `command -v` |
| My groups | `gtperson` + `coc-rg-login` and other CoC course/lab groups; no obvious IPMI/admin group | `id` |
| Login node CPU | 2× Xeon E5-2650 v4 (Broadwell, AVX2, no AVX-512), 12 cores/socket, 24 physical / 48 threads, 2 NUMA nodes, 251 GB RAM | `lscpu`, `free -g` |
| HPL / BLAS / MPI | Unknown — `module` wasn't defined, so the empty grep means nothing. No `xhpl` on PATH, nothing matching in `/opt` or `/usr/local`. | `module avail`, `which xhpl` |

**Note on the ipmitool error text.** It printed `Could not open device at
/dev/ipmi0 or /dev/ipmi/0 or /dev/ipmidev/0: No such file or directory`.
`/dev/ipmi0` *does* exist; ipmitool tries all three paths and reports the
errno of the last one (`/dev/ipmidev/0`, which doesn't exist). The real
failure on `/dev/ipmi0` is permission denied (mode 0600, root). Per the
rules, it was not retried with elevated access.

**Implication.** In-band IPMI reads need root (or a udev rule / group that
grants read on `/dev/ipmi0`) — on compute nodes too, most likely. So Jal's
collector either runs as root via an admin-installed service, or SLURM's own
`acct_gather_energy/ipmi` (which runs inside root-owned `slurmd`) is the data
source. That's the first question for the prof.

### Still pending (needs run 2)

SLURM version · cluster name · partitions and high-mem nodes ·
`AcctGatherEnergyType` / `EnergyIPMIFrequency` · whether `ConsumedEnergy` is
populated · profiling plugin · `PrologFlags` · my associations (can I submit) ·
node sharing policy · available modules.

## How to run it (run 2 onward)

Run it on rg so the output is written there as UTF-8 (PowerShell's `>`
saves UTF-16 and wraps ssh's banner in error records), then copy it back:

```bash
scp cluster/probe.sh rg:~/ipmi-energy-cluster/probe.sh
ssh rg 'bash -l ~/ipmi-energy-cluster/probe.sh > ~/probe_rg.txt 2>&1'
scp rg:~/probe_rg.txt cluster/probe_rg_run2.txt
```

Repeat on the pho login node with `pho` in place of `rg`.
