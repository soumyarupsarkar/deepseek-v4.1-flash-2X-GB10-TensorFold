# DeepSeek-V4.1 Flash + Keys on two GB10s

A TensorFold TP2 fork combining Bertholomus's engine, Mia's EXL3 weights and drowzeys' Keys abliteration overlay, with vision, constrained JSON/schema and tool output, and a large shared KV pool. [Credits and source pins](deployment/COMPARISON.md#attribution).

**Publication candidate:** the engine below was qualified on an existing two-GB10 deployment. This checkout preserves its engine files exactly, but the new portable installer has only offline tests so far. A fresh two-node installation and rollback qualification is required before release. [Release status](release/STATUS.md).

## What this fork adds

- **8,650,752 logical KV tokens shared across 32 slots**, with a **1,048,576-token prompt-plus-reply ceiling per request**. Pool tensors consume 7.49 GiB per rank in the measured configuration.
- Temporary DRM allocation, bounded graph/scratch memory, admission diagnostics and up to 32 retained prefixes with two recent checkpoints each. Session KV writes to NVMe are off.
- The Keys overlay, image input, strict structured output, and configurable random or prompt-derived request seeds. The recipe selects random seeds; explicit request seeds still work.
- Selective Bertholomus v0.5 improvements: compact prompt histories and RoPE tables, reduced indexer/attention work, and grouped-expert prefill. The framework remains based on TensorFold 0.6.3; this is not a full 0.6.6 merge.
- A measured draft-cost policy, shared round outputs and bounded 8K/262K/1M graph widths. The selected 32-row target budget uses ordinary decoding at C17–32 and resumes drafting as concurrency falls. The experimental 64-row configurations are not included as qualified portable profiles.
- New installation ownership, pinned asset acquisition, paired failure handling and journaled host restoration. These tools are **awaiting hardware qualification**.

## Measured performance and capacity

Historical measurements from 2026-10-07; **not measurements of a fresh install from this repository**. Two GB10s, Mia 2.9-bpw + Keys, 1K prefill chunks, 32 slots and the pool above.

| Workload | Result | Measurement |
|---|---:|---|
| C1 code / prose / counting decode | **94.4 / 58.8 / 138.8 output tok/s** | Unchanged upstream client, set-b, T=0, 384-token maximum, medians of 3 |
| Cold 32K / 128K input throughput | **2,006 / 1,843 input tok/s** | Input divided by first-content latency, upstream client, medians of 3 |
| C4 burst / sustained | **120.9 / 133.0 aggregate output tok/s** | Upstream client; median of 9 bursts / one 90-second window |
| C16 / C32 steady decode | **209.6 / 267.5 aggregate output tok/s** | Local suite; distinct 1K prompts, 256 forced outputs, medians of 2 |
| C16 / C32 whole cold wave | **112.3 / 139.8 aggregate output tok/s** | Same suite, including admission and prefill |
| Large-session capacity | **32 × 262,144 total tokens**, twice | Identical primed document, independent active session states; not 32 cold independent document prefills |
| Native-million retrieval | **1,048,576 total tokens** | Cold input, all three embedded passphrases recovered |
| Vision / Keys / strict output | Enabled and tested together | Constrained requests use ordinary decoding |

The pool budget is not populated history or a guarantee of 32 million-token sessions. The large-session test sampled 8,388,416 populated logical tokens; retained prefixes share the pool, and contiguous-allocation requirements can queue requests before every slot fills. The counting benchmark is not a strict-JSON benchmark. Feature qualification does not establish the overlay's quality across all tasks.

[Methods, ranges and reproduction](benchmarks/README.md) · [Historical qualification](benchmarks/QUALIFICATION.md) · [Comparison with Bertholomus, Urtho and coolbho3k](deployment/COMPARISON.md).

![Historical throughput and first-content latency by concurrency](benchmarks/throughput.svg)

## Getting started

Review [installation](deployment/README.md) and [rollback](deployment/ROLLBACK.md). The following command renders an example plan with no SSH, Docker, credentials or host changes:

```bash
python3 cluster --config deployment/config/cluster.example.json plan
```

[Sampling](deployment/SAMPLING.md) · [Integration decisions](deployment/UPSTREAM-V05.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md).

The inherited TensorFold families and backends remain in the source tree. This recipe qualifies only the DeepSeek-V4.1 CUDA TP2 configuration described above. Consult [upstream TensorFold](https://github.com/ashhart/TensorFold) for its other supported configurations.

Code licensing and attribution are preserved in [LICENSE](LICENSE), [NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [family attribution](tools/dsv41/ATTRIBUTION.md). Model weights, overlays and the NVIDIA container base have their own terms; no weights or container images are redistributed here.
