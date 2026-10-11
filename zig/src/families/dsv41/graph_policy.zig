//! Bounded native graph variants. Evict cold executables before capturing new shapes.
const std = @import("std");

/// Engine-thread-only LRU storage. The caller owns values, including values
/// returned by takeOldest, so CUDA handles can be destroyed before a new capture.
pub fn Lru(comptime Key: type, comptime Value: type) type {
    return struct {
        const Self = @This();
        const Entry = struct { value: Value, used: u64 };
        map: std.AutoHashMapUnmanaged(Key, Entry) = .empty,
        clock: u64 = 0,

        pub fn get(self: *Self, key: Key) ?*Value {
            const entry = self.map.getPtr(key) orelse return null;
            self.clock += 1;
            entry.used = self.clock;
            return &entry.value;
        }

        pub fn put(self: *Self, gpa: std.mem.Allocator, key: Key, value: Value) !void {
            std.debug.assert(!self.map.contains(key));
            self.clock += 1;
            try self.map.put(gpa, key, .{ .value = value, .used = self.clock });
        }

        pub fn takeOldest(self: *Self) ?Value {
            var oldest: ?Key = null;
            var used: u64 = std.math.maxInt(u64);
            var it = self.map.iterator();
            while (it.next()) |entry| {
                if (oldest == null or entry.value_ptr.used < used) {
                    oldest = entry.key_ptr.*;
                    used = entry.value_ptr.used;
                }
            }
            return if (oldest) |key| self.map.fetchRemove(key).?.value.value else null;
        }

        pub fn count(self: *const Self) usize {
            return self.map.count();
        }

        pub fn deinit(self: *Self, gpa: std.mem.Allocator) void {
            std.debug.assert(self.count() == 0); // release each owned value first
            self.map.deinit(gpa);
            self.* = undefined;
        }
    };
}

test "graph LRU hits protect hot shapes and removal transfers each value once" {
    const Key = struct { rows: u32, bucket: u64, stretch: u32 };
    var cache: Lru(Key, u32) = .{};
    defer cache.deinit(std.testing.allocator);
    const a: Key = .{ .rows = 32, .bucket = 8192, .stretch = 0 };
    const b: Key = .{ .rows = 32, .bucket = 262144, .stretch = 0 };
    const c: Key = .{ .rows = 32, .bucket = 8192, .stretch = 1 };
    try cache.put(std.testing.allocator, a, 11);
    try cache.put(std.testing.allocator, b, 22);
    try std.testing.expectEqual(@as(u32, 11), cache.get(a).?.*);
    try std.testing.expectEqual(@as(?u32, 22), cache.takeOldest());
    try cache.put(std.testing.allocator, c, 33);
    try std.testing.expectEqual(@as(usize, 2), cache.count());
    try std.testing.expect(cache.get(b) == null);
    try std.testing.expectEqual(@as(?u32, 11), cache.takeOldest());
    try std.testing.expectEqual(@as(?u32, 33), cache.takeOldest());
    try std.testing.expect(cache.takeOldest() == null);
}

test "graph LRU stays bounded while switching context working sets" {
    var cache: Lru(u32, u32) = .{};
    defer cache.deinit(std.testing.allocator);
    var evicted: usize = 0;
    for (0..4) |bucket| {
        for (0..144) |shape| {
            const key: u32 = @intCast(bucket * 144 + shape);
            if (cache.count() == 144) {
                try std.testing.expect(cache.takeOldest() != null);
                evicted += 1;
            }
            try cache.put(std.testing.allocator, key, key);
            try std.testing.expect(cache.count() <= 144);
        }
        // Every row/stretch of the current bucket remains warm on replay.
        for (0..144) |shape| {
            const key: u32 = @intCast(bucket * 144 + shape);
            try std.testing.expectEqual(key, cache.get(key).?.*);
        }
    }
    try std.testing.expectEqual(@as(usize, 432), evicted);
    while (cache.takeOldest() != null) evicted += 1;
    try std.testing.expectEqual(@as(usize, 576), evicted);
}

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
