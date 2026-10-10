//! Opt-in GB10 display-reserved memory for sparsely read KV buffers.
//! Adapted from this fork's Python carveout.py and urtho/TensorFold
//! 27404275d0f14bba8e97e7ca801de4c956d369be (Apache-2.0), using the
//! Linux DRM UAPI and CUDA driver API. Idea credit: Emi Huang (coolbho3k),
//! DeepSeek-v4.1-Flash-2x-DGX-Spark/display_kv.c; no code from that AGPL source.
//! The model owns the mapping until all kernels/graphs using it have stopped.
const std = @import("std");
const abi = @import("abi.zig");
const Driver = @import("driver.zig").Driver;

const row_bytes: usize = 4096 * 4;
pub const default_bytes: usize = 1792 << 20;
const Create = extern struct { height: u32, width: u32 = 4096, bpp: u32 = 32, flags: u32 = 0, handle: u32 = 0, pitch: u32 = 0, size: u64 = 0 };
const Map = extern struct { handle: u32, pad: u32 = 0, offset: u64 = 0 };
const Destroy = extern struct { handle: u32 };
extern "c" fn ioctl(c_int, c_ulong, ...) c_int;

fn iowr(comptime nr: u8, comptime T: type) c_ulong {
    return (@as(c_ulong, 3) << 30) | (@as(c_ulong, @sizeOf(T)) << 16) | (@as(c_ulong, 'd') << 8) | @as(c_ulong, nr);
}

pub const Usage = struct { reserved: u64, used: u64 };
var reserved_bytes: std.atomic.Value(u64) = .init(0);
var used_bytes: std.atomic.Value(u64) = .init(0);

pub fn usage() Usage {
    return .{ .reserved = reserved_bytes.load(.monotonic), .used = used_bytes.load(.monotonic) };
}

const HostReg = struct {
    lib: std.DynLib,
    register: *const fn (?*anyopaque, usize, c_uint) callconv(.c) abi.Result,
    unregister: *const fn (?*anyopaque) callconv(.c) abi.Result,

    fn open() !HostReg {
        var lib = try std.DynLib.open("libcuda.so.1");
        errdefer lib.close();
        return .{
            .lib = lib,
            .register = lib.lookup(*const fn (?*anyopaque, usize, c_uint) callconv(.c) abi.Result, "cuMemHostRegister_v2") orelse return error.NoHostRegister,
            .unregister = lib.lookup(*const fn (?*anyopaque) callconv(.c) abi.Result, "cuMemHostUnregister") orelse return error.NoHostRegister,
        };
    }
};

/// An allocation either fits wholly in the scanout buffer or uses ordinary CUDA
/// storage. Splitting a tensor over mappings would violate its contiguous layout.
pub fn fit(size: usize, used: usize, bytes: usize) ?usize {
    if (used > size or used > std.math.maxInt(usize) - 255) return null;
    const start = std.mem.alignForward(usize, used, 256);
    if (start > size or bytes > size - start) return null;
    return start;
}

pub const Carveout = struct {
    fd: c_int,
    handle: u32,
    mem: []align(std.heap.page_size_min) u8,
    ptr: abi.DevicePtr,
    hr: HostReg,
    used: usize = 0,
    tensor_bytes: usize = 0,

    pub fn fromEnv(d: *const Driver) !?Carveout {
        const enabled = std.mem.span(std.c.getenv("TF_CARVEOUT") orelse return null);
        if (std.mem.eql(u8, enabled, "0")) return null;
        if (!std.mem.eql(u8, enabled, "1")) return error.BadCarveout;
        const bytes = if (std.c.getenv("TF_CARVEOUT_BYTES")) |v| try std.fmt.parseInt(usize, std.mem.span(v), 10) else default_bytes;
        const card = std.c.getenv("TF_DRM_CARD") orelse "/dev/dri/card0";
        return try open(d, card, bytes);
    }

    pub fn open(d: *const Driver, card: [*:0]const u8, bytes: usize) !Carveout {
        if (bytes == 0 or bytes % row_bytes != 0 or bytes / row_bytes > std.math.maxInt(u32)) return error.BadCarveout;
        const flags: std.posix.O = .{ .ACCMODE = .RDWR, .CLOEXEC = true };
        const fd = std.c.open(card, flags);
        if (fd < 0) return error.DrmOpenFailed;
        errdefer _ = std.c.close(fd);
        var create: Create = .{ .height = @intCast(bytes / row_bytes) };
        if (ioctl(fd, iowr(0xb2, Create), &create) != 0) return error.DrmCreateFailed;
        errdefer destroy(fd, create.handle);
        if (create.pitch != row_bytes or create.size < bytes) return error.DrmLayoutMismatch;
        var map: Map = .{ .handle = create.handle };
        if (ioctl(fd, iowr(0xb3, Map), &map) != 0) return error.DrmMapFailed;
        const mem = try std.posix.mmap(null, bytes, .{ .READ = true, .WRITE = true }, .{ .TYPE = .SHARED }, fd, map.offset);
        errdefer std.posix.munmap(mem);
        var hr = try HostReg.open();
        errdefer hr.lib.close();
        var rc = hr.register(mem.ptr, mem.len, 0x02); // DEVICEMAP
        if (rc != abi.success) rc = hr.register(mem.ptr, mem.len, 0x02 | 0x04); // IOMEMORY on drivers requiring it
        try d.check(rc, "cuMemHostRegister(DRM)");
        errdefer _ = hr.unregister(mem.ptr);
        var ptr: abi.DevicePtr = 0;
        try d.check(d.api.cuMemHostGetDevicePointer_v2(&ptr, mem.ptr, 0), "cuMemHostGetDevicePointer(DRM)");
        _ = reserved_bytes.fetchAdd(mem.len, .monotonic);
        return .{ .fd = fd, .handle = create.handle, .mem = mem, .ptr = ptr, .hr = hr };
    }

    pub fn take(cv: *Carveout, bytes: usize) ?abi.DevicePtr {
        const start = fit(cv.mem.len, cv.used, bytes) orelse return null;
        cv.used = start + bytes;
        cv.tensor_bytes += bytes;
        _ = used_bytes.fetchAdd(bytes, .monotonic);
        return cv.ptr + start;
    }

    pub fn deinit(cv: *Carveout) void {
        _ = cv.hr.unregister(cv.mem.ptr);
        std.posix.munmap(cv.mem);
        destroy(cv.fd, cv.handle);
        _ = std.c.close(cv.fd);
        cv.hr.lib.close();
        _ = reserved_bytes.fetchSub(cv.mem.len, .monotonic);
        _ = used_bytes.fetchSub(cv.tensor_bytes, .monotonic);
        cv.* = undefined;
    }

    fn destroy(fd: c_int, handle: u32) void {
        var value: Destroy = .{ .handle = handle };
        _ = ioctl(fd, iowr(0xb4, Destroy), &value);
    }
};

test "DRM UAPI layouts and request numbers" {
    try std.testing.expectEqual(32, @sizeOf(Create));
    try std.testing.expectEqual(16, @sizeOf(Map));
    try std.testing.expectEqual(4, @sizeOf(Destroy));
    try std.testing.expectEqual(@as(c_ulong, 0xc02064b2), iowr(0xb2, Create));
    try std.testing.expectEqual(@as(c_ulong, 0xc01064b3), iowr(0xb3, Map));
    try std.testing.expectEqual(@as(c_ulong, 0xc00464b4), iowr(0xb4, Destroy));
}

test "carveout allocation bounds include alignment and integer overflow" {
    try std.testing.expectEqual(@as(?usize, 256), fit(1024, 1, 768));
    try std.testing.expectEqual(@as(?usize, null), fit(1024, 1, 769));
    try std.testing.expectEqual(@as(?usize, null), fit(1024, 1025, 1));
    try std.testing.expectEqual(@as(?usize, null), fit(std.math.maxInt(usize), std.math.maxInt(usize), 1));
    try std.testing.expectEqual(@as(?usize, null), fit(1024, 0, std.math.maxInt(usize)));
}
