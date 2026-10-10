const std = @import("std");
const lanes = @import("lanes");
const api = @import("engine_api.zig");
const pc = @import("prompt_cache.zig");
const LaneHost = @import("lane_host.zig").LaneHost;
const a = std.testing.allocator;

const Box = struct {
    done: std.atomic.Value(bool) = .init(false),
    prefilled: std.atomic.Value(bool) = .init(false),
    other_prefilled: ?*std.atomic.Value(bool) = null,
    finished_before_other: bool = false,
    reason: api.Reason = .failed,
    cached: u32 = 0,
    tokens: std.ArrayList(u32) = .empty,

    fn event(ptr: *anyopaque, _: api.Id, value: *const api.Event) void {
        const b: *@This() = @ptrCast(@alignCast(ptr));
        switch (value.*) {
            .prefilled => |cached| {
                b.cached = cached;
                b.prefilled.store(true, .release);
            },
            .tokens => |tokens| b.tokens.appendSlice(a, tokens) catch unreachable,
            .finished => |finished| {
                b.reason = finished.reason;
                if (b.other_prefilled) |other| b.finished_before_other = !other.load(.acquire);
                b.done.store(true, .release);
            },
            else => {},
        }
    }

    fn sink(b: *@This()) api.Sink {
        return .{ .ctx = b, .event = event };
    }

    fn wait(b: *@This()) !void {
        for (0..5000) |_| {
            if (b.done.load(.acquire)) return;
            try std.Io.sleep(std.testing.io, .fromMilliseconds(1), .awake);
        }
        return error.TestTimedOut;
    }

    fn check(b: *@This(), prompt: []const u32, count: usize) !void {
        try b.wait();
        try std.testing.expectEqual(api.Reason.length, b.reason);
        try std.testing.expectEqual(count, b.tokens.items.len);
        var history: std.ArrayList(u32) = .empty;
        defer history.deinit(a);
        try history.appendSlice(a, prompt);
        for (b.tokens.items) |token| {
            try std.testing.expectEqual(lanes.fake.next(history.items, null, history.items.len), token);
            try history.append(a, token);
        }
    }
};

test "a short arrival finishes while a long prompt is still filling" {
    var cfg = try lanes.Config.init(a, .{ .exact_width = 8, .gpu_tokens = true, .hidden_rows = true }, 8, 7);
    defer cfg.deinit(a);
    var target: lanes.fake.Fake = .{ .gpa = a };
    defer target.deinit();
    var clock: lanes.fake.FixedClock = .{};
    var core = lanes.Engine.init(a, &cfg, target.incrementalBackend(), clock.clock());
    defer core.deinit();
    var host = LaneHost.init(a, std.testing.io, &core, .{ .lanes = 2 });
    var long: Box = .{};
    defer long.tokens.deinit(a);
    var short: Box = .{ .other_prefilled = &long.prefilled };
    defer short.tokens.deinit(a);
    const long_prompt: [64]u32 = @splat(7);
    const short_prompt = [_]u32{ 11, 5 };
    const long_request: api.Request = .{ .prompt = &long_prompt, .max_tokens = 8, .drafts = false };
    const short_request: api.Request = .{ .prompt = &short_prompt, .max_tokens = 3, .drafts = false };
    const Arrival = struct {
        engine: api.Engine,
        request: *const api.Request,
        box: *Box,
        once: bool = false,
        fn chunk(ptr: *anyopaque, s: *lanes.Stream, _: usize) void {
            const x: *@This() = @ptrCast(@alignCast(ptr));
            if (s.prompt_len != 64 or x.once) return;
            x.once = true;
            x.engine.submit(2, x.request, x.box.sink()) catch unreachable;
        }
    };
    var arrival: Arrival = .{ .engine = host.engine(), .request = &short_request, .box = &short };
    target.prefill_hook = Arrival.chunk;
    target.prefill_hook_ctx = &arrival;
    try host.engine().submit(1, &long_request, long.sink());
    try host.start();
    defer host.stop();
    try short.check(&short_prompt, 3);
    try long.check(&long_prompt, 8);
    try std.testing.expect(short.finished_before_other);
}

test "cancellation during incremental prefill releases the lane and permits follow-up" {
    var cfg = try lanes.Config.init(a, .{ .exact_width = 8, .gpu_tokens = true, .hidden_rows = true }, 8, 7);
    defer cfg.deinit(a);
    var target: lanes.fake.Fake = .{ .gpa = a };
    defer target.deinit();
    var clock: lanes.fake.FixedClock = .{};
    var core = lanes.Engine.init(a, &cfg, target.incrementalBackend(), clock.clock());
    defer core.deinit();
    var host = LaneHost.init(a, std.testing.io, &core, .{ .lanes = 1 });
    var cancelled: Box = .{};
    defer cancelled.tokens.deinit(a);
    var follow: Box = .{};
    defer follow.tokens.deinit(a);
    const prompt: [64]u32 = @splat(9);
    const tail = [_]u32{ 2, 5 };
    const request: api.Request = .{ .prompt = &prompt, .max_tokens = 8, .drafts = false };
    const follow_request: api.Request = .{ .prompt = &tail, .max_tokens = 4, .drafts = false };
    const Cancel = struct {
        engine: api.Engine,
        fn chunk(ptr: *anyopaque, s: *lanes.Stream, _: usize) void {
            const x: *@This() = @ptrCast(@alignCast(ptr));
            if (s.prompt_len == 64) x.engine.cancel(1);
        }
    };
    var cancel: Cancel = .{ .engine = host.engine() };
    target.prefill_hook = Cancel.chunk;
    target.prefill_hook_ctx = &cancel;
    try host.engine().submit(1, &request, cancelled.sink());
    try host.engine().submit(2, &follow_request, follow.sink());
    try host.start();
    defer host.stop();
    try cancelled.wait();
    try std.testing.expectEqual(api.Reason.cancelled, cancelled.reason);
    try std.testing.expectEqual(@as(usize, 0), cancelled.tokens.items.len);
    try follow.check(&tail, 4);
    try std.testing.expectEqual(@as(usize, 0), target.lanes.count());
}

test "capacity waits for unfinished prefills even when no stream is decoding" {
    var cfg = try lanes.Config.init(a, .{ .exact_width = 8, .gpu_tokens = true, .hidden_rows = true }, 8, 7);
    defer cfg.deinit(a);
    var target: lanes.fake.Fake = .{ .gpa = a, .incremental_capacity = 2 };
    defer target.deinit();
    var clock: lanes.fake.FixedClock = .{};
    var core = lanes.Engine.init(a, &cfg, target.incrementalBackend(), clock.clock());
    defer core.deinit();
    var host = LaneHost.init(a, std.testing.io, &core, .{ .lanes = 4 });
    var boxes: [3]Box = @splat(.{});
    defer for (&boxes) |*box| box.tokens.deinit(a);
    const prompt: [32]u32 = @splat(3);
    const request: api.Request = .{ .prompt = &prompt, .max_tokens = 1, .drafts = false };
    for (&boxes, 1..) |*box, id| try host.engine().submit(id, &request, box.sink());
    try host.start();
    defer host.stop();
    for (&boxes) |*box| try box.check(&prompt, 1);
    try std.testing.expect(target.incremental_refusals > 0);
    try std.testing.expectEqual(@as(usize, 0), target.lanes.count());
}

test "another filling prompt may evict a restored prefix before its owner finishes" {
    var cfg = try lanes.Config.init(a, .{ .exact_width = 8, .gpu_tokens = true, .hidden_rows = true }, 8, 7);
    defer cfg.deinit(a);
    var target: lanes.fake.Fake = .{ .gpa = a };
    defer target.deinit();
    var clock: lanes.fake.FixedClock = .{};
    var core = lanes.Engine.init(a, &cfg, target.incrementalBackend(), clock.clock());
    defer core.deinit();
    const Snaps = struct {
        fn bytes(_: *anyopaque, at: u32) u64 {
            return 64 + 4 * @as(u64, at);
        }
        fn save(ptr: *anyopaque, owner: ?*anyopaque, at: u32) anyerror!pc.Saved {
            const fake: *lanes.fake.Fake = @ptrCast(@alignCast(ptr));
            return fake.save(@ptrCast(@alignCast(owner.?)), at);
        }
        fn restore(_: *anyopaque, _: ?*anyopaque, _: pc.Saved) anyerror!void {
            return error.BackendRestores;
        }
        fn drop(ptr: *anyopaque, saved: pc.Saved) void {
            const fake: *lanes.fake.Fake = @ptrCast(@alignCast(ptr));
            fake.drop(saved);
        }
    };
    var store = pc.Store.init(a, .{ .ptr = &target, .vtable = &.{ .bytes = Snaps.bytes, .save = Snaps.save, .restore = Snaps.restore, .drop = Snaps.drop } }, .{ .min_gap = 1, .min_prompt = 0, .max_entries = 1 }, 1 << 20);
    defer store.deinit();
    const long_prompt: [64]u32 = @splat(7);
    var warm = try lanes.Stream.init(a, .{ .id = "warm", .prompt = long_prompt[0..8], .max_new = 1 });
    defer warm.deinit(a);
    try target.backend().prefill(&warm);
    try std.testing.expect(store.keep(&long_prompt, 8, &warm, &.{}));
    target.backend().release(&warm);
    var host = LaneHost.init(a, std.testing.io, &core, .{ .lanes = 2 });
    host.cache = &store;
    var long: Box = .{};
    defer long.tokens.deinit(a);
    var short: Box = .{ .other_prefilled = &long.prefilled };
    defer short.tokens.deinit(a);
    const short_prompt = [_]u32{ 11, 5 };
    const long_request: api.Request = .{ .prompt = &long_prompt, .max_tokens = 8, .drafts = false };
    const short_request: api.Request = .{ .prompt = &short_prompt, .max_tokens = 3, .history_len = 1, .drafts = false };
    try host.engine().submit(1, &long_request, long.sink());
    try host.engine().submit(2, &short_request, short.sink());
    try host.start();
    defer host.stop();
    try short.check(&short_prompt, 3);
    try long.check(&long_prompt, 8);
    try std.testing.expect(short.finished_before_other);
    try std.testing.expectEqual(@as(u32, 8), long.cached);
    try std.testing.expectEqual(@as(u64, 1), store.counts.hits);
    try std.testing.expectEqual(@as(u64, 1), store.counts.evicted);
}
