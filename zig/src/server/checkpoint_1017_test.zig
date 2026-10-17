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
