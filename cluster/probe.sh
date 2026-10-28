#!/usr/bin/env bash
# Read-only probe of a SLURM cluster for energy-accounting work.
#
# Run on the login node:   bash probe.sh > probe_$(hostname -s).txt 2>&1
#
# Every command here only reads state. Nothing uses sudo, submits jobs or
# writes outside the current directory. The two ipmitool calls are attempted
# exactly once each; a permission error is recorded, not retried.

section() { printf '\n===== %s =====\n$ %s\n' "$1" "$2"; }
run() {  # run <title> <command...>
    local title=$1; shift
    section "$title" "$*"
    timeout 60 bash -c "$*" 2>&1
    echo "[exit=$?]"
}

echo "probe run at $(date -Is) by ${USER} on $(hostname -f 2>/dev/null || hostname)"

run "host" "hostname; hostname -f; uname -a"
run "slurm version" "scontrol --version"
run "cluster name" "scontrol show config | grep -i -E '^ClusterName'"
run "partitions" "sinfo -s"
run "nodes (long)" "sinfo -N -l"
run "node memory/cpus/features" \
    "sinfo -N -o '%N %P %c %m %f %G %T' | sort -u"
run "high-mem candidates (RealMemory >= 512 GB)" \
    "sinfo -N -h -o '%N %P %m %c %f' | awk '\$3 >= 512000' | sort -u"
run "energy / acct_gather config" \
    "scontrol show config | grep -i -E 'energy|acctgather|jobacct|PrologFlags|SelectType|OverSubscribe'"
run "acct_gather.conf (if world-readable)" \
    "ls -l /etc/slurm/acct_gather.conf 2>&1; cat /etc/slurm/acct_gather.conf 2>&1 | grep -v -i password"
run "partition sharing policy" \
    "scontrol show partition | grep -E 'PartitionName|OverSubscribe|ExclusiveUser|MaxTime|AllowAccounts|AllowGroups|AllowQos'"

SACCT_FIELDS=JobID,NodeList,Elapsed,ConsumedEnergy,ConsumedEnergyRaw
section "ConsumedEnergy populated? (all users, last 7 days)" \
    "sacct -S now-7days -a -o $SACCT_FIELDS | head -50"
out=$(timeout 60 sacct -S now-7days -a -o "$SACCT_FIELDS" 2>&1)
if [ $? -ne 0 ] || grep -qi -E 'denied|not allowed|permission' <<<"$out"; then
    echo "$out" | head -5
    echo "(-a denied; falling back to own jobs)"
    timeout 60 sacct -S now-7days -o "$SACCT_FIELDS" 2>&1 | head -50
else
    echo "$out" | head -50
fi
run "how many recent jobs have non-zero energy" \
    "sacct -S now-7days -a -X -n -P -o ConsumedEnergyRaw | awk -F'|' '\$1+0>0{n++} END{print n+0, \"of\", NR, \"jobs\"}'"

run "my associations (can I submit?)" \
    "sacctmgr -n -P show assoc user=\$USER format=cluster,account,partition,qos"
run "my QOS limits" "sacctmgr -n -P show qos format=name,maxwall,maxtrespu,flags | head -30"
run "my groups" "id"

run "IPMI device nodes" "ls -l /dev/ipmi* /dev/ipmi/* 2>&1"
run "ipmitool present" "command -v ipmitool ipmi-sensors ipmi-dcmi 2>&1"
# One attempt each, no sudo.
run "ipmitool DCMI power (no sudo, single attempt)" "ipmitool dcmi power reading"
run "ipmitool PSU sensors (no sudo, single attempt)" "ipmitool sdr type 'Power Supply'"

run "HPL / BLAS / MPI modules" "module avail 2>&1 | grep -i -E 'hpl|blas|mkl|mpi|aocl|blis|openmpi|mvapich'"
run "xhpl on PATH" "which xhpl"
run "spack / easybuild hints" "ls -d /opt/* /usr/local/* 2>/dev/null | grep -i -E 'hpl|intel|oneapi|aocl|spack' | head"

run "login node lscpu (compute nodes may differ)" "lscpu"
run "login node memory" "free -g"

echo
echo "probe done at $(date -Is)"
