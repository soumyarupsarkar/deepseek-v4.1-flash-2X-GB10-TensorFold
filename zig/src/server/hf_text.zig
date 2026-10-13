//! A checkpoint's tokenizer.json and chat template behind ``model_text.Text`` (our tokenizer and template engines).
const std = @import("std");
const tokenizer = @import("tokenizer");
const template = @import("template");
const json = @import("json.zig");
const model_text = @import("model_text.zig");
const Value = json.Value;
const Allocator = std.mem.Allocator;

pub const HfText = struct {
    gpa: Allocator,
    io: std.Io,
    // Bound CPU preparation scratch across concurrent long conversations.
    // Decoding and the GPU scheduler do not acquire this lock.
    preparation: std.Io.Mutex = .init,
    arena: std.heap.ArenaAllocator,
    tok: tokenizer.Tokenizer,
    source: []const u8 = "",
    tool_source: []const u8 = "",
    compiled: ?template.Compiled = null,
    tool_compiled: ?template.Compiled = null,
    specials: std.json.Value = .null,
    eos: []const u32 = &.{},
    prefix: []const u32 = &.{}, // the post-processor's tokens before a text (add_special_tokens)
    suffix: []const u32 = &.{},

    /// Loads ``dir``'s tokenizer.json, chat template, special tokens and end-of-sequence ids; a failure's reason in `problem` (from `pa`).
    pub fn load(gpa: Allocator, io: std.Io, dir: []const u8, pa: Allocator, problem: *[]const u8) !*HfText {
        const t = try gpa.create(HfText);
        errdefer gpa.destroy(t);
        t.* = .{ .gpa = gpa, .io = io, .arena = .init(gpa), .tok = undefined };
        errdefer t.arena.deinit();
        const a = t.arena.allocator();
        t.tok = tokenizer.loadTokenizer(io, gpa, dir) catch |e| {
            problem.* = try std.fmt.allocPrint(pa, "cannot read {s}/tokenizer.json ({s})", .{ dir, @errorName(e) });
            return error.Load;
        };
        const config = readJson(io, a, dir, "tokenizer_config.json");
        const model_config = readJson(io, a, dir, "config.json");
        try t.readTemplates(io, a, dir, config);
        t.specials = try specialsOf(a, config);
        t.eos = try t.eosIds(a, model_config, config);
        try t.readPostProcessor(io, a, dir);
        if (t.source.len > 0) {
            var diag: template.Diag = .{};
            t.compiled = template.compile(gpa, t.source, &diag) catch |e| {
                problem.* = try std.fmt.allocPrint(pa, "the chat template does not compile: {s} ({s})", .{ diag.msg, @errorName(e) });
                return error.Load;
            };
        }
        if (t.tool_source.len > 0) t.tool_compiled = template.compile(gpa, t.tool_source, null) catch null;
        return t;
    }

    pub fn deinit(t: *HfText) void {
        if (t.compiled) |*c| c.deinit();
        if (t.tool_compiled) |*c| c.deinit();
        t.tok.deinit();
        t.arena.deinit();
        t.gpa.destroy(t);
    }

    fn readJson(io: std.Io, a: Allocator, dir: []const u8, name: []const u8) std.json.Value {
        const path = std.fs.path.join(a, &.{ dir, name }) catch return .null;
        const bytes = std.Io.Dir.cwd().readFileAlloc(io, path, a, .limited(64 << 20)) catch return .null;
        return std.json.parseFromSliceLeaky(std.json.Value, a, bytes, .{}) catch .null;
    }

    /// chat_template.jinja, else chat_template.json, else tokenizer_config.json's (named: "default", and "tool_use").
    fn readTemplates(t: *HfText, io: std.Io, a: Allocator, dir: []const u8, config: std.json.Value) !void {
        const jinja = try std.fs.path.join(a, &.{ dir, "chat_template.jinja" });
        if (std.Io.Dir.cwd().readFileAlloc(io, jinja, a, .limited(16 << 20))) |s| {
            t.source = s;
            return;
        } else |_| {}
        const sidecar = readJson(io, a, dir, "chat_template.json");
        if (sidecar == .object) if (sidecar.object.get("chat_template")) |s| if (s == .string) {
            t.source = s.string;
            return;
        };
        if (config != .object) return;
        const found = config.object.get("chat_template") orelse return;
        switch (found) {
            .string => |s| t.source = s,
            .array => |list| for (list.items) |entry| {
                if (entry != .object) continue;
                const name = entry.object.get("name") orelse continue;
                const body = entry.object.get("template") orelse continue;
                if (name != .string or body != .string) continue;
                if (std.mem.eql(u8, name.string, "default")) t.source = body.string;
                if (std.mem.eql(u8, name.string, "tool_use")) t.tool_source = body.string;
            },
            .object => |o| {
                if (o.get("default")) |d| if (d == .string) {
                    t.source = d.string;
                };
                if (o.get("tool_use")) |d| if (d == .string) {
                    t.tool_source = d.string;
                };
            },
            else => {},
        }
    }

    /// Every ``*_token`` string (or ``{"content": ...}``) in tokenizer_config.json, as apply_chat_template passes them.
    fn specialsOf(a: Allocator, config: std.json.Value) !std.json.Value {
        var out: std.json.ObjectMap = .empty;
        if (config == .object) {
            var it = config.object.iterator();
            while (it.next()) |e| {
                if (!std.mem.endsWith(u8, e.key_ptr.*, "_token")) continue;
                switch (e.value_ptr.*) {
                    .string => try out.put(a, e.key_ptr.*, e.value_ptr.*),
                    .object => |o| if (o.get("content")) |c| if (c == .string) try out.put(a, e.key_ptr.*, c),
                    else => {},
                }
            }
        }
        return .{ .object = out };
    }

    /// Model end ids plus the tokenizer's chat end, when both are declared.
    fn eosIds(t: *HfText, a: Allocator, model_config: std.json.Value, config: std.json.Value) ![]const u32 {
        var out: std.ArrayList(u32) = .empty;
        if (model_config == .object) {
            const holders = [_]?std.json.Value{ model_config.object.get("eos_token_id"), if (model_config.object.get("text_config")) |tc| (if (tc == .object) tc.object.get("eos_token_id") else null) else null };
            for (holders) |h| {
                const v = h orelse continue;
                switch (v) {
                    .integer => |i| try out.append(a, @intCast(i)),
                    .array => |list| for (list.items) |x| if (x == .integer) try out.append(a, @intCast(x.integer)),
                    else => {},
                }
                if (out.items.len > 0) break;
            }
        }
        if (config == .object) if (config.object.get("eos_token")) |e| {
            const piece = switch (e) {
                .string => |s| s,
                .object => |o| if (o.get("content")) |c| (if (c == .string) c.string else "") else "",
                else => "",
            };
            if (t.tok.specialTokenId(piece)) |id| if (std.mem.indexOfScalar(u32, out.items, id) == null) try out.append(a, id);
        };
        return out.items;
    }

    /// The tokens ``add_special_tokens`` adds: TemplateProcessing's single template, or Bert and Roberta's cls and sep.
    fn readPostProcessor(t: *HfText, io: std.Io, a: Allocator, dir: []const u8) !void {
        const doc = readJson(io, a, dir, "tokenizer.json");
        if (doc != .object) return;
        const pp = doc.object.get("post_processor") orelse return;
        var prefix: std.ArrayList(u32) = .empty;
        var suffix: std.ArrayList(u32) = .empty;
        try addProcessor(a, pp, &prefix, &suffix);
        t.prefix = prefix.items;
        t.suffix = suffix.items;
    }

    fn addProcessor(a: Allocator, pp: std.json.Value, prefix: *std.ArrayList(u32), suffix: *std.ArrayList(u32)) !void {
        if (pp != .object) return;
        const kind = pp.object.get("type") orelse return;
        if (kind != .string) return;
        if (std.mem.eql(u8, kind.string, "Sequence")) {
            const list = pp.object.get("processors") orelse return;
            if (list == .array) for (list.array.items) |p| try addProcessor(a, p, prefix, suffix);
            return;
        }
        if (std.mem.eql(u8, kind.string, "BertProcessing") or std.mem.eql(u8, kind.string, "RobertaProcessing")) {
            if (pp.object.get("cls")) |c| if (c == .array and c.array.items.len == 2 and c.array.items[1] == .integer) try prefix.append(a, @intCast(c.array.items[1].integer));
            if (pp.object.get("sep")) |s| if (s == .array and s.array.items.len == 2 and s.array.items[1] == .integer) try suffix.append(a, @intCast(s.array.items[1].integer));
            return;
        }
        if (!std.mem.eql(u8, kind.string, "TemplateProcessing")) return;
        const single = pp.object.get("single") orelse return;
        const specials = pp.object.get("special_tokens") orelse return;
        if (single != .array or specials != .object) return;
        var after = false;
        for (single.array.items) |piece| {
            if (piece != .object) continue;
            if (piece.object.get("Sequence") != null) {
                after = true;
                continue;
            }
            const st = piece.object.get("SpecialToken") orelse continue;
            if (st != .object) continue;
            const id = st.object.get("id") orelse continue;
            if (id != .string) continue;
            const entry = specials.object.get(id.string) orelse continue;
            if (entry != .object) continue;
            const ids = entry.object.get("ids") orelse continue;
            if (ids != .array) continue;
            for (ids.array.items) |x| if (x == .integer) try (if (after) suffix else prefix).append(a, @intCast(x.integer));
        }
    }

    pub fn text(t: *HfText) model_text.Text {
        return .{ .ctx = t, .vtable = &.{
            .encode = encodeFn,
            .decode = decodeFn,
            .token_id = tokenIdFn,
            .token_string = tokenStringFn,
            .vocab_size = vocabFn,
            .eos_ids = eosFn,
            .render = renderFn,
            .template_source = sourceFn,
            .special = specialFn,
        } };
    }

    fn specialFn(ctx: *anyopaque, id: u32) bool {
        const t = self(ctx);
        const piece = t.tok.id_to_token.get(id) orelse return false;
        return t.tok.specials.contains(piece);
    }

    fn self(ctx: *anyopaque) *HfText {
        return @ptrCast(@alignCast(ctx));
    }

    fn encodeFn(ctx: *anyopaque, a: Allocator, s: []const u8, add_special: bool) model_text.Error![]u32 {
        const t = self(ctx);
        t.preparation.lockUncancelable(t.io);
        defer t.preparation.unlock(t.io);
        // The caller is usually a request arena. Nesting the tokenizer's work
        // arena in it retains all BPE scratch until the entire reply ends.
        // Only the resulting ids belong to that lifetime.
        var scratch: std.heap.ArenaAllocator = .init(t.gpa);
        defer scratch.deinit();
        const ids = t.tok.encode(scratch.allocator(), s) catch |e| return if (e == error.OutOfMemory) error.OutOfMemory else error.Template;
        if (!add_special or (t.prefix.len == 0 and t.suffix.len == 0)) return a.dupe(u32, ids);
        return std.mem.concat(a, u32, &.{ t.prefix, ids, t.suffix });
    }

    fn decodeFn(ctx: *anyopaque, a: Allocator, ids: []const u32) Allocator.Error![]u8 {
        return self(ctx).tok.decode(a, ids, false) catch |e| if (e == error.OutOfMemory) error.OutOfMemory else a.dupe(u8, "\u{fffd}");
    }

    fn tokenIdFn(ctx: *anyopaque, piece: []const u8) ?u32 {
        return self(ctx).tok.specialTokenId(piece);
    }

    fn tokenStringFn(ctx: *anyopaque, a: Allocator, id: u32) Allocator.Error![]u8 {
        const piece = self(ctx).tok.id_to_token.get(id) orelse return a.dupe(u8, "");
        return a.dupe(u8, piece);
    }

    fn vocabFn(ctx: *anyopaque) u32 {
        return @intCast(self(ctx).tok.id_to_token.tokens.items.len);
    }

    fn eosFn(ctx: *anyopaque) []const u32 {
        return self(ctx).eos;
    }

    fn sourceFn(ctx: *anyopaque) []const u8 {
        const t = self(ctx);
        return if (t.tool_source.len > 0) std.mem.concat(t.arena.allocator(), u8, &.{ t.source, " ", t.tool_source }) catch t.source else t.source;
    }

    fn renderFn(ctx: *anyopaque, out_a: Allocator, messages: Value, options: model_text.RenderOptions, problem: *[]const u8) model_text.Error![]u8 {
        const t = self(ctx);
        t.preparation.lockUncancelable(t.io);
        defer t.preparation.unlock(t.io);
        const compiled = if (options.tools != null and t.tool_compiled != null) &t.tool_compiled.? else if (t.compiled) |*c| c else {
            problem.* = "this checkpoint has no chat template: send a completion prompt instead";
            return error.Template;
        };
        // Template evaluation and JSON conversion are temporary even when the
        // caller holds the rendered prompt for a long-running streamed reply.
        var scratch: std.heap.ArenaAllocator = .init(t.gpa);
        defer scratch.deinit();
        const a = scratch.allocator();
        var context: std.json.ObjectMap = .empty;
        if (t.specials == .object) {
            var it = t.specials.object.iterator();
            while (it.next()) |e| try context.put(a, e.key_ptr.*, e.value_ptr.*);
        }
        try context.put(a, "enable_thinking", .{ .bool = options.enable_thinking });
        try context.put(a, "thinking_mode", .{ .string = if (options.enable_thinking) "thinking" else "chat" });
        if (options.reasoning_effort_value) |v| {
            try context.put(a, "reasoning_effort", .{ .integer = v });
        } else if (options.reasoning_effort) |e| try context.put(a, "reasoning_effort", .{ .string = e });
        var diag: template.Diag = .{};
        const tools: std.json.Value = if (options.tools) |tl| try toStd(a, tl) else .null;
        const out = template.render(a, compiled, try toStd(a, messages), tools, .{ .object = context }, options.add_generation_prompt, &diag) catch |e| {
            if (e == error.OutOfMemory) return error.OutOfMemory;
            problem.* = try out_a.dupe(u8, diag.msg);
            return error.Template;
        };
        return out_a.dupe(u8, out);
    }
};

test "model EOS does not hide a different tokenizer chat end" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var t: HfText = undefined;
    t.tok.vocab = std.StringHashMap(u32).init(a);
    try t.tok.vocab.put("<|im_end|>", 248046);
    const model = try std.json.parseFromSliceLeaky(std.json.Value, a, "{\"text_config\":{\"eos_token_id\":248044}}", .{});
    const config = try std.json.parseFromSliceLeaky(std.json.Value, a, "{\"eos_token\":\"<|im_end|>\"}", .{});
    try std.testing.expectEqualSlices(u32, &.{ 248044, 248046 }, try t.eosIds(a, model, config));
    const same = try std.json.parseFromSliceLeaky(std.json.Value, a, "{\"eos_token_id\":[248046]}", .{});
    try std.testing.expectEqualSlices(u32, &.{248046}, try t.eosIds(a, same, config));
    const added = try std.json.parseFromSliceLeaky(std.json.Value, a, "{\"eos_token\":{\"content\":\"<|im_end|>\"}}", .{});
    try std.testing.expectEqualSlices(u32, &.{ 248044, 248046 }, try t.eosIds(a, model, added));
    try std.testing.expectEqualSlices(u32, &.{248046}, try t.eosIds(a, .null, config));
}

test "tokenization retains only ids in the request arena" {
    const gpa = std.testing.allocator;
    var t: HfText = .{ .gpa = gpa, .io = std.testing.io, .arena = .init(gpa), .tok = try tokenizer.parse(gpa,
        \\{"added_tokens":[],"pre_tokenizer":{"type":"ByteLevel","add_prefix_space":false,"use_regex":true},
        \\ "decoder":{"type":"ByteLevel"},"model":{"type":"BPE","vocab":{"a":0,"b":1,"Ġ":2,"ab":3},"merges":["a b"]}}
    ) };
    defer t.tok.deinit();
    defer t.arena.deinit();
    var request: std.heap.ArenaAllocator = .init(gpa);
    defer request.deinit();
    const text = try gpa.alloc(u8, 3 * 4096);
    defer gpa.free(text);
    for (0..4096) |i| @memcpy(text[i * 3 ..][0..3], "ab ");
    const expected = try t.tok.encode(gpa, text);
    defer gpa.free(expected);
    const ids = try HfText.encodeFn(&t, request.allocator(), text, false);
    try std.testing.expectEqualSlices(u32, expected, ids);
    // Arena bookkeeping/growth is allowed, tokenizer working storage is not.
    try std.testing.expect(request.queryCapacity() <= 2 * ids.len * @sizeOf(u32) + 4096);
    _ = request.reset(.free_all);
    t.prefix = &.{42};
    t.suffix = &.{43};
    const special = try HfText.encodeFn(&t, request.allocator(), text, true);
    try std.testing.expectEqual(@as(u32, 42), special[0]);
    try std.testing.expectEqualSlices(u32, expected, special[1 .. special.len - 1]);
    try std.testing.expectEqual(@as(u32, 43), special[special.len - 1]);
    try std.testing.expect(request.queryCapacity() <= 2 * special.len * @sizeOf(u32) + 4096);
}

test "template scratch is released and error diagnostics outlive it" {
    const gpa = std.testing.allocator;
    var t: HfText = .{ .gpa = gpa, .io = std.testing.io, .arena = .init(gpa), .tok = undefined };
    defer t.arena.deinit();
    t.compiled = try template.compile(gpa, "{% for m in messages %}{{ m.content }}{% endfor %}", null);
    defer if (t.compiled) |*compiled| compiled.deinit();
    var input: std.heap.ArenaAllocator = .init(gpa);
    defer input.deinit();
    const message = try json.newObject(input.allocator());
    const phrase = "synthetic template fixture ";
    const text = try input.allocator().alloc(u8, phrase.len * 512);
    for (0..512) |i| @memcpy(text[i * phrase.len ..][0..phrase.len], phrase);
    try message.put(input.allocator(), "role", .{ .string = "user" });
    try message.put(input.allocator(), "content", .{ .string = text });
    var items = [_]Value{.{ .object = message }};
    var request: std.heap.ArenaAllocator = .init(gpa);
    defer request.deinit();
    var problem: []const u8 = "";
    const rendered = try HfText.renderFn(&t, request.allocator(), .{ .array = &items }, .{}, &problem);
    try std.testing.expectEqualStrings(text, rendered);
    try std.testing.expect(request.queryCapacity() <= 2 * rendered.len + 4096);
    t.compiled.?.deinit();
    t.compiled = null;
    t.compiled = try template.compile(gpa, "{{ raise_exception(messages[0].content) }}", null);
    _ = request.reset(.free_all);
    try std.testing.expectError(error.Template, HfText.renderFn(&t, request.allocator(), .{ .array = &items }, .{}, &problem));
    try std.testing.expect(std.mem.indexOf(u8, problem, "synthetic template fixture") != null);
}

/// Our JSON value as std.json's, ints exact (past i64 as number strings) and keys in order.
pub fn toStd(a: Allocator, v: Value) Allocator.Error!std.json.Value {
    return switch (v) {
        .null => .null,
        .bool => |b| .{ .bool = b },
        .int => |s| if (std.fmt.parseInt(i64, s, 10)) |i| .{ .integer = i } else |_| .{ .number_string = s },
        .float => |f| .{ .float = f },
        .string => |s| .{ .string = s },
        .array => |items| blk: {
            var list: std.json.Array = .init(a);
            try list.ensureTotalCapacity(items.len);
            for (items) |item| list.appendAssumeCapacity(try toStd(a, item));
            break :blk .{ .array = list };
        },
        .object => |o| blk: {
            var map: std.json.ObjectMap = .empty;
            try map.ensureTotalCapacity(a, o.count());
            for (o.keys(), o.values()) |k, item| map.putAssumeCapacity(k, try toStd(a, item));
            break :blk .{ .object = map };
        },
    };
}
