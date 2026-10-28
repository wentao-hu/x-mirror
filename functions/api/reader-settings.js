/**
 * X Mirror · 阅读设置 API
 *
 * GET /api/reader-settings -> { ok, settings: { fs, lh, w }, updatedAt }
 * PUT /api/reader-settings -> body { fs, lh, w, updatedAt }
 *
 * 与文章评分共用 ARTICLE_META KV，独立 key，按 updatedAt 做 last-write-wins。
 */

const KEY = 'reader-settings:v1';
const RANGES = {
  fs: [0.85, 1.5],
  lh: [0.85, 1.3],
  w: [0.6, 1.2],
};
const DEFAULTS = { fs: 1, lh: 1, w: 1 };
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

function clampField(key, value) {
  const [min, max] = RANGES[key];
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULTS[key];
  return Math.min(max, Math.max(min, Math.round(n * 100) / 100));
}

/* 三项都必须显式提交；越界值吸附到区间边界 */
function normalizeSettings(value) {
  if (!value || typeof value !== 'object') return null;
  for (const key of Object.keys(RANGES)) {
    if (typeof value[key] !== 'number' || !Number.isFinite(value[key])) return null;
  }
  return {
    fs: clampField('fs', value.fs),
    lh: clampField('lh', value.lh),
    w: clampField('w', value.w),
  };
}

async function readCurrent(kv) {
  const raw = await kv.get(KEY, { type: 'json' });
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { settings: { ...DEFAULTS }, updatedAt: null };
  }
  return {
    settings: normalizeSettings(raw.settings) || { ...DEFAULTS },
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

    const settings = normalizeSettings(body);
    if (!settings) {
      return json({ ok: false, error: 'fs, lh and w are required numbers' }, 400);
    }

    const updatedAt = isValidDate(body.updatedAt)
      ? new Date(body.updatedAt).toISOString()
      : new Date().toISOString();
    const current = await readCurrent(kv);

    if (current.updatedAt && parseTime(updatedAt) < parseTime(current.updatedAt)) {
      return json({ ok: true, applied: false, ...current });
    }

    const next = { settings, updatedAt };
    await kv.put(KEY, JSON.stringify(next));
    return json({ ok: true, applied: true, ...next });
  }

  return json({ ok: false, error: 'method not allowed' }, 405);
}
