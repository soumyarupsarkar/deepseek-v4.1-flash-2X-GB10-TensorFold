# Initial native C1 measurements

The current hero uses the expanded [C1/C32 workload measurements](NATIVE-WORKLOADS.md).
This report preserves the earlier unchanged-kit C1 run and mixed C32 diagnostic.

The C1 code/prose/counting results were measured on 2026-10-11 against the
running native deployment, using the original unpadded set-b prompts and the
unchanged [Bertholomus benchmark kit](../tools/dsv41/kit_bench.py).

| C1 task | Median output tok/s | All three repetitions, tok/s | Input tokens | Output tokens per repetition |
| --- | ---: | --- | ---: | --- |
| Code | **99.9** | 99.271 / 99.888 / 100.141 | 43 | 384 / 384 / 384 |
| Prose | **59.5** | 59.433 / 59.499 / 59.547 | 23 | 299 / 299 / 299 |
| Counting | **142.4** | 143.002 / 142.391 / 142.383 | 23 | 384 / 384 / 384 |

The tasks are a Python LRU cache with unit tests, a 400-word essay about the
printing press, and counting from 1 to 200 with one number per line. The kit
names the last task `structured`; it uses ordinary text output without a JSON
grammar. These are public benchmark prompts. No inference-user prompts were
used or adapted.

Each prompt has one unscored 32-token warm-up followed by three measured replies
at temperature 0, thinking off, with a 384-token maximum and normal stopping
enabled. Prose finished at 299 tokens in all three repetitions; its actual
length remains in the results. Within each task, all three returned texts had
the same SHA256 digest. Every measured repetition is included.

C1 decode throughput is `(output tokens - 1) / (last-content time - first-content
time)`. It excludes time to first content. Median first-content latencies were
157.5 ms for code, 112.8 ms for prose and 108.3 ms for counting. This is a warm
decode measurement with a per-prompt warm-up; it makes no cold-prefix claim.

[Complete timing and counter receipt](evidence/native-kit-decode-20261011.json).
The receipt retains all 12 requests, including warm-ups, full-precision timings,
actual token counts, output-text hashes and the identities of the kit, runner,
profile, source and image. Request and token counters matched exactly. Both
ranks kept their identities with zero restarts, and the paired monitor remained
active. The benchmark changed no host or server configuration.

## Earlier mixed C32 aggregate throughput

The earlier mixed C32 diagnostic completed three repetitions on the same
native source and image:

| Temperature | Steady aggregate output tok/s | End-to-end aggregate output tok/s |
| --- | ---: | ---: |
| 0 (greedy) | **290.1** | **149.6** |
| 1 (sampled, explicit seeds) | **261.3** | **140.5** |

Each wave contains 11 code, 11 prose and 10 counting requests. Each input is
padded with seeded random common words to exactly 1,024 tokens, and each reply
is forced to 256 tokens with `ignore_eos=true`. Actual cached input was zero.
The three repetitions per temperature use fixed seeds and the same fixtures.

Steady decode counts generated tokens during health-counter intervals with all
32 decoders active and no prefill or queued work. End-to-end throughput divides
all output tokens by the complete wave time, including admission, prefill and
replies. These two timing boundaries stay separate. The C1 row above uses the
original short prompts and its own first-to-last-content timing method.

[C32 methods, controls and later confirmation](NATIVE-DRAFTING.md#completed-short-c32-measurements)
and [complete evidence](../release/native-throughput-policy-20261010.json) retain
all repetitions. The earlier padded C1 drafting diagnostic also remains there;
the hero now uses the original per-task C1 benchmark.

## Runtime identity

Both measurement sets belong to native source
`6aaec5b3616f4547fabbe2fcc3fb1e779bb75f82`, image
`sha256:baa3fc8d748766476d694da36f3e79ac501f18bed6b9572e36c1c80c4baa7bc7`.
The deployment has Keys, vision and structured-output support enabled, 32 active
slots and an 8,650,752-token shared KV pool. These measurements use text prompts.

The unchanged kit's SHA256 is
`83a4fbeb987032f906cf00d3f6c9dd2fad47dd675e75dd498c4c4188d63a6c0d`.
The [checked runner](native_decode.py) calls the kit's original `cmd_decode`
without changing its prompts, requests, ordering or timing calculations. Its
additional checks surround the timed requests and detect other traffic through
the completed-request and input/output-token counters.

## Reproduce C1 on an idle deployment

Use the clean, pinned checkout that owns the running deployment as `--source`.
From that checkout, the command is:

```bash
mkdir -p deployment/.local/measurements
python3 -B benchmarks/native_decode.py --source . \
  --out deployment/.local/measurements/native-c1-new.json
```

When running the benchmark helper from a separate development checkout, pass
the serving checkout's absolute path to `--source`. The runner checks the build,
launch, image and rank identities and refuses an existing receipt path. Use a
new filename for each attempt. An active request or counter mismatch fails the
run instead of publishing a contaminated speed result.

The equivalent unwrapped kit command is:

```bash
python3 tools/dsv41/kit_bench.py \
  --base http://127.0.0.1:8000 --model DeepSeek-V4.1-Flash-Keys \
  decode --set b --tokens 384 --reps 3 \
  --out deployment/.local/measurements/kit-c1-new.json
```

Use the configured API port. The unwrapped command uses the same workload and
timing method; the checked runner additionally verifies ownership and counters.
