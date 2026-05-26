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

function clearEvidenceFiles(paths) {
  for (const evidencePath of paths) {
    fs.rmSync(evidencePath, { force: true });
  }
}

function runPlaywright(playwrightJson) {
  fs.mkdirSync(path.dirname(playwrightJson), { recursive: true });
  const outputFile = path.resolve(playwrightJson);
  const args = [
    'playwright',
    'test',
    'e2e/journey-trader.spec.ts',
    'e2e/journey-risk-manager.spec.ts',
    'e2e/journey-auditor.spec.ts',
    '--reporter=json'
  ];
  const command = process.platform === 'win32' ? `npx ${args.join(' ')}` : 'npx';
  const result = spawnSync(
    command,
    process.platform === 'win32' ? [] : args,
    {
      cwd: 'frontend-svelte',
      stdio: 'inherit',
      shell: process.platform === 'win32',
      env: {
        ...playwrightEnv(outputFile)
      }
    }
  );
  return spawnExitCode(result);
}

function playwrightEnv(outputFile, env = process.env) {
  return {
    ...env,
    BASE_URL: env.BASE_URL || 'http://localhost:5173',
    PLAYWRIGHT_JSON_OUTPUT_FILE: outputFile
  };
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
  clearEvidenceFiles([pytestJson, playwrightJson]);

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

module.exports = {
  backendPytestEnv,
  clearEvidenceFiles,
  finalExitCode,
  playwrightEnv,
  spawnExitCode
};
