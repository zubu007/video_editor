import test from 'node:test';
import assert from 'node:assert/strict';

import { buildDeathCutEdits } from './deathCuts.js';

test('buildDeathCutEdits keeps normal and quick-buyback intervals at zero padding', () => {
  const result = buildDeathCutEdits(
    [
      { start: 10, end: 25 },
      { start: 40, end: 41.1 },
    ],
    0,
    'asset-1'
  );

  assert.equal(result.skipped, 0);
  assert.deepEqual(
    result.edits.map(({ start, end }) => ({ start, end })),
    [
      { start: 10, end: 25 },
      { start: 40, end: 41.1 },
    ]
  );
});

test('buildDeathCutEdits skips intervals entirely consumed by padding', () => {
  const result = buildDeathCutEdits(
    [
      { start: 10, end: 10.8 },
      { start: 20, end: 30 },
    ],
    1.5,
    'asset-1'
  );

  assert.equal(result.skipped, 1);
  assert.equal(result.edits.length, 1);
  assert.equal(result.edits[0].start, 21.5);
  assert.equal(result.edits[0].end, 30);
});
