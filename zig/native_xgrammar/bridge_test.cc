// Synthetic CPU contract tests of the actual xgrammar masks, with no GPU or Python.
#include "bridge.h"
#include <picojson.h>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {
using Json = picojson::value;
using Object = picojson::object;
using Array = picojson::array;
constexpr uint32_t dsml = 128, blocked_special = 129, eos = 130;
Json str(const char* v) { return Json(std::string(v)); }
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
std::string tokenizer() {
  Object vocab;
  for (int i = 0; i < 128; ++i) vocab[std::string(1, char(i))] = Json(int64_t(i));
  Array added;
  for (const auto& pair : std::vector<std::pair<uint32_t, const char*>>{
      {dsml, "｜DSML｜"}, {blocked_special, "<blocked>"}, {eos, "<eos>"}}) {
    added.emplace_back(Object{{"id", Json(int64_t(pair.first))}, {"content", str(pair.second)},
      {"special", Json(true)}});
  }
  return Json(Object{{"model", Json(Object{{"type", str("BPE")}, {"vocab", Json(vocab)},
      {"merges", Json(Array{})}})}, {"added_tokens", Json(added)}}).serialize();
}
using Handle = std::unique_ptr<void, void(*)(void*)>;
Handle match(void* compiler, uint32_t kind, const std::string& text) {
  char error[1024]{};
  auto* m = tf_xg_matcher_create(compiler, kind, text.data(), text.size(), error, sizeof(error));
  if (!m) throw std::runtime_error(std::string("compile: ") + error);
  return Handle(m, tf_xg_matcher_destroy);
}
std::vector<float> mask(void* m) {
  std::vector<float> logits(160, 1.0f);
  require(tf_xg_mask(m, logits.data(), logits.size()) == 0, "mask failed");
  require(!std::isfinite(logits[159]), "padded vocabulary entry was allowed");
  require(!std::isfinite(logits[blocked_special]), "unrelated added token was allowed");
  return logits;
}
void feed(void* m, const std::string& text) {
  for (size_t i = 0; i < text.size();) {
    uint32_t token = static_cast<unsigned char>(text[i]);
    if (text.compare(i, std::string("｜DSML｜").size(), "｜DSML｜") == 0) {
      token = dsml; i += std::string("｜DSML｜").size();
    } else ++i;
    require(std::isfinite(mask(m)[token]), "valid continuation was masked");
    require(tf_xg_accept(m, token) == 0, "valid continuation was rejected");
  }
}
void finish(void* m) {
  require(std::isfinite(mask(m)[eos]), "completed grammar cannot stop");
  require(tf_xg_accept(m, eos) == 0, "stop token rejected");
  std::vector<float> out(160);
  require(tf_xg_mask(m, out.data(), out.size()) == -1, "terminated matcher accepted another draw");
}
std::string tool_tag() {
  const Json schema(Object{{"type", str("object")}, {"properties", Json(Object{{"city",
      Json(Object{{"type", str("string")}, {"enum", Json(Array{str("Paris")})}})}})},
      {"required", Json(Array{str("city")})}, {"additionalProperties", Json(false)}});
  const Json tag(Object{{"type", str("tag")}, {"begin", str("<｜DSML｜ invoke name=\"weather\">\n")},
      {"content", Json(Object{{"type", str("json_schema")}, {"style", str("deepseek_v4_1_xml")},
       {"json_schema", schema}, {"max_whitespace_cnt", Json(int64_t(32))}})},
      {"end", str("</｜DSML｜ invoke>\n")}});
  return Json(Object{{"type", str("structural_tag")}, {"format", Json(Object{
      {"type", str("sequence")}, {"elements", Json(Array{
       Json(Object{{"type", str("const_string")}, {"value", str("\n\n<｜DSML｜ calls>\n")}}), tag,
       Json(Object{{"type", str("const_string")}, {"value", str("</｜DSML｜ calls>")}})})}})}}).serialize();
}
}
int main() {
  try {
    require(tf_xg_abi_version() == 2, "ABI mismatch");
    const auto tok = tokenizer();
    char error[1024]{};
    Handle compiler(tf_xg_compiler_create(tok.data(), tok.size(), &eos, 1, 2, 8 << 20,
        error, sizeof(error)), tf_xg_compiler_destroy);
    if (!compiler) throw std::runtime_error(std::string("tokenizer: ") + error);
    {
      auto m = match(compiler.get(), 0, "");
      auto allowed = mask(m.get());
      require(!std::isfinite(allowed['[']) && std::isfinite(allowed['{']), "json_object accepted an array");
      feed(m.get(), "{}"); finish(m.get());
    }
    const std::string schema = R"({"type":"object","properties":{"ok":{"const":true},"count":{"type":"integer","enum":[7]}},"required":["ok","count"],"additionalProperties":false})";
    {
      auto m = match(compiler.get(), 1, schema);
      // A thinking-budget close must not force a newline into this grammar:
      // whitespace between JSON terms does not permit a prefix before root.
      require(!std::isfinite(mask(m.get())['\n']), "schema unexpectedly permits a forced leading newline");
      require(tf_xg_accept(m.get(), '\n') == -1, "invalid leading newline was accepted");
      feed(m.get(), "{\"ok\":true,\"count\":");
      require(!std::isfinite(mask(m.get())['8']), "schema enum did not constrain the argument");
      feed(m.get(), "7}"); finish(m.get());
    }
    for (const auto& test : std::vector<std::tuple<uint32_t,std::string,std::string>>{
        {2, "AB{2}", "ABB"}, {3, R"(["red","blue"])", "blue"}, {4, "root ::= \"ok\"", "ok"}}) {
      auto m = match(compiler.get(), std::get<0>(test), std::get<1>(test));
      feed(m.get(), std::get<2>(test)); finish(m.get());
    }
    {
      auto m = match(compiler.get(), 5, tool_tag());
      feed(m.get(), "\n\n<｜DSML｜ calls>\n<｜DSML｜ invoke name=\"weather\">\n<｜DSML｜ parameter name=\"city\" string=\"true\">");
      require(!std::isfinite(mask(m.get())['R']), "DSML schema allowed Rome instead of Paris");
      feed(m.get(), "Paris</｜DSML｜ parameter>\n</｜DSML｜ invoke>\n</｜DSML｜ calls>");
      finish(m.get());
    }
    require(!tf_xg_matcher_create(compiler.get(), 1, "{", 1, error, sizeof(error)), "malformed schema compiled");
    require(!tf_xg_matcher_create(compiler.get(), 99, "", 0, error, sizeof(error)), "unknown format compiled");
    require(tf_xg_cache_bytes(compiler.get()) <= (16 << 20), "compiler exceeded the two cache budgets");
    {
      auto m = match(compiler.get(), 2, "AB{2}");
      const auto before = mask(m.get());
      const uint32_t valid[] = {'A', 'B'};
      std::vector<float> logits(160, 1.0f);
      require(tf_xg_preview_mask(m.get(), valid, 2, logits.data(), logits.size()) == 0, "preview failed");
      require(std::isfinite(logits['B']) && !std::isfinite(logits['A']), "preview did not advance its mask");
      require(mask(m.get()) == before, "successful preview changed committed state");
      const uint32_t invalid[] = {'A', 'B', 'Z'};
      require(tf_xg_preview_mask(m.get(), invalid, 3, logits.data(), logits.size()) == -1, "invalid draft accepted");
      require(mask(m.get()) == before, "rejected preview left its accepted prefix behind");
      const uint32_t end[] = {'A', 'B', 'B', eos};
      require(tf_xg_preview_mask(m.get(), end, 4, logits.data(), logits.size()) == -1, "terminated preview permitted another token");
      require(mask(m.get()) == before, "EOS preview did not restore the matcher");
      // The next committed path can differ from a preview, as at a forced cut.
      feed(m.get(), "A");
      const auto partial = mask(m.get());
      const uint32_t tail[] = {'B', 'B'};
      logits.assign(160, 1.0f);
      require(tf_xg_preview_mask(m.get(), tail, 2, logits.data(), logits.size()) == 0, "committed-prefix preview failed");
      require(std::isfinite(logits[eos]), "preview could not complete the grammar");
      require(mask(m.get()) == partial, "preview rewound committed tokens");
      require(tf_xg_preview_mask(m.get(), nullptr, 1, logits.data(), logits.size()) == -1, "null draft accepted");
      require(tf_xg_preview_mask(m.get(), tail, 65, logits.data(), logits.size()) == -1, "unbounded preview accepted");
      feed(m.get(), "BB"); finish(m.get());
    }
    std::cout << "native grammar contracts passed\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
