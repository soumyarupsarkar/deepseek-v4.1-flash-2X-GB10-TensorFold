# Measurement definitions and reproduction

The bundle contains original two-GB10 measurements from 2026-10-07, portable-cutover measurements from 2026-10-08, and the later FP32 correctness update on 2026-10-08 (UTC). Both portable builds reused fully verified model/prepared assets. Current engine fingerprints and historical provenance are in [engine-source.json](../release/engine-source.json). Sanitized summaries retain ranges and source-receipt hashes. Private raw operational receipts, host inventories and logs are not bundled; their hashes are provenance references, not links to downloadable files.

The [October 9 selective update](../deployment/UPSTREAM-V06.md) has separate
correctness, capacity, memory and lifecycle evidence. The throughput tables here
retain their October 8 source/image identity; speeds were not remeasured for that
update, and acceptance timings are not substituted for matched benchmarks.

## Two distinct methods

**Unchanged upstream kit:** [kit_bench.py](../tools/dsv41/kit_bench.py) uses published set-b prompts. C1 reports `(output tokens - 1) / first-to-last-content time`, allowing EOS with a 384-token maximum. All measured C1 replies reached that maximum. Three repetitions follow per-prompt warm-up, so these are not cold-prefix claims. Cold prefill uses fresh time-seeded word inputs, one output token, and input tokens divided by first-content latency; a wrapper verified zero prefix hits. Model weights and compiled kernels were warm. Burst timing includes complete waves. Sustained timing estimates window tokens from clipped response decode spans, rather than counting each token event at the window boundary.

**Local fixed-input protocol 4:** [benchmark.py](../deployment/scripts/benchmark.py) uses the same prompt corpus where applicable, explicit sampling seeds, and forced output lengths. The suite runs two repetitions with separately retained unscored warm-up, verified zero prefix hits, and exact usage/counter checks. C16/C32 use distinct 1,024-token synthetic prompts and 256 generated tokens per request. Concurrency means observed active decoders, not merely launched HTTP clients. Whole-wave rates include admission, prefill and replies. Sampled steady rates require full requested decode occupancy, no prefill/queued work, adjacent health polls at most three seconds apart, and at least two seconds of eligible observations. Insufficient windows remain null. Engine-only prefill is distinct from input/TTFT.

The local benchmark client differs from its original deployment version only in imports and receipt paths. Its calculation method is retained. The unchanged upstream kit is separately source-pinned. Neither method is an application-quality evaluation, and the prompt named `structured` is a counting task, not grammar-constrained JSON.

## October 8 FP32 correctness update

Source `c068898375337c1f2a7bd222e5d1c342b0a83f9c`, local image ID
`sha256:928fc8e4416e4494de8e600ef81c3ed60393f3871959d77ae20965bc99d2e8ba`,
profile `c32-keys-v051`. The recipe enforces
`TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=0`; the earlier container inherited 1.
The optional reasoning-loop guard is off. Assets, capacity, draft policy and
the 225-line dependency inventory match the prior build.

| Matched method | Previous TF32 build | FP32 update |
|---|---:|---:|
| Kit C1 code / prose / counting, output tok/s | 93.9 / 58.2 / 136.7 | 94.5 / 59.0 / 137.8 |
| Kit cold 32K / 128K, input divided by TTFT | 2,021 / 1,852 | 2,000 / 1,837 |
| Local C1 code / prose / counting, output tok/s | 94.1 / 59.0 / 137.0 | 88.2 / 58.1 / 136.2 |
| Local cold 32K / 128K, input divided by TTFT | 1,936 / 1,767 | 1,904 / 1,762 |
| Local C16 / C32 steady aggregate output tok/s | 214.5 / 266.9 | 209.9 / 272.2 |
| Local C16 / C32 whole-wave aggregate output tok/s | 108.6 / 133.0 | 117.2 / 145.5 |

Both local suites completed 178 scored requests and 46,336 output tokens with
matching prompts and usage budgets. **76/178** token/text hashes agree with the
earlier TF32 build; **89/89** repeated fixed-input pairs agree within this FP32
build. These timings compare complete builds with different reply trajectories.
Output-hash counts are not a quality score.

The local code repetitions were **82.9 and 93.5 tok/s**, producing the same reply
with the same 99 decode rounds. Both are retained in the 88.2 median. The
separate kit code repetitions were **93.4–94.6 tok/s** after their per-prompt
warm-up. These methods have different cache and timing boundaries; the kit's
result does not replace the slower local sample. Steady-window summaries retain
their actual sample counts, including null values for insufficient windows.

[Local ranges and hash comparisons](evidence/upstream-v051-headlines.json) and
[unchanged-kit results](evidence/upstream-v051-kit.json) retain every scored
repetition. All nine scored kit C1 replies reached the 384-token maximum.
The kit wrapper verified exact request/token counters and zero cached input for
all six prefill requests. No allocator or graph counter growth occurred. Kit
C4 burst/sustained was not repeated during this update.

[The integration report](../deployment/UPSTREAM-V051.md) records arithmetic,
guard, C32/million-context, retention and restoration checks separately.

## Portable cutover measurements

This section records the earlier TF32 build; its results remain historical.

Source `2f65892284376d6a59eda1270e3a9ab59f79897b`, local image ID
`sha256:07cd312dca050f9be3c14c5ca9c3ec728c3a28d1b9c2142e45c6a4d1fe54f98b`,
profile `c32-keys-v05`, 109 GiB allocator upper bound. The startup host floor can
lower the effective ceiling. Engine files and dependency inventory match the
previous selected deployment.

| Matched method | Original | Cutover |
|---|---:|---:|
| Kit C1 code / prose / counting, output tok/s | 94.4 / 58.8 / 138.8 | 93.9 / 58.2 / 136.7 |
| Kit cold 32K / 128K, input divided by TTFT | 2,006 / 1,843 | 2,021 / 1,852 |
| Local C1 code / prose / counting, output tok/s | 93.2 / 58.6 / 137.9 | 94.1 / 59.0 / 137.0 |
| Local cold 32K / 128K, input divided by TTFT | 1,959 / 1,756 | 1,936 / 1,767 |
| Local C16 / C32 steady aggregate output tok/s | 209.6 / 267.5 | 214.5 / 266.9 |
| Local C16 / C32 whole-wave aggregate output tok/s | 112.3 / 139.8 | 108.6 / 133.0 |

The local suites used the same prompts and usage budgets: **178/178** token and
text hashes matched, with 46,336 scored output tokens in each suite. The cutover
retains both repetitions and all three unscored warm-up waves. Cold whole-wave
throughput was lower at C16 and C32 even though steady
decode stayed close; the [full local ranges](evidence/cutover-headlines.json)
include those results. Counting's eligible steady window was too short and
remains null; its C1 number uses the response's first-to-last-content span.

The [unchanged-kit receipt](evidence/cutover-upstream-kit.json) includes three
runs per C1 prompt and per prefill length. Every C1 reply reached the 384-token
maximum. The wrapper checked the owned pair, exact request/token counters and
zero prefill prefix hits. Kit C4 burst/sustained was not repeated for the cutover.
No speed claim combines the kit and local timing definitions.

The [cutover report](../deployment/CUTOVER.md) covers acquisition scope, capacity,
memory headroom and lifecycle validation separately from these speed samples.

## Historical headlines

| Method / workload | Result |
|---|---:|
| Kit C1 code / prose / counting, medians of 3 | 94.4 / 58.8 / 138.8 output tok/s |
| Kit cold 32K / 128K input divided by TTFT, medians of 3 | 2,006 / 1,843 input tok/s |
| Kit C4 burst, median of 9 | 120.9 aggregate output tok/s |
| Kit C4 sustained, one 90-second run | 133.0 aggregate output tok/s |
| Local C1 code / prose / counting, medians of 2 | 93.2 / 58.6 / 137.9 output tok/s |
| Local cold 32K / 128K input divided by TTFT | 1,959 / 1,756 input tok/s |
| Local C16 / C32 steady decode | 209.6 / 267.5 aggregate output tok/s |
| Local C16 / C32 complete wave | 112.3 / 139.8 aggregate output tok/s |

Raw summary ranges, sample counts and timing scopes: [kit](evidence/v05-final-upstream-kit.json), [selected engine](evidence/v05-final-headlines.json), [previous-engine control](evidence/v05-final-control.json). The first C4 burst was slower, 78.7 tok/s, and remains in the nine-run distribution. No best-run replacement is used.

The matched local control had 69.6 / 49.3 / 89.9 C1 code/prose/counting output tok/s; C16/C32 steady 114.7 / 130.3; whole-wave 77.7 / 90.0; cold 32K/128K input/TTFT 1,642 / 1,471. Each configuration completed 178 scored requests and 46,336 output tokens. First-content latency did not improve in every batch. Output-hash parity across the final configurations was **174/178**, not perfect. The earlier fixed-512-chunk comparison was 178/178; changing prefill chunking can alter quantized numerical trajectories. A matched long-context C1 evaluation and broader overlay-quality evaluation remain release work before stronger claims.

## Capacity is a separate test

The 8,650,752 logical-token pool stores active and retained KV states. Its tensor allocation was 7.49 GiB per rank; this is not total process memory, original input bytes, or the sum of clients' requested maxima. Thirty-two slots share that pool. Allocation fragmentation and prefix retention can cause waiting before every slot is active.

The large-session qualification used an identical primed document, 261,120 input plus 1,024 output tokens per stream, twice at C32. It is evidence of populated simultaneous session states, not cold ingestion of 32 independent 262K documents. Both the [cutover](../deployment/CUTOVER.md) and [historical qualification](QUALIFICATION.md) record observed occupancy, recovery, memory headroom and observation gaps. NVMe session KV retention is disabled; prepared weight/kernel caches and logs still write to disk.

## Reproduce on an idle qualified installation

Use an otherwise idle pair and record the source, image, asset/profile hashes, dependencies, drivers, power/temperature state, client revision and complete workload. Keep output outside Git. These commands send substantial inference workloads; they are not preparation checks.

```bash
mkdir -p deployment/.local/measurements
python3 tools/dsv41/kit_bench.py \
  --base http://127.0.0.1:8000 --model DeepSeek-V4.1-Flash-Keys \
  decode --set b --tokens 384 --reps 3 \
  --out deployment/.local/measurements/kit-decode.json
python3 deployment/scripts/benchmark.py \
  --suite benchmarks/headline-suite.json --record fresh-headlines --warmup
```

The local script requires the portable launch receipt at `deployment/.local/launch.json`, archives its own code and prompt fixture, and fails on cold-cache reuse, counter contamination or allocator/capture growth. Use a unique record name; preserve failed receipts. For kit prefill comparisons, additionally prove zero prefix hits through health counters and retain that evidence. A kit command alone does not establish a cold-cache claim.

Do not combine kit and local timing definitions into a speed ranking. [Other recipes](../deployment/COMPARISON.md) differ in hardware runs, overlay, KV format, memory budget, chunking and client workloads.
