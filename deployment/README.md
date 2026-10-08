# Portable two-GB10 setup

**The verified asset-reuse path has paired hardware evidence.** The [cutover report](CUTOVER.md) covers a fresh portable image, inference/capacity, failure cleanup and restoration. Fresh model download/extraction remains an end-to-end [release gate](../release/STATUS.md). A successful offline plan alone does not establish resource fit or recovery.

Run the controller on the head node. Both nodes need an already configured compatible NVIDIA driver, Docker with NVIDIA GPU support, RDMA tools, Python 3.12+, rsync, verified passwordless SSH, and noninteractive sudo for the documented Docker/display operations. Host CUDA development packages and host NCCL are not installed by this recipe. Use two connected RoCE rails, stable IPv4 addresses, Ethernet MTU 9000 and active RDMA MTU 4096; `doctor` checks those settings without changing them.

Use otherwise idle hosts. This profile needs at least 112 GiB `MemAvailable` per host before model loading and temporarily takes over the NVIDIA display. Kernel compilation happens before loading weights. There is no boot service for the inference pair.

## Configuration and baseline

```bash
cp deployment/config/cluster.example.json deployment/local.json
# Edit deployment/local.json for this installation.
python3 cluster plan
python3 cluster doctor
python3 cluster init
```

Set the worker SSH target, each node's two rail devices/addresses, and dedicated data roots. The configured SSH users must be able to create/write those roots; the `/srv` example is not automatically made writable with sudo. Empty dedicated directories under the appropriate users' home directories are also supported. Existing nonempty or symlinked directories are refused.

The example binds the API to loopback. To expose it on a trusted LAN, set `api.bind` to the desired local IPv4 address (or `0.0.0.0`) and explicitly set `api.allow_unauthenticated_lan=true`. There is no API authentication in this recipe. Review [security](../SECURITY.md).

After reviewing [rollback](ROLLBACK.md), explicitly set `allow_temporary_drm=true` **before `init`** if using the selected profile. `init` pins the configuration, captures both hosts' baseline and creates per-installation ownership records. Later configuration drift is rejected; the original settings are saved as `deployment/.local/installed.json` for recovery. Do not edit that saved record.

`deployment/local.json` and `deployment/.local/` are Git-ignored and private. Keep the latter until every host change has been restored. Setup does not install host packages or change persistent network, boot, module or display configuration.

## Acquire and verify assets

```bash
python3 cluster fetch
python3 cluster replicate
python3 cluster verify
```

`fetch` reads `HF_TOKEN` or `HF_TOKEN_PATH` if access is needed. Provide the credential outside this repository; do not paste it into a command that records it in shell history. Credentials are not put into image layers or serving containers.

[assets.json](config/assets.json) pins the Mia checkpoint, matching Keys EXL3 sidecar, original Engram shards and metadata to immutable Hugging Face revisions and file hashes. The tool creates a separate hardlinked model view, checks the exact 104 tensor overrides and their shapes/dtypes, and verifies overlay index precedence. Original stock files are retained.

Original Engram shards are downloaded and extracted into standard safetensors files with the pinned headers/hashes in [engram-layouts.json](config/engram-layouts.json). The vision extra is assembled from bounded ranges of the pinned original weights. Files are fully hashed before replication; replication uses rsync without deletion and is followed by full worker verification.

Allow space for stock weights, the overlay, original Engram shards, extracted assets, image layers, temporary downloads and the generated rank caches. The pinned inputs are about 210.7 GB of stock files, 0.68 GB of overlay and 203.1 GB of original Engram files; derived Engram files add about 202.8 GB. With hardlinked model views and the observed prepared caches, budget roughly 724 GB on the head and 520 GB on the worker before images, logs and free-space margin (decimal GB). Prepared rank caches alone were approximately 106 GB per rank in the original installation. The controller retains the original Engram shards; it does not silently delete them to make room. Derive download sizes from the manifest and check local free space before beginning.

Downloads resume through their own range journals. A failed extraction can leave a `.prepare-part` file; inspect the failure and remove only that incomplete output before retrying. A completed file with a different hash is refused, not overwritten. Serving mounts model assets read-only. It still writes prepared weights, compiled kernels and bounded logs; disabling session KV writes does not eliminate all SSD writes.

### Reuse an existing pinned installation

On idle hosts, a migration can reuse the existing files instead of downloading another copy:

```bash
python3 cluster reuse --from-head /path/to/previous-head-data \
  --from-worker /path/to/previous-worker-data --reuse-prepared
```

Run `init` first with **new, empty data roots**. The head source must contain `stock-model/`, `overlays/`, `engram/` and `vision-extra/`; the worker source needs `model/`, `engram/` and `vision-extra/`. Both sources must match the pinned assets. This command verifies hashes and creates hardlinks on each host's filesystem, builds a new model index, and verifies both complete runtime views. It copies no ownership markers, host journals, private provenance or request logs. Source and destination must be on the same filesystem.

The optional prepared-cache import verifies complete cache files, records their hashes and loader source, and mounts them **read-only** in the new serving containers. Both prepared caches must be imported successfully before startup. Mutable kernel caches remain separate and are rebuilt by `precompile`. Incompatible prepared caches can fall back to reading the original weights; the read-only mount prevents the new deployment from replacing the old prepared bytes.

Prepared files created by Docker may be root-owned. Their import uses scoped sudo to create protected hardlinks without changing source ownership or permissions. A cache-only retry is available as `cluster reuse-prepared --from-head ... --from-worker ...`; follow an interrupted model import with `cluster verify` before startup. Cache hashes record the imported bytes; they do not independently establish that a cache was prepared from the intended weights. Import prepared files only from a trusted, previously qualified installation; omit `--reuse-prepared` otherwise.

Hardlinks preserve file contents and modification times but change inode change times. **Refresh the previous installation's full asset verification receipts before starting it again** if it checks change times. Keep its image, source and journals. Removing a link from the new root does not remove the original file; writing through either link would change shared bytes, so never edit imported assets in place. The controller serves all model files read-only.

## Build, precompile and start

```bash
python3 cluster build
python3 cluster precompile
python3 cluster start
python3 cluster status
```

`build` requires a clean committed checkout, builds from `git archive` with the pinned NVIDIA base, transfers the same image to the worker and compares image IDs. It does not push to a registry. The [resolved dependency inventory](config/requirements-resolved.txt) describes the historical image; its container-local wheel URLs are not portable pip requirements. The Dockerfile derives package constraints and preserves the base's PyTorch. A fresh build still needs dependency and hardware qualification.

`precompile` compiles serving extensions on both nodes with weights unloaded, network disabled and a bounded 16 GiB container. `start` verifies ownership, assets, rails, image, memory and ports; journals display state; applies current-boot DRM settings; then launches worker and head. It requires both ranks and an active transient monitor before reporting success.

The selected profile has a 2.5 GiB engine memory floor and a 2 GiB host-availability watchdog. The monitor stops both owned ranks after repeated failed health/memory checks or stalled progress; it does not automatically restart a poisoned runtime. No monitoring service is enabled at boot. See [sampling](SAMPLING.md) and [capacity/measurement limits](../benchmarks/README.md).

Once ready, a local request is:

```bash
curl --fail http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"DeepSeek-V4.1-Flash-Keys","messages":[{"role":"user","content":"What is 12 times 13?"}],"max_tokens":64}'
```

The 1,048,576 limit covers prompt plus reply; the 8,650,752-token pool is shared by active and retained states. The 32 slots do not promise 32 simultaneously full million-token histories.

The [paired acceptance clients](../tools/qualification/README.md) exercise the
selected installation with synthetic inputs and keep their receipts private.
Run them during qualification before treating a new build as serving-ready.

## Stop and restore

```bash
python3 cluster stop
python3 cluster check-host
```

Stop retains weights, caches, images and source. It removes only this installation's labeled rank containers and transient monitor, and restores captured display state where safe. `check-host` compares driver/kernel, display/module state and configured rail addresses/MTUs with the baseline. It reports differences without automatically correcting them. [Recovery and removal details](ROLLBACK.md).
