# Native structured-output bridge

This C ABI connects the Zig HTTP/lane engine to xgrammar's C++ compiler and
matcher. It does not load Python or PyTorch. The ordinary decode path masks
the first token and every subsequent token; speculative decoding is disabled
for these requests. Compilation and validation happen before queue submission.
Each request owns its matcher until completion or acknowledged cancellation.

Build with xgrammar **v0.2.8**, commit
`97787376faee5ed8466cfad57c99855e4ce2f6aa`, including its pinned submodules:

```sh
cmake -S zig/native_xgrammar -B /path/to/build/grammar \
  -DXGRAMMAR_SOURCE_DIR=/path/to/verified/xgrammar -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/build/grammar --parallel 2
ctest --test-dir /path/to/build/grammar --output-on-failure
```

Set `TENSORFOLD_XGRAMMAR_LIBRARY` to the resulting `libtf_xgrammar.so`. A configured
library that cannot load makes startup fail; constraints are never silently
dropped. `TF_DSV41_TOOL_GRAMMAR=all` constrains every offered function to its
schema. `required` constrains required/named/strict tools; `off` disables tool
constraints and refuses required calls. JSON/schema/regex/choice/EBNF remain
independent of this tool setting. `TENSORFOLD_GRAMMAR_CACHE_MIB` bounds each
compiled-grammar LRU (plain and DSML vocabularies independently), with four
compiler threads. The runtime default is 256 MiB per vocabulary; this recipe
sets 64 MiB per vocabulary to leave more host memory for request processing.
Accepted values are 1–1024 MiB; invalid values fail startup. Active matchers
retain their grammar while using it, so this cache limit is not a bound on all
grammar memory during concurrent compilation or generation. Evicted entries
are compiled again when needed; grammar constraints remain enforced.

The CPU tests check actual token masks, invalid schemas, padded vocabulary,
added special tokens, JSON-object semantics, regex/choice/EBNF and DSML tool
arguments. Hardware and full HTTP qualification are separate migration gates.

Attribution: [MLC AI/xgrammar](https://github.com/mlc-ai/xgrammar/tree/97787376faee5ed8466cfad57c99855e4ce2f6aa)
and its contributors (Apache-2.0). The DSML tag construction is adapted from
that revision's `python/xgrammar/builtin_structural_tag.py`. The vocabulary
policy comes through this fork's MIT `engine/grammar.py`, originally adapted
from Jay Leaton's TensorFold Spark grammar integration. Distributions must
include xgrammar's license and its third-party notices alongside TensorFold's.
