import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spokenText } from './spokenText.js';

test('fenced code stays silent at every streamed prefix', () => {
  const response = 'Here it is.\n```js\nSECRET_CODE();\n```\nAll done.';
  for (let i = 1; i <= response.length; i++) {
    assert.ok(!spokenText(response.slice(0, i), false).includes('SECRET'));
  }
  assert.ok(spokenText(response).includes('Look at the transcript for the code.'));
  assert.ok(spokenText(response).includes('All done.'));
});
test('inline commands and unfinished fences are not read', () => {
  assert.ok(!spokenText('Run `find . -name test` please.').includes('find .'));
  assert.ok(!spokenText('~~~python\nprint(123)').includes('print'));
  assert.equal(spokenText('Hello there.'), 'Hello there.');
});
