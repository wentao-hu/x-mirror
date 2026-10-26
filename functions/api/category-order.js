/**
 * X Mirror · 分类顺序偏好 API
 *
 * GET /api/category-order -> { ok, order, updatedAt }
 * PUT /api/category-order -> body { order, updatedAt }
 * order 必须是 taxonomy 正式分类的完整排列；alias 只用于读取旧状态。
 *
 * 分类顺序与文章评分共用 ARTICLE_META KV，但使用独立 key。
 * 按 updatedAt 做 last-write-wins，便于多端同步和离线后补传。
 */

import { CATEGORY_ALIASES, CATEGORY_NAMES } from '../_lib/category-names.js';

const KEY = 'category-order:v1';
const MAX_CATEGORIES = 100;
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, PUT, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Accept',
  'Access-Control-Max-Age': '86400',
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      ...CORS_HEADERS,
    },
  });
}

function preflight() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

function isValidDate(value) {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

function parseTime(value) {
  const t = Date.parse(value || '');
  return Number.isNaN(t) ? 0 : t;
}

function normalizeKey(value) {
  return value.normalize('NFKC').replace(/\s+/g, '').toLowerCase();
}

const ALLOWED = new Set(CATEGORY_NAMES);
const ALIASES = new Map(
  Object.entries(CATEGORY_ALIASES).map(([alias, category]) => [normalizeKey(alias), category])
);
const ALLOWED_BY_KEY = new Map(CATEGORY_NAMES.map((name) => [normalizeKey(name), name]));

function canonicalStockOrder() {
  return CATEGORY_NAMES.slice();
}

function sanitizeStoredOrder(value) {
  if (!Array.isArray(value) || value.length > MAX_CATEGORIES) return null;
  const seen = new Set();
  const order = [];
  for (const raw of value) {
    if (typeof raw !== 'string') continue;
    const key = normalizeKey(raw.trim());
    const category = ALLOWED.has(raw.trim())
      ? raw.trim()
      : (ALIASES.get(key) || ALLOWED_BY_KEY.get(key));
    if (!category || seen.has(category)) continue;
    seen.add(category);
    order.push(category);
  }
  CATEGORY_NAMES.forEach((category) => {
    if (!seen.has(category)) order.push(category);
  });
  return order;
}

function normalizeSubmittedOrder(value) {
  if (!Array.isArray(value) || value.length !== CATEGORY_NAMES.length) return null;
  const seen = new Set();
  const order = [];
  for (const raw of value) {
    if (typeof raw !== 'string') return null;
    const category = raw.trim();
    if (!ALLOWED.has(category) || seen.has(category)) return null;
    seen.add(category);
    order.push(category);
  }
  return seen.size === CATEGORY_NAMES.length ? order : null;
}

async function readCurrent(kv) {
  const raw = await kv.get(KEY, { type: 'json' });
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { order: canonicalStockOrder(), updatedAt: null };
  }
  const storedOrder = sanitizeStoredOrder(raw.order);
  return {
    order: storedOrder || canonicalStockOrder(),
    updatedAt: isValidDate(raw.updatedAt) ? new Date(raw.updatedAt).toISOString() : null,
  };
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === 'OPTIONS') return preflight();
  if (!env || !env.ARTICLE_META) {
    return json({ ok: false, error: 'KV binding ARTICLE_META is not configured' }, 500);
  }
  const kv = env.ARTICLE_META;

  if (request.method === 'GET') {
    const current = await readCurrent(kv);
    return json({ ok: true, ...current });
  }

  if (request.method === 'PUT') {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, error: 'invalid JSON body' }, 400);
    }

    const order = normalizeSubmittedOrder(body && body.order);
    if (!order) {
      return json(
        { ok: false, error: 'order must be a complete permutation of official categories' },
        400
      );
    }

    const updatedAt = isValidDate(body.updatedAt)
      ? new Date(body.updatedAt).toISOString()
      : new Date().toISOString();
    const current = await readCurrent(kv);

    if (current.updatedAt && parseTime(updatedAt) < parseTime(current.updatedAt)) {
      return json({ ok: true, applied: false, ...current });
    }

    const next = { order, updatedAt };
    await kv.put(KEY, JSON.stringify(next));
    return json({ ok: true, applied: true, ...next });
  }

  return json({ ok: false, error: 'method not allowed' }, 405);
}
