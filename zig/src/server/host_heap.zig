//! Numeric glibc accounting, separate from CUDA and Zig's page-backed allocator.
//! No trimming or allocator-policy changes occur when reading this snapshot.
const std = @import("std");
const builtin = @import("builtin");

const supported = builtin.link_libc and builtin.os.tag == .linux and builtin.abi == .gnu;

const Mallinfo = extern struct {
    arena: usize,
    ordblks: usize,
    smblks: usize,
    hblks: usize,
    hblkhd: usize,
    usmblks: usize,
    fsmblks: usize,
    uordblks: usize,
    fordblks: usize,
    keepcost: usize,
};
const MallinfoFn = *const fn () callconv(.c) Mallinfo;

pub const Snapshot = struct {
    /// Allocator in-use blocks plus direct mappings, including allocator overhead.
    in_use_bytes: usize,
    /// Free arena space; may include already discarded pages, so this is not RSS.
    free_arena_bytes: usize,
    arena_bytes: usize,
    mmap_bytes: usize,
};

pub fn snapshot() ?Snapshot {
    if (comptime !supported) return null;
    // mallinfo2 arrived in glibc 2.33. Keep the existing binary target's
    // minimum unchanged and omit accounting on older runtimes.
    const read: MallinfoFn = @ptrCast(@alignCast(std.c.dlsym(null, "mallinfo2") orelse return null));
    const m = read();
    return .{
        .in_use_bytes = m.uordblks + m.hblkhd,
        .free_arena_bytes = m.fordblks,
        .arena_bytes = m.arena,
        .mmap_bytes = m.hblkhd,
    };
}

test "glibc snapshot observes an actual libc allocation and its release" {
    if (comptime !supported) return error.SkipZigTest;
    const before = snapshot() orelse return error.SkipZigTest;
    const bytes = try std.heap.c_allocator.alloc(u8, 2 << 20);
    @memset(bytes, 0x5a);
    std.mem.doNotOptimizeAway(bytes);
    const during = snapshot().?;
    std.mem.doNotOptimizeAway(bytes);
    std.heap.c_allocator.free(bytes);
    const after = snapshot().?;
    try std.testing.expect(during.in_use_bytes >= before.in_use_bytes + (2 << 20));
    try std.testing.expect(after.in_use_bytes < during.in_use_bytes);
}
