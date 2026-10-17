# DeepSeek V4.1 Flash 1017 migration

The candidate uses the stock **DeepSeek-V4.1-Flash-1017** checkpoint. The original
Keys overlay contains replacement attention weights, not deltas. Applying it
to 1017 would replace updated weights with weights from the previous model.
A separately produced, checkpoint-matched overlay needs its own qualification.

## Inputs and compatibility

| Input | Immutable revision |
|---|---|
| [LibertAIDAI EXL3 2.9 bpw](https://huggingface.co/LibertAIDAI/DeepSeek-V4.1-Flash-1017-EXL3-2.9bpw) | `c178a01284fc5c0e859d8668cffaac81ca8f4042` |
| [DeepSeek 1017 reference and Engram](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) | `1bae0e1088993b9b82de08f59de5be5a34e42170` |

The text and vision configurations match the previous checkpoint, and
`tokenizer.json` is byte-identical. Weight contents and the two Engram tables
have changed. Rebuild both rank caches; do not reuse an old prepared cache or
retained KV state across checkpoints. The EXL3 conversion raises several MTP
dense projections from 4 to 6 bpw, while routed MTP experts remain 4 bpw.

The native path implements the reference's new E4M3 activation rounding before
`wo_a`, after inverse RoPE and before EXL3 input rotation, in prompt processing,
target decoding and all three draft stages. `TF_DS_FP8_WOA=1` selects that math
on both ranks. The original checkpoint's path remains available with `0`.
The explicit `TF_DS_VISION_BIAS` path selects the new checkpoint's verified
routing biases instead of the older biases bundled in the kernel kit.

The 1017 repository ships a Python reference encoder without a Jinja template.
The recipe adapts Mia's template: tool-only results do not start a new user turn,
text content blocks retain the reference separators, and tool images are ordered
with their results before image bytes are collected. Thirty synthetic cases
recorded from the pinned encoder exercise both the Python and native renderers.
Their inputs do not come from the inference server's request history.

## Reversible migration

Keep the previous **clean source checkout, built image on both hosts,
`deployment/local.json`, entire `deployment/.local/` directory, model/Engram
files and both prepared rank caches**. The state directory contains ownership,
asset hashes, cache fingerprints and the actual host restoration journals.
Git alone is not a deployment backup.

Stage new downloads in separate directories. The model download is about
211 GB and the original Engram source shards about 203 GB. Completed download
ranges are journaled, and every completed file is checked against its pinned
hash. The native Engram reader already addresses named tensors by header
offset, so the serving view hardlinks the verified original shards on the head
instead of writing another 203 GB extraction. The downloader flushes and releases file-cache pages during large ranges.

If the worker cannot hold both installations, copy its old rank cache to the
head and verify its SHA256 against both the source and a readback of the copy.
Verify that every old worker model and Engram asset also has a matching copy on
the head. **Do bulk backup/copy/hash work with the old pair stopped**: the worker's
2 GiB guard was triggered during this migration's backup despite both copy
processes having memory limits. Preserve all old hardlink
locations in the private migration journal before reclaiming any worker files.
Delete only the verified, backed-up asset files; retain images, configuration,
ownership markers and host journals. Do not use a global Docker prune.

Stop the previous pair through its own controller and confirm restoration:

```bash
# In the preserved previous checkout:
python3 cluster stop
python3 cluster check-host
```

Initialize the new installation only after restoration, using new empty data
roots and its own ownership UUID. Follow [setup](README.md) to acquire, extract,
replicate, build, prepare and qualify. Keep the same 32 slots, 8,650,752-token
pool, 1,048,576-token ceiling and 2 GiB host-memory floor while qualifying.
No driver, kernel, networking or persistent DRM change is required by this
migration. No reboot is expected.

## Restore the previous deployment

1. Stop the candidate with its controller, then run `python3 cluster check-host`.
2. If old worker assets were removed, first preserve any candidate assets needed
   for another attempt on the head. Reclaim only candidate files recorded in its
   manifest, then copy the old model, Engram and prepared cache back to their
   original paths. Verify all copies against the preserved old hashes.
3. In the original checkout, run `python3 cluster verify` and
   `python3 cluster precompile`. The latter compares every prepared tensor with
   the old checkpoint. A restored file has a new inode and change time: for an
   imported prepared cache, refresh its saved fingerprint **only after** its
   original saved SHA256 and complete native cache comparison pass. Keep an
   audit receipt of the old and new fingerprints. Never remove integrity checks
   or substitute the candidate's manifests for the original ones.
4. Run `python3 cluster start` in the old checkout, check `/health`, and complete
   a small synthetic request using the old model ID.

Do not overwrite live restoration journals with their backups: a successful
stop has already advanced their state. A restart cannot recover in-memory
sessions that were present before shutdown; clients must resend their histories.

## Acceptance gates

Before promoting the candidate, verify all assets and prepared tensors, GPU
checks on both hosts, strict JSON/tool calls, image and tool-image inputs,
explicit-seed replay, all draft stages, odd compression boundaries, the
long-text request-memory regression, full-window C32 and a million-token request.
Collect fresh C1/C32 code, prose and counting measurements for greedy and sampled
requests, then run a bounded mixed-workload soak with host-memory and rank-health
monitoring. Report new checkpoint results separately from the old Keys results.

The standalone attention test is `tools/qualification/check_1017_fp8.cu`;
`cluster precompile` builds on the same check and runs it on both GPUs. It compares
E4M3 rounding against an independent enumeration oracle, including signed zeros,
tiny values, halfway bins, multiple row sizes, a grid-stride case and CUDA graph
replay. Passing this operation check is necessary but does not replace the
serving and capacity tests above.
