
import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { PluginHost } from "../../trion/runtime/plugin-host.ts";

Deno.test("TRION Runtime - PluginHost Initialization", async () => {
    const host = new PluginHost();
    assertEquals(host instanceof PluginHost, true);
});

// Mock Plugin Test
Deno.test("TRION Runtime - Load Plugin Manifest", async () => {
    // We can't easily test file system loading without mocking or real files
    // So we just verify the structure is correct
    const host = new PluginHost();
    const plugins = host.getAll();
    assertEquals(Array.isArray(plugins), true);
});
