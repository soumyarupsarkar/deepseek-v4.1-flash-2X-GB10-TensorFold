//! Prompt-derived replay stays available; the deployment selects random unseeded sampling.
const std = @import("std");
const api = @import("engine_api");
pub const Mode = enum { prompt, random };

pub fn parse(value: []const u8) !Mode {
    return std.meta.stringToEnum(Mode, std.mem.trim(u8, value, " \t\r\n")) orelse error.BadSeedMode;
}

pub fn choose(explicit: ?u64, prompt: []const u32, salt: i64, mode: Mode, entropy: u64) u64 {
    if (explicit) |seed| return seed;
    return if (mode == .prompt) api.seedFor(prompt, salt) else entropy;
}

test "explicit zero and keyed replay are independent of random entropy" {
    try std.testing.expectEqual(@as(u64, 0), choose(0, &.{ 1, 2 }, 9, .random, 77));
    try std.testing.expectEqual(@as(u64, 0), choose(0, &.{ 1, 2 }, 9, .prompt, 77));
    try std.testing.expectEqual(choose(null, &.{ 1, 2 }, 9, .prompt, 17), choose(null, &.{ 1, 2 }, 9, .prompt, 99));
    try std.testing.expectEqual(@as(u64, 17), choose(null, &.{ 1, 2 }, 9, .random, 17));
    try std.testing.expectEqual(@as(u64, 99), choose(null, &.{ 1, 2 }, 9, .random, 99));
    try std.testing.expectError(error.BadSeedMode, parse("randmo"));
}
