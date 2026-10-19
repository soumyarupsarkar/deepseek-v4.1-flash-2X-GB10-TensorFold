//! Prepare the native loader's rank cache from the verified checkpoint, CPU only.
//! A failed write stays .partial for inspection. Completed files are never replaced.
const std = @import("std");
const ds = @import("dsv41");

fn nameOf(dtype: ds.rank_cache.DType) []const u8 {
    return switch (dtype) {
        .bf16 => "bfloat16",
        .f16 => "float16",
        .f32 => "float32",
        .i16 => "int16",
        .i32 => "int32",
        .i64 => "int64",
        .u8 => "uint8",
        .f8e4m3 => "float8_e4m3fn",
    };
}

pub fn main(init: std.process.Init) !u8 {
    const a = init.arena.allocator();
    const io = init.io;
    const args = try init.minimal.args.toSlice(a);
    const overlay_dir: ?[]const u8 = if (args.len == 8 and std.mem.eql(u8, args[6], "--keys-overlay")) args[7] else null;
    if (args.len != 6 and overlay_dir == null) {
        std.debug.print("usage: tf-dsv41-prepare MODEL_DIR CACHE_DIR RANK WORLD INPUT_SHA256 [--keys-overlay SIDECAR_DIR]\n", .{});
        return 2;
    }
    const rank = try std.fmt.parseInt(u32, args[3], 10);
    const world = try std.fmt.parseInt(u32, args[4], 10);
    if (world != 2 or rank >= world) return error.BadSplit;
    const key = args[5];
    if (key.len != 64) return error.BadInputDigest;
    for (key) |c| if (!(c >= '0' and c <= '9') and !(c >= 'a' and c <= 'f')) return error.BadInputDigest;
    var dir = try std.Io.Dir.cwd().openDir(io, args[2], .{ .iterate = true });
    defer dir.close(io);
    if (ds.rank_cache.find(a, io, dir, rank, world)) |_| {
        return error.RankCacheAlreadyExists;
    } else |err| if (err != error.NoRankCache) return err;
    const cfg = try ds.Config.read(a, io, args[1]);
    const want = if (overlay_dir != null) try ds.weight_overlay.wants(a, rank, world) else
        try ds.plan.wants(a, cfg, .{ .rank = rank, .world = world }, true);
    var shards = try ds.checkpoint.Shards.open(init.gpa, io, overlay_dir orelse args[1]);
    defer shards.close(io);
    const name = try std.fmt.allocPrint(a, "rank{d}of{d}-native-{s}.bin", .{ rank, world, key });
    const partial = try std.fmt.allocPrint(a, "{s}.partial", .{name});
    var file = try dir.createFile(io, partial, .{ .exclusive = true });
    defer file.close(io);
    var buffer: std.ArrayList(u8) = .empty;
    defer buffer.deinit(init.gpa);
    var index: std.Io.Writer.Allocating = .init(init.gpa);
    defer index.deinit();
    const w = &index.writer;
    try w.writeByte('[');
    var at: u64 = 0;
    for (want, 0..) |entry, i| {
        const slice = try ds.checkpoint.describe(&shards, entry.key);
        if (entry.dtype) |d| if (slice.dtype != d) return error.UnexpectedDType;
        if (entry.k16) |k| if (slice.shape[0] != k) return error.UnexpectedShape;
        if (entry.n16) |n| if (slice.shape[1] != n) return error.UnexpectedShape;
        try buffer.resize(init.gpa, slice.bytes);
        try ds.checkpoint.read(&shards, entry.key, buffer.items);
        try file.writePositionalAll(io, buffer.items, at);
        if (i != 0) try w.writeByte(',');
        try std.json.Stringify.value(.{ entry.key, nameOf(slice.dtype), slice.shape[0..slice.rank], at, slice.bytes }, .{}, w);
        at = try std.math.add(u64, at, slice.bytes);
    }
    try w.writeByte(']');
    try file.writePositionalAll(io, index.written(), at);
    var footer: [16]u8 = undefined;
    std.mem.writeInt(u64, footer[0..8], at, .little);
    @memcpy(footer[8..], ds.rank_cache.magic);
    try file.writePositionalAll(io, &footer, at + index.written().len);
    try file.sync(io);
    // Use the real reader to validate the complete index before publication.
    var checked = try ds.rank_cache.open(init.gpa, io, dir, partial);
    defer checked.deinit();
    if (checked.entries.count() != want.len or checked.data_end != at) return error.BadPreparedCache;
    try dir.renamePreserve(partial, dir, name, io);
    if (std.c.fsync(dir.handle) != 0) return error.DirectorySyncFailed;
    std.debug.print("prepared rank {d}/{d}: {d} tensors, {d} tensor bytes; {s}\n", .{ rank, world, want.len, at, name });
    return 0;
}
