//! DeepSeek-V4.1 DSML structural tags, adapted from xgrammar v0.2.8
//! builtin_structural_tag.py (_get_deepseek_v4_structural_tag), Apache-2.0,
//! Copyright MLC AI/xgrammar contributors. Keep the native and reference forms equivalent.
const std = @import("std");
const json = @import("json.zig");
const errors = @import("errors.zig");
const api = @import("engine_api");
const Value = json.Value;
pub const Mode = enum { off, required, all };

fn node(a: std.mem.Allocator, kind: []const u8) !*json.Object {
    const out = try json.newObject(a);
    try out.put(a, "type", .{ .string = kind });
    return out;
}
fn string(a: std.mem.Allocator, text: []const u8) !Value {
    const o = try node(a, "const_string");
    try o.put(a, "value", .{ .string = text });
    return .{ .object = o };
}
fn tag(a: std.mem.Allocator, begin: []const u8, content: Value, end: []const u8) !Value {
    const o = try node(a, "tag");
    try o.put(a, "begin", .{ .string = begin });
    try o.put(a, "content", content);
    try o.put(a, "end", .{ .string = end });
    return .{ .object = o };
}
fn array(a: std.mem.Allocator, values: []const Value) !Value {
    return .{ .array = try a.dupe(Value, values) };
}

pub fn spec(cx: *errors.Cx, fields: Value, tools: []const Value, mode: Mode, after: ?u32) errors.Refused!?api.Structure {
    if (tools.len == 0) return null;
    const required = if (fields.get("tool_call_required")) |v| v.truthy() else false;
    const forced = if (fields.get("tool_choice")) |v| namedChoice(v) else false;
    if (mode == .off) {
        if (required or forced) return cx.refuse("required tool calls need TF_DSV41_TOOL_GRAMMAR=required or all");
        return null;
    }
    var strict = false;
    for (tools) |t| {
        const f = t.get("function") orelse t;
        if (f.get("strict")) |v| if (v == .bool and v.bool) {
            strict = true;
        };
    }
    if (!required and !forced and !strict and mode != .all) return null;
    if (forced and tools.len != 1) return cx.refuse("a named tool choice must select exactly one function");
    const a = cx.a;
    const parallel = if (fields.get("parallel_tool_calls")) |v| v != .bool or v.bool else true;
    const tags = try a.alloc(Value, tools.len);
    for (tools, tags) |t, *out| {
        const f = t.get("function") orelse t;
        const name = (f.get("name") orelse return cx.refuse("every function tool needs a name")).str() orelse return cx.refuse("every function tool needs a name");
        const declared_strict = if (f.get("strict")) |v| v == .bool and v.bool else false;
        var schema: Value = .{ .bool = true };
        if (f.field("parameters")) |p| {
            if (p != .object) return cx.refuse("tool parameters must be a JSON schema object");
            if (mode == .all or declared_strict) schema = p;
        }
        const content = try node(a, "json_schema");
        try content.put(a, "json_schema", schema);
        try content.put(a, "style", .{ .string = "deepseek_v4_1_xml" });
        try content.put(a, "any_order", .{ .bool = false });
        try content.put(a, "max_whitespace_cnt", .{ .int = "32" });
        out.* = try tag(a, try std.fmt.allocPrint(a, "<｜DSML｜ invoke name=\"{s}\">\n", .{name}), .{ .object = content }, "</｜DSML｜ invoke>\n");
    }
    const calls = try node(a, "tags_with_separator");
    try calls.put(a, "tags", .{ .array = tags });
    try calls.put(a, "separator", .{ .string = "" });
    try calls.put(a, "at_least_one", .{ .bool = true });
    try calls.put(a, "stop_after_first", .{ .bool = !parallel });
    var format: Value = undefined;
    if (required or forced) {
        const seq = try node(a, "sequence");
        try seq.put(a, "elements", try array(a, &.{
            try string(a, "\n\n<｜DSML｜ calls>\n"),
            if (forced) tags[0] else .{ .object = calls },
            try string(a, "</｜DSML｜ calls>"),
        }));
        format = .{ .object = seq };
    } else {
        const triggered = try node(a, "triggered_tags");
        try triggered.put(a, "triggers", try array(a, &.{.{ .string = "<｜DSML｜ calls>" }}));
        try triggered.put(a, "tags", try array(a, &.{try tag(a, "<｜DSML｜ calls>\n", .{ .object = calls }, "</｜DSML｜ calls>")}));
        try triggered.put(a, "excludes", try array(a, &.{ .{ .string = "<think>" }, .{ .string = "</think>" } }));
        try triggered.put(a, "stop_after_first", .{ .bool = !parallel });
        format = .{ .object = triggered };
    }
    const root = try node(a, "structural_tag");
    try root.put(a, "format", format);
    return .{ .kind = .tools, .text = try json.stringify(a, .{ .object = root }, .{ .ascii = false }), .after = after };
}

fn namedChoice(value: Value) bool {
    if (value != .object) return false;
    const kind = (value.get("type") orelse return false).str() orelse return false;
    return std.ascii.eqlIgnoreCase(kind, "function");
}

fn parsed(a: std.mem.Allocator, raw: []const u8) !Value {
    return switch (try json.parseText(a, raw)) {
        .ok => |v| v,
        .err => error.BadFixture,
    };
}

test "required and named tools have distinct cardinality and preserve strict schemas" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var cx: errors.Cx = .{ .a = a };
    const tools = (try parsed(a,
        \\[{"type":"function","function":{"name":"weather","strict":true,"parameters":{"type":"object","properties":{"city":{"enum":["Paris"]}},"required":["city"],"additionalProperties":false}}},{"type":"function","function":{"name":"time","parameters":{"type":"object"}}}]
    )).array;
    const required = try parsed(a,
        \\{"tool_call_required":true,"tool_choice":{"type":"required"},"parallel_tool_calls":false}
    );
    const result = (try spec(&cx, required, tools, .required, 123)).?;
    try std.testing.expectEqual(@as(?u32, 123), result.after);
    const doc = try parsed(a, result.text);
    const elements = doc.get("format").?.get("elements").?.array;
    const calls = elements[1];
    try std.testing.expect(calls.get("stop_after_first").?.bool);
    try std.testing.expectEqual(@as(usize, 2), calls.get("tags").?.array.len);
    const schema = calls.get("tags").?.array[0].get("content").?.get("json_schema").?;
    try std.testing.expectEqualStrings("Paris", schema.get("properties").?.get("city").?.get("enum").?.array[0].string);
    const named = try parsed(a,
        \\{"tool_choice":{"type":"function","function":{"name":"weather"}},"tool_call_required":true}
    );
    try std.testing.expectError(error.Refused, spec(&cx, named, tools, .required, null));
    const chosen = (try spec(&cx, named, tools[0..1], .required, null)).?;
    const chosen_doc = try parsed(a, chosen.text);
    try std.testing.expectEqualStrings("tag", chosen_doc.get("format").?.get("elements").?.array[1].get("type").?.string);
    try std.testing.expectError(error.Refused, spec(&cx, required, tools, .off, null));
}

test "auto mode only constrains calls when requested by policy or strict tools" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var cx: errors.Cx = .{ .a = a };
    const tools = (try parsed(a,
        \\[{"type":"function","function":{"name":"weather","parameters":{"type":"object","properties":{"city":{"enum":["Paris"]}}}}}]
    )).array;
    const fields = try parsed(a, "{}");
    try std.testing.expect((try spec(&cx, fields, tools, .required, null)) == null);
    const result = (try spec(&cx, fields, tools, .all, null)).?;
    const doc = try parsed(a, result.text);
    try std.testing.expectEqualStrings("triggered_tags", doc.get("format").?.get("type").?.string);
    try std.testing.expect((try spec(&cx, fields, &.{}, .all, null)) == null);
}
