# Native release status

This branch is a migration candidate, not a qualified production release.

The current image passed 291 CPU/server tests, the C++ grammar bridge, GPU
primitives, router widths 1–48, and full native rank-cache comparison on both
hosts. Twenty live synthetic client runs completed, including serving features,
strict outputs at C32, two full-window C32 replay waves, and cold million-token
retrieval with small requests completing during prefill.

The [functional evidence snapshot](native-functional-20261010.json) binds those
results to runtime source `80b399cd023d3a88ad69501c8261143ea622328b` and its exact
image. Partial-prefill compaction still needs an independent cold reference.
Matched performance and memory acceptance, selected-image recovery (including
a controlled reboot), and a new bounded 24-hour endurance run remain pending.
The six-minute mixed soak is not endurance qualification. No native throughput
advantage or production qualification is claimed.

The Python reference remains the qualified fallback and is stopped during the
loopback candidate's hardware qualification. Its benchmark and qualification
records are historical; they do not establish native performance or stability.
See [MIGRATION.md](../MIGRATION.md), [native setup](../deployment/README.md)
and [migration rollback](../deployment/MIGRATION-ROLLBACK.md).

The source inventory detects changes to build/engine/controller inputs. It is
not proof of hardware qualification. CI exercises portable and native CPU
contracts, without GPUs or downloaded model weights. No model or proprietary
container layers are included in the repository.
