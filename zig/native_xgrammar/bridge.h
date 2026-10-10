// TensorFold's small C ABI over xgrammar 0.2.8. No Python runtime or CUDA dependency.
#ifndef TENSORFOLD_XGRAMMAR_BRIDGE_H
#define TENSORFOLD_XGRAMMAR_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define TF_XG_EXPORT __attribute__((visibility("default")))
TF_XG_EXPORT uint32_t tf_xg_abi_version(void);
// The returned compiler owns both bounded vocabulary-specific caches. It must
// outlive its matchers. Every exception is caught inside this ABI.
TF_XG_EXPORT void* tf_xg_compiler_create(const char* tokenizer, size_t length,
    const uint32_t* stop_ids, size_t stop_count, int threads, int64_t cache_bytes,
    char* error, size_t error_size);
TF_XG_EXPORT void tf_xg_compiler_destroy(void* compiler);
// kind: 0 JSON object, 1 JSON schema, 2 regex, 3 choice JSON array, 4 EBNF,
// 5 structural-tag JSON. Mask/accept calls belong to one engine thread.
TF_XG_EXPORT void* tf_xg_matcher_create(void* compiler, uint32_t kind,
    const char* text, size_t length, char* error, size_t error_size);
TF_XG_EXPORT void tf_xg_matcher_destroy(void* matcher);
TF_XG_EXPORT int tf_xg_accept(void* matcher, uint32_t token);
TF_XG_EXPORT int tf_xg_mask(void* matcher, float* logits, size_t count);
TF_XG_EXPORT uint64_t tf_xg_cache_bytes(void* compiler);
#ifdef __cplusplus
}
#endif
#endif
