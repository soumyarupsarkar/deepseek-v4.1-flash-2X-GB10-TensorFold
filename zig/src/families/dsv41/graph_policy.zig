//! Bounded native graph variants. Uncaptured shapes can always execute eagerly.
const std = @import("std");
pub const Policy = struct {
    buckets: [16]usize = undefined,
    len: usize = 0,
    ceiling: usize,
    limit: usize = 512,

    pub fn parse(text: ?[]const u8, ceiling: usize, limit: usize) !Policy {
        if (ceiling == 0 or limit == 0 or limit > 4096) return error.BadGraphPolicy;
        var out: Policy = .{ .ceiling = ceiling, .limit = limit };
        if (text) |raw| {
            var it = std.mem.splitScalar(u8, raw, ',');
            var previous: usize = 0;
            while (it.next()) |piece| {
                const n = std.fmt.parseInt(usize, std.mem.trim(u8, piece, " \t"), 10) catch return error.BadGraphPolicy;
                if (out.len == out.buckets.len or n < 1024 or n % 1024 != 0 or n <= previous or n > ceiling) return error.BadGraphPolicy;
                out.buckets[out.len] = n;
                out.len += 1;
                previous = n;
            }
        }
        return out;
    }

    pub fn bucket(p: Policy, n: usize, fallback: usize) usize {
        if (p.len == 0) return fallback;
        for (p.buckets[0..p.len]) |b| if (b >= n) return b;
        return p.ceiling;
    }
};

test "explicit buckets end at the request window, independent of shared capacity" {
    const p = try Policy.parse("8192,262144", 1048576, 432);
    try std.testing.expectEqual(@as(usize, 8192), p.bucket(100, 1024));
    try std.testing.expectEqual(@as(usize, 262144), p.bucket(8193, 16384));
    try std.testing.expectEqual(@as(usize, 1048576), p.bucket(262145, 524288));
    try std.testing.expectEqual(@as(usize, 4096), (try Policy.parse(null, 1048576, 512)).bucket(3000, 4096));
    try std.testing.expectError(error.BadGraphPolicy, Policy.parse("8192,8192", 1048576, 432));
    try std.testing.expectError(error.BadGraphPolicy, Policy.parse("262144,8192", 1048576, 432));
    try std.testing.expectError(error.BadGraphPolicy, Policy.parse("2097152", 1048576, 432));
    try std.testing.expectError(error.BadGraphPolicy, Policy.parse("8192", 1048576, 0));
}
