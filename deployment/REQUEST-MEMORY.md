# Concurrent text-prompt memory investigation

On October 12, 2026 at 20:58 PDT, the paired watchdog stopped the native
deployment after head-host available memory crossed its unchanged 2 GiB floor
twice. The last failed sample had 1.77 GiB available. Inference was still
progressing; there was no recorded OOM, poisoned runtime or RoCE failure.

The preceding twelve-hour diagnostic had completed successfully. Its short
mixed replies and token-array deep prompts did not reproduce the CPU working
memory of concurrent long text conversations. During the later C32 workload,
head-process anonymous memory plus swap grew by about 1.1 GiB in seven minutes,
while live glibc allocation and the grammar cache stayed nearly flat.

## Cause and correction

The tokenizer and chat-template evaluator created temporary arenas backed by
the request's own arena. Freeing those nested arenas did not release their
working buffers from the outer arena. Large BPE and template intermediates
therefore lived until the entire inference reply ended. Chat preparation
renders both the generation prompt and the conversation history, magnifying
the retained working memory at concurrency.

`HfText` now gives encoding and rendering independent scratch arenas backed by
the general allocator. Only returned token IDs, rendered text and error
diagnostics are copied into the request arena. Scratch is released before
inference waits or decodes. A per-model mutex also bounds simultaneous CPU
encoding/template work; decode callbacks and GPU scheduling do not take it.
This prevents transient preparation buffers from multiplying by C32.

The change preserves 32 GPU slots, the 8,650,752-token shared pool, the
1,048,576-token request ceiling, sampling, Keys weights, vision, structured
output, the existing glibc trim policy and the paired watchdog's 2 GiB floor.

## Controlled reproduction

These CPU-only tests use the real checkpoint tokenizer/template with the
existing scripted engine. Prompts are generated synthetic code; no production
prompts or replies are used. Both binaries generated the same token sequences.
RSS includes the tokenizer, HTTP server and scripted engine, but no model
weights or GPU memory. The table reports the process high-water RSS rather than
a sampled maximum that might miss brief allocation bursts.

| CPU HTTP workload | Original peak RSS | Corrected peak RSS |
|---|---:|---:|
| C32, 17,613 prompt tokens, four delayed output tokens | 1,153 MiB | 160 MiB |
| C32, 261,813 prompt tokens, four delayed output tokens | — | 686 MiB |
| C32, 17,613 prompt tokens, 4,096 streamed output tokens | — | 501 MiB |
| C8, 990,013 prompt tokens, four delayed output tokens | — | 1,022 MiB |

The last exploratory case completed all eight correct replies but exceeded a
900 MiB diagnostic ceiling. Its measured peak was about 0.91 GiB above the
idle process; this is distinct from a GPU serving result or a watchdog-floor
failure. The original ceiling failure is retained in the private evidence.

Releasing scratch without bounding concurrent preparation reduced sustained
memory substantially, but a C32/264,013-token case still reached 3,262 MiB RSS
briefly. The preparation mutex addresses that burst as well as the retention.

Two unit regressions check that tokenization and rendering retain only their
results in the caller's arena, including special tokens and error-diagnostic
lifetime. The existing real-tokenizer protocol corpus matched in all 35 cases
after normalizing IDs and timing fields, including native `decode_seconds`.

To reproduce inside a development environment using the repository's pinned
Zig compiler, build the existing CPU test server:

```bash
zig build-exe -O ReleaseSafe -lc -femit-bin=/tmp/fake-serve \
  --dep server --dep engine_api --dep tokenizer --dep template \
  -Mroot=zig/tests/server/fake_serve.zig \
  --dep engine_api --dep tokenizer --dep template \
  -Mserver=zig/src/server/root.zig \
  --dep lanes -Mengine_api=zig/src/core/engine_api.zig \
  -Mlanes=zig/src/core/lanes/lanes.zig \
  -Mtokenizer=zig/src/core/tokenizer/tokenizer.zig \
  -Mtemplate=zig/src/core/template/template.zig

python3 tools/qualification/native_request_memory.py \
  --binary /tmp/fake-serve --tokenizer /path/to/model \
  --output /tmp/new-c32-memory-run --stream
```

Use a new output directory for each run. `--repeat 11900` exercises near-262k
text prompts; `--parallel 8 --repeat 45000` exercises near-million-token text
prompts. `--chunks 4096 --delay-ms 2` exercises longer streamed replies. The
client starts only its scripted child on an ephemeral loopback port, records
numeric memory/usage and output digests, then terminates the child. It never
connects to or changes an existing inference deployment.

## Live verification

Runtime `0d39dfcf` passed 318 native build tests, 84 publication tests and
14 controller tests. Both hosts passed seven GPU checks and a full comparison
of all 143,770 prepared-cache entries, with no byte or layout differences.

The restored pair completed 556 synthetic requests across feature checks,
memory regression, capacity, throughput and a LAN canary:

- Text, vision, strict JSON, tool calls, streaming and drafted/ordinary parity
  passed.
- Two C32 waves with 17,613-token text prompts and 768-token streamed replies
  completed; all 32 reply-token sequences matched on replay.
- Two C32 waves filled each session to 262,144 tokens (261,120 prompt plus
  1,024 reply). Both reached 32 decoding sessions, and all 32 replay-token
  sequences matched. Vision also passed afterward.
- All 24 code/prose/counting throughput waves completed. C32 rates were within
  2.1% of the previous image's single-run comparison. Initial greedy C1 code
  measured 93.5 tok/s while capturing six graphs; three declared repeats
  measured 100.0, 100.8 and 99.7 tok/s without new captures. All four replies
  matched; their combined median was 99.8 tok/s versus the headline baseline's
  100.2 tok/s. The original lower result remains in the report.

Available memory stayed above 3.18 GiB on the head and 3.40 GiB on the worker
during the monitored follow-up. There were no observed OOMs, poisoned runtime,
RDMA failures, rank restarts or watchdog probe errors. The worker verified LAN
access and all four context aliases. This finite follow-up does not repeat the
earlier twelve-hour test; the code/prose/counting hero measurements remain the
existing three-repetition baseline.

The [numeric report](../release/native-request-memory-20261012.json) identifies
the exact source/image and retains all comparisons, including the exploratory
CPU ceiling failure. Raw incident logs and installation details remain local.

## Rollback

The previous source/image and stopped-state recovery records are retained
locally. No host configuration or weight files change for this fix.

Run `python3 cluster stop` from the owning deployment checkout to stop both
ranks and restore the journaled display state. To select the previous runtime,
use its committed source and retained image with matching build, precompile
and prepared-cache verification receipts; rerun verification if the cached
inputs changed. Keep current ownership and host-restoration journals. Never
copy an old `active.json`, launch record or DRM journal over live state.

The previous image still has the reproduced request-memory issue. Restoring
it is a rollback mechanism, not a correction for the failure.
