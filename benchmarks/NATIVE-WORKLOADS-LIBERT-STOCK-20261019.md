# Native decode by workload and concurrency

Historical LibertAIDAI integration. Use its pinned source/image when reproducing
these results; the current setup uses [Mia EAQ 1017](../deployment/MIA-1017.md).

These measurements use **stock DeepSeek-V4.1-Flash-1017** on two GB10s,
with LibertAIDAI's EXL3 2.9 bpw pack and no Keys replacements loaded.
The same runtime also supports the separately qualified optional Keys variant. C1 is one request; C32 is 32 concurrent requests
of the same task type. Greedy means temperature 0; sampled means temperature 1
with explicit per-request seeds.

Measured on 2026-10-19 (UTC). Each value is the median of all three scored waves.
C32 rates are aggregate output tok/s across all 32 active decoders.

| Decode configuration | Code | Prose | Counting |
| --- | ---: | ---: | ---: |
| C1 greedy | **94.0** | **59.6** | **134.2** |
| C32 greedy | **302.2** | **253.5** | **372.6** |
| C1 sampled | **96.2** | **56.3** | **130.7** |
| C32 sampled | **264.1** | **241.0** | **360.8** |

[Complete evidence: every request, health sample and repetition](evidence/native-workloads-1017-stock-comparison-20261018.json).
The campaign completed 36 scored waves (594 requests) and 12 warm-up
waves (198 requests), for 792 requests total. All 18
scored C32 waves reached 32 active decoders, with 28.3–48.2
seconds of eligible steady observations each. Request and token counters
matched exactly. Both ranks stayed running with zero restarts and the paired
monitor active.

## All measured repetitions

C1 uses first-to-last-content decode timing. C32 uses aggregate steady decode.
The final column includes admission, prefill and completion tails. Prompt and
reply ranges retain early stopping; a 384-token cap does not mean every reply
reaches that length.

| Configuration | Task | Decode repetitions, output tok/s | Prompt tokens | Reply tokens | End-to-end median, output tok/s |
| --- | --- | --- | --- | --- | ---: |
| C1 greedy | Code | 87.54 / 94.00 / 94.63 | 43 | 384 | 90.6 |
| C1 greedy | Prose | 59.21 / 59.90 / 59.56 | 23 | 384 | 58.4 |
| C1 greedy | Counting | 133.67 / 135.54 / 134.22 | 23 | 384 | 129.5 |
| C32 greedy | Code | 304.00 / 301.83 / 302.17 | 48 | 384 | 261.3 |
| C32 greedy | Prose | 251.88 / 253.47 / 254.04 | 28 | 322–384 | 229.1 |
| C32 greedy | Counting | 375.61 / 372.26 / 372.60 | 28 | 384 | 332.7 |
| C1 sampled | Code | 95.89 / 96.19 / 96.23 | 43 | 384 | 92.6 |
| C1 sampled | Prose | 56.30 / 56.75 / 55.83 | 23 | 384 | 55.3 |
| C1 sampled | Counting | 131.89 / 127.63 / 130.70 | 23 | 384 | 125.0 |
| C32 sampled | Code | 264.81 / 263.69 / 264.06 | 48 | 384 | 233.9 |
| C32 sampled | Prose | 238.74 / 240.98 / 241.38 | 28 | 383–384 | 220.6 |
| C32 sampled | Counting | 360.83 / 358.11 / 361.87 | 28 | 384 | 321.6 |

Returned-text hashes matched at every request index across all three scored
repetitions in 12 of the 12 configurations. Repetitions reuse fixed
prompt/seed fixtures. All repetitions remain in the report.

## Workloads and timing

The inputs come from [Bertholomus's benchmark kit, set b](../tools/dsv41/kit_bench.py):

- Code: implement a Python LRU cache with O(1) operations and unit tests.
- Prose: write a 400-word essay about the printing press and its effect on Europe.
- Counting: count from 1 to 200, one number per line. The kit calls this task
  `structured`; it uses text output without a JSON grammar.

C1 uses the original prompt. C32 uses the same task with the kit's
` (variant N)` suffix for request indices 0 through 31. There is no random-word
padding. All requests use the chat endpoint with thinking off, the default
drafting policy, a 384-token output cap and normal stopping enabled. Actual
reply lengths are retained, including replies that finish before the cap.
These are public benchmark prompts; no inference-user prompts were used or
adapted.

Each concurrency/task/temperature combination has one unscored warm-up wave,
with a 32-token cap at C1 or 64 at C32, followed by three scored waves. Request
seeds are `42000 + index` and repeat across the three repetitions. The order is
temperature, task, then concurrency. Repetitions reuse the same prompt/seed
fixtures. This is a warm throughput measurement with no cold-prefix claim.
Lazy graph captures during scored waves remain in the timings, and their
counts are retained per wave. No repetition is discarded or replaced.

**C1 decode** uses the kit's `(output tokens - 1) / first-to-last-content time`
calculation, excluding time to first content. **C32 aggregate decode** counts
generated tokens through adjacent health samples while all 32 decoders are
active, with no prefill or queued work. Samples are taken every 0.25 seconds;
eligible observations must span at least two seconds, and gaps over three
seconds are excluded. Request arrival and completion tails are excluded from
that steady rate. Summing individual request rates is not used.

End-to-end aggregate throughput divides all returned output tokens by the time
from the earliest request start to the latest response end. It includes
admission, prefill and completion tails. The complete receipt keeps both timing
methods, individual request timings and lengths, and all health samples.



## Runtime and verification

Runtime source `9f8d14e349be3811147b1fd5b35bcbdac6f824fd`, image
`sha256:eedc8c3acc3109262c92ccb4fcd8221b115f992cc34f644acd1bc40034c1a84a`. The profile has 32 slots, an
8,650,752-token shared KV pool and a 1,048,576-token request limit. This
benchmark uses short text requests; it does not independently qualify full
context capacity, vision, structured outputs or long-run stability.

The [runner](native_workloads.py) checks the owned rank/image identities,
readiness, graph budget, paired monitor and exact completed-request and
input/output-token counters. Every scored C32 wave must show all 32 active
decoders and sufficient eligible steady time. No host or server configuration
is changed.

## Reproduction

Use an otherwise idle deployment and a new receipt filename. Run the helper
from this checkout, pointing `--source` at the clean, pinned checkout that owns
the running deployment; use `.` if it is the same checkout.

```bash
mkdir -p deployment/.local/measurements
python3 -B benchmarks/native_workloads.py --source . \
  --out deployment/.local/measurements/native-workloads-new.json
```

The complete campaign consists of 48 waves: 12 unscored warm-ups and 36 scored
waves, covering both concurrency levels, all three task types and both
temperatures. The runner refuses existing receipt paths, preserves failed or
interrupted attempts, and rejects counter contamination. It leaves the ranks
running.



## Earlier measurements

The [stock 1017 workload report](NATIVE-WORKLOADS-STOCK-1017-20261018.md)
preserves the original stock migration results. A new matched stock/Keys
comparison is recorded in [Keys qualification](KEYS-LIBERT-1017-COMPARISON.md).

The [previous Keys workload report](NATIVE-WORKLOADS-KEYS-20261011.md) preserves
its original measurements and evidence. Those results use a different
checkpoint. The [earlier unchanged-kit C1 run](NATIVE-DECODE.md) and
[mixed C32 drafting investigation](NATIVE-DRAFTING.md) retain their original
protocols and runtime identities as well.
