//! Synthetic prompts recorded from DeepSeek's immutable 1017 reference encoder.
//! Exercise the actual native normalization AND template engine, without a GPU.
const std = @import("std");
const template = @import("template");
const messages = @import("messages.zig");
const json = @import("json.zig");
const hf_text = @import("hf_text.zig");
const errors = @import("errors.zig");

test "1017 native prompts and image order match the pinned reference encoder" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const source = @import("checkpoint_1017").template;
    const fixture = @import("checkpoint_1017").prompts;
    const cases = (try json.parse(a, fixture)).ok.get("cases").?.array;
    var diag: template.Diag = .{};
    var compiled = try template.compile(a, source, &diag);
    defer compiled.deinit();
    for (cases) |case| {
        var cx: errors.Cx = .{ .a = a };
        var images: messages.Images = .{ .placeholder = "<｜deepseek_image｜>" };
        const normalized = try messages.normalizeImages(&cx, case.get("wire_messages"), "system", false, &images);
        const with_args = try messages.toolArguments(&cx, normalized);
        const rendered = try template.render(a, &compiled, try hf_text.toStd(a, with_args), .null, try hf_text.toStd(a, case.get("kwargs").?), true, &diag);
        const expected = case.get("expected").?.string;
        if (!std.mem.eql(u8, rendered, expected)) std.debug.print("1017 prompt case: {s}\n", .{case.get("name").?.string});
        try std.testing.expectEqualStrings(expected, rendered);
        const wanted_images = case.get("expected_images").?.array;
        try std.testing.expectEqual(wanted_images.len, images.list.items.len);
        for (wanted_images, images.list.items) |im, bytes| {
            const url = im.get("url").?.string;
            const b64 = url[(std.mem.indexOfScalar(u8, url, ',') orelse unreachable) + 1 ..];
            const n = try std.base64.standard.Decoder.calcSizeForSlice(b64);
            const decoded = try a.alloc(u8, n);
            try std.base64.standard.Decoder.decode(decoded, b64);
            try std.testing.expectEqualStrings(decoded, bytes);
        }
    }
}

test "assistant reasoning aliases and opt-in omission preserve the 1017 tool round" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var cx: errors.Cx = .{ .a = a };
    var diag: template.Diag = .{};
    var compiled = try template.compile(a, @import("checkpoint_1017").template, &diag);
    defer compiled.deinit();
    const cases = (try json.parse(a, @import("checkpoint_1017").prompts)).ok.get("cases").?.array;
    const case = for (cases) |c| {
        if (std.mem.eql(u8, c.strField("name").?, "tool_round-thinking-high")) break c;
    } else return error.MissingFixture;
    const wire = case.get("wire_messages").?;
    const assistant = wire.array[1].object;
    const thought = assistant.get("reasoning_content").?.string;
    const expected = case.strField("expected").?;
    const omitted = try std.mem.replaceOwned(u8, a, expected, thought, "");
    const kwargs = try hf_text.toStd(a, case.get("kwargs").?);
    for ([_]?json.Value{ .{ .string = thought }, null, .null, .{ .string = "" } }, 0..) |canonical, i| {
        _ = assistant.orderedRemove("reasoning_content");
        if (canonical) |field| try assistant.put(a, "reasoning_content", field);
        try assistant.put(a, "reasoning", .{ .string = if (i == 0) "ignored alias" else thought });
        const normalized = try messages.toolArguments(&cx, try messages.normalize(&cx, wire, "system", false));
        const actual = try template.render(a, &compiled, try hf_text.toStd(a, normalized), .null, kwargs, true, &diag);
        try std.testing.expectEqualStrings(expected, actual);
        const dropped = try messages.dropReasoning(&cx, normalized);
        const rendered = try template.render(a, &compiled, try hf_text.toStd(a, dropped), .null, kwargs, true, &diag);
        try std.testing.expectEqualStrings(omitted, rendered);
        try std.testing.expect(!dropped.array[1].has("reasoning") and !dropped.array[1].has("reasoning_content"));
        try std.testing.expectEqualStrings(thought, normalized.array[1].strField("reasoning_content").?);
        try std.testing.expectEqual(canonical != null, assistant.contains("reasoning_content"));
    }
    const user = (try json.parse(a, "[{\"role\":\"user\",\"content\":\"hello\",\"reasoning\":\"keep\"}]")).ok;
    try std.testing.expect((try messages.dropReasoning(&cx, user)).array.ptr == user.array.ptr);
}
