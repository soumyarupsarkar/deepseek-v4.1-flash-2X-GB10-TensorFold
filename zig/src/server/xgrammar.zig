//! Native C ABI to a pinned, bounded xgrammar compiler. No embedded Python.
//! Compilation runs on the HTTP thread before submission, never inside a rank round.
const std = @import("std");
const api = @import("engine_api");

const Abi = struct {
    tf_xg_abi_version: *const fn () callconv(.c) u32,
    tf_xg_compiler_create: *const fn ([*]const u8, usize, [*]const u32, usize, c_int, i64, [*]u8, usize) callconv(.c) ?*anyopaque,
    tf_xg_compiler_destroy: *const fn (*anyopaque) callconv(.c) void,
    tf_xg_matcher_create: *const fn (*anyopaque, u32, [*]const u8, usize, [*]u8, usize) callconv(.c) ?*anyopaque,
    tf_xg_matcher_destroy: *const fn (*anyopaque) callconv(.c) void,
    tf_xg_accept: *const fn (*anyopaque, u32) callconv(.c) c_int,
    tf_xg_mask: *const fn (*anyopaque, [*]f32, usize) callconv(.c) c_int,
    tf_xg_cache_bytes: *const fn (*anyopaque) callconv(.c) u64,
};

/// Each vocabulary has its own LRU. Matchers keep their compiled grammar
/// alive while a request uses it, even if that entry is evicted from the LRU.
fn cacheLimit(raw: ?[]const u8) !i64 {
    const mib = if (raw) |text| std.fmt.parseInt(u32, text, 10) catch return error.BadGrammarCacheLimit else 256;
    if (mib < 1 or mib > 1024) return error.BadGrammarCacheLimit;
    return @as(i64, mib) << 20;
}

test "grammar cache limit is per vocabulary and rejects invalid budgets" {
    try std.testing.expectEqual(@as(i64, 256 << 20), try cacheLimit(null));
    try std.testing.expectEqual(@as(i64, 64 << 20), try cacheLimit("64"));
    try std.testing.expectEqual(@as(i64, 1024 << 20), try cacheLimit("1024"));
    for ([_][]const u8{ "", "0", "1025", "-1", "1.5", "bad" }) |text| {
        try std.testing.expectError(error.BadGrammarCacheLimit, cacheLimit(text));
    }
}

pub const Compiler = struct {
    gpa: std.mem.Allocator,
    lib: std.DynLib,
    fns: Abi,
    handle: *anyopaque,
    stop: []const u32,

    pub fn open(gpa: std.mem.Allocator, path: []const u8, tokenizer: []const u8, stop: []const u32, problem: []u8) !*Compiler {
        var lib = try std.DynLib.open(path);
        errdefer lib.close();
        var fns: Abi = undefined;
        inline for (@typeInfo(Abi).@"struct".field_names, @typeInfo(Abi).@"struct".field_types) |name, T| {
            @field(fns, name) = lib.lookup(T, name) orelse return error.MissingGrammarSymbol;
        }
        if (fns.tf_xg_abi_version() != 1) return error.WrongGrammarAbi;
        const budget = try cacheLimit(if (std.c.getenv("TENSORFOLD_GRAMMAR_CACHE_MIB")) |v| std.mem.span(v) else null);
        const handle = fns.tf_xg_compiler_create(tokenizer.ptr, tokenizer.len, stop.ptr, stop.len, 4, budget, problem.ptr, problem.len) orelse return error.GrammarCompilerFailed;
        errdefer fns.tf_xg_compiler_destroy(handle);
        const self = try gpa.create(Compiler);
        self.* = .{ .gpa = gpa, .lib = lib, .fns = fns, .handle = handle, .stop = stop };
        return self;
    }

    pub fn deinit(self: *Compiler) void {
        self.fns.tf_xg_compiler_destroy(self.handle);
        self.lib.close();
        self.gpa.destroy(self);
    }

    pub fn matcher(self: *Compiler, spec: api.Structure, problem: []u8) !Matcher {
        const kind: u32 = switch (spec.kind) {
            .json => 0,
            .json_schema => 1,
            .regex => 2,
            .choice => 3,
            .grammar => 4,
            .tools => 5,
        };
        const handle = self.fns.tf_xg_matcher_create(self.handle, kind, spec.text.ptr, spec.text.len, problem.ptr, problem.len) orelse return error.InvalidGrammar;
        return .{ .compiler = self, .handle = handle, .after = spec.after };
    }

    pub fn cacheBytes(self: *Compiler) u64 {
        return self.fns.tf_xg_cache_bytes(self.handle);
    }
};

pub const Matcher = struct {
    compiler: *Compiler,
    handle: *anyopaque,
    after: ?u32,
    seen: usize = 0,

    pub fn deinit(self: *Matcher) void {
        self.compiler.fns.tf_xg_matcher_destroy(self.handle);
    }

    pub fn gate(self: *Matcher) api.LogitGate {
        return .{ .ctx = self, .mask = mask };
    }

    fn mask(ctx: *anyopaque, logits: []f32, committed: []const u32) anyerror!void {
        const self: *Matcher = @ptrCast(@alignCast(ctx));
        if (committed.len < self.seen) return error.GrammarRewind;
        // Only committed tokens advance the matcher. A sampled token can still be
        // replaced by the engine's forced reasoning close, so never accept at draw.
        for (committed[self.seen..]) |token| {
            if (self.after) |end| {
                if (token == end) self.after = null;
            } else if (self.compiler.fns.tf_xg_accept(self.handle, token) != 0) return error.GrammarRejectedToken;
        }
        self.seen = committed.len;
        if (self.after != null) {
            // A reasoning block must close before a constrained answer can end.
            for (self.compiler.stop) |id| if (id < logits.len) {
                logits[id] = -std.math.inf(f32);
            };
            return;
        }
        if (self.compiler.fns.tf_xg_mask(self.handle, logits.ptr, logits.len) != 0) return error.NoGrammarToken;
    }
};
