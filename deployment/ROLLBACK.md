# Restore the pre-installation host state

The portable lifecycle is awaiting hardware qualification. These are the intended recovery operations; perform and record them during the fresh-pair release gate.

## Normal stop

```bash
python3 cluster stop
python3 cluster check-host
```

Keep the checkout and **all of `deployment/.local/`** until restoration passes. The state contains the installation UUID, pinned configuration, baseline, current-boot display journals, image IDs and stop receipts. Each installation must have its own data roots and state; never copy an ownership marker to adopt another deployment's files.

Stop checks exact ownership, attempts both rank cleanups even if one operation fails, saves logs, removes those containers, and attempts display restoration on both hosts. It retains models, prepared/kernel caches and image layers. No global Docker prune, recursive model deletion, host package uninstall or network rollback is performed.

## Interrupted start or changed local configuration

Re-run stop using the original saved configuration:

```bash
python3 cluster --config deployment/.local/installed.json stop
python3 cluster --config deployment/.local/installed.json check-host
```

A display journal is saved before the first display/module change. An unresolved restoration keeps that journal active and the command fails. If the worker is unreachable, bring it back and retry with the same state; do not erase the journal to make an error disappear. Unexpected container ownership or a conflicting transient service is refused.

Across a reboot, the tool compares the new boot with the saved state but does not impose stale current-boot module settings. A difference remains available for review. A failed `check-host` is evidence to inspect, not authorization to force the host back to an old driver/kernel or network configuration.

## Preserve an installation before updating source

1. Stop and verify restoration with the current checkout and its journals.
2. Save the source commit, private configuration/state, selected image ID, precompile receipt, asset manifest and owned data roots. Git alone does not back up ignored state or downloaded assets.
3. Keep the previous local image and source available while qualifying the update. Do not run two controllers against the same ownership state.
4. If the update fails, use the update's own intact journals to stop/restore first. Only then restore the previous checkout/configuration and select its preserved image/precompile records.

The engine provenance image in this repository is not a downloadable rollback image. A new user must retain images built by their own installation.

## Optional final removal

After both hosts match their baselines, the owner can separately remove the installation's data roots, image tags and source checkout. Check the UUID in each root's `.spark-owned.json` against the saved ownership record and confirm no other installation references those assets or images. Automatic deletion is intentionally not provided. Retaining downloads and build artifacts after `stop` is different from leaving active host configuration changes behind.
