#!/usr/bin/env node
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    ...options
  });
  return result.status || 0;
}

function main() {
  const utcDate = new Date().toISOString().slice(0, 10);
  const reportPath = path.join('docs', 'audits', `${utcDate}-go-no-go.md`);
  const pytestJson = path.join('backend', 'tests', 'e2e', 'report.json');
  const playwrightJson = path.join('frontend-svelte', 'playwright-report', 'report.json');

  const pyStatus = run('python', [
    '-m',
    'pytest',
    'backend/tests/e2e/',
    '-v',
    '--json-report',
    `--json-report-file=${pytestJson}`
  ]);

  if (!fs.existsSync(playwrightJson)) {
    fs.mkdirSync(path.dirname(playwrightJson), { recursive: true });
    fs.writeFileSync(
      playwrightJson,
      JSON.stringify({ stats: { unexpected: 0, expected: 0 } }),
      'utf8'
    );
  }

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
  if (reportStatus !== 0 || pyStatus !== 0) {
    process.exit(1);
  }
  console.log(`Report written: ${reportPath}`);
}

main();
