# Recipe comparison and attribution

The table records source snapshots reviewed for the 2026-10-07 qualification. It is not a claim about the latest versions or a matched speed ranking. The local results are historical. The later [portable cutover](CUTOVER.md) qualified verified asset reuse and lifecycle recovery; [the v0.5.1 integration](UPSTREAM-V051.md) records the 2026-10-08 Bertholomus review separately.

| Recipe at cited revision | Runtime | Reported performance | Capacity evidence |
|---|---|---|---|
| This fork + Keys | TensorFold TP2 | Kit C1 code/prose/counting 94.4/58.8/138.8 output tok/s; cold 32K input/TTFT 2,006; kit C4 burst/sustained 120.9/133.0 | 8,650,752 pooled logical tokens, 32 slots, 1M per request; C32 large-session conditions in the qualification document |
| [Bertholomus v0.5](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/blob/753dffaac61893c9b20fdd5c9450f45cbc3ce037/README.md) | TensorFold TP2 | Author C1 code/prose/counting 100.5/62.5/140.0; cold 32K/128K prefill 2,189/2,004; C4 burst/sustained 112.4/125.1 | Four slots sharing approximately 1M pooled tokens; 1M request ceiling; 4 × 160K qualified; Mia weights without our Keys overlay |
| [Urtho](https://github.com/urtho/TensorFold/blob/8b05ee70ef2891c579ce7f3292a65dfd39fe600c/deploy/dsv41-tp2/README.md) | TensorFold TP2 | Dated October 2 result: C8 aggregate 85 output tok/s; matching C1 and 32K figures not reported there | [Example config](https://github.com/urtho/TensorFold/blob/8b05ee70ef2891c579ce7f3292a65dfd39fe600c/deploy/dsv41-tp2/.env.example): approximately 5.9M pooled FP4 tokens, 16 slots with 614,400 ceilings; optional NVMe prefix retention |
| [coolbho3k / Emi Huang](https://github.com/coolbho3k/DeepSeek-v4.1-Flash-2x-DGX-Spark/blob/1d8ac64af01c6fec87f39eb1dd526ff183615c73/README.md) | Specialized vLLM TP2/DCP2 | Latest cited Engram trial: 30.78 pooled serial output tok/s, approximately 1,078 cold 32K input tok/s; earlier fixed-K3 C6 control: 62.05/54.10 at T=0/1 | 3,313,955 allocated KV tokens, six slots, 1M ceiling; earlier run filled 3,146,968 independent input tokens |

Rates are tokens per second. Different dated experiments in one source are labeled separately. Urtho's example is an illustrative budget, not 16 simultaneously full independent 614K histories or a maximum capacity claim. The same caution applies to four million-token ceilings sharing a roughly 1M pool. The local C16/C32 steady rates use a different client protocol from the kit C4 results and belong in [the method table](../benchmarks/README.md), not an unlabeled cross-recipe leaderboard.

The unchanged kit reduces one methodological difference with Bertholomus, but physical machines, Keys, pool/slot budget and 1K versus 2K prefill still differ. Our 2K candidate exceeded the unchanged memory ceiling and was rejected. No pool or memory-floor reduction was used to obtain the selected gains.

The v0.5.1 review also identified a precision difference: the earlier local
container inherited `TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1`. The updated profile
explicitly selects 0 and checks FP32 arithmetic at startup. Earlier output hashes
and performance remain scoped to their original builds; they are not evidence of
bitwise agreement with the corrected engine or another recipe.

## Attribution

- [ashhart/TensorFold](https://github.com/ashhart/TensorFold) and its contributors provide the framework, EXL3 foundation and inherited kernels.
- [Bertholomus / Albert Lee](https://github.com/bertholomus/TensorFold/tree/deepseek-v41-tp2) provides the DeepSeek TP2 engine, vision/RDMA integration, benchmark kit, selective v0.5 kernel/memory improvements and v0.5.1 FP32/loop-guard fixes. [Detailed family provenance](../tools/dsv41/ATTRIBUTION.md).
- [Capicua25x](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/pull/9) provided the novelty signal that Bertholomus reimplemented for the optional reasoning-loop guard.
- [Mia-AiLab](https://huggingface.co/Mia-AiLab/DeepSeek-V4.1-Flash-EXL3-2.9bpw) provides the EXL3 checkpoint; [drowzeys / Keys](https://huggingface.co/drowzeys/DeepSeek-V4.1-Flash-Abliterated-Cybersecurity-Unleashed) provides the matching attention overlay. They are downloaded separately at [pinned revisions](config/assets.json).
- [DeepSeek](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) provides the original model/assets and model research; the original family provenance identifies its math references.
- [Urtho](https://github.com/urtho/TensorFold) supplies adapted structured-output/DRM work and the memory/graph-budget approaches described in [third-party notices](../THIRD_PARTY_NOTICES.md). Relevant code pins include `27404275d0f14bba8e97e7ca801de4c956d369be` and `8b05ee70ef2891c579ce7f3292a65dfd39fe600c`.
- [Jay Leaton](https://github.com/jayleaton/deepseek-v41-tensorfold-spark) is credited for MIT-licensed parsing/grammar work adapted through Urtho; [the MIT notice](../LICENSES/JayLeaton-MIT.txt) is preserved.
- [coolbho3k / Emi Huang](https://github.com/coolbho3k/DeepSeek-v4.1-Flash-2x-DGX-Spark) provides the vLLM recipe reference and the display-memory idea credited by Urtho's independent DRM implementation. No AGPL `display_kv.c` source is included by this adaptation.
- Soumyarup Sarkar's local work combines the recipe, configurable sampling, strict output, bounded capacity/graphs/checkpoints, occupancy diagnostics and measured draft policy; it adds portable installation ownership, restoration and publication evidence. Kernel performance credit remains with the originating authors as documented.

The inherited original-family account is scoped to that original implementation; later local adaptations and their licenses are explicitly separate. This checkout preserves upstream notices and ancestry but omits private installation history. [Release status](../release/STATUS.md) records the remaining code/model/container license review before a release tag or stronger distribution claims.
