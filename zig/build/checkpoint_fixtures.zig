//! Immutable model-encoding examples embedded only into the CPU test binary.
const std = @import("std");
pub fn add(b: *std.Build, module: *std.Build.Module) void {
    const files = b.addWriteFiles();
    _ = files.addCopyFile(b.path("deployment/config/chat-template-1017.jinja"), "template.jinja");
    _ = files.addCopyFile(b.path("tests/publication/fixtures/checkpoint-1017-prompts.json"), "prompts.json");
    module.addAnonymousImport("checkpoint_1017", .{ .root_source_file = files.add("fixtures.zig",
        \\pub const template = @embedFile("template.jinja");
        \\pub const prompts = @embedFile("prompts.json");
    ) });
}
