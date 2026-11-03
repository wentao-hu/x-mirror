import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { createHash } from 'node:crypto';

const path = new URL('../functions/api/search.js', import.meta.url);
async function handler() {
  assert.ok(existsSync(path), '慢网络需要只传输命中结果的边缘搜索入口');
  return (await import(path)).onRequest;
}
const raw = readFileSync(new URL('../assets/search-index.json', import.meta.url));
const version = createHash('sha256').update(raw).digest('hex').slice(0, 8);
const request = (query, options = {}) => new Request(`https://example.com/api/search?q=${encodeURIComponent(query)}&v=${version}`, options);

test('边缘搜索返回仅正文命中与片段，而非传输全部正文', async () => {
  const run = await handler();
  const response = await run({ request: request('优待期') });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.version, version);
  assert.deepEqual(body.results.map(r => r.slug), ['xiaofeiyang-gsc-simulator-new-site-traffic-6-lessons']);
  assert.ok(body.results[0].snippet.includes('优待期'));
  assert.ok(JSON.stringify(body).length < 1500);
});
test('多关键词跨字段与标题范围沿用相同引擎', async () => {
  const run = await handler();
  const response = await run({ request: request('小肥羊 优待期') });
  assert.equal((await response.json()).results.length, 1);
  const title = await run({ request: new Request(request('优待期').url + '&scope=title') });
  assert.deepEqual((await title.json()).results, []);
});
test('旧版本和不支持的方法明确报错', async () => {
  const run = await handler();
  const stale = await run({ request: new Request('https://example.com/api/search?q=SEO&v=old') });
  assert.equal(stale.status, 409);
  const post = await run({ request: request('SEO', {method: 'POST'}) });
  assert.equal(post.status, 405);
  const huge = await run({ request: request('字'.repeat(501)) });
  assert.equal(huge.status, 400);
});
