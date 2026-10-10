//! Deterministic left compaction of disjoint live KV reservations. No GPU state.
const std = @import("std");
pub const max_items = 32;
pub const Extent = struct { slot: usize, base: usize, end: usize };
pub const Move = struct { slot: usize, from: usize, to: usize, len: usize };
pub const Plan = struct { moves: [max_items]Move = undefined, count: usize = 0, end: usize = 0 };

pub fn plan(extents: []const Extent, need: usize, cap: usize, alignment: usize) !?Plan {
    if (extents.len > max_items or alignment == 0 or !std.math.isPowerOfTwo(alignment)) return error.BadExtents;
    if (need > cap) return null;
    var sorted: [max_items]Extent = undefined;
    @memcpy(sorted[0..extents.len], extents);
    std.mem.sort(Extent, sorted[0..extents.len], {}, struct {
        fn less(_: void, x: Extent, y: Extent) bool {
            return x.base < y.base;
        }
    }.less);
    var result: Plan = .{};
    var prior: usize = 0;
    var slots: [max_items]bool = @splat(false);
    for (sorted[0..extents.len]) |extent| {
        if (extent.slot >= max_items or slots[extent.slot] or extent.end <= extent.base or extent.end > cap or
            extent.base < prior or extent.base % alignment != 0 or extent.end % alignment != 0) return error.BadExtents;
        slots[extent.slot] = true;
        const len = extent.end - extent.base;
        if (len > cap - result.end) return error.BadExtents;
        result.moves[result.count] = .{ .slot = extent.slot, .from = extent.base, .to = result.end, .len = len };
        result.count += 1;
        result.end += len;
        prior = extent.end;
    }
    if (need > cap - result.end) return null;
    return result;
}

test "fragmented live extents pack in source order and preserve reservation sizes" {
    const p = (try plan(&.{ .{ .slot = 1, .base = 12, .end = 20 }, .{ .slot = 0, .base = 4, .end = 8 } }, 12, 24, 4)).?;
    try std.testing.expectEqual(@as(usize, 12), p.end);
    try std.testing.expectEqualDeep(Move{ .slot = 0, .from = 4, .to = 0, .len = 4 }, p.moves[0]);
    try std.testing.expectEqualDeep(Move{ .slot = 1, .from = 12, .to = 4, .len = 8 }, p.moves[1]);
    try std.testing.expectEqual(@as(?Plan, null), try plan(&.{.{ .slot = 0, .base = 4, .end = 20 }}, 12, 24, 4));
    try std.testing.expectError(error.BadExtents, plan(&.{ .{ .slot = 0, .base = 4, .end = 12 }, .{ .slot = 1, .base = 8, .end = 16 } }, 4, 24, 4));
    try std.testing.expectError(error.BadExtents, plan(&.{ .{ .slot = 0, .base = 0, .end = 4 }, .{ .slot = 0, .base = 8, .end = 12 } }, 4, 24, 4));
}

test "32 complete 262k reservations fit the independent shared pool" {
    var extents: [max_items]Extent = undefined;
    const reserve = std.mem.alignForward(usize, 262144 + 48 + 2, 2048);
    for (&extents, 0..) |*extent, i| extent.* = .{ .slot = i, .base = i * reserve, .end = (i + 1) * reserve };
    const p = (try plan(&extents, 0, 8650752, 2048)).?;
    try std.testing.expectEqual(@as(usize, 32), p.count);
    try std.testing.expect(p.end <= 8650752);
    try std.testing.expectEqual(@as(?Plan, null), try plan(&extents, reserve, 8650752, 2048));
}
