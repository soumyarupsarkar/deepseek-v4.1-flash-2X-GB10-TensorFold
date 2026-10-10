# Roll back the native candidate

Preserve the qualified Python checkout and image on both hosts, its immutable
assets, private configuration, ownership state and current host journals. An
asset link and a backup of ignored state are not a replacement for the current
recovery journals.

1. Stop the candidate with its own `cluster stop` and run `cluster check-host`.
   If a host is unreachable, recover that host and finish the same restoration.
2. Keep the candidate source, image, manifests and successful or failed receipts
   for diagnosis. Stop does not delete weights or images.
3. In the retained reference checkout, reverify assets if hardlink creation
   changed their metadata. For imported prepared caches, compare their content
   hashes to the preserved hashes before refreshing fingerprints. Do not weaken
   the previous controller's checks or restore stale journals.
4. Start the reference with its matching source/image/precompile records and its
   own unchanged private configuration. Confirm its health, capacity, paired
   monitor and a small synthetic request before reporting restoration complete.

The reference remains the production fallback until the native candidate passes
feature, capacity, performance, stability and recovery gates. A passing native
build or GPU primitive test alone does not authorize a cutover claim. Never
restart a previously user-stopped endurance unit as part of rollback.
