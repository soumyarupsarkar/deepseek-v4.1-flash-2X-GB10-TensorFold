// Uses xgrammar's public C++ API, Apache-2.0, MLC AI/xgrammar contributors.
// The vocabulary policy follows this fork's MIT engine/grammar.py, adapted
// originally from Jay Leaton's TensorFold Spark grammar integration.
#include "bridge.h"
#include <xgrammar/xgrammar.h>
#include <picojson.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Json = picojson::value;
Json parse(const std::string& text) {
  Json result;
  const auto error = picojson::parse(result, text);
  if (!error.empty()) throw std::invalid_argument("invalid JSON");
  return result;
}
const Json& field(const Json& value, const char* key) {
  if (!value.is<picojson::object>() || !value.contains(key))
    throw std::invalid_argument("missing tokenizer field");
  return value.get(key);
}
int index(const Json& value) {
  if (value.is<int64_t>()) {
    const auto n = value.get<int64_t>();
    if (n < 0 || n > 1048576) throw std::invalid_argument("token id out of range");
    return static_cast<int>(n);
  }
  if (!value.is<double>()) throw std::invalid_argument("invalid token id");
  const double n = value.get<double>();
  if (!std::isfinite(n) || n < 0 || n > 1048576 || std::floor(n) != n)
    throw std::invalid_argument("token id out of range");
  return static_cast<int>(n);
}
std::vector<std::string> vocabulary(const Json& doc, bool tools) {
  const auto& model = field(doc, "model");
  const auto& vocab = field(model, "vocab");
  if (!vocab.is<picojson::object>())
    throw std::invalid_argument("native grammar bridge currently requires a BPE vocabulary");
  std::vector<std::string> result;
  const auto put = [&](int id, const std::string& piece) {
    if (static_cast<size_t>(id) >= result.size()) result.resize(id + 1);
    result[id] = piece;
  };
  for (const auto& [piece, id] : vocab.get<picojson::object>()) put(index(id), piece);
  if (doc.contains("added_tokens")) {
    const auto& added = doc.get("added_tokens");
    if (!added.is<picojson::array>()) throw std::invalid_argument("invalid added_tokens");
    for (const auto& entry : added.get<picojson::array>()) {
      const auto& content = field(entry, "content");
      if (!content.is<std::string>()) throw std::invalid_argument("invalid added token");
      const auto& piece = content.get<std::string>();
      put(index(field(entry, "id")), tools && piece == "｜DSML｜" ? piece : "");
    }
  }
  return result;
}
void report(char* out, size_t n, const char* message) noexcept {
  if (out && n) std::snprintf(out, n, "%s", message);
}
struct Compiler {
  std::mutex mutex;
  std::unique_ptr<xgrammar::GrammarCompiler> plain;
  std::unique_ptr<xgrammar::GrammarCompiler> tools;
  int vocab_size;
  Compiler(const std::string& raw, const std::vector<int32_t>& stop, int threads, int64_t bytes) {
    if (threads < 1 || threads > 16 || bytes < (1 << 20) || bytes > (1LL << 30))
      throw std::invalid_argument("invalid compiler resource limit");
    const auto doc = parse(raw);
    auto normal = vocabulary(doc, false);
    auto special = vocabulary(doc, true);
    if (normal.empty() || normal.size() != special.size()) throw std::invalid_argument("invalid vocabulary");
    vocab_size = static_cast<int>(normal.size());
    for (auto id : stop) if (id < 0 || id >= vocab_size) throw std::invalid_argument("invalid stop token");
    const auto meta = parse(xgrammar::TokenizerInfo::DetectMetadataFromHF(raw));
    const auto& kind = field(meta, "vocab_type");
    const auto& prefix = field(meta, "add_prefix_space");
    if (!prefix.is<bool>() || index(kind) > 2) throw std::invalid_argument("invalid tokenizer metadata");
    const auto type = static_cast<xgrammar::VocabType>(index(kind));
    const auto make = [&](const auto& vocab) {
      const xgrammar::TokenizerInfo info(vocab, type, vocab_size, stop, prefix.get<bool>());
      return std::make_unique<xgrammar::GrammarCompiler>(info, threads, true, bytes);
    };
    plain = make(normal);
    tools = make(special); // built before the scheduler starts; never in a rank-to-rank round
  }
};
struct Matcher {
  xgrammar::GrammarMatcher matcher;
  std::vector<int32_t> bits;
  int vocab_size;
  int64_t shape;
  explicit Matcher(const xgrammar::CompiledGrammar& grammar, int vocab)
      : matcher(grammar), bits(xgrammar::GetBitmaskSize(vocab)), vocab_size(vocab),
        shape(static_cast<int64_t>(bits.size())) {}
};
}

uint32_t tf_xg_abi_version() { return 2; }
void* tf_xg_compiler_create(const char* tokenizer, size_t length, const uint32_t* stop_ids,
    size_t stop_count, int threads, int64_t cache_bytes, char* error, size_t error_size) {
  try {
    if (!tokenizer || length == 0 || length > (64 << 20) || stop_count == 0 || stop_count > 64 || !stop_ids)
      throw std::invalid_argument("invalid tokenizer input");
    std::vector<int32_t> stop;
    for (size_t i = 0; i < stop_count; ++i) {
      if (stop_ids[i] > 1048576) throw std::invalid_argument("invalid stop token");
      stop.push_back(static_cast<int32_t>(stop_ids[i]));
    }
    return new Compiler(std::string(tokenizer, length), stop, threads, cache_bytes);
  } catch (const std::exception& e) { report(error, error_size, e.what()); }
    catch (...) { report(error, error_size, "grammar compiler failed"); }
  return nullptr;
}
void tf_xg_compiler_destroy(void* compiler) { delete static_cast<Compiler*>(compiler); }

void* tf_xg_matcher_create(void* compiler, uint32_t kind, const char* text, size_t length,
    char* error, size_t error_size) {
  try {
    if (!compiler || !text || length > (4 << 20)) throw std::invalid_argument("invalid grammar input");
    auto* c = static_cast<Compiler*>(compiler);
    std::lock_guard<std::mutex> lock(c->mutex);
    const std::string source(text, length);
    const auto compile = [&]() -> xgrammar::CompiledGrammar {
      switch (kind) {
        case 0: return c->plain->CompileJSONSchema("{\"type\":\"object\"}", true, std::nullopt, std::nullopt, true, 32);
        case 1: return c->plain->CompileJSONSchema(source, true, std::nullopt, std::nullopt, true, 32);
        case 2: return c->plain->CompileRegex(source);
        case 3: {
          const auto choices = parse(source);
          if (!choices.is<picojson::array>() || choices.get<picojson::array>().empty())
            throw std::invalid_argument("choices must be nonempty strings");
          std::string rule = "root ::= ";
          for (const auto& choice : choices.get<picojson::array>()) {
            if (!choice.is<std::string>() || choice.get<std::string>().empty())
              throw std::invalid_argument("choices must be nonempty strings");
            if (rule.size() > 9) rule += " | ";
            rule += choice.serialize();
          }
          return c->plain->CompileGrammar(rule);
        }
        case 4: return c->plain->CompileGrammar(source);
        case 5: return c->tools->CompileStructuralTag(source);
        default: throw std::invalid_argument("unknown grammar kind");
      }
    };
    return new Matcher(compile(), c->vocab_size);
  } catch (const std::exception& e) { report(error, error_size, e.what()); }
    catch (...) { report(error, error_size, "grammar compilation failed"); }
  return nullptr;
}
void tf_xg_matcher_destroy(void* matcher) { delete static_cast<Matcher*>(matcher); }
int tf_xg_accept(void* matcher, uint32_t token) {
  try {
    auto* m = static_cast<Matcher*>(matcher);
    if (!m || token >= static_cast<uint32_t>(m->vocab_size) || m->matcher.IsTerminated()) return -1;
    return m->matcher.AcceptToken(static_cast<int32_t>(token)) ? 0 : -1;
  } catch (...) { return -1; }
}
int tf_xg_mask(void* matcher, float* logits, size_t count) {
  try {
    auto* m = static_cast<Matcher*>(matcher);
    if (!m || !logits || count < static_cast<size_t>(m->vocab_size) || m->matcher.IsTerminated()) return -1;
    DLTensor mask{};
    mask.data = m->bits.data();
    mask.device = {kDLCPU, 0};
    mask.ndim = 1;
    mask.dtype = xgrammar::GetBitmaskDLType();
    mask.shape = &m->shape;
    const bool apply = m->matcher.FillNextTokenBitmask(&mask);
    bool any = false;
    for (size_t i = 0; i < count; ++i) {
      const bool allowed = i < static_cast<size_t>(m->vocab_size) &&
          (!apply || (static_cast<uint32_t>(m->bits[i / 32]) & (uint32_t{1} << (i % 32))));
      if (!allowed) logits[i] = -std::numeric_limits<float>::infinity();
      else if (std::isfinite(logits[i])) any = true;
    }
    return any ? 0 : -1;
  } catch (...) { return -1; }
}
int tf_xg_preview_mask(void* matcher, const uint32_t* tokens,
    size_t token_count, float* logits, size_t count) {
  auto* m = static_cast<Matcher*>(matcher);
  if (!m || token_count > 64 || (token_count && !tokens)) return -1;
  int accepted = 0, result = -1;
  try {
    for (size_t i = 0; i < token_count; ++i) {
      if (tf_xg_accept(m, tokens[i]) != 0) break;
      ++accepted;
    }
    if (static_cast<size_t>(accepted) == token_count)
      result = tf_xg_mask(m, logits, count);
  } catch (...) { result = -1; }
  // In particular this restores a temporarily accepted EOS, and partial paths
  // that fail before their last token. Callers must stop on a rollback error.
  try { if (accepted) m->matcher.Rollback(accepted); }
  catch (...) { return -1; }
  return result;
}
uint64_t tf_xg_cache_bytes(void* compiler) {
  try {
    auto* c = static_cast<Compiler*>(compiler);
    if (!c) return 0;
    std::lock_guard<std::mutex> lock(c->mutex);
    return c->plain->GetCacheSizeBytes() + c->tools->GetCacheSizeBytes();
  } catch (...) { return 0; }
}
