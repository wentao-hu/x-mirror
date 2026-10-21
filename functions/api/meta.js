/**
 * X Mirror · 评分 / 已读 API
 *
 * GET /api/meta   -> { ok, items: { [slug]: { rating, read, updatedAt } } }
 * PUT /api/meta   -> body { slug, rating?, read?, pinned?, updatedAt }
 *                    按 updatedAt 做 last-write-wins，返回 { ok, applied, item }
 *
 * 全部条目存在单个 KV key `meta:v1`。个人站点、文章数 <1000，读改写足够；
 * 多请求同时写同一 key 有小概率互相覆盖，个人使用可接受。
 */

const KEY = 'meta:v1';
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,79}$/;
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

function clampRating(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(5, Math.round(n)));
}

function isValidDate(value) {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

function normalizeItem(value) {
  const item = value && typeof value === 'object' ? value : {};
  return {
    rating: clampRating(item.rating),
    read: item.read === true,
    pinned: item.pinned === true,
    updatedAt: isValidDate(item.updatedAt) ? new Date(item.updatedAt).toISOString() : null,
  };
}

function parseTime(value) {
  const t = Date.parse(value || '');
  return Number.isNaN(t) ? 0 : t;
}

async function readAll(kv) {
  const raw = await kv.get(KEY, { type: 'json' });
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const items = {};
  for (const [slug, item] of Object.entries(raw)) {
    if (SLUG_RE.test(slug)) items[slug] = normalizeItem(item);
  }
  return items;
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === 'OPTIONS') return preflight();
  if (!env || !env.ARTICLE_META) {
    return json({ ok: false, error: 'KV binding ARTICLE_META is not configured' }, 500);
  }
  const kv = env.ARTICLE_META;

  if (request.method === 'GET') {
    const items = await readAll(kv);
    return json({ ok: true, items });
  }

  if (request.method === 'PUT') {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, error: 'invalid JSON body' }, 400);
    }
    if (!body || typeof body !== 'object') {
      return json({ ok: false, error: 'invalid JSON body' }, 400);
    }

    const slug = typeof body.slug === 'string' ? body.slug.trim() : '';
    if (!SLUG_RE.test(slug)) {
      return json({ ok: false, error: 'slug must match [a-z0-9-]' }, 400);
    }

    const hasRating = Object.prototype.hasOwnProperty.call(body, 'rating');
    const hasRead = Object.prototype.hasOwnProperty.call(body, 'read');
    const hasPinned = Object.prototype.hasOwnProperty.call(body, 'pinned');
    if (!hasRating && !hasRead && !hasPinned) {
      return json({ ok: false, error: 'rating, read or pinned is required' }, 400);
    }

    let rating;
    if (hasRating) {
      const n = Number(body.rating);
      if (!Number.isInteger(n) || n < 0 || n > 5) {
        return json({ ok: false, error: 'rating must be an integer between 0 and 5' }, 400);
      }
      rating = n;
    }

    let read;
    if (hasRead) {
      if (typeof body.read !== 'boolean') {
        return json({ ok: false, error: 'read must be a boolean' }, 400);
      }
      read = body.read;
    }

    let pinned;
    if (hasPinned) {
      if (typeof body.pinned !== 'boolean') {
        return json({ ok: false, error: 'pinned must be a boolean' }, 400);
      }
      pinned = body.pinned;
    }

    const updatedAt = isValidDate(body.updatedAt)
      ? new Date(body.updatedAt).toISOString()
      : new Date().toISOString();

    const items = await readAll(kv);
    const prev = items[slug] || { rating: 0, read: false, pinned: false, updatedAt: null };

    // last-write-wins：比服务器旧的写入直接忽略，返回服务器现值。
    if (prev.updatedAt && parseTime(updatedAt) < parseTime(prev.updatedAt)) {
      return json({ ok: true, applied: false, slug, item: prev });
    }

    const next = {
      rating: hasRating ? rating : prev.rating,
      read: hasRead ? read : prev.read,
      pinned: hasPinned ? pinned : prev.pinned,
      updatedAt,
    };
    items[slug] = next;
    await kv.put(KEY, JSON.stringify(items));
    return json({ ok: true, applied: true, slug, item: next });
  }

  return json({ ok: false, error: 'method not allowed' }, 405);
}
