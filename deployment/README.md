# Native two-GB10 setup

This runbook describes the native Zig deployment. See [current measured
acceptance](../release/STATUS.md). A build, a successful plan, and
cache compatibility checks do not establish serving qualification. Consult the
release's qualification report before selecting it for production. Historical
Python benchmark and recovery receipts are reference results, not native results.

## Prerequisites

Use two otherwise idle NVIDIA GB10 Linux hosts with compatible NVIDIA drivers,
Docker with NVIDIA GPU support, Python 3.12+, rsync, verified passwordless SSH,
noninteractive sudo, systemd, module tools, `ip`, `ibv_devinfo` and `nvidia-smi`.
Install Git on the head. The controller runs there and manages the worker over
SSH. Host CUDA development packages, host NCCL and a host Zig installation are
not required: compilation and inference dependencies stay in the image.

Prepare both RoCE rails, stable IPv4 addresses, Ethernet MTU 9000 and active
RDMA MTU 4096 before capturing the baseline. Startup requires at least 112 GiB
`MemAvailable` on each host and temporarily takes over the NVIDIA display.
Routine start/stop needs no reboot. Prerequisite driver/package/network changes
are outside the recipe's rollback scope.

Use dedicated writable data roots, initially empty and without symlink
redirection. Fresh acquisition needs roughly 521 GB on each host, plus the approximately 24.5 GB image, temporary download/build
space, logs and free-space margin. These are decimal GB. The estimate includes approximately 106 GB of prepared weights per rank.
The native Engram view hardlinks the verified original shards on the head,
avoiding a second 203 GB copy. The pinned native kit adds approximately 0.67 GB per node.

## Configure and record the baseline

```bash
cp deployment/config/cluster.example.json deployment/local.json
# Edit this file before init.
python3 cluster plan
python3 cluster doctor
python3 cluster init
```

Configure the worker SSH target, both hosts' rail devices and addresses, data
roots, API bind/port and rendezvous port. Review rollback before setting
`allow_temporary_drm=true`. Keep the default loopback bind while qualifying a
new build. A LAN bind additionally requires
`api.allow_unauthenticated_lan=true`; this recipe exposes no API authentication.

`plan` performs no host actions. `doctor` reads host/network state. `init`
creates an installation UUID, captures both host baselines and pins the local
configuration. Later configuration drift is refused. Preserve the ignored
`deployment/local.json` and the complete `deployment/.local/` directory; Git
alone does not back up recovery state.

## Acquire verified inputs

If model access needs authentication, set `HF_TOKEN_PATH` to an external file
containing a read-only token. Do not put credentials in this checkout, image,
command history or serving containers.

```bash
python3 cluster fetch
python3 cluster replicate
python3 cluster verify
```

The manifests pin LibertAIDAI's stock 1017 EXL3 weights, matching 1017
Engram/vision assets, the adapted chat template and Bertholomus's native
kernel kit to immutable revisions and hashes. The previous Keys overlay is
not applied to this checkpoint; it contains replacement weights from the
original model. See [the checkpoint migration notes](CHECKPOINT-1017.md). Extraction creates a separate verified model view and
retains stock files. Replication uses rsync without deletion. Completed files
whose hashes differ are refused.

For a migration from an installation with the same pinned assets, initialize
new empty roots, then reuse the files instead:

```bash
python3 cluster reuse --from-head /path/to/previous-head-data \
  --from-worker /path/to/previous-worker-data --reuse-prepared
python3 cluster fetch-kit
python3 cluster replicate-kit
```

Reuse verifies files and creates immutable hardlinks on each host's filesystem.
It does not copy ownership markers, host journals, private request logs or
mutable caches. Prepared caches are mounted read-only. A complete comparison
of every prepared tensor with the intended checkpoint is required below; a
file hash alone does not establish which weights a cache contains.

Additional hardlinks change inode change times. Before restarting a previous
installation, refresh its full asset verification and revalidate its prepared
cache fingerprints against the original content hashes. Never edit shared
files, erase an integrity check, or replace current host journals with a backup.

## Build, prepare, verify and start

Use a clean, committed checkout. Run each step only after its predecessor
succeeds:

```bash
python3 cluster build
python3 cluster prepare
python3 cluster precompile
python3 cluster start
python3 cluster status
```

`build` archives the exact Git commit, verifies the pinned Zig compiler,
compiles the native engine/kernels and xgrammar bridge, runs their CPU tests,
and transfers the identical image to the worker. It does not publish an image.

`prepare` creates absent rank caches with a CPU-only native tool, or preserves
imported caches. It prepares the compressed Engram token map and checks it
against the pinned kit's digest. Completed rank caches are never overwritten.
A failed write retains its `.partial` file; inspect the failure before removing
only that incomplete output and retrying. This preparation writes persistent
weight/cache artifacts, not session KV histories.

`precompile` exercises CUDA copies, graphs, sampling, cuBLAS and NCCL with
weights unloaded, verifies router widths 1–48 against single-row GPU launches,
then compares every prepared tensor byte on both hosts. Its
receipts bind the results to the selected image and asset identities. Native
kernels are already built into the image; no model-time extension compilation
is required.

`start` checks ownership, immutable assets and kit, cache compatibility,
identical image IDs, rails, memory and ports. It journals display state before
applying current-boot DRM settings, then starts worker and head. A transient
monitor observes both ranks and stops the pair on repeated health/memory
failures or stalled progress. A poisoned runtime requires both ranks to restart.
No inference service is enabled at boot.

The serving engine, scheduler and sampler are native Zig/CUDA. xgrammar is a
pinned C++ library. Offline token-map preparation uses `tokenizers`; upstream's
bounded Pillow helper handles image codecs beyond native PNG. The NVIDIA base
contains Python/PyTorch, but no Python model engine or PyTorch tensor loop runs
in this native serving path.

## API and resource policy

The base model ID is `DeepSeek-V4.1-Flash-1017`. Advertised suffix aliases are
`-262k`, `-524k`, `-614k` and `-1m`, with ceilings of 262,144, 524,288, 614,400 and
1,048,576 tokens respectively, counting prompt plus reply. The aliases use the
same loaded model and shared pool; they do not allocate separate models.

The profile provides 32 active slots and 8,650,752 shared KV tokens. Active and
retained sessions share this capacity. Thirty-two slots do not imply thirty-two
full million-token histories. Read measured qualification evidence for the
release's supported combinations.

Unseeded sampled requests use random seeds in the deployment. Explicit seeds
remain replayable, and prompt-derived seeding remains configurable. Greedy
requests remain deterministic where kernels and request paths are deterministic.
Prefix snapshots stay in memory; session KV writes to NVMe are disabled.

## Stop and restore

```bash
python3 cluster stop
python3 cluster check-host
```

Stop removes only this installation's owned rank containers and transient
monitor, saves logs and restores captured display/module state. It retains
models, prepared/kernel caches, images and source. `check-host` compares the
host baseline, including rail addresses and MTUs, without overwriting unexpected
differences. Keep all recovery state until restoration succeeds.

If local configuration changed, use its saved original copy:

```bash
python3 cluster --config deployment/.local/installed.json stop
python3 cluster --config deployment/.local/installed.json check-host
```

If a worker is unavailable, bring it back and retry with the same journals.
After reboot, the controller compares state without imposing stale current-boot
module settings. Do not alter ownership records to silence a failure. Removing
retained assets or image tags is a separate decision after restoration and
shared-reference checks; no global Docker prune is part of rollback.
