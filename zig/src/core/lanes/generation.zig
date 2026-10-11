//! An empirical guard for draft generation in shared rounds. Each caller-owned
//! cell represents one comparable workload shape. It measures committed tokens
//! per wall time, including verification and generating the next round's drafts.
//! Mixed transition rounds and graph construction must not be observed.
const std = @import("std");

pub const Mode = enum(u1) { plain, draft };

pub const Stamp = struct { key: usize, mode: Mode };

/// A round can price a mode only if every eligible stream's incoming proposals
/// came from that same mode and workload cell. This excludes transition rounds.
pub const Trace = struct {
    key: usize,
    incoming: ?Mode = null,
    eligible: usize = 0,
    stable: bool = true,

    pub fn include(t: *Trace, stamp: ?Stamp) void {
        t.eligible += 1;
        const s = stamp orelse {
            t.stable = false;
            return;
        };
        if (s.key != t.key) t.stable = false;
        if (t.incoming) |mode| {
            if (s.mode != mode) t.stable = false;
        } else t.incoming = s.mode;
    }

    pub fn permits(t: Trace, outgoing: Mode) bool {
        return t.eligible > 0 and t.stable and t.incoming == outgoing;
    }
};

pub const Rate = struct {
    rounds: u64 = 0,
    tokens_per_ms: f64 = 0,

    fn add(r: *Rate, tokens: usize, ns: u64) void {
        const value = @as(f64, @floatFromInt(tokens)) * 1e6 / @as(f64, @floatFromInt(ns));
        r.tokens_per_ms = if (r.rounds == 0) value else r.tokens_per_ms + 0.2 * (value - r.tokens_per_ms);
        r.rounds += 1;
    }
};

pub const Guard = struct {
    pub const probe_rounds = 4;
    pub const retry_rounds = 64;
    pub const margin = 1.03;

    rates: [2]Rate = .{ .{}, .{} },
    mode: Mode = .draft,
    probing: u32 = probe_rounds,
    settled: u32 = 0,
    probes: u64 = 0,

    pub fn selected(g: *const Guard) Mode {
        return g.mode;
    }

    fn preferred(g: *const Guard) Mode {
        return if (g.rates[1].tokens_per_ms > margin * g.rates[0].tokens_per_ms) .draft else .plain;
    }

    /// A completed round whose incoming and outgoing generation modes agree.
    /// Skipping invalid observations does not consume a probe's sample budget.
    pub fn observe(g: *Guard, mode: Mode, tokens: usize, ns: u64) void {
        if (mode != g.mode or tokens == 0 or ns == 0) return;
        g.rates[@backingInt(mode)].add(tokens, ns);
        if (g.probing > 0) {
            g.probing -= 1;
            if (g.probing != 0) return;
            const other: Mode = if (mode == .draft) .plain else .draft;
            if (g.rates[@backingInt(other)].rounds < probe_rounds) {
                g.mode = other;
                g.probing = probe_rounds;
                g.probes += 1;
            } else {
                g.mode = g.preferred();
                g.settled = 0;
            }
            return;
        }
        g.settled += 1;
        if (g.settled >= retry_rounds) {
            g.mode = if (mode == .draft) .plain else .draft;
            g.probing = probe_rounds;
            g.settled = 0;
            g.probes += 1;
        }
    }
};

test "shared drafting measures its real generation cost and selects plain when slower" {
    var g: Guard = .{};
    for (0..Guard.probe_rounds) |_| g.observe(.draft, 44, 180_000_000);
    try std.testing.expectEqual(Mode.plain, g.selected());
    for (0..Guard.probe_rounds) |_| g.observe(.plain, 32, 107_000_000);
    try std.testing.expectEqual(Mode.plain, g.selected());
    try std.testing.expectEqual(@as(u32, 0), g.probing);
}

test "profitable shared drafting remains selected irrespective of stream count" {
    var g: Guard = .{};
    // A 32-stream shape with cheaper drafts can profit within a 48-row budget.
    for (0..Guard.probe_rounds) |_| g.observe(.draft, 47, 120_000_000);
    for (0..Guard.probe_rounds) |_| g.observe(.plain, 32, 107_000_000);
    try std.testing.expectEqual(Mode.draft, g.selected());
}

test "unprofitable generation is retried and can recover on a changed workload" {
    var g: Guard = .{};
    for (0..Guard.probe_rounds) |_| g.observe(.draft, 44, 180_000_000);
    for (0..Guard.probe_rounds) |_| g.observe(.plain, 32, 107_000_000);
    for (0..Guard.retry_rounds) |_| g.observe(.plain, 32, 107_000_000);
    try std.testing.expectEqual(Mode.draft, g.selected());
    for (0..Guard.probe_rounds) |_| g.observe(.draft, 48, 70_000_000);
    try std.testing.expectEqual(Mode.draft, g.selected());
}

test "invalid and stale transition observations cannot consume the probe" {
    var g: Guard = .{};
    g.observe(.plain, 32, 100_000_000);
    g.observe(.draft, 0, 100_000_000);
    g.observe(.draft, 32, 0);
    try std.testing.expectEqual(@as(u32, Guard.probe_rounds), g.probing);
    try std.testing.expectEqual(@as(u64, 0), g.rates[0].rounds + g.rates[1].rounds);
}

test "a marginal noisy win does not enable draft generation" {
    var g: Guard = .{};
    for (0..Guard.probe_rounds) |_| g.observe(.draft, 32, 99_000_000);
    for (0..Guard.probe_rounds) |_| g.observe(.plain, 32, 100_000_000);
    try std.testing.expectEqual(Mode.plain, g.selected());
}

test "transitions and new workload cells do not price a mixed round" {
    var t: Trace = .{ .key = 32 };
    try std.testing.expect(!t.permits(.draft));
    t.include(.{ .key = 32, .mode = .draft });
    try std.testing.expect(t.permits(.draft));
    try std.testing.expect(!t.permits(.plain));
    t.include(.{ .key = 32, .mode = .plain });
    try std.testing.expect(!t.permits(.draft) and !t.permits(.plain));
    t = .{ .key = 33 };
    t.include(.{ .key = 32, .mode = .draft });
    try std.testing.expect(!t.permits(.draft));
    t = .{ .key = 32 };
    t.include(null);
    t.include(.{ .key = 32, .mode = .draft });
    try std.testing.expect(!t.permits(.draft));
}
