//! GET /health, /v1/models, /metrics, and the opt-in dashboard.
const std = @import("std");
const api = @import("engine_api");
const json = @import("json.zig");
const live = @import("live.zig");
const routes = @import("routes.zig");
const Server = @import("server.zig").Server;
const Conn = @import("http_conn.zig").Conn;
const Value = json.Value;
const Allocator = std.mem.Allocator;

/// With keys on, health names nothing about the model.
pub fn health(srv: *Server, conn: *Conn, a: Allocator) !void {
    var status: api.Status = .{};
    srv.engine.status(&status, &.{});
    const failed = status.failed or (if (status.diagnostics) |d| d.rdma_failed else false);
    const code: u16 = if (failed) 503 else 200;
    if (srv.keys) |k| if (k.enabled()) return conn.sendJson(code, if (failed) "{\"status\":\"failed\"}" else "{\"status\":\"ok\"}");
    const o = try json.newObject(a);
    try o.put(a, "status", .{ .string = if (failed) "failed" else "ok" });
    try o.put(a, "runtime_poisoned", .{ .bool = failed });
    if (failed) try o.put(a, "failure", .{ .string = status.failure });
    try o.put(a, "engine", .{ .string = srv.info.name });
    try o.put(a, "max_model_len", try json.intValue(a, srv.info.context_window));
    try o.put(a, "seed_mode", .{ .string = @tagName(srv.config.seed_mode) });
    try o.put(a, "structured_outputs", .{ .bool = srv.info.structures });
    if (srv.config.grammars) |compiler| try o.put(a, "grammar_cache_bytes", try json.intValue(a, compiler.cacheBytes()));
    try o.put(a, "model", .{ .string = srv.config.served_name });
    const ids = try a.alloc(Value, srv.config.model_ids.len);
    for (srv.config.model_ids, ids) |id, *slot| slot.* = .{ .string = id };
    try o.put(a, "model_ids", .{ .array = ids });
    try o.put(a, "max_batch_size", try json.intValue(a, srv.info.lanes));
    try o.put(a, "warming", .{ .bool = status.warming });
    const scheduler = try json.newObject(a);
    try scheduler.put(a, "running", try json.intValue(a, status.running));
    try scheduler.put(a, "waiting", try json.intValue(a, status.waiting));
    try scheduler.put(a, "generation_tokens_running", try json.intValue(a, status.generation_tokens));
    try scheduler.put(a, "generation_tokens_total", try json.intValue(a, status.generation_tokens_total));
    try o.put(a, "scheduler", .{ .object = scheduler });
    // Only aggregate counters; request text and API key labels never enter health.
    srv.metrics.mutex.lockUncancelable(srv.io);
    const prompt = srv.metrics.prompt;
    const cached = srv.metrics.cached;
    const generation = srv.metrics.generation;
    const rounds = srv.metrics.rounds;
    const requests = srv.metrics.latency.n;
    srv.metrics.mutex.unlock(srv.io);
    try o.put(a, "prompt_tokens_total", try json.intValue(a, prompt));
    try o.put(a, "generation_tokens_total", try json.intValue(a, generation));
    if (srv.info.prompt_cache) try o.put(a, "cached_tokens_total", try json.intValue(a, cached));
    const completed = try json.newObject(a);
    try completed.put(a, "requests", try json.intValue(a, requests));
    try completed.put(a, "prompt_tokens", try json.intValue(a, prompt));
    if (srv.info.prompt_cache) try completed.put(a, "cached_tokens", try json.intValue(a, cached));
    try completed.put(a, "generation_tokens", try json.intValue(a, generation));
    try completed.put(a, "decode_rounds", try json.intValue(a, rounds));
    try o.put(a, "completed", .{ .object = completed });
    const memory = try json.newObject(a);
    if (@import("host_heap.zig").snapshot()) |heap|
        try memory.put(a, "host_glibc", try diagnosticValue(a, heap));
    if (srv.engine.memory(std.mem.indexOf(u8, conn.path, "reset_peak=1") != null)) |mem| {
        try memory.put(a, "active", try json.intValue(a, mem.active));
        try memory.put(a, "cache", try json.intValue(a, mem.cache));
        try memory.put(a, "peak", try json.intValue(a, mem.peak));
    }
    try o.put(a, "memory", .{ .object = memory });
    if (status.diagnostics) |d| try o.put(a, "native", try nativeDiagnostics(a, d));
    try o.put(a, "live", try live.snapshot(a, srv.engine));
    routes.sendValue(conn, a, code, .{ .object = o });
}

pub fn nativeDiagnostics(a: Allocator, d: api.Diagnostics) Allocator.Error!Value {
    const o = try json.newObject(a);
    inline for (@typeInfo(@TypeOf(d)).@"struct".field_names) |name| {
        const value = @field(d, name);
        // Optional instrumentation stays absent when disabled. Tables are
        // bounded and contain only counts, elapsed times and shape indices.
        if (@typeInfo(@TypeOf(value)) == .optional) {
            if (value) |v| try o.put(a, name, try diagnosticValue(a, v));
        } else try o.put(a, name, try diagnosticValue(a, value));
    }
    return .{ .object = o };
}

fn diagnosticValue(a: Allocator, value: anytype) Allocator.Error!Value {
    return switch (@typeInfo(@TypeOf(value))) {
        .bool => .{ .bool = value },
        .int => try json.intValue(a, value),
        .array => blk: {
            const out = try a.alloc(Value, value.len);
            for (value, out) |v, *item| item.* = try diagnosticValue(a, v);
            break :blk .{ .array = out };
        },
        .@"struct" => blk: {
            const out = try json.newObject(a);
            inline for (@typeInfo(@TypeOf(value)).@"struct".field_names) |name|
                try out.put(a, name, try diagnosticValue(a, @field(value, name)));
            break :blk .{ .object = out };
        },
        else => @compileError("Unsupported diagnostic value"),
    };
}

pub fn models(srv: *Server, conn: *Conn, a: Allocator) !void {
    const created = std.Io.Clock.real.now(srv.io).toSeconds();
    const data = try a.alloc(Value, srv.config.model_ids.len);
    for (srv.config.model_ids, data) |id, *slot| {
        const m = try json.newObject(a);
        try m.put(a, "id", .{ .string = id });
        try m.put(a, "object", .{ .string = "model" });
        try m.put(a, "created", try json.intValue(a, created));
        try m.put(a, "owned_by", .{ .string = "tensorfold" });
        try m.put(a, "max_model_len", try json.intValue(a, srv.modelWindow(id)));
        slot.* = .{ .object = m };
    }
    const o = try json.newObject(a);
    try o.put(a, "object", .{ .string = "list" });
    try o.put(a, "data", .{ .array = data });
    routes.sendValue(conn, a, 200, .{ .object = o });
}

/// Prometheus text, version 0.0.4.
pub fn metrics(srv: *Server, conn: *Conn, a: Allocator) void {
    var out: std.Io.Writer.Allocating = .init(a);
    srv.metrics.render(srv.io, &out.writer, srv.engine, srv.info.context_window) catch return;
    const body = out.written();
    conn.startResponse(200, null) catch return;
    conn.addHeader("Content-Type", "text/plain; version=0.0.4; charset=utf-8") catch return;
    var len: [24]u8 = undefined;
    conn.addHeader("Content-Length", std.fmt.bufPrint(&len, "{d}", .{body.len}) catch return) catch return;
    conn.finish(body) catch {};
}

pub fn dashboard(srv: *Server, conn: *Conn, a: Allocator) void {
    if (!srv.config.dashboard) return routes.unknown(conn, a);
    conn.startResponse(200, null) catch return;
    conn.addHeader("Content-Type", "text/html; charset=utf-8") catch return;
    var len: [24]u8 = undefined;
    conn.addHeader("Content-Length", std.fmt.bufPrint(&len, "{d}", .{dashboard_page.len}) catch return) catch return;
    conn.finish(dashboard_page) catch {};
}

pub fn stats(srv: *Server, conn: *Conn, a: Allocator) void {
    if (!srv.config.dashboard) return routes.unknown(conn, a);
    var status: api.Status = .{};
    srv.engine.status(&status, &.{});
    const memory = srv.engine.memory(false);
    srv.metrics.mutex.lockUncancelable(srv.io);
    const prompt = srv.metrics.prompt;
    const generation = srv.metrics.generation;
    const drafted = srv.metrics.drafted;
    const accepted = srv.metrics.accepted;
    const rounds = srv.metrics.rounds;
    srv.metrics.mutex.unlock(srv.io);
    const body = statsSnapshot(a, status, memory, prompt, generation, drafted, accepted, rounds) catch return;
    conn.quiet_log = true;
    routes.sendValue(conn, a, 200, body);
}

pub fn statsSnapshot(a: Allocator, status: api.Status, memory: ?api.Memory, prompt: u64, generation: u64, drafted: u64, accepted: u64, rounds: u64) Allocator.Error!Value {
    const o = try json.newObject(a);
    try o.put(a, "running", try json.intValue(a, status.running));
    try o.put(a, "waiting", try json.intValue(a, status.waiting));
    try o.put(a, "decode_tokens_per_second", .{ .float = status.decode_tokens_per_second });
    try o.put(a, "prefill_tokens_per_second", .{ .float = status.prefill_tokens_per_second });
    try o.put(a, "generation_tokens_running", try json.intValue(a, status.generation_tokens));
    try o.put(a, "prompt_tokens_total", try json.intValue(a, prompt));
    try o.put(a, "generation_tokens_total", try json.intValue(a, generation));
    try o.put(a, "mtp_drafted_total", try json.intValue(a, drafted));
    try o.put(a, "mtp_accepted_total", try json.intValue(a, accepted));
    try o.put(a, "decode_rounds_total", try json.intValue(a, rounds));
    const mem = try json.newObject(a);
    if (memory) |m| {
        try mem.put(a, "active", try json.intValue(a, m.active));
        try mem.put(a, "cache", try json.intValue(a, m.cache));
        try mem.put(a, "peak", try json.intValue(a, m.peak));
    }
    try o.put(a, "memory", .{ .object = mem });
    return .{ .object = o };
}

const dashboard_page = @embedFile("dashboard.html");

test "stats snapshot exposes counters and omits unknown memory" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const value = try statsSnapshot(arena.allocator(), .{ .running = 1, .generation_tokens = 2 }, null, 3, 4, 5, 6, 7);
    const object = value.object;
    for ([_][]const u8{ "running", "waiting", "generation_tokens_running", "prompt_tokens_total", "generation_tokens_total", "mtp_drafted_total", "mtp_accepted_total", "decode_rounds_total", "memory" }) |key|
        try std.testing.expect(object.contains(key));
    try std.testing.expectEqual(@as(usize, 0), object.get("memory").?.object.count());
}

test "native diagnostics expose measured allocation and compaction facts" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const v = try nativeDiagnostics(arena.allocator(), .{ .pool_tokens = 8650752, .context_tokens = 1048576, .stream_slots = 32, .compactions = 2, .drm_used_bytes = 1024, .rdma_failed = true });
    try std.testing.expectEqualStrings("8650752", v.get("pool_tokens").?.int);
    try std.testing.expectEqualStrings("2", v.get("compactions").?.int);
    try std.testing.expect(v.get("rdma_failed").?.bool);
    try std.testing.expect(v.get("timing") == null and v.get("costs") == null);
}

test "opt-in timing diagnostics retain integer precision and bounded shape tables" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const v = try nativeDiagnostics(arena.allocator(), .{ .timing = .{ .verify_ns = 9007199254740993 }, .costs = .{} });
    try std.testing.expectEqualStrings("9007199254740993", v.get("timing").?.get("verify_ns").?.int);
    try std.testing.expectEqual(@as(usize, 4), v.get("costs").?.get("verify_count").?.array.len);
    try std.testing.expectEqual(@as(usize, 7), v.get("costs").?.get("verify_count").?.array[0].array.len);
    try std.testing.expectEqual(@as(usize, 49), v.get("costs").?.get("verify_count").?.array[0].array[6].array.len);
}
