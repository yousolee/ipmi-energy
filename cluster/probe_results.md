# Cluster probe results

**Status: NOT RUN YET.** No SLURM/cluster access as of 2026-10-28 (expected
by end of day). From the laptop, `ssh rg` (rg-login.crnch.gatech.edu, user
`ylee880`) reaches the login banner but key auth is refused — login needs a
password, so the probe has to be run interactively.

## How to fill this in

```bash
scp -r cluster rg:~/ipmi-energy-cluster      # or copy probe.sh by hand
ssh rg
bash ~/ipmi-energy-cluster/probe.sh > ~/probe_$(hostname -s).txt 2>&1
```

Then paste the output below (or `scp` it back) and fill in the
interpretation. Repeat on the pho login node.

## Raw output

_pending_

## Interpretation

| Question | Answer | Evidence |
|---|---|---|
| Host / cluster | _pending_ | `hostname`, `ClusterName` |
| SLURM version | _pending_ | `scontrol --version` |
| High-mem partition / nodes | _pending_ | `sinfo -N -l`, RealMemory ≥ 512 GB |
| Energy plugin & frequency | _pending_ | `AcctGatherEnergyType`, `EnergyIPMIFrequency` |
| ConsumedEnergy populated? | _pending_ | non-zero fraction from sacct |
| Energy profiling (hdf5)? | _pending_ | `AcctGatherProfileType` |
| PrologFlags=Contain? | _pending_ | affects which step carries job energy |
| Can I submit, where? | _pending_ | `sacctmgr show assoc` |
| Nodes shared or exclusive? | _pending_ | `OverSubscribe`, `SelectTypeParameters` |
| IPMI without sudo? | _pending_ | `/dev/ipmi*` perms, ipmitool exit |
| HPL / BLAS / MPI available? | _pending_ | `module avail`, `which xhpl` |
| Login node CPU | _pending_ | `lscpu` (compute nodes may differ) |
