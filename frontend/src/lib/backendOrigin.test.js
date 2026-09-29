import test from 'node:test';
import assert from 'node:assert/strict';
import { isBackendRequest } from './backendOrigin.js';

const backend = 'https://nova.example';
test('credentials follow the exact backend origin', () => {
  for (const input of ['/operator/status', backend + '/operator/status', new URL(backend + '/health'), new Request(backend + '/health')]) {
    assert.equal(isBackendRequest(input, backend, backend + '/app'), true);
  }
});
test('similar hosts, userinfo, protocol-relative outsiders and ports get no credential', () => {
  for (const input of ['https://nova.example.evil.test', 'https://nova.example@evil.test', '//evil.test/path', 'https://nova.example:8443', 'http://nova.example']) {
    assert.equal(isBackendRequest(input, backend, backend + '/app'), false);
  }
  assert.equal(isBackendRequest('/dev-script', backend, 'http://localhost:5173'), false);
});
