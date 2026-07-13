import { afterEach, describe, expect, it, vi } from "vitest";
import {
  attachQuery,
  fetchLocalRunners,
  fetchHosts,
  remoteLocalRunnerEnabled,
  stateFromAttachClose,
} from "./remoteRunner";

afterEach(() => vi.unstubAllGlobals());

describe("remote runner attach contract", () => {
  it("prefers control when advertised", () => {
    expect(attachQuery({ transports: ["control", "pty"], readOnly: false })).toBe(
      "transport=control",
    );
  });

  it("falls back to pty when control is absent", () => {
    expect(attachQuery({ transports: ["pty"], readOnly: true })).toBe(
      "transport=pty&read_only=true",
    );
  });

  it("lets the debug override win", () => {
    expect(attachQuery({ transports: ["control"], debugOverride: "pty", readOnly: false })).toBe(
      "transport=pty",
    );
  });

  it("maps lifecycle close codes and leaves generic codes alone", () => {
    expect(stateFromAttachClose(4503)).toBe("runner_offline");
    expect(stateFromAttachClose(4404)).toBe("terminal_exited");
    expect(stateFromAttachClose(4405)).toBe("terminal_detached");
    expect(stateFromAttachClose(1006)).toBeNull();
    expect(stateFromAttachClose(1011)).toBeNull();
  });
});

describe("remote runner discovery", () => {
  it("fetches opaque runner and workspace identifiers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: [
              {
                runner_id: "runner_abc",
                online: true,
                harnesses: ["codex"],
                terminal_transports: ["control"],
                tool_capabilities: ["read_file"],
                workspaces: [
                  { workspace_id: "ws_123", path_label: "~/src/app", capabilities: ["read"] },
                ],
              },
            ],
          }),
        ),
      ),
    );

    const runners = await fetchLocalRunners();
    expect(runners[0].runner_id).toBe("runner_abc");
    expect(runners[0].workspaces[0].workspace_id).toBe("ws_123");
  });

  it("fetches the hosts-shaped API envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            hosts: [{ host_id: "h1", name: "Laptop", owner: "alice", status: "online" }],
          }),
        ),
      ),
    );
    const hosts = await fetchHosts();
    expect(hosts[0].host_id).toBe("h1");
  });

  it("fails closed on a disabled capability", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ remote_local_runner: false }))),
    );
    await expect(remoteLocalRunnerEnabled()).resolves.toBe(false);
  });
});
