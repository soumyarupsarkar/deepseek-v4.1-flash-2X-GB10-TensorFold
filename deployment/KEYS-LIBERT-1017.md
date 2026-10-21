# Optional Keys mixed precision

Historical LibertAIDAI integration. Use its pinned source/image when reproducing
these results; the current setup uses [Mia EAQ 1017](../deployment/MIA-1017.md).

The optional `keys` variant keeps the stock LibertAIDAI 1017 2.9 bpw pack and
replaces `wo_b` attention projections in layers 10–35 with drowzeys' 1017 Keys
EXL3 K6 tensors. The original projections are K5. Experts, MTP, Engram, vision
and all other tensors retain their stock precision and bytes. This does not
convert the whole model to 3.5 bpw, and does not use the native FP8 sidecar.

The [published sidecar](https://huggingface.co/drowzeys/keys-DeepSeek-V4.1-Flash-1017-Abliterated)
targets the LibertAIDAI 3.5 bpw / four-GB10 configuration. This repository's
mixed-precision TP2 integration passed separate finite, full-context, throughput
and bounded memory checks on two GB10s. See the [numeric qualification
report](../release/native-keys-1017-20261018.json) and [matched stock/Keys
measurements](../benchmarks/KEYS-LIBERT-1017-COMPARISON.md). Credit goes to
Keys and drowzeys for the intervention and 1017 sidecar, LibertAIDAI for the
quantized base, and Bertholomus/TensorFold for the underlying EXL3 kernels.

## Install once

First complete the normal stock setup, including `build`, `prepare` and
`precompile`. Use the exact clean source checkout associated with the built
image. Then, with both ranks stopped:

```bash
python3 cluster setup-keys
python3 cluster start --variant keys
```

If authentication is required, point `HF_TOKEN_PATH` to an external file with
your existing read-only token. Credentials never enter the image or inference
containers. You can instead import an already downloaded, pinned sidecar:

```bash
python3 cluster setup-keys --overlay-source /absolute/path/exl3_wo_b_l10_35_1017.safetensors
```

Setup verifies the immutable revision, file hash and all 104 tensor layouts,
copies the source to the worker over SSH, and prepares only the 78 tensor
slices each rank needs. The native reader checks every prepared byte against
the sidecar and verifies the complete allowed scope against the stock cache.
Completed files are reused and never overwritten. Re-running setup after a
new build requalifies the same small caches without downloading the model.

The source sidecar is 818,590,872 bytes. Prepared tensor payloads add
409,423,872 bytes per node, plus a small index: approximately **1.23 GB extra
disk space per machine** altogether. The full stock rank cache stays shared.
Only selected tensors are uploaded, adding **65 MiB of resident weights per
GPU**. The configured 8,650,752-token shared pool and 32 slots are unchanged;
both full-window C32 and a cold million-token request passed with Keys.

## Switch and inspect

```bash
python3 cluster switch --variant stock
python3 cluster switch --variant keys
python3 cluster status
```

Pause client submissions and let active requests finish before switching.
Switching requires a healthy, idle server. It
stops both ranks, restores their temporary host settings, then starts the
chosen variant through the normal checks. A failed start attempts to restore
the previous running variant and records the result in the ignored
`deployment/.local/switch.json`. No reboot or Internet access is required.

Both variants expose the **same model IDs and context aliases**. Status reports
the selected variant; `/health` reports the actual loaded replacement count
as `native.weight_overlay_entries` (0 for stock, 78 for Keys on the head rank).
The worker's startup log reports its own count. The last successful selection
is saved locally, so `cluster start` without `--variant` uses it. A fresh
installation defaults to stock. Selection does not enable startup at boot.

Restarting discards active and retained KV state. Clients must resend their
histories; KV/prefix snapshots cannot be shared across different weights.

## Rollback and storage

To return to stock while keeping Keys available:

```bash
python3 cluster switch --variant stock
```

If the server is unhealthy or stopped, use explicit paired recovery:

```bash
python3 cluster stop
python3 cluster start --variant stock
```

To restore the captured host state and leave inference off:

```bash
python3 cluster stop
python3 cluster check-host
```

No command edits the stock safetensors or prepared cache. The Keys source and
prepared files live under each owned data root's `overlays/keys-1017/`, with
identities and verification receipts in `deployment/.local/keys-overlay.json`.
Preserve those receipts, `variant.json`, the complete installation journals,
local configuration and tested source/image. Removing either variant's assets
is a separate deliberate action, never part of switching or rollback.
