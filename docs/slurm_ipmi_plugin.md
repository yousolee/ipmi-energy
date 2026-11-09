# How SLURM's `acct_gather_energy/ipmi` plugin computes energy

Source read: `github.com/SchedMD/slurm` at tag **`slurm-25-05-5-1`**, matching
the Rogues Gallery cluster (`scontrol --version` → `slurm 25.05.5`, probed
2026-11-08). All line numbers below are for that tag. They were first written
against `master` at `ee3ebedaec57` (26.11 pre-release) and remapped with a
line-level diff; every cited range is textually identical between the two
except where noted. The only behavioural difference in the plugin between the
two is that newer `master` skips the `EnergyIPMICalcAdjustment` extrapolation
for a sensor reading `NO_VAL`; 25.05.5 extrapolates unconditionally.

**But the cluster does not run this plugin.** `scontrol show config` reports
`AcctGatherEnergyType = (null)`, so no BMC polling happens and `sacct`
`ConsumedEnergy` is never populated. Everything below describes what SLURM
*would* do if an admin enabled it.

Paths below are relative to the SLURM repo root. `ipmi.c` means
`src/plugins/acct_gather_energy/ipmi/acct_gather_energy_ipmi.c`.

## 1. Who polls the BMC, and how often

* The plugin only does real work inside `slurmd`/`slurmstepd`
  (`ipmi.c:1626`). In **slurmd** it starts a launcher thread
  (`ipmi.c:1634-1636`), which starts the polling thread `_thread_ipmi_run`
  (`ipmi.c:932`) and waits up to `EnergyIPMITimeout` seconds (default 10,
  `acct_gather_energy_ipmi_config.c:57,68`) for it to initialise; if it
  doesn't, the thread is cancelled and energy accounting is off for that slurmd
  (`ipmi.c:943-963`).
* The polling loop (`ipmi.c:910-917`) calls `_thread_update_node_energy()`, then
  sleeps on a condition variable until `abs.tv_sec += EnergyIPMIFrequency`:

  ```c
  _thread_update_node_energy(&ipmi_dcmi_ctx);
  abs.tv_sec += slurm_ipmi_conf.freq;
  slurm_cond_timedwait(&ipmi_cond, &ipmi_mutex, &abs);
  ```

  `EnergyIPMIFrequency` defaults to **30 s** (`DEFAULT_IPMI_FREQ`,
  `acct_gather_energy_ipmi_config.h:42`) and must be > 0 (`ipmi.c:1597-1599`).
* The loop can also be woken early: a `slurmstepd` asking for energy sends an
  RPC to slurmd; if slurmd's last poll is older than the requested `delta`
  (10 s from `_get_joules_task(10)`, `ipmi.c:1278,1294`), slurmd forces a fresh
  read (`src/slurmd/slurmd/req.c:3617-3619`), and `ENERGY_DATA_JOULES_TASK`
  signals `ipmi_cond` (`ipmi.c:1306-1309`).
* Timestamps are `time(NULL)` — **whole seconds** (`ipmi.c:671-672`).

So the BMC is read *at most* every `EnergyIPMIFrequency` seconds plus whenever
a step asks for a fresh value, and every reading carries a 1-second-resolution
timestamp.

## 2. Which libfreeipmi / DCMI calls read power

Two paths, selected by `EnergyIPMIPowerSensors` (section 4):

| Path | Call | Where |
|---|---|---|
| SDR sensor (default) | `ipmi_monitoring_sensor_readings_by_record_id()` from libipmimonitoring, then `ipmi_monitoring_sensor_read_sensor_units()` / `..._read_sensor_reading()` | discovery `ipmi.c:392-466`, periodic read `ipmi.c:608-648` |
| DCMI | `ipmi_cmd_dcmi_get_power_reading()` (libfreeipmi) with mode `IPMI_DCMI_POWER_READING_MODE_SYSTEM_POWER_STATISTICS` (`DCMI`) or `..._ENHANCED_SYSTEM_POWER_STATISTICS` (`DCMI_ENHANCED`), then `FIID_OBJ_GET(dcmi_rs, "current_power", ...)` | `ipmi.c:480-536` |

* In-band only for DCMI: `ipmi_ctx_find_inband()` (`ipmi.c:228-235`) — i.e. the
  local `/dev/ipmi0` (KCS/SSIF) driver, run as root by slurmd.
* With no `EnergyIPMIPowerSensors`, `_find_power_sensor()` walks **all** SDR
  sensors and takes **the first one whose unit is Watts**
  (`ipmi.c:419-465`; unit set by `EnergyIPMIVariable`, default Watts,
  `acct_gather_energy_ipmi_config.c:94`). Which sensor that is depends on the
  BMC's SDR order — it could be a PSU input sensor, a "Pwr Consumption"
  sensor, or something narrower. This is worth checking on our nodes with
  `ipmitool sdr type "Power Supply"` / `ipmi-sensors -t Current`.
* The reading is truncated to an integer: `(uint32_t) (*((double *)sensor_reading))`
  (`ipmi.c:447-448`, `581-582`). DCMI `current_power` is already integer watts.

## 3. Watts → joules (the core math)

The accumulator is `_update_energy()` (`ipmi.c:678-706`), called once per
sensor per poll (`ipmi.c:722-728`). The increment is
`_get_additional_consumption()` (`ipmi.c:205-209`):

```c
return (uint64_t) ((time1 - time0)*(watt1 + watt0)/2);
```

i.e. **trapezoid rule** between consecutive polls:

    ΔE_k = (t_k − t_{k−1}) · (P_{k−1} + P_k) / 2         [J]
    consumed_energy += ΔE_k

Details that matter for accuracy:

* `time0/time1` are `previous_update_time` / `last_update_time` (integer
  seconds, `ipmi.c:692-696`); `watt0` is the previous `current_watts`,
  `watt1` the new one.
* All integer arithmetic: watts truncated to int, Δt in whole seconds,
  and `/2` is integer division — each step loses up to 0.5 J from the
  division plus up to 1 W·Δt from truncating each reading.
* The very first reading only initialises `current_watts`; it contributes no
  energy (`ipmi.c:699-703`), and the first interval after slurmd start uses
  `base_consumed_energy = 0` when `previous_update_time == 0` (`ipmi.c:688-689`).
* `ave_watts` is a running mean of readings (`ipmi.c:685-686`), not E/t, and
  uses the *previous* reading — it lags by one sample.

So: **SLURM's default is trapezoid, not rectangle.** There is no option to
change it.

### What `EnergyIPMICalcAdjustment` changes

Default `false` (`acct_gather_energy_ipmi_config.c:67`, `ipmi.c:1601-1603`).
It only affects the value seen by **slurmstepd** (the per-step number), not
slurmd's node counter. In `_get_joules_task()` (`ipmi.c:1017-1021`):

```c
adjustment = _get_additional_consumption(
        new->poll_time, time(NULL),
        new->current_watts, new->current_watts);
```

That is a **rectangle extrapolation**: energy from the last BMC poll up to
"now" assuming power stayed at the last reading. It is added to the step's
consumed energy (`ipmi.c:1050`) and remembered in `last_adjustment`
(`ipmi.c:1124`); on the next call the previous adjustment is subtracted before
adding the real increment (`ipmi.c:1125-1127`, `1090-1095`), so it never
double-counts. Net effect: the step's energy at start/end is estimated to the
second instead of being quantised to the last poll — this matters most for
short jobs relative to `EnergyIPMIFrequency`. Without it, energy between the
last poll and the step end (up to one full poll interval) is simply missing.

## 4. `EnergyIPMIPowerSensors`

Parsed by `_parse_sensor_descriptions()` (`ipmi.c:1363-1473`). Format:

    EnergyIPMIPowerSensors=Node=DCMI;Socket0=4,5;Socket1=6,7

* `;` separates labelled groups, `,` separates sensor IDs (SDR record IDs) or
  the keywords `DCMI` / `DCMI_ENHANCED` (`ipmi.c:1414-1423`).
* A group labelled `Node` is **mandatory**, otherwise `fatal()`
  (`ipmi.c:1436-1441`, `1467-1470`).
* Node energy = sum of the energies of all sensors listed under `Node`
  (`_get_node_energy`, `ipmi.c:1156-1182`; sum in `_sum_energy`,
  `ipmi.c:1143-1154`). Each sensor is integrated separately with the
  trapezoid rule, then summed — useful for nodes with two PSUs, each with its
  own input-power sensor.
* Other labels only feed the `acct_gather_profile` time series
  (`_ipmi_send_profile`, `ipmi.c:815-864`), named `<Label>Power`.
* If unset, the "first Watts sensor" auto-discovery in section 2 applies.

## 5. From node energy to `sacct ConsumedEnergy`

1. **slurmd** keeps a monotonically increasing per-node joule counter since
   slurmd start (section 3).
2. Each **slurmstepd** asks slurmd for it via RPC
   (`slurm_get_node_energy`, `ipmi.c:985`). On the first call it stores the
   counter as `start_current_energies` (`ipmi.c:1106-1108`); afterwards the
   step's energy is *counter now − counter at step start*
   (`ipmi.c:1090-1095`, `1125-1127`). slurmd restarts are detected via
   `slurmd_start_time` (`ipmi.c:1035-1048`); a counter going backwards marks
   the IPMI as faulty and zeroes the step's energy (`ipmi.c:1062-1087`).
3. jobacct_gather reads it every `JobAcctGatherFrequency` into
   `tres_usage_in_tot[TRES_ARRAY_ENERGY]` — **once per node**, not per task
   (`src/plugins/jobacct_gather/common/common_jag.c:1173-1189`).
4. Per-node step records are combined by **summing** consumed energy
   (`jobacctinfo_aggregate`, `src/interfaces/jobacct_gather.c:1241-1246`). A
   multi-node step's energy = Σ over its nodes.
5. When a step ends, slurmctld adds its energy into the job's
   `tres_alloc_cnt[TRES_ARRAY_ENERGY]` (`src/stepmgr/stepmgr.c:255-260`).
   **Exception:** with `PrologFlags=Contain` only the `extern` step is counted
   (`stepmgr.c:250-252`), since it spans the whole job and the others would
   double-count.
6. `sacct` prints the job's `ConsumedEnergy` from the job's TRES string
   (`TRES_ENERGY`), and a step's from `step->stats.consumed_energy`
   (`src/sacct/print.c:687-699`). Units are joules; `ConsumedEnergy` is
   formatted with SI prefixes (K, M), `ConsumedEnergyRaw` is the raw integer.

## 6. Known limitations

* **Sampling resolution.** Default 30 s polls, 1-s timestamps, integer watts.
  A 60-s job gets ~2 trapezoids. Short power spikes between polls are lost
  (aliasing). See `docs/energy_math.md` for the measured error vs. poll
  interval.
* **Edges.** Without `EnergyIPMICalcAdjustment`, energy is quantised to poll
  boundaries: the step start is aligned to the last poll before it and up to
  one interval at the end is dropped.
* **Whole-node measurement.** The BMC sensor measures the whole node
  (typically AC input at the PSU, including fans, PSU losses, disks, NICs,
  idle draw). Nothing is subtracted for idle.
* **Shared nodes.** Every step on a node gets the *full* node delta over its
  lifetime (step 2 above). Two jobs sharing a node are each charged the whole
  node — node energy is **not** split by CPUs. Sum of `ConsumedEnergy` over
  jobs can therefore exceed what the node actually used.
* **BMC behaviour.** The BMC itself may average (DCMI uses a rolling window,
  often 1 s–several s) and update its sensor less often than we poll, so
  faster `EnergyIPMIFrequency` doesn't necessarily add information.
* **Sensor choice.** Auto-discovery takes the first Watts sensor in SDR
  order, which may not be total node input power.
* **Fragility.** IPMI calls can hang; failure → `faulty_ipmi`, energy zeroed
  for the step (`ipmi.c:1084-1086`), and `sacct` shows 0.

## Confirmed vs. assumed

* **Confirmed from source** (`slurm-25-05-5-1`): everything with a line
  reference above.
* **Confirmed on the cluster** (rg-login, 2026-11-08): SLURM 25.05.5;
  `AcctGatherEnergyType = (null)` (plugin **not enabled**);
  `AcctGatherProfileType = (null)`; `PrologFlags = Alloc,Contain,X11`;
  `JobAcctGatherType = jobacct_gather/linux`, frequency 10 s; `energy` is
  listed in `AccountingStorageTRES` but nothing feeds it.
* **Unknown:** what `EnergyIPMIFrequency` / `EnergyIPMIPowerSensors` /
  `EnergyIPMICalcAdjustment` would be set to if it were enabled (no
  `acct_gather.conf` exists), and whether compute-node BMCs support DCMI
  power reading at all.
