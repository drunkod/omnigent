import { expect, test } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const API_URL = (process.env.OMNIGENT_E2E_API_URL ?? "http://127.0.0.1:6767").replace(/\/+$/, "");
const E2E_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(E2E_DIRECTORY, "../..");

interface SessionSummary {
  id: string;
  created_at: number;
  agent_name?: string | null;
}

interface SessionListResponse {
  data?: SessionSummary[];
  has_more?: boolean;
}

interface ProcessRow {
  pid: number;
  processGroupId: number;
  command: string;
}

interface PreparedAgent {
  directory: string;
  agentName: string;
}

let ownedProcessGroupId: number | null = null;
let createdSessionId: string | null = null;
let generatedAgentDir: string | null = null;
let testFilePath: string | null = null;

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await globalThis.fetch(url, init);

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(
      `${init?.method ?? "GET"} ${url} failed: ${response.status} ${response.statusText}` +
        (body ? `\n${body}` : ""),
    );
  }

  return (await response.json()) as T;
}

async function listSessions(): Promise<SessionSummary[]> {
  const result = await fetchJson<SessionListResponse>(`${API_URL}/v1/sessions?limit=100`);
  return Array.isArray(result.data) ? result.data : [];
}

async function waitForValue<T>(
  producer: () => Promise<T | null> | T | null,
  options: { timeoutMs: number; intervalMs?: number; description: string },
): Promise<T> {
  const deadline = Date.now() + options.timeoutMs;
  let lastError: unknown;

  while (Date.now() < deadline) {
    try {
      const value = await producer();
      if (value !== null) return value;
    } catch (error) {
      lastError = error;
    }

    await sleep(options.intervalMs ?? 500);
  }

  const suffix = lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new Error(`Timed out waiting for ${options.description}.${suffix}`);
}

function readProcessTable(): ProcessRow[] {
  const output = execFileSync("ps", ["-axo", "pid=,pgid=,command="], { encoding: "utf8" });
  const rows: ProcessRow[] = [];

  for (const line of output.split("\n")) {
    const match = line.match(/^\s*(\d+)\s+(\d+)\s+(.*)$/);
    if (!match) continue;

    rows.push({
      pid: Number.parseInt(match[1], 10),
      processGroupId: Number.parseInt(match[2], 10),
      command: match[3],
    });
  }

  return rows;
}

function findOwnedRunnerPid(processGroupId: number): number | null {
  const candidates = readProcessTable().filter(
    (row) =>
      row.processGroupId === processGroupId && row.command.includes("omnigent.runner._entry"),
  );

  if (candidates.length > 1) {
    throw new Error(
      "More than one runner exists in the test process group: " +
        candidates.map((candidate) => `${candidate.pid}: ${candidate.command}`).join(", "),
    );
  }

  return candidates[0]?.pid ?? null;
}

function signalOwnedGroup(signal: NodeJS.Signals): void {
  if (ownedProcessGroupId === null) return;

  try {
    process.kill(-ownedProcessGroupId, signal);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== "ESRCH") throw error;
  }
}

async function terminateOwnedGroup(): Promise<void> {
  if (ownedProcessGroupId === null) return;

  // A runner left in SIGSTOP cannot process SIGTERM.
  signalOwnedGroup("SIGCONT");
  signalOwnedGroup("SIGTERM");
  await sleep(1_000);

  signalOwnedGroup("SIGKILL");
  ownedProcessGroupId = null;
}

async function deleteOwnedSession(): Promise<void> {
  if (createdSessionId === null) return;

  const sessionId = createdSessionId;
  let lastError: unknown;

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await globalThis.fetch(
        `${API_URL}/v1/sessions/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" },
      );

      if (response.ok || response.status === 404) {
        createdSessionId = null;
        return;
      }

      lastError = new Error(`DELETE session failed: ${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }

    if (attempt < 3) await sleep(500 * attempt);
  }

  // Do not let a later test accidentally claim this ID.
  createdSessionId = null;
  const detail = lastError instanceof Error ? lastError.message : String(lastError);
  throw new Error(`Failed to delete test-owned session ${sessionId}: ${detail}`);
}

function removeGeneratedFiles(): void {
  if (testFilePath !== null) {
    fs.rmSync(testFilePath, { force: true });
    testFilePath = null;
  }

  if (generatedAgentDir !== null) {
    fs.rmSync(generatedAgentDir, { recursive: true, force: true });
    generatedAgentDir = null;
  }
}

function prepareAgent(): PreparedAgent {
  const baseConfigPath = path.join(
    REPO_ROOT,
    "examples",
    "polly",
    "agents",
    "codex",
    "config.yaml",
  );
  const baseConfig = fs.readFileSync(baseConfigPath, "utf8");
  const agentName = `terminal-e2e-${randomUUID()}`;
  const namedConfig = baseConfig.replace(/^name:\s*.*$/m, `name: ${agentName}`);

  if (namedConfig === baseConfig) {
    throw new Error(`Agent config has no replaceable name field: ${baseConfigPath}`);
  }

  const terminalsBlock = `
terminals:
  shell:
    command: bash
    allow_cwd_override: true
    os_env:
      type: caller_process
      cwd: .
      sandbox:
        type: none
`;

  generatedAgentDir = fs.mkdtempSync(path.join(os.tmpdir(), "omnigent-terminal-e2e-agent-"));
  fs.writeFileSync(
    path.join(generatedAgentDir, "config.yaml"),
    `${namedConfig}\n${terminalsBlock}`,
    "utf8",
  );
  return { directory: generatedAgentDir, agentName };
}

function startCli(agentDirectory: string): number {
  const child = spawn(
    "nix",
    [
      "develop",
      "-c",
      "uv",
      "run",
      "--frozen",
      "omnigent",
      "run",
      agentDirectory,
      "--server",
      API_URL,
    ],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, TERM: "xterm-256color" },
      // Create one process group containing only this test's CLI and descendants.
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  if (child.pid === undefined) throw new Error("Failed to obtain the spawned CLI PID");

  ownedProcessGroupId = child.pid;
  child.stdout?.on("data", (data: Buffer) => console.log(`[CLI] ${data.toString()}`));
  child.stderr?.on("data", (data: Buffer) => console.error(`[CLI STDERR] ${data.toString()}`));
  child.on("exit", (code, signal) => console.log(`CLI exited: code=${code}, signal=${signal}`));
  return child.pid;
}

async function waitForCreatedSession(
  existingSessionIds: Set<string>,
  expectedAgentName: string,
): Promise<SessionSummary> {
  return waitForValue(
    async () => {
      const matchingSessions = (await listSessions()).filter(
        (session) =>
          !existingSessionIds.has(session.id) && session.agent_name === expectedAgentName,
      );

      if (matchingSessions.length > 1) {
        throw new Error(
          `Multiple sessions matched agent ${expectedAgentName}: ` +
            matchingSessions.map((session) => session.id).join(", "),
        );
      }

      return matchingSessions[0] ?? null;
    },
    { timeoutMs: 60_000, description: `the session for agent ${expectedAgentName}` },
  );
}

test.describe.configure({ mode: "serial" });
test.skip(
  process.platform === "win32",
  "This test requires Unix process groups and SIGSTOP/SIGCONT.",
);

test.afterEach(async () => {
  const cleanupErrors: unknown[] = [];

  try {
    signalOwnedGroup("SIGCONT");
  } catch (error) {
    cleanupErrors.push(error);
  }

  // Stop the owned runner before deleting its durable session, preventing late
  // callbacks from racing with deletion.
  try {
    await terminateOwnedGroup();
  } catch (error) {
    cleanupErrors.push(error);
  }

  try {
    await deleteOwnedSession();
  } catch (error) {
    cleanupErrors.push(error);
  }

  try {
    removeGeneratedFiles();
  } catch (error) {
    cleanupErrors.push(error);
  }

  if (cleanupErrors.length > 0) {
    throw new AggregateError(cleanupErrors, "Terminal E2E cleanup failed");
  }
});

test("same-process terminal reconnect and 404 cleanup", async ({ page }) => {
  // Fail immediately with a useful error when the explicit backend prerequisite is absent.
  await fetchJson<SessionListResponse>(`${API_URL}/v1/sessions?limit=1`);

  const existingSessionIds = new Set((await listSessions()).map((session) => session.id));
  const preparedAgent = prepareAgent();
  testFilePath = path.join(os.tmpdir(), `omnigent-same-process-${process.pid}-${Date.now()}.txt`);

  startCli(preparedAgent.directory);
  const createdSession = await waitForCreatedSession(existingSessionIds, preparedAgent.agentName);
  createdSessionId = createdSession.id;

  if (ownedProcessGroupId === null) {
    throw new Error("The test process group was not initialized");
  }

  const processGroupId = ownedProcessGroupId;
  const ownedRunnerPid = await waitForValue(() => findOwnedRunnerPid(processGroupId), {
    timeoutMs: 60_000,
    description: "the runner in the test-owned process group",
  });

  await page.goto(`/c/${encodeURIComponent(createdSessionId)}`);
  await page.keyboard.press("Escape");

  const shellsTab = page.getByRole("tab", { name: "Shells" });
  await expect(shellsTab).toBeVisible({ timeout: 30_000 });
  await shellsTab.click();

  const newShellButton = page.getByRole("button", { name: "New shell" });
  await expect(newShellButton).toBeVisible({ timeout: 30_000 });
  await newShellButton.click();

  const shellMenuItem = page.getByRole("menuitem", { name: "shell" });
  if (await shellMenuItem.isVisible().catch(() => false)) await shellMenuItem.click();

  const terminal = page.locator("div.xterm").first();
  await expect(terminal).toBeVisible({ timeout: 30_000 });

  const snapshotKey = `omnigent.terminals.${createdSessionId}`;
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), snapshotKey), {
      timeout: 30_000,
    })
    .not.toBeNull();

  await terminal.click();
  await page.keyboard.type("echo 'same-process test starting'");
  await page.keyboard.press("Enter");

  process.kill(ownedRunnerPid, "SIGSTOP");

  const offlineOverlay = page.getByTestId("terminal-runner-offline").first();
  await expect(offlineOverlay).toBeVisible({ timeout: 140_000 });

  await page.reload();
  await expect(page.getByTestId("terminal-runner-offline").first()).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator("div.xterm").first()).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), snapshotKey))
    .not.toBeNull();

  process.kill(ownedRunnerPid, "SIGCONT");
  await expect(page.getByTestId("terminal-runner-offline").first()).not.toBeVisible({
    timeout: 45_000,
  });

  const resumedTerminal = page.locator("div.xterm").first();
  await resumedTerminal.click();
  await page.keyboard.type(`printf 'same-process-ok\\n' > ${testFilePath}`);
  await page.keyboard.press("Enter");

  await expect
    .poll(
      () => {
        if (testFilePath === null || !fs.existsSync(testFilePath)) return null;
        return fs.readFileSync(testFilePath, "utf8").trim();
      },
      { timeout: 20_000 },
    )
    .toBe("same-process-ok");

  const deletedSessionId = createdSessionId;
  const deleteResponse = await globalThis.fetch(
    `${API_URL}/v1/sessions/${encodeURIComponent(deletedSessionId)}`,
    { method: "DELETE" },
  );
  expect(deleteResponse.ok).toBe(true);
  createdSessionId = null;

  await page.reload();
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), snapshotKey), {
      timeout: 20_000,
    })
    .toBeNull();
  await expect(page.locator("div.xterm:visible")).toHaveCount(0, { timeout: 20_000 });
});
