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
  first_id?: string | null;
  last_id?: string | null;
  has_more?: boolean;
}

interface ProcessRow {
  pid: number;
  parentPid: number;
  processGroupId: number;
  command: string;
}

interface OwnedRunner {
  pid: number;
  processGroupId: number;
}

interface PreparedAgent {
  directory: string;
  dataDirectory: string;
  agentName: string;
}

let cliProcessGroupId: number | null = null;
let daemonProcessGroupId: number | null = null;
let ownedRunner: OwnedRunner | null = null;
let createdSessionId: string | null = null;
let generatedAgentDir: string | null = null;
let generatedDataDir: string | null = null;
let testFilePath: string | null = null;

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
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
  const sessions: SessionSummary[] = [];
  let after: string | null = null;

  while (true) {
    const params = new URLSearchParams({
      limit: "1000",
      order: "desc",
    });

    if (after !== null) {
      params.set("after", after);
    }

    const page = await fetchJson<SessionListResponse>(
      `${API_URL}/v1/sessions?${params.toString()}`,
    );
    const pageSessions = Array.isArray(page.data) ? page.data : [];

    sessions.push(...pageSessions);

    if (!page.has_more) {
      return sessions;
    }

    const nextAfter = page.last_id ?? pageSessions.at(-1)?.id ?? null;

    if (nextAfter === null || nextAfter === after) {
      throw new Error(
        "Session pagination reported has_more without a usable next cursor",
      );
    }

    after = nextAfter;
  }
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
  const output = execFileSync(
    "ps",
    ["-axo", "pid=,ppid=,pgid=,command="],
    { encoding: "utf8" },
  );
  const rows: ProcessRow[] = [];

  for (const line of output.split("\n")) {
    const match = line.match(
      /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/,
    );
    if (!match) continue;

    rows.push({
      pid: Number.parseInt(match[1], 10),
      parentPid: Number.parseInt(match[2], 10),
      processGroupId: Number.parseInt(match[3], 10),
      command: match[4],
    });
  }

  return rows;
}

function readHostDaemonPid(dataDirectory: string): number | null {
  const pidFilePath = path.join(dataDirectory, "host.pid");

  if (!fs.existsSync(pidFilePath)) {
    return null;
  }

  const firstLine = fs
    .readFileSync(pidFilePath, "utf8")
    .trim()
    .split(/\r?\n/, 1)[0];

  const pid = Number.parseInt(firstLine, 10);

  if (!Number.isSafeInteger(pid) || pid <= 1) {
    throw new Error(
      `Invalid host daemon PID in ${pidFilePath}: ${firstLine}`,
    );
  }

  return pid;
}

function isDescendantOf(
  candidatePid: number,
  ancestorPid: number,
  rowsByPid: Map<number, ProcessRow>,
): boolean {
  let current = rowsByPid.get(candidatePid);
  const visited = new Set<number>();

  while (current !== undefined && !visited.has(current.pid)) {
    if (current.parentPid === ancestorPid) {
      return true;
    }

    visited.add(current.pid);
    current = rowsByPid.get(current.parentPid);
  }

  return false;
}

function findOwnedRunner(daemonPid: number): OwnedRunner | null {
  const rows = readProcessTable();
  const rowsByPid = new Map(
    rows.map((row): [number, ProcessRow] => [row.pid, row]),
  );

  const candidates = rows.filter(
    (row) =>
      row.command.includes("omnigent.runner._entry") &&
      isDescendantOf(row.pid, daemonPid, rowsByPid),
  );

  if (candidates.length > 1) {
    throw new Error(
      `More than one runner belongs to daemon ${daemonPid}: ` +
        candidates
          .map(
            (candidate) =>
              `${candidate.pid}/${candidate.processGroupId}: ${candidate.command}`,
          )
          .join(", "),
    );
  }

  const candidate = candidates[0];

  return candidate
    ? {
        pid: candidate.pid,
        processGroupId: candidate.processGroupId,
      }
    : null;
}

function processGroupExists(processGroupId: number): boolean {
  try {
    process.kill(-processGroupId, 0);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;

    if (code === "ESRCH") {
      return false;
    }

    throw error;
  }
}

function signalProcessGroup(
  processGroupId: number,
  signal: NodeJS.Signals,
): void {
  try {
    process.kill(-processGroupId, signal);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;

    if (code !== "ESRCH") {
      throw error;
    }
  }
}

async function waitForProcessGroupExit(
  processGroupId: number,
  timeoutMs: number,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    if (!processGroupExists(processGroupId)) {
      return true;
    }

    await sleep(200);
  }

  return !processGroupExists(processGroupId);
}

async function terminateProcessGroup(
  processGroupId: number,
): Promise<void> {
  // A runner paused with SIGSTOP cannot process SIGTERM.
  signalProcessGroup(processGroupId, "SIGCONT");
  signalProcessGroup(processGroupId, "SIGTERM");

  if (await waitForProcessGroupExit(processGroupId, 10_000)) {
    return;
  }

  signalProcessGroup(processGroupId, "SIGKILL");

  if (!(await waitForProcessGroupExit(processGroupId, 2_000))) {
    throw new Error(
      `Process group ${processGroupId} remained alive after SIGKILL`,
    );
  }
}

async function terminateOwnedProcesses(): Promise<void> {
  const processGroups = new Set<number>();

  // Stop the actual runner first, then the CLI and its isolated daemon.
  if (ownedRunner !== null) {
    processGroups.add(ownedRunner.processGroupId);
  }
  if (cliProcessGroupId !== null) {
    processGroups.add(cliProcessGroupId);
  }
  if (daemonProcessGroupId !== null) {
    processGroups.add(daemonProcessGroupId);
  }

  const errors: unknown[] = [];

  for (const processGroupId of processGroups) {
    try {
      await terminateProcessGroup(processGroupId);
    } catch (error) {
      errors.push(error);
    }
  }

  ownedRunner = null;
  cliProcessGroupId = null;
  daemonProcessGroupId = null;

  if (errors.length > 0) {
    throw new AggregateError(
      errors,
      "Failed to terminate test-owned process groups",
    );
  }
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
    fs.rmSync(generatedAgentDir, {
      recursive: true,
      force: true,
    });
    generatedAgentDir = null;
  }

  if (generatedDataDir !== null) {
    fs.rmSync(generatedDataDir, {
      recursive: true,
      force: true,
    });
    generatedDataDir = null;
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
  const namedConfig = baseConfig.replace(
    /^name:\s*.*$/m,
    `name: ${agentName}`,
  );

  if (namedConfig === baseConfig) {
    throw new Error(
      `Agent config has no replaceable name field: ${baseConfigPath}`,
    );
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

  generatedAgentDir = fs.mkdtempSync(
    path.join(os.tmpdir(), "omnigent-terminal-e2e-agent-"),
  );
  generatedDataDir = fs.mkdtempSync(
    path.join(os.tmpdir(), "omnigent-terminal-e2e-data-"),
  );

  fs.writeFileSync(
    path.join(generatedAgentDir, "config.yaml"),
    `${namedConfig}\n${terminalsBlock}`,
    "utf8",
  );

  return {
    directory: generatedAgentDir,
    dataDirectory: generatedDataDir,
    agentName,
  };
}

function startCli(preparedAgent: PreparedAgent): void {
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
      preparedAgent.directory,
      "--server",
      API_URL,
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        TERM: "xterm-256color",
        // Gives this test its own daemon pidfile, runner identity, logs,
        // registration state, and other per-user Omnigent state.
        OMNIGENT_DATA_DIR: preparedAgent.dataDirectory,
      },
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  if (child.pid === undefined) {
    throw new Error("Failed to obtain the spawned CLI PID");
  }

  cliProcessGroupId = child.pid;

  child.stdout?.on("data", (data: Buffer) => {
    console.log(`[CLI] ${data.toString()}`);
  });
  child.stderr?.on("data", (data: Buffer) => {
    console.error(`[CLI STDERR] ${data.toString()}`);
  });
  child.on("exit", (code, signal) => {
    console.log(`CLI exited: code=${code}, signal=${signal}`);
  });
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

  // Stop every process before deleting durable session and daemon state.
  try {
    await terminateOwnedProcesses();
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
    throw new AggregateError(
      cleanupErrors,
      "Terminal E2E cleanup failed",
    );
  }
});

test("same-process terminal reconnect and 404 cleanup", async ({
  page,
}) => {
  test.setTimeout(600_000);

  // Fail immediately when the explicit backend prerequisite is absent.
  await fetchJson<SessionListResponse>(
    `${API_URL}/v1/sessions?limit=1`,
  );

  const existingSessionIds = new Set(
    (await listSessions()).map((session) => session.id),
  );
  const preparedAgent = prepareAgent();

  testFilePath = path.join(
    os.tmpdir(),
    `omnigent-same-process-${process.pid}-${Date.now()}.txt`,
  );

  startCli(preparedAgent);

  const daemonPid = await waitForValue(
    () => readHostDaemonPid(preparedAgent.dataDirectory),
    {
      timeoutMs: 60_000,
      description: "the isolated host daemon PID file",
    },
  );

  const daemonRow = await waitForValue(
    () =>
      readProcessTable().find((row) => row.pid === daemonPid) ??
      null,
    {
      timeoutMs: 30_000,
      description: `host daemon process ${daemonPid}`,
    },
  );
  daemonProcessGroupId = daemonRow.processGroupId;

  const createdSession = await waitForCreatedSession(
    existingSessionIds,
    preparedAgent.agentName,
  );
  createdSessionId = createdSession.id;

  const runner = await waitForValue(
    () => findOwnedRunner(daemonPid),
    {
      timeoutMs: 60_000,
      description: `runner owned by host daemon ${daemonPid}`,
    },
  );
  ownedRunner = runner;

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

  signalProcessGroup(ownedRunner.processGroupId, "SIGSTOP");

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

  signalProcessGroup(ownedRunner.processGroupId, "SIGCONT");
  await expect(page.getByTestId("terminal-runner-offline").first()).not.toBeVisible({
    timeout: 45_000,
  });

  const resumedTerminal = page.locator("div.xterm").first();
  await resumedTerminal.click();
  if (testFilePath === null) {
    throw new Error("The terminal test output path was not initialized");
  }
  await page.keyboard.type(
    `printf '%s\\n' 'same-process-ok' > ${shellQuote(testFilePath)}`,
  );
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
