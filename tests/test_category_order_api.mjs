import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/category-order.js';
import { CATEGORY_NAMES } from '../functions/_lib/category-names.js';

class MemoryKV {
  constructor() {
    this.values = new Map();
  }

  async get(key, options = {}) {
    const raw = this.values.get(key);
    if (raw == null) return null;
    return options.type === 'json' ? JSON.parse(raw) : raw;
  }

  async put(key, value) {
    this.values.set(key, value);
  }
}

const kv = new MemoryKV();
const env = { ARTICLE_META: kv };

function context(method, body) {
  const init = {
    method,
    headers: { Accept: 'application/json' },
  };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  return {
    env,
    request: new Request('https://example.com/api/category-order', init),
  };
}

let response = await onRequest(context('GET'));
assert.equal(response.status, 200);
assert.deepEqual(await response.json(), {
  ok: true,
  order: CATEGORY_NAMES,
  updatedAt: null,
});

const firstTime = '2026-10-23T15:00:00.000Z';
const firstOrder = [...CATEGORY_NAMES.slice(1), CATEGORY_NAMES[0]];
response = await onRequest(context('PUT', {
  order: firstOrder,
  updatedAt: firstTime,
}));
assert.equal(response.status, 200);
assert.equal((await response.json()).applied, true);

response = await onRequest(context('GET'));
assert.deepEqual(await response.json(), {
  ok: true,
  order: firstOrder,
  updatedAt: firstTime,
});

const staleOrder = CATEGORY_NAMES.slice().reverse();
response = await onRequest(context('PUT', {
  order: staleOrder,
  updatedAt: '2026-10-23T14:59:59.000Z',
}));
const stale = await response.json();
assert.equal(stale.applied, false);
assert.deepEqual(stale.order, firstOrder);

response = await onRequest(context('PUT', {
  order: [CATEGORY_NAMES[0], ...CATEGORY_NAMES.slice(0, -1)],
  updatedAt: '2026-10-23T16:00:00.000Z',
}));
assert.equal(response.status, 400);

response = await onRequest(context('PUT', {
  order: [...CATEGORY_NAMES.slice(0, -1), '不存在'],
  updatedAt: '2026-10-23T16:00:00.000Z',
}));
assert.equal(response.status, 400);

response = await onRequest(context('PUT', {
  order: CATEGORY_NAMES.slice(0, -1),
  updatedAt: '2026-10-23T16:00:00.000Z',
}));
assert.equal(response.status, 400);

const aliasKv = new MemoryKV();
await aliasKv.put('category-order:v1', JSON.stringify({
  order: ['AI 工具', '新词站实战复盘', 'SEO基础'],
  updatedAt: '2026-10-23T17:00:00.000Z',
}));
response = await onRequest({
  env: { ARTICLE_META: aliasKv },
  request: new Request('https://example.com/api/category-order', {
    method: 'GET',
    headers: { Accept: 'application/json' },
  }),
});
const aliased = await response.json();
assert.equal(aliased.order.length, CATEGORY_NAMES.length);
assert.deepEqual(aliased.order.slice(0, 3), ['AI工具', '实战复盘', 'SEO获客']);

console.log('category-order API tests passed');
