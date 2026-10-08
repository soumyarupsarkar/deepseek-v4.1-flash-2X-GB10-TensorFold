# Publication preparation status

This is a publication candidate, not a released installer. The publication destination is [soumyarupsarkar/deepseek-v4.1-flash-2X-GB10-TensorFold](https://github.com/soumyarupsarkar/deepseek-v4.1-flash-2X-GB10-TensorFold). Preparing and publishing this source does not change the existing deployment or its rollback repository. Hardware qualification and release gates below remain pending.

## Prepared

- Public upstream ancestry retained; private deployment commits, host journals and raw operational logs omitted.
- Qualified engine snapshot identified by per-file hashes in [engine-source.json](engine-source.json). The private revision and image identifiers are provenance, not publicly fetchable artifacts.
- Portable configuration, pinned asset acquisition, paired lifecycle and restoration tools, with offline contract tests.
- Historical benchmark summaries, reproducible clients, methodology, attribution and release boundaries.
- Local Git author settings; no global Git configuration changes.

Completed preparation checks are recorded in [preparation-checks.json](preparation-checks.json). That receipt distinguishes offline checks from pending hardware acceptance.

## Required before a release tag

1. Use a fresh checkout on an idle two-GB10 pair. Exercise asset fetch/extraction, hash verification, image build/transfer, kernel precompile, start, stop and host restoration. Record dependency inventory and compare with the historical image; the Dockerfile's inventory is not a hermetic package lock.
2. Re-run text, vision, strict JSON/schema/tools, sampling, ordinary/drafted parity, C32 capacity, native-million, queue/cancel, retention and soak tests on the portable build. Exercise an idle worker failure, an interrupted start and reboot-aware cleanup. Prove both hosts return to their own captured baseline.
3. Repeat headline benchmarks on that build with the documented workload and timing boundaries. Keep slow runs and failures. Add matched long-context C1 and quality evaluations before making stronger performance or overlay-quality claims.
4. Finish the code/model/container license and modified-file notice review. Preserve Apache and MIT notices and verify the exact pinned asset terms. Confirm that inherited upstream history is suitable for the intended public fork.
5. Re-run secret and private-identifier scans on every ref being published and inspect the final diff. The GitHub destination and initial source publication have been authorized. Configure a reporting contact and confirm the hosted CI result before a release tag.

No live server restart, model download, image build or privileged host operation is part of these preparation checks. Unit tests and source identity do not substitute for paired hardware qualification.
