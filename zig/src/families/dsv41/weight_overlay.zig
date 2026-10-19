//! Optional 1017 Keys replacements over an immutable stock TP2 rank cache.
//! The complete base remains authoritative for all but L10-35 attention wo_b.
//! This is deliberately a narrow format, not an arbitrary tensor override.
const std = @import("std");
const cache = @import("rank_cache.zig");
const plan = @import("plan.zig");

pub const entry_count = 26 * 3;
pub const extra_bytes_per_rank = 65 * 1024 * 1024;

pub fn wants(a: std.mem.Allocator, rank: u32, world: u32) ![]plan.Want {
    if (world != 2 or rank >= world) return error.UnsupportedWeightOverlaySplit;
    const out = try a.alloc(plan.Want, entry_count);
    var n: usize = 0;
    for (10..36) |layer| {
        const prefix = try std.fmt.allocPrint(a, "layers.{d}.attn.wo_b", .{layer});
        defer a.free(prefix);
        for ([_][]const u8{ "tr", "suh", "svh" }) |part| {
            var buf: [256]u8 = undefined;
            const key = try plan.partKey(&buf, prefix, null, .{ rank * 4096, (rank + 1) * 4096 }, part);
            const tr = std.mem.eql(u8, part, "tr");
            out[n] = .{ .key = try a.dupe(u8, key), .dtype = if (tr) .i16 else .f16,
                .k16 = if (tr) 256 else null, .n16 = if (tr) 320 else null };
            n += 1;
        }
    }
    return out;
}

/// Both indexes have already passed rank_cache's offset/size/duplicate checks.
/// Require all 78 entries, exactly the expected TP2 slices and K5 -> K6 change.
pub fn validate(a: std.mem.Allocator, base: *const cache.Index, overlay: *const cache.Index, rank: u32, world: u32) !void {
    const expected = try wants(a, rank, world);
    defer {
        for (expected) |entry| a.free(entry.key);
        a.free(expected);
    }
    if (overlay.entries.count() != entry_count) return error.IncompleteWeightOverlay;
    for (expected, overlay.entries.keys()) |want, key| {
        if (!std.mem.eql(u8, want.key, key)) return error.UnexpectedWeightOverlayKey;
        const old = base.get(key) orelse return error.WeightOverlayBaseMissing;
        const replacement = overlay.get(key).?;
        if (old.dtype != want.dtype.? or replacement.dtype != old.dtype) return error.WeightOverlayDType;
        if (want.k16 != null) {
            if (old.rank != 3 or replacement.rank != 3 or
                !std.mem.eql(usize, old.shape[0..3], &.{ 256, 320, 80 }) or
                !std.mem.eql(usize, replacement.shape[0..3], &.{ 256, 320, 96 }))
                return error.WeightOverlayShape;
        } else {
            const width: usize = if (std.mem.endsWith(u8, key, "|suh")) 4096 else 5120;
            if (old.rank != 1 or replacement.rank != 1 or old.shape[0] != width or replacement.shape[0] != width)
                return error.WeightOverlayShape;
        }
    }
}

/// Kept open only during upload. Replacement bytes never overwrite base files.
pub const Opened = struct {
    dir: std.Io.Dir,
    file: std.Io.File,
    index: cache.Index,

    pub fn open(a: std.mem.Allocator, io: std.Io, path: []const u8, base: *const cache.Index, rank: u32, world: u32) !Opened {
        var dir = try std.Io.Dir.cwd().openDir(io, path, .{ .iterate = true });
        errdefer dir.close(io);
        const name = try cache.find(a, io, dir, rank, world);
        defer a.free(name);
        var ix = try cache.open(a, io, dir, name);
        errdefer ix.deinit();
        try validate(a, base, &ix, rank, world);
        const file = try dir.openFile(io, name, .{});
        return .{ .dir = dir, .file = file, .index = ix };
    }

    pub fn close(o: *Opened, io: std.Io) void {
        o.file.close(io);
        o.index.deinit();
        o.dir.close(io);
        o.* = undefined;
    }
};

test "Keys overlay accepts only the complete pinned K5 to K6 TP2 scope" {
    const a = std.testing.allocator;
    var arena = std.heap.ArenaAllocator.init(a);
    defer arena.deinit();
    const temp = arena.allocator();
    for (0..2) |rank| {
        const expected = try wants(temp, @intCast(rank), 2);
        var base: cache.Index = .{ .arena = std.heap.ArenaAllocator.init(a), .entries = .empty, .data_end = 0 };
        defer base.deinit();
        var over: cache.Index = .{ .arena = std.heap.ArenaAllocator.init(a), .entries = .empty, .data_end = 0 };
        defer over.deinit();
        for (expected) |want| {
            const tr = want.k16 != null;
            const width: usize = if (std.mem.endsWith(u8, want.key, "|suh")) 4096 else 5120;
            const e: cache.Entry = .{ .dtype = want.dtype.?, .rank = if (tr) 3 else 1,
                .shape = if (tr) .{ 256, 320, 80, 1 } else .{ width, 1, 1, 1 }, .offset = 0, .bytes = 0 };
            try base.entries.put(base.arena.allocator(), want.key, e);
            var r = e;
            if (tr) r.shape[2] = 96;
            try over.entries.put(over.arena.allocator(), want.key, r);
        }
        try validate(a, &base, &over, @intCast(rank), 2);
        try std.testing.expectError(error.UnexpectedWeightOverlayKey, validate(a, &base, &over, @intCast(1 - rank), 2));
        over.entries.values()[0].shape[2] = 80;
        try std.testing.expectError(error.WeightOverlayShape, validate(a, &base, &over, @intCast(rank), 2));
        over.entries.values()[0].shape[2] = 96;
        over.entries.values()[1].dtype = .f32;
        try std.testing.expectError(error.WeightOverlayDType, validate(a, &base, &over, @intCast(rank), 2));
        over.entries.values()[1].dtype = .f16;
        _ = over.entries.orderedRemove(expected[0].key);
        try std.testing.expectError(error.IncompleteWeightOverlay, validate(a, &base, &over, @intCast(rank), 2));
    }
    try std.testing.expectError(error.UnsupportedWeightOverlaySplit, wants(a, 0, 4));
}
