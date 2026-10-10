//! Check every supported backbone router width against independent one-row GPU
//! launches. Synthetic tensors only; the model is not loaded.
const std = @import("std");
const cuda = @import("cuda");
const ds = @import("dsv41");

pub fn main(init: std.process.Init) !u8 {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len != 2) return error.ExpectedAotDirectory;
    var driver = try cuda.Driver.open();
    defer driver.close();
    var ctx = try cuda.Context.init(&driver, 0);
    defer ctx.deinit();
    var stream = try cuda.Stream.init(&driver, true);
    defer stream.deinit();
    var set = try cuda.aot.Set.load(init.gpa, init.io, &driver, ctx.device, args[1]);
    defer set.deinit();
    const t: ds.tri.Tri = .{ .set = &set, .stream = stream };
    ds.tri.decode_rows = 48;
    const rows = 48;
    const k = 5120;
    const n = 384;
    const kc = k / 256;
    const slots = 7;
    const hx = try a.alloc(u16, rows * k);
    for (hx, 0..) |*v, i| {
        const value: f32 = @as(f32, @floatFromInt(@as(i32, @intCast((i * 13 + i / k * 7) % 127)) - 63)) / 64;
        v.* = @intCast(@as(u32, @bitCast(value)) >> 16);
    }
    const hw = try a.alloc(f16, n * k);
    for (hw, 0..) |*v, i| v.* = @floatCast(@as(f32, @floatFromInt(@as(i32, @intCast((i * 7 + i / k * 11) % 31)) - 15)) / 32);
    const hb = try a.alloc(f32, n);
    for (hb, 0..) |*v, i| v.* = @as(f32, @floatFromInt(i % 19)) / 128;
    var x = try cuda.DeviceBuffer.fromHost(&driver, std.mem.sliceAsBytes(hx));
    defer x.free();
    var w = try cuda.DeviceBuffer.fromHost(&driver, std.mem.sliceAsBytes(hw));
    defer w.free();
    var bias = try cuda.DeviceBuffer.fromHost(&driver, std.mem.sliceAsBytes(hb));
    defer bias.free();
    var reference = try cuda.DeviceBuffer.alloc(&driver, rows * kc * n * 4);
    defer reference.free();
    var output = try cuda.DeviceBuffer.alloc(&driver, (rows + 1) * kc * n * 4);
    defer output.free();
    var picks = try cuda.DeviceBuffer.alloc(&driver, rows * slots * 4);
    defer picks.free();
    var weights = try cuda.DeviceBuffer.alloc(&driver, rows * slots * 4);
    defer weights.free();
    for (0..rows) |r| {
        if (try ds.tri_norm.rowmmGate(t, x.ptr + r * k * 2, k, w.ptr, reference.ptr + r * kc * n * 4, 1, k, n) != kc) return error.WrongLayout;
    }
    try ds.tri_norm.route(t, reference.ptr, kc, bias.ptr, 6, 1.0, n, picks.ptr, weights.ptr, rows, n, slots);
    try stream.synchronize();
    const expected = try a.alloc(u32, rows * kc * n);
    const expected_picks = try a.alloc(u32, rows * slots);
    const expected_weights = try a.alloc(u32, rows * slots);
    try reference.download(0, std.mem.sliceAsBytes(expected));
    try picks.download(0, std.mem.sliceAsBytes(expected_picks));
    try weights.download(0, std.mem.sliceAsBytes(expected_weights));
    const actual = try a.alloc(u32, (rows + 1) * kc * n);
    const actual_picks = try a.alloc(u32, rows * slots);
    const actual_weights = try a.alloc(u32, rows * slots);
    var compared: usize = 0;
    for (1..rows + 1) |count| {
        errdefer std.debug.print("router width {d} failed\n", .{count});
        try output.fill32(0x7fc12345, null);
        if (try ds.tri_norm.rowmmGate(t, x.ptr, k, w.ptr, output.ptr, count, k, n) != kc) return error.WrongLayout;
        try ds.tri_norm.route(t, output.ptr, kc, bias.ptr, 6, 1.0, n, picks.ptr, weights.ptr, count, n, slots);
        try stream.synchronize();
        try output.download(0, std.mem.sliceAsBytes(actual));
        try picks.download(0, std.mem.sliceAsBytes(actual_picks));
        try weights.download(0, std.mem.sliceAsBytes(actual_weights));
        const used = count * kc * n;
        if (!std.mem.eql(u32, expected[0..used], actual[0..used])) return error.PartialsDiffer;
        if (!std.mem.eql(u32, expected_picks[0 .. count * slots], actual_picks[0 .. count * slots])) return error.PicksDiffer;
        if (!std.mem.eql(u32, expected_weights[0 .. count * slots], actual_weights[0 .. count * slots])) return error.WeightsDiffer;
        for (actual[used..]) |word| if (word != 0x7fc12345) return error.WritePastLastRow;
        compared += used + 2 * count * slots;
    }
    var buf: [1024]u8 = undefined;
    var out = std.Io.File.stdout().writer(init.io, &buf);
    try out.interface.print("{{\"ok\":true,\"widths\":48,\"compared_words\":{d},\"mismatches\":0}}\n", .{compared});
    try out.interface.flush();
    return 0;
}
