# Selective Bertholomus v0.5 integration

The public base is `d5d7bb389ddf4325c1edf4a15dd1c23727040ea1` in [Bertholomus/TensorFold](https://github.com/bertholomus/TensorFold). The selective port was reviewed at `808eb4a1090ca7b79173cc2c799de16da5f923e3`, following release `508bfb34743f88d35abcb514f7013ef531ce34a5`.

Imported changes include compact host histories, cosine/sine-only positional tables, exact pruned top-k selection, candidate-only scoring, invisible attention-tile skipping, grouped-expert work lists and smaller prompt scratch. Associated correctness probes remain in `tools/dsv41/`. Credits and license notices are retained in [family attribution](../tools/dsv41/ATTRIBUTION.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).

Local adaptations retain the request-bounded positional tables, explicit decode workspace, 8,650,752-token logical pool, 32 slots, bounded prefix checkpoints and shared round outputs. The selected profile uses 1,024-token prefill, three graph widths and the October 6 draft-cost table. Repeated policy comparisons gave mixed results from a new fit, so the established table stayed selected. The profile uses ordinary decoding at C17–32 within its 32-row target budget. Larger experimental target-row profiles are outside this portable candidate.

A 2,048-token prefill candidate exceeded the unchanged allocator ceiling and was rejected. The selected profile does not enable upstream experimental MMA/mHC paths or merge the entire TensorFold 0.6.6 framework. Tests with identical 512-token chunking had 178/178 output-hash parity; the final change to 1K chunks had 174/178 parity, with the four differing numerical trajectories preserved as a limitation.

[engine-source.json](../release/engine-source.json) fingerprints every engine file and the unchanged upstream benchmark client from the measured source. Private development commits are not imported into this public history. New orchestration is independently testable and awaiting fresh hardware acceptance; unchanged engine bytes do not qualify new asset extraction or lifecycle code.

[Benchmarks](../benchmarks/README.md), [historical qualification](../benchmarks/QUALIFICATION.md), [portable installation](README.md) and [rollback](ROLLBACK.md) define the public candidate's scope. Each new installation must preserve its own source, images and journals rather than relying on the original deployment's private records.
