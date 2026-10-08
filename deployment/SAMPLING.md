# Sampling and replay

The engine supports both `TENSORFOLD_SEED_MODE=prompt` and `random`. Its code default remains prompt-derived; this recipe explicitly selects **random**. An explicit integer request seed, including zero, overrides either mode. Greedy decoding can return identical output regardless of seed mode.

The normal API defaults are temperature 1, top-p 0.95 and top-k 20. Benchmarks explicitly override sampling, commonly using temperature zero. Returned TensorFold metadata exposes the effective seed where applicable. With random mode, repeated unseeded requests can differ; repeatability is still available through an explicit seed. Prompt mode derives a keyed seed from the prompt and can produce identical repeated answers.

This resembles the usual vLLM client expectation of varying unseeded sampling, but is not a promise of bitwise parity with vLLM. Different engines, batch shapes, precision, prefill chunking or model revisions can change results even with the same seed. Reproduction claims must pin those settings too.

Strict JSON/schema and tool-constrained requests use ordinary constrained decoding. The short counting prompt used in headline benchmarks does not exercise that path. Changing the seed mode in the profile requires a rebuilt/requalified configuration; do not edit an initialized installation's private ownership records to bypass configuration checks.
