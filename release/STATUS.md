# Native release status

This branch is a migration candidate, not a qualified production release.

The image build, native CPU/server tests, C++ grammar bridge, GPU primitives,
router widths 1–48, and fresh rank-cache preparation/readback have independent
checks. Live feature, full capacity, replay/compaction, matched performance,
new 24-hour endurance and recovery gates must all pass before cutover.

The Python reference remains the fallback. Its benchmark and qualification
records are historical; they do not establish native performance or stability.
See [MIGRATION.md](../MIGRATION.md), [native setup](../deployment/README.md)
and [migration rollback](../deployment/MIGRATION-ROLLBACK.md).

The source inventory detects changes to build/engine/controller inputs. It is
not proof of hardware qualification. CI exercises portable and native CPU
contracts, without GPUs or downloaded model weights. No model or proprietary
container layers are included in the repository.
