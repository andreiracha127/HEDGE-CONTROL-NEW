const assert = require('node:assert/strict');
const { test } = require('node:test');

const { backendPytestEnv, finalExitCode, playwrightEnv, spawnExitCode } = require('./run_go_no_go.js');

test('spawnExitCode treats signaled child process as failure', () => {
  assert.equal(spawnExitCode({ status: null, signal: 'SIGTERM' }), 1);
});

test('spawnExitCode returns numeric process status', () => {
  assert.equal(spawnExitCode({ status: 2, signal: null }), 2);
});

test('finalExitCode follows go/no-go report verdict', () => {
  assert.equal(finalExitCode(0), 0);
  assert.equal(finalExitCode(1), 1);
});

test('backendPytestEnv targets the docker-compose stack by default', () => {
  const env = backendPytestEnv({});

  assert.equal(env.E2E_FULL_STACK, '1');
  assert.equal(env.E2E_FULL_STACK_BASE_URL, 'http://localhost:8000');
  assert.equal(env.DATABASE_URL, 'postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol');
});

test('playwrightEnv writes JSON reporter output to a file', () => {
  const env = playwrightEnv('/tmp/playwright-report.json', {});

  assert.equal(env.BASE_URL, 'http://localhost:5173');
  assert.equal(env.PLAYWRIGHT_JSON_OUTPUT_FILE, '/tmp/playwright-report.json');
});
