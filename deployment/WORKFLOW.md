# Development, deployment and cutover

Use this repository as the source for future changes. Keep a separate, clean
checkout at the selected commit for the running installation. Its directory
must stay at the same path while active: the paired monitor records that path.
Develop, review and publish changes from the development checkout; production
should not follow an automatic `git pull` or build uncommitted files.

The deployment checkout owns its Git-ignored `deployment/local.json` and
`deployment/.local/` state. Preserve the whole state directory, including the
installation UUID, original configuration, host baselines, display journals,
asset receipts and image/precompile records. Git history does not back it up.

## Qualify a cutover

1. Save the currently selected source commit, image ID, configuration, journals
   and asset roots in a private backup. Record any existing fault separately.
2. Stop the existing pair with its own controller and check its host restoration.
   Only one installation may occupy the GPUs and API port at a time.
3. Prepare a clean deployment checkout of the reviewed candidate. Initialize
   new, empty data roots with its own configuration and ownership records.
4. Fetch pinned assets, or use the [verified reuse workflow](README.md#reuse-an-existing-pinned-installation).
   Reuse shares immutable bytes; it does not copy ownership records or mutable
   kernel caches. Refresh the previous controller's hash receipts if new
   hardlinks change the fingerprints it guards.
5. Build and transfer the exact same image, compare dependency inventories,
   precompile with weights unloaded, and exercise interrupted-setup recovery.
6. Start the candidate and run the [paired acceptance workloads](../tools/qualification/README.md),
   retention checks and [benchmarks](../benchmarks/README.md). Keep failed and
   slow runs. Inspect host headroom as well as API/GPU health.
7. Exercise idle worker-loss cleanup and verify both hosts return to their own
   baselines. If an old-server fallback is part of the plan, test it separately
   before the final candidate restart.
8. Leave the selected source/image pair pinned, confirm LAN access and the
   paired monitor, and publish reviewed summaries with exact scope and limits.
   Keep raw host inventories, journals, credentials and ordinary traffic out
   of Git.

An allocator upper bound supplements the host floor; it does not reserve RAM
against unrelated processes or prove indefinite uptime. Preserve the monitor's
memory checks and qualify large-context/concurrent workloads after changing
memory policy. A short smoke test does not establish C32 or million-token fit.

## Restore normal host operation

Use the active installation's saved configuration:

```bash
python3 -B cluster --config deployment/.local/installed.json stop
python3 -B cluster --config deployment/.local/installed.json check-host
```

This restores the recipe-managed host state while retaining source, weights,
images and caches. Returning to a previous server is an optional separate step,
after restoration, using that server's own intact controller and journals.
See [rollback](ROLLBACK.md) before removing retained assets or image tags.

After a successful cutover, continue development in the canonical repository.
The previous operational repository remains a rollback reference, rather than
a second source of ongoing changes. Stop and verify restoration before changing
the production checkout or its selected image. Re-run the relevant acceptance
checks for each future deployment.

If an update changes asset revisions or prepared-weight compatibility, create
new owned data roots and qualify a separate installation. Preserve the original
shared files and import receipts. A loader-hash or asset-fingerprint refusal is
a compatibility check to resolve, not a reason to remove a receipt or overwrite
shared bytes. Reuse prepared caches only when their producer and compatibility
are established; otherwise prepare fresh caches from the verified model assets.
