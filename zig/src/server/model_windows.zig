//! Explicit alias limits share one model and one resident KV pool.
const std = @import("std");
pub const Entry = struct { name: []const u8, tokens: u32 };

pub fn parse(a: std.mem.Allocator, raw: []const u8, names: []const []const u8, ceiling: u32) ![]const Entry {
    if (ceiling == 0) return error.NoContextCeiling;
    const doc = try std.json.parseFromSliceLeaky(std.json.Value, a, raw, .{ .duplicate_field_behavior = .@"error" });
    if (doc != .object) return error.BadModelContexts;
    const entries = try a.alloc(Entry, doc.object.count());
    var it = doc.object.iterator();
    var i: usize = 0;
    while (it.next()) |field| : (i += 1) {
        const name = field.key_ptr.*;
        for (names) |known| {
            if (std.mem.eql(u8, known, name)) break;
        } else return error.UnknownModelAlias;
        const n = field.value_ptr.*;
        if (n != .integer or n.integer <= 0 or n.integer > ceiling) return error.BadModelContext;
        entries[i] = .{ .name = name, .tokens = @intCast(n.integer) };
    }
    return entries;
}

pub fn window(entries: []const Entry, name: ?[]const u8, ceiling: u32) u32 {
    if (name) |requested| for (entries) |entry| {
        if (std.mem.eql(u8, requested, entry.name)) return @min(ceiling, entry.tokens);
    };
    return ceiling;
}

test "aliases bound individual requests without resizing the engine" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const names = &[_][]const u8{ "model", "model-262k", "model-524k", "model-614k", "model-1m" };
    const entries = try parse(a, "{\"model-262k\":262144,\"model-524k\":524288,\"model-614k\":614400,\"model-1m\":1048576}", names, 1048576);
    try std.testing.expectEqual(@as(u32, 262144), window(entries, "model-262k", 1048576));
    try std.testing.expectEqual(@as(u32, 1048576), window(entries, "model", 1048576));
    try std.testing.expectError(error.BadModelContext, parse(a, "{\"model-1m\":1048577}", names, 1048576));
    try std.testing.expectError(error.BadModelContext, parse(a, "{\"model-1m\":0}", names, 1048576));
    try std.testing.expectError(error.UnknownModelAlias, parse(a, "{\"typo\":262144}", names, 1048576));
    try std.testing.expectError(error.DuplicateField, parse(a, "{\"model\":1,\"model\":2}", names, 1048576));
}
