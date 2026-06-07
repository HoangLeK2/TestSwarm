import assert from 'node:assert/strict';
import test from 'node:test';

import { createSingleFlight } from './single-flight.ts';

test('single-flight shares one in-flight call for the same key', async () => {
  let calls = 0;
  let release!: (value: string) => void;
  const fetchValue = createSingleFlight(async () => {
    calls += 1;
    return new Promise<string>((resolve) => {
      release = resolve;
    });
  });

  const first = fetchValue();
  const second = fetchValue();
  assert.equal(first, second);
  assert.equal(calls, 1);

  release('ok');
  assert.equal(await first, 'ok');

  const third = fetchValue();
  assert.notEqual(third, first);
  assert.equal(calls, 2);
});

test('single-flight separates concurrent calls by key', async () => {
  let calls = 0;
  const fetchValue = createSingleFlight(
    async (key: string) => {
      calls += 1;
      return key.toUpperCase();
    },
    (key) => key
  );

  const [a, b] = await Promise.all([fetchValue('a'), fetchValue('b')]);
  assert.equal(a, 'A');
  assert.equal(b, 'B');
  assert.equal(calls, 2);
});
