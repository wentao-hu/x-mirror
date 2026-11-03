/* 边缘全文搜索：复用静态引擎，仅传输命中结果，避免慢网络下载整站正文。 */
import Search from '../../assets/search.js';
import payload from '../../assets/search-index.json' with { type: 'json' };
import { SEARCH_VERSION } from '../_lib/search-version.js';

const documents = Search.prepare(payload.documents);

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': status === 200 ? 'public, max-age=3600' : 'no-store',
    },
  });
}

export function onRequest({ request }) {
  if (request.method !== 'GET') return json({ ok: false, error: '只支持 GET' }, 405);
  const url = new URL(request.url);
  const query = url.searchParams.get('q') || '';
  if (query.length > 500) return json({ ok: false, error: '关键词过长' }, 400);
  if (url.searchParams.get('v') !== SEARCH_VERSION) {
    return json({ ok: false, error: '搜索版本已更新，请刷新页面' }, 409);
  }
  const scope = url.searchParams.get('scope') === 'title' ? 'title' : 'all';
  const results = Search.normalize(query) ? Search.search(documents, query, scope) : [];
  return json({ ok: true, version: SEARCH_VERSION, total: documents.length, results });
}
