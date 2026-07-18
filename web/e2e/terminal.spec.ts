import { test, expect } from '@playwright/test';
import { execSync, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

function killRunners() {
  console.log('Killing existing runner processes...');
  try { execSync("pkill -9 -f 'omnigent run'"); } catch(e){}
  try { execSync("pkill -9 -f 'omnigent.runner'"); } catch(e){}
  try { execSync("pkill -9 -f 'omnigent.runtime'"); } catch(e){}
  try { execSync("pkill -9 -f 'omnigent.runner._entry'"); } catch(e){}
}

// Relies on the clean slate established by killRunners() at test start: after
// that, the only `omnigent.runner._entry` process is the one this test spawned,
// so the first pgrep match is the current session's runner.
function getRunnerPid(): number | null {
  try {
    const stdout = execSync("pgrep -f 'omnigent.runner._entry'").toString().trim();
    if (stdout) {
      const pids = stdout.split('\n').map(p => parseInt(p, 10)).filter(p => !isNaN(p));
      return pids[0] || null;
    }
  } catch(e){}
  return null;
}

// Hoisted so afterEach can tear the process down even when an assertion throws
// mid-test, instead of leaking the runner until the next run's global kill.
let cliProc: ReturnType<typeof spawn> | null = null;

test.afterEach(() => {
  try { cliProc?.kill(); } catch(e){}
  cliProc = null;
  killRunners();
});

test('same-process terminal reconnect and 404 cleanup', async ({ page }) => {
  // Per-run unique temp path so repeated or parallel runs never collide.
  const testFilePath = `/tmp/omnigent-demo-same-process-${Date.now()}.txt`;
  if (fs.existsSync(testFilePath)) {
    fs.unlinkSync(testFilePath);
  }

  // Kill existing runners
  killRunners();
  await new Promise(resolve => setTimeout(resolve, 2000));

  // Prepare config
  console.log('Preparing temporary config...');
  const baseConfig = fs.readFileSync('../examples/polly/agents/codex/config.yaml', 'utf8');
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
  const agentDir = path.join(process.cwd(), 'e2e/test_agent');
  fs.mkdirSync(agentDir, { recursive: true });
  fs.writeFileSync(path.join(agentDir, 'config.yaml'), baseConfig + '\n' + terminalsBlock);

  // Start fresh session
  console.log('Starting fresh session...');
  cliProc = spawn('nix', ['develop', '-c', 'uv', 'run', '--frozen', 'omnigent', 'run', agentDir, '--server', 'http://localhost:6767'], {
    cwd: path.join(process.cwd(), '..'),
    env: { ...process.env, TERM: 'xterm-256color' }
  });

  // Log cli output
  cliProc.stdout.on('data', (data) => console.log(`[CLI] ${data}`));
  cliProc.stderr.on('data', (data) => console.error(`[CLI STDERR] ${data}`));

  await new Promise(resolve => setTimeout(resolve, 15000));

  // Get session ID
  const response = await fetch('http://localhost:6767/v1/sessions');
  const data = await response.json();
  if (!data.data || data.data.length === 0) {
    cliProc?.kill();
    throw new Error('No sessions found');
  }
  const sessions = data.data;
  sessions.sort((a, b) => b.created_at - a.created_at);
  const sessionId = sessions[0].id;
  console.log(`Parsed Session ID: ${sessionId}`);

  // Navigate to session
  const targetUrl = `http://localhost:5173/c/${sessionId}`;
  console.log(`Navigating to: ${targetUrl}`);
  await page.goto(targetUrl);
  await page.waitForTimeout(5000);

  // Reload page
  console.log('Reloading page...');
  await page.reload();
  await page.waitForTimeout(8000);

  // Dismiss overlays or click shells tab
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1000);

  const shellsTab = page.locator("button:has-text('Shells')").first();
  await shellsTab.click();
  await page.waitForTimeout(2000);

  // Create new shell
  const newShellBtn = page.locator("button:has-text('New shell')").first();
  await newShellBtn.click();
  await page.waitForTimeout(8000);

  // Focus terminal
  await page.locator('div.xterm').first().click();
  await page.waitForTimeout(1000);

  // Verify terminal works
  console.log('Sending test command...');
  await page.keyboard.type("echo 'same-process test starting'");
  await page.keyboard.press('Enter');
  await page.waitForTimeout(3000);

  // Get runner ID from session details
  const sessionDetailResponse = await fetch(`http://localhost:6767/v1/sessions/${sessionId}`);
  const sessionDetail = await sessionDetailResponse.json();
  const runnerId = sessionDetail.runner_id;
  if (!runnerId) {
    cliProc?.kill();
    throw new Error('Runner ID not found in session details');
  }
  console.log(`Parsed Runner ID: ${runnerId}`);

  // Get runner pid
  const runnerPid = getRunnerPid();
  if (!runnerPid) {
    cliProc?.kill();
    throw new Error('Runner PID not found');
  }
  console.log(`Found runner process PID: ${runnerPid}`);

  // SIGSTOP
  console.log(`Sending SIGSTOP to PID ${runnerPid}...`);
  process.kill(runnerPid, 'SIGSTOP');

  console.log('Waiting for health poll to trigger offline state (up to 140s)...');
  const offlineOverlay = page.locator("[data-testid='terminal-runner-offline']").first();
  await expect(offlineOverlay).toBeVisible({ timeout: 140000 });

  // Hard reload
  console.log('Hard reloading browser...');
  await page.reload();
  await page.waitForTimeout(8000);

  // Verify same terminal is selected and overlay is visible
  const offlineOverlayAfterReload = page.locator("[data-testid='terminal-runner-offline']").first();
  await expect(offlineOverlayAfterReload).toBeVisible({ timeout: 10000 });

  // SIGCONT
  console.log(`Sending SIGCONT to PID ${runnerPid}...`);
  process.kill(runnerPid, 'SIGCONT');

  console.log('Waiting for auto-reattachment (up to 45s)...');
  await expect(offlineOverlayAfterReload).not.toBeVisible({ timeout: 45000 });

  // Execute a command successfully
  await page.locator('div.xterm').first().click();
  await page.waitForTimeout(1000);
  await page.keyboard.type(`printf 'same-process-ok\\n' > ${testFilePath}`);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(5000);

  expect(fs.existsSync(testFilePath)).toBe(true);
  const fileContent = fs.readFileSync(testFilePath, 'utf8').trim();
  expect(fileContent).toBe('same-process-ok');
  console.log('Same-process reconnection test PASSED!');

  // Test 404 behavior: Delete all sessions
  console.log('Deleting all sessions to test 404 behavior...');
  while (true) {
    const getAllSessionsResponse = await fetch('http://localhost:6767/v1/sessions?limit=100');
    const allSessionsData = await getAllSessionsResponse.json();
    if (!allSessionsData.data || allSessionsData.data.length === 0) {
      break;
    }
    for (const s of allSessionsData.data) {
      await fetch(`http://localhost:6767/v1/sessions/${s.id}`, { method: 'DELETE' });
    }
    if (!allSessionsData.has_more) {
      break;
    }
  }

  console.log('Reloading page after delete...');
  await page.reload();
  await page.waitForTimeout(8000);

  const xtermVisible = await page.locator('div.xterm').first().isVisible();
  const tabsVisible = await page.locator("button:has-text('bash')").first().isVisible();
  expect(xtermVisible).toBe(false);
  expect(tabsVisible).toBe(false);
  console.log('404 cleanup test PASSED!');

  // Process teardown (cliProc + runners) is handled by afterEach so it runs
  // even if an assertion above fails.
});
