//! Walk verified rows under the existing xgrammar gate. Adapted from the path
//! approach in MiaAI-Lab PR85 (markyu0401); compiler and schema support stay local.
const std = @import("std");
const accept = @import("accept.zig");
const be = @import("backend.zig");
const Stream = @import("stream.zig").Stream;
const Redraw = *const fn (*anyopaque, *Stream, u32, u32, u64, []const u32) anyerror!u32;

pub const Path = struct { rows: []u32, last: u32, redrawn: bool = false };

pub fn active(b: be.Backend, s: *const Stream) bool {
    return b.vtable.redraw != null and s.logit_gate != null and s.logit_gate.?.preview != null;
}

pub fn path(a: std.mem.Allocator, b: be.Backend, s: *Stream, window: u32, sampled: []const u32, tokens: []const u32, parents: []const i32, positions: []const u64) !Path {
    if (!active(b, s)) {
        const rows = try accept.acceptPath(a, tokens, parents, sampled);
        return .{ .rows = rows, .last = sampled[rows[rows.len - 1]] };
    }
    return walk(a, b.ptr, b.vtable.redraw.?, s, window, tokens, parents, positions);
}

fn walk(a: std.mem.Allocator, ctx: *anyopaque, redraw: Redraw, s: *Stream, window: u32, tokens: []const u32, parents: []const i32, positions: []const u64) !Path {
    var rows: std.ArrayList(u32) = .empty;
    errdefer rows.deinit(a);
    var prefix: std.ArrayList(u32) = .empty;
    defer prefix.deinit(a);
    try rows.append(a, 0);
    while (true) {
        const at = rows.items[rows.items.len - 1];
        const want = try redraw(ctx, s, window, at, positions[at], prefix.items);
        // Never ask the grammar for a token after EOS. The engine still applies
        // length, stop strings and forced thinking cuts to this accepted path.
        const next = if (s.isEos(want)) null else for (parents, 0..) |p, row| {
            if (p == @as(i32, @intCast(at)) and tokens[row] == want) break @as(?usize, row);
        } else null;
        if (next) |row| {
            try prefix.append(a, want);
            try rows.append(a, @intCast(row));
        } else return .{ .rows = try rows.toOwnedSlice(a), .last = want, .redrawn = true };
    }
}

pub fn tail(b: be.Backend, s: *Stream, window: u32, forced: []const u32, sampled: []const u32, positions: []const u64) !u32 {
    const last: u32 = @intCast(sampled.len - 1);
    if (!active(b, s)) return sampled[last];
    return b.vtable.redraw.?(b.ptr, s, window, last, positions[last], forced);
}

test "constrained paths redraw only matching prefixes and stop before grammar termination" {
    const a = std.testing.allocator;
    const Probe = struct {
        picks: []const u32,
        calls: usize = 0,
        fn redraw(ctx: *anyopaque, s: *Stream, window: u32, row: u32, position: u64, prefix: []const u32) !u32 {
            const self: *@This() = @ptrCast(@alignCast(ctx));
            try std.testing.expectEqual(@as(u32, 3), window);
            try std.testing.expectEqual(@as(u64, 100 + row), position);
            try std.testing.expectEqualSlices(u32, self.picks[0..row], prefix);
            try std.testing.expectEqualSlices(u32, &.{8}, s.emitted());
            self.calls += 1;
            return self.picks[row];
        }
    };
    var s = try Stream.init(a, .{ .id = "grammar", .prompt = &.{4}, .max_new = 20, .eos = &.{99} });
    defer s.deinit(a);
    _ = try s.commit(a, &.{8});
    for ([_]struct { picks: []const u32, rows: []const u32, last: u32 }{
        .{ .picks = &.{ 10, 11, 12 }, .rows = &.{ 0, 1, 2 }, .last = 12 },
        .{ .picks = &.{ 10, 77 }, .rows = &.{ 0, 1 }, .last = 77 },
        .{ .picks = &.{99}, .rows = &.{0}, .last = 99 },
    }) |c| {
        var probe: Probe = .{ .picks = c.picks };
        const got = try walk(a, &probe, Probe.redraw, &s, 3, &.{ 8, 10, 11 }, &.{ -1, 0, 1 }, &.{ 100, 101, 102 });
        defer a.free(got.rows);
        try std.testing.expectEqualSlices(u32, c.rows, got.rows);
        try std.testing.expectEqual(c.last, got.last);
        try std.testing.expectEqual(c.rows.len, probe.calls);
        try std.testing.expect(got.redrawn);
    }
}
