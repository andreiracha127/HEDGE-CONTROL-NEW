const assert = require('node:assert/strict');
const { test } = require('node:test');

const { spawnExitCode } = require('./run_go_no_go.js');

test('spawnExitCode treats signaled child process as failure', () => {
  assert.equal(spawnExitCode({ status: null, signal: 'SIGTERM' }), 1);
});

test('spawnExitCode returns numeric process status', () => {
  assert.equal(spawnExitCode({ status: 2, signal: null }), 2);
});
