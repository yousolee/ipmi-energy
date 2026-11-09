#!/usr/bin/env bash
# HPL energy-validation run on ONE high-mem node.  DO NOT SUBMIT until the
# prof has OK'd it AND the two blockers below are resolved.
#
# Target (from cluster/probe_results.md, rg-login 2026-11-08): crush in
# rg-dev -- the only x86 node with >= 512 GB (1,030,000 MB), 80 CPUs =
# 4 sockets x 10 cores x 2 threads.
# BLOCKER 1: no power source inside the job. /dev/ipmi0 is root-only and
#   AcctGatherEnergyType/AcctGatherProfileType are (null), so neither the
#   ipmitool sampler below nor --profile=energy will work. Needs Jal's
#   collector (with admin-granted BMC access) running during the job.
# BLOCKER 2: no HPL/MPI/BLAS module was found; build HPL + OpenBLAS +
#   OpenMPI under $HOME first and point XHPL / MODULES_OR_PATH at it.
# Also unconfirmed: `sacctmgr show assoc user=$USER` returned nothing, so
#   submission may be rejected until an account/association exists.
#
#   phase 1: idle baseline   (node allocated exclusively, nothing running)
#   phase 2: HPL             (sized for ~15 min from this node's lscpu/meminfo)
#   phase 3: idle tail       (watch the node cool back to idle)
#
# Outputs, in $RUN_DIR:
#   phases.csv      jobs-format rows (one per phase) for `python -m energy_calc`
#   samples.csv     samples-format power readings, if this job can read IPMI
#   HPL.dat, hpl.out, lscpu.txt, meminfo.txt, env.txt
#
#SBATCH --job-name=hpl-energy
#SBATCH --partition=rg-dev             # crush's partition (MaxTime 1-01:00:00)
#SBATCH --nodelist=crush               # only x86 node >= 512 GB (~1 TB)
#SBATCH --nodes=1
#SBATCH --exclusive                    # whole node: BMC power is whole-node
#SBATCH --ntasks-per-node=40           # 4 sockets x 10 cores (sinfo S:C:T 4:10:2); one rank per physical core
#SBATCH --time=00:45:00                # 5 idle + ~15 HPL + 5 tail + slack
#SBATCH --output=%x-%j.out
## Energy profiling is OFF on rg (AcctGatherProfileType=(null), 2026-11-08).
## If an admin enables hdf5 profiling + the ipmi energy plugin, these give a
## per-sample node power series via `sh5util -j <jobid>`:
##SBATCH --profile=energy
##SBATCH --acctg-freq=energy=5

set -euo pipefail

IDLE_S=${IDLE_S:-300}
TAIL_S=${TAIL_S:-300}
TARGET_HPL_S=${TARGET_HPL_S:-900}
POLL_S=${POLL_S:-1}
NB=${NB:-192}
XHPL=${XHPL:-$HOME/opt/hpl/bin/xhpl}   # path to the HPL binary (built in $HOME)

# CHANGE_ME: no MPI/BLAS/HPL module exists on rg (probe 2026-11-08). After
# building them under $HOME, put them on PATH / LD_LIBRARY_PATH here, e.g.
# export PATH=$HOME/opt/openmpi/bin:$PATH
# export LD_LIBRARY_PATH=$HOME/opt/openmpi/lib:$HOME/opt/openblas/lib:${LD_LIBRARY_PATH:-}

RUN_DIR="$HOME/ipmi-energy-runs/${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"
cd "$RUN_DIR"
NODE=$(hostname -s)

lscpu > lscpu.txt
cat /proc/meminfo > meminfo.txt
env | grep -E '^SLURM_' | sort > env.txt

# ---------- power sampler (only if IPMI is readable without privileges) -----
sampler_pid=""
if command -v ipmitool >/dev/null && ipmitool dcmi power reading >/dev/null 2>&1; then
    echo "timestamp,node,watts" > samples.csv
    (
        while true; do
            w=$(ipmitool dcmi power reading 2>/dev/null \
                | awk '/Instantaneous power reading/ {print $4}')
            [ -n "$w" ] && echo "$(date +%s.%N),$NODE,$w" >> samples.csv
            sleep "$POLL_S"
        done
    ) &
    sampler_pid=$!
    echo "sampler: ipmitool dcmi every ${POLL_S}s (pid $sampler_pid)"
else
    echo "sampler: IPMI not readable from the job; rely on Jal's collector," \
         "SLURM energy profile (sh5util), or sacct ConsumedEnergy."
fi
cleanup() { [ -n "$sampler_pid" ] && kill "$sampler_pid" 2>/dev/null || true; }
trap cleanup EXIT

CPUS=$(nproc)
echo "jobid,nodes,start,end,alloc_cpus,total_cpus" > phases.csv
mark() {  # mark <phase> <start>  -- append a jobs-format row ending now
    echo "${SLURM_JOB_ID}.$1,$NODE,$2,$(date +%s.%N),$CPUS,$CPUS" >> phases.csv
}

# ---------- phase 1: idle baseline ------------------------------------------
t0=$(date +%s.%N)
sleep "$IDLE_S"
mark idle "$t0"

# ---------- size HPL from this node ------------------------------------------
# N is the smaller of: 80% of RAM, and the size that runs ~TARGET_HPL_S at an
# assumed 70% of a rough peak (cores x GHz x DP FLOPs/cycle).
read -r N P Q <<<"$(python3 - "$TARGET_HPL_S" "$NB" <<'EOF'
import math, os, re, sys
target, nb = float(sys.argv[1]), int(sys.argv[2])
lscpu = open("lscpu.txt").read()
def field(name, default=None):
    m = re.search(rf"^{name}:\s*(.+)$", lscpu, re.M)
    return m.group(1).strip() if m else default
cores = int(field("Socket\\(s\\)", 1)) * int(field("Core\\(s\\) per socket", 1))
ghz = float(field("CPU max MHz", field("CPU MHz", "2000"))) / 1000
flags = field("Flags", "")
flops_per_cycle = 32 if "avx512f" in flags else 16 if "fma" in flags else 8
rpeak = cores * ghz * 1e9 * flops_per_cycle
mem_kb = int(re.search(r"MemTotal:\s+(\d+)", open("meminfo.txt").read()).group(1))
n_mem = math.sqrt(0.8 * mem_kb * 1024 / 8)
n_time = (1.5 * 0.7 * rpeak * target) ** (1 / 3)   # flops = 2/3 N^3
n = int(min(n_mem, n_time)) // nb * nb
ranks = int(os.environ.get("SLURM_NTASKS", cores))
p = int(math.sqrt(ranks))
while ranks % p:
    p -= 1
print(n, p, ranks // p)
EOF
)"
echo "HPL sizing: N=$N NB=$NB P=$P Q=$Q (ranks=$((P * Q)))"

cat > HPL.dat <<EOF
HPLinpack benchmark input file
energy validation run
HPL.out      output file name (if any)
6            device out (6=stdout,7=stderr,file)
1            # of problems sizes (N)
$N           Ns
1            # of NBs
$NB          NBs
0            PMAP process mapping (0=Row-,1=Column-major)
1            # of process grids (P x Q)
$P           Ps
$Q           Qs
16.0         threshold
1            # of panel fact
2            PFACTs (0=left, 1=Crout, 2=Right)
1            # of recursive stopping criterium
4            NBMINs (>= 1)
1            # of panels in recursion
2            NDIVs
1            # of recursive panel fact.
1            RFACTs (0=left, 1=Crout, 2=Right)
1            # of broadcast
1            BCASTs (0=1rg,1=1rM,2=2rg,3=2rM,4=Lng,5=LnM)
1            # of lookahead depth
1            DEPTHs (>=0)
2            SWAP (0=bin-exch,1=long,2=mix)
64           swapping threshold
0            L1 in (0=transposed,1=no-transposed) form
0            U  in (0=transposed,1=no-transposed) form
1            Equilibration (0=no,1=yes)
8            memory alignment in double (> 0)
EOF

# ---------- phase 2: HPL ------------------------------------------------------
t0=$(date +%s.%N)
OMP_NUM_THREADS=1 srun --ntasks=$((P * Q)) --cpu-bind=cores "$XHPL" > hpl.out 2>&1 || \
    echo "xhpl exited with $?"
mark hpl "$t0"
grep -E '^W[RC]' hpl.out || true

# ---------- phase 3: idle tail -----------------------------------------------
t0=$(date +%s.%N)
sleep "$TAIL_S"
mark tail "$t0"

echo "done; results in $RUN_DIR"
