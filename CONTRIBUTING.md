# Contributing

This checkout prepares a focused DeepSeek-V4.1 TP2 fork for publication. It preserves upstream TensorFold history and notices; it is not the upstream project's support or release policy.

Keep engine changes separate from orchestration and documentation. Explain the concrete failure or behavior change, credit adapted code at an immutable source revision, retain applicable notices, and include relevant correctness evidence. Kernel changes need ordinary/drafted and numerical controls in addition to speed measurements. Performance claims must name their input/output sizes, concurrency, cache and sampling state, memory budget, timing boundaries and repetitions.

Run the offline checks from a clean checkout:

```bash
python3 -B -m unittest discover -s tests/publication -v
python3 -B scripts/check_release.py
python3 -B cluster --config deployment/config/cluster.example.json plan
```

These checks require only Python's standard library. The broader inherited test suite needs the engine dependencies and GPU tests require supported hardware; neither is replaced by publication checks. Engine source hashes deliberately fail after an unqualified engine edit. Update the manifest only alongside reviewed hardware qualification evidence.

Never commit `deployment/local.json`, `.local/` journals, credentials, weight files, raw service logs or private prompts. Use examples with documentation hostnames. Scan all proposed public history, not only the working tree. Do not submit model files or proprietary container layers.

Installation experiments need an idle dedicated pair and a captured baseline. Keep data and images until stop/restoration passes. Do not run privileged hardware CI on untrusted pull requests. See [release status](release/STATUS.md) for remaining acceptance work.
