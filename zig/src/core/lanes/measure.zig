//! Opt-in, bounded timing counters. No extra GPU synchronization is required.
//! HTTP readers use atomic counters; detailed tables are returned only at idle.
//! Independent counters are not a transactional snapshot during active work.
const std = @import("std");
const Counter = std.atomic.Value(u64);

pub const contexts = 4;
pub const cohorts = 7;
pub const widths = 49;
pub const pass_widths = 17;
pub const depths = 6;

pub fn contextBucket(tokens: usize) usize {
    return if (tokens <= 8192) 0 else if (tokens <= 32768) 1 else if (tokens <= 262144) 2 else 3;
}

pub fn liveBucket(streams: usize) usize {
    return if (streams <= 1) 0 else if (streams <= 4) 1 else if (streams <= 8) 2 else if (streams <= 16) 3 else if (streams <= 24) 4 else if (streams < 32) 5 else 6;
}

pub const Summary = struct {
    send_ns: u64 = 0,
    verify_ns: u64 = 0,
    logits_ns: u64 = 0,
    sample_ns: u64 = 0,
    draft_send_ns: u64 = 0,
    draft_ns: u64 = 0,
    generated_proposals: u64 = 0,
    held_proposals: u64 = 0,
    draft_hidden_rows: u64 = 0, // the fixed drafter block, including unreturned positions
    shared_round_ns: u64 = 0,
    shared_rounds: u64 = 0,
    shared_backend_ns: u64 = 0,
    shared_other_ns: u64 = 0, // planning, acceptance, bookkeeping and callback overhead
    verify_capture_rounds: u64 = 0,
    draft_capture_passes: u64 = 0,
};

pub const Snapshot = struct {
    context_upper_bounds: [contexts]u64 = .{ 8192, 32768, 262144, 1048576 },
    stream_ranges: [cohorts][2]u64 = .{ .{ 1, 1 }, .{ 2, 4 }, .{ 5, 8 }, .{ 9, 16 }, .{ 17, 24 }, .{ 25, 31 }, .{ 32, 32 } },
    verify_count: [contexts][cohorts][widths]u64 = @splat(@splat(@splat(0))),
    verify_ns: [contexts][cohorts][widths]u64 = @splat(@splat(@splat(0))),
    draft_count: [pass_widths][depths]u64 = @splat(@splat(0)),
    draft_ns: [pass_widths][depths]u64 = @splat(@splat(0)),
};

pub const Measurements = struct {
    totals: [@typeInfo(Summary).@"struct".field_names.len]Counter = @splat(Counter.init(0)),
    verify_count: [contexts][cohorts][widths]Counter = @splat(@splat(@splat(Counter.init(0)))),
    verify_ns: [contexts][cohorts][widths]Counter = @splat(@splat(@splat(Counter.init(0)))),
    draft_count: [pass_widths][depths]Counter = @splat(@splat(Counter.init(0))),
    draft_ns: [pass_widths][depths]Counter = @splat(@splat(Counter.init(0))),

    pub fn add(m: *Measurements, values: Summary) void {
        inline for (@typeInfo(Summary).@"struct".field_names, 0..) |name, i| {
            const v = @field(values, name);
            if (v != 0) _ = m.totals[i].fetchAdd(v, .monotonic);
        }
    }

    pub fn verify(m: *Measurements, tokens: usize, streams: usize, rows: usize, ns: u64, captured: bool) void {
        if (captured) {
            m.add(.{ .verify_capture_rounds = 1 });
            return;
        }
        if (rows == 0 or rows >= widths) return;
        const bucket = contextBucket(tokens);
        const live = liveBucket(streams);
        _ = m.verify_ns[bucket][live][rows].fetchAdd(ns, .monotonic);
        _ = m.verify_count[bucket][live][rows].fetchAdd(1, .monotonic);
    }

    pub fn draft(m: *Measurements, streams: usize, steps: usize, ns: u64, captured: bool) void {
        if (captured) {
            m.add(.{ .draft_capture_passes = 1 });
            return;
        }
        if (streams == 0 or streams >= pass_widths or steps == 0 or steps >= depths) return;
        _ = m.draft_ns[streams][steps].fetchAdd(ns, .monotonic);
        _ = m.draft_count[streams][steps].fetchAdd(1, .monotonic);
    }

    pub fn summary(m: *const Measurements) Summary {
        var out: Summary = .{};
        inline for (@typeInfo(Summary).@"struct".field_names, 0..) |name, i|
            @field(out, name) = m.totals[i].load(.monotonic);
        return out;
    }

    pub fn snapshot(m: *const Measurements) Snapshot {
        var out: Snapshot = .{};
        for (0..contexts) |c| {
            for (0..cohorts) |s| for (0..widths) |w| {
                out.verify_count[c][s][w] = m.verify_count[c][s][w].load(.monotonic);
                out.verify_ns[c][s][w] = m.verify_ns[c][s][w].load(.monotonic);
            };
        }
        for (0..pass_widths) |s| for (0..depths) |d| {
            out.draft_count[s][d] = m.draft_count[s][d].load(.monotonic);
            out.draft_ns[s][d] = m.draft_ns[s][d].load(.monotonic);
        };
        return out;
    }
};

test "cost measurements separate width and context and exclude graph construction" {
    var m: Measurements = .{};
    m.verify(8192, 32, 32, 100, false);
    m.verify(8193, 32, 32, 200, false);
    m.verify(32769, 32, 48, 300, false);
    m.verify(1048576, 32, 48, 400, false);
    m.verify(1048576, 31, 48, 500, false);
    m.verify(1048576, 32, 48, 9999, true);
    m.verify(0, 32, 49, 9999, false);
    const s = m.snapshot();
    try std.testing.expectEqual(@as(u64, 100), s.verify_ns[0][6][32]);
    try std.testing.expectEqual(@as(u64, 200), s.verify_ns[1][6][32]);
    try std.testing.expectEqual(@as(u64, 300), s.verify_ns[2][6][48]);
    try std.testing.expectEqual(@as(u64, 400), s.verify_ns[3][6][48]);
    try std.testing.expectEqual(@as(u64, 500), s.verify_ns[3][5][48]);
    try std.testing.expectEqual(@as(u64, 1), s.verify_count[3][6][48]);
    try std.testing.expectEqual(@as(u64, 1), m.summary().verify_capture_rounds);
}

test "draft work counts generated proposals separately from retained proposals" {
    var m: Measurements = .{};
    m.add(.{ .generated_proposals = 48, .held_proposals = 20, .draft_ns = 170 });
    m.add(.{ .generated_proposals = 48, .held_proposals = 22, .draft_ns = 180 });
    m.draft(16, 3, 170, false);
    m.draft(16, 3, 180, false);
    m.draft(16, 3, 9999, true);
    const s = m.snapshot();
    try std.testing.expectEqual(@as(u64, 96), m.summary().generated_proposals);
    try std.testing.expectEqual(@as(u64, 42), m.summary().held_proposals);
    try std.testing.expectEqual(@as(u64, 2), s.draft_count[16][3]);
    try std.testing.expectEqual(@as(u64, 350), s.draft_ns[16][3]);
    try std.testing.expectEqual(@as(u64, 1), m.summary().draft_capture_passes);
}
