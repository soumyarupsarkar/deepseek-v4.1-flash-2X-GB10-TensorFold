# Security and deployment boundaries

This candidate is intended for an operator-controlled pair. The API defaults to loopback and has no authentication. A LAN bind requires an explicit configuration flag; restrict access at the network boundary if using it. Do not expose it directly to an untrusted network.

Setup needs noninteractive sudo for Docker and current-boot display/module operations. Docker/GPU access and the worker SSH account are trusted operator capabilities. The recipe uses verified SSH host keys, per-installation ownership, immutable asset revisions, read-only model mounts and a transient paired monitor. It does not provide tenant isolation or a public multi-user security boundary.

HF credentials are used only by asset acquisition. Keep them outside the repository and serving image. Installation journals, configuration, logs, prompts, benchmark responses and memory/host inventories may contain private information; `.gitignore` is only one protection, and publication needs an all-ref scan and human review.

No vulnerability reporting address is configured yet. Set one, or enable private GitHub security reporting, before publication. Do not post credentials, private prompts or an exploitable privileged-controller issue in a public issue. Third-party model and container terms remain applicable separately from source-code licensing.
