#!/usr/bin/env node
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function spawnExitCode(result) {
  if (result.status !== null && result.status !== undefined) {
    return result.status;
  }
  return 1;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    ...options
  });
  return spawnExitCode(result);
}

function runPlaywright(playwrightJson) {
  fs.mkdirSync(path.dirname(playwrightJson), { recursive: true });
  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const result = spawnSync(
    npx,
    [
      'playwright',
      'test',
      'e2e/journey-trader.spec.ts',
      'e2e/journey-risk-manager.spec.ts',
      'e2e/journey-auditor.spec.ts',
      '--reporter=json'
    ],
    {
      cwd: 'frontend-svelte',
      encoding: 'utf8',
      env: {
        ...process.env,
        BASE_URL: process.env.BASE_URL || 'http://localhost:5173'
      }
    }
  );
  if (result.stdout) {
    fs.writeFileSync(playwrightJson, result.stdout, 'utf8');
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  return spawnExitCode(result);
}

function backendPytestEnv(env = process.env) {
  return {
    ...env,
    E2E_FULL_STACK: '1',
    E2E_FULL_STACK_BASE_URL: env.E2E_FULL_STACK_BASE_URL || 'http://localhost:8000',
    DATABASE_URL: env.DATABASE_URL || 'postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol'
  };
}

function finalExitCode(reportStatus) {
  return reportStatus === 0 ? 0 : 1;
}

function main() {
  const utcDate = new Date().toISOString().slice(0, 10);
  const reportPath = path.join('docs', 'audits', `${utcDate}-go-no-go.md`);
  const pytestJson = path.join('backend', 'tests', 'e2e', 'report.json');
  const playwrightJson = path.join('frontend-svelte', 'playwright-report', 'report.json');

  run('python', [
    '-m',
    'pytest',
    'backend/tests/e2e/',
    '-v',
    '--json-report',
    `--json-report-file=${pytestJson}`
  ], {
    env: backendPytestEnv()
  });

  runPlaywright(playwrightJson);

  const reportArgs = [
    'scripts/e2e_go_no_go_report.py',
    '--pytest-json',
    pytestJson,
    '--playwright-json',
    playwrightJson,
    '--output',
    reportPath
  ];
  if (process.env.OVERRIDE_RATIONALE) {
    reportArgs.push('--override-rationale', process.env.OVERRIDE_RATIONALE);
  }
  const reportStatus = run('python', reportArgs);
  const exitCode = finalExitCode(reportStatus);
  if (exitCode !== 0) {
    process.exit(exitCode);
  }
  console.log(`Report written: ${reportPath}`);
}

if (require.main === module) {
  main();
}

module.exports = { backendPytestEnv, finalExitCode, spawnExitCode };
