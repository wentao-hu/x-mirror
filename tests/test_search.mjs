import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';

const require = createRequire(import.meta.url);
const enginePath = new URL('../assets/search.js', import.meta.url);
function engine() {
  assert.ok(existsSync(enginePath), '首页需要可复用的全文匹配引擎');
  return require(enginePath.pathname);
}
const documents = [
  { slug: 'body', title: '实战经验', metadata: '小王 海外收款', text: '开头。提高付费转化率，谷歌会继续索引。末尾独有词。' },
  { slug: 'title', title: '付费转化率指南', metadata: '萧禹', text: '使用 Google Search Console 分析网站。' },
  { slug: 'metadata', title: '作者访谈', metadata: '付费转化率', text: '其他内容' },
  { slug: 'code', title: 'C++ 与 C#', metadata: '', text: 'ＦＯＯ 使用 <script>alert(1)</script> 与 emoji 😀。' },
  { slug: 'link', title: '链接条目', metadata: 'GSC 工具', text: '' },
];
const slugs = results => results.map(x => x.slug);

test('正文独有词命中，不要求标题重复', () => {
  const s = engine();
  assert.deepEqual(slugs(s.search(s.prepare(documents), '末尾独有词', 'all')), ['body']);
});
test('连续中文按片段精确匹配，不散字误召回', () => {
  const s = engine();
  const docs = s.prepare([{ slug: 'wrong', title: '付出', metadata: '', text: '收费与转向' }, ...documents]);
  assert.deepEqual(slugs(s.search(docs, '付费转化率', 'all')), ['title', 'metadata', 'body']);
});
test('多个关键词跨标题作者正文采用 AND', () => {
  const s = engine();
  const docs = s.prepare(documents);
  assert.deepEqual(slugs(s.search(docs, '小王 索引', 'all')), ['body']);
  assert.deepEqual(s.search(docs, '小王 不存在', 'all'), []);
});
test('仅标题不包括正文作者与标签', () => {
  const s = engine();
  const docs = s.prepare(documents);
  assert.deepEqual(slugs(s.search(docs, '付费转化率', 'title')), ['title']);
  assert.deepEqual(s.search(docs, '小王', 'title'), []);
});
test('归一化英文大小写全角与连续空白', () => {
  const s = engine();
  const docs = s.prepare(documents);
  assert.deepEqual(slugs(s.search(docs, '  ｇｏｏｇｌｅ　 SEARCH  ', 'all')), ['title']);
  assert.deepEqual(slugs(s.search(docs, 'foo', 'all')), ['code']);
});
test('特殊字符按字面搜索，不作为正则或 HTML 执行', () => {
  const s = engine();
  const docs = s.prepare(documents);
  for (const q of ['C++', 'C#', '<script>', '😀']) {
    assert.deepEqual(slugs(s.search(docs, q, 'all')), ['code']);
  }
  assert.deepEqual(s.search(docs, '[.*]', 'all'), []);
});
test('空搜索返回全部，外链条目也可检索元信息', () => {
  const s = engine();
  const docs = s.prepare(documents);
  assert.equal(s.search(docs, '   ', 'all').length, documents.length);
  assert.deepEqual(slugs(s.search(docs, 'gsc', 'all')), ['link']);
});
test('片段取命中位置，保留原文并返回安全文本分段', () => {
  const s = engine();
  const docs = s.prepare([{ slug: 'long', title: '标题', metadata: '', text: '远处内容。'.repeat(1000) + '只在末尾命中ＦＯＯ<script>。' }]);
  const [result] = s.search(docs, 'foo', 'all');
  assert.ok(result.snippet.length < 180);
  assert.ok(result.snippet.includes('ＦＯＯ<script>'));
  const parts = s.highlight(result.snippet, 'foo');
  assert.equal(parts.map(x => x.text).join(''), result.snippet);
  assert.equal(parts.filter(x => x.match).map(x => x.text).join(''), 'ＦＯＯ');
});
test('归一化后长度变化仍定位到原始字符', () => {
  const s = engine();
  const parts = s.highlight('使用ﬃ与ＦＯＯ', 'ffi foo');
  assert.deepEqual(parts.filter(x => x.match).map(x => x.text), ['ﬃ', 'ＦＯＯ']);
});

test('Unicode 前后伸缩抵消时仍正确定位命中范围', () => {
  const s = engine();
  const original = 'ﬃ é ö TARGET';
  assert.equal(original.length, s.normalize(original).length);
  const parts = s.highlight(original, 'é');
  assert.deepEqual(parts.filter(x => x.match).map(x => x.text), ['é']);
});

test('普通命中不为整篇混合全角正文创建 Unicode 映射', () => {
  const context = createContext({ module: { exports: {} }, Intl: {
    Segmenter: class { constructor() { throw new Error('不应扫描完整正文的字符簇'); } },
  }});
  runInContext(readFileSync(enginePath, 'utf8'), context);
  const s = context.module.exports;
  const docs = s.prepare([{slug:'long',title:'标题',metadata:'',text:'Ａ中文“'.repeat(10000)+' 优待期 正文'}]);
  assert.ok(s.search(docs, '优待期', 'all')[0].snippet.includes('优待期'));
});

test('索引损坏或首页与索引不是同批文章时拒绝假装完成', () => {
  const s = engine();
  assert.equal(typeof s.validate, 'function');
  assert.deepEqual(s.validate({ version: 1, documents }, documents.map(x => x.slug)), documents);
  assert.throws(() => s.validate({ version: 1, documents: documents.slice(1) }, documents.map(x => x.slug)));
  assert.throws(() => s.validate({ version: 1, documents: [documents[0], documents[0]] }, ['body']));
  assert.throws(() => s.validate({ version: 1, documents: [{ slug: 'body', title: '标题' }] }, ['body']));
});

test('无 Worker 时仍搜索全文，只加载一次，丢弃过期与清空前的查询', async () => {
  const s = engine();
  assert.equal(typeof s.createClient, 'function');
  const originalFetch = globalThis.fetch;
  let calls = 0, release;
  globalThis.fetch = async () => {
    calls++;
    await new Promise(resolve => { release = resolve; });
    return { ok: true, json: async () => ({ version: 1, documents }) };
  };
  const results = [], states = [];
  try {
    const client = s.createClient({
      documents: documents.map(x => ({ ...x, text: '' })), indexUrl: 'https://example.com/index.json',
      onResult: (rows, q) => results.push({ q, slugs: slugs(rows) }), onStatus: state => states.push(state),
    });
    assert.equal(calls, 0);
    client.search('付费转化率', 'title');
    assert.deepEqual(results.at(-1).slugs, ['title']);
    assert.equal(calls, 0);
    client.search('末尾独有词', 'all');
    client.search('google', 'all');
    const loaded = client.warm();
    release();
    await loaded;
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(calls, 1);
    assert.deepEqual(results.at(-1), { q: 'google', slugs: ['title'] });
    assert.equal(results.filter(x => x.q === '末尾独有词' && x.slugs.length).length, 0);
    client.search('末尾独有词', 'all');
    client.search('', 'all');
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(results.at(-1).q, '');
    assert.equal(results.at(-1).slugs.length, documents.length);
    assert.ok(states.includes('loading'));
  } finally { globalThis.fetch = originalFetch; }
});

test('失败后重新预热成功会自动补全当前正文查询', async () => {
  const s = engine();
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    if (++calls === 1) throw new Error('离线');
    return { ok: true, json: async () => ({ version: 1, documents }) };
  };
  const results = [];
  try {
    const client = s.createClient({
      documents: documents.map(doc => ({ ...doc, text: '' })), indexUrl: 'https://example.com/index.json',
      onResult: rows => results.push(slugs(rows)), onStatus() {},
    });
    client.search('末尾独有词', 'all');
    await assert.rejects(client.warm());
    await client.warm();
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.deepEqual(results.at(-1), ['body']);
  } finally { globalThis.fetch = original; }
});

test('边缘搜索只取结果，标题即出且相同查询复用缓存', async () => {
  const s = engine();
  assert.equal(typeof s.createRemoteClient, 'function');
  const actualFetch = globalThis.fetch;
  const urls = [], results = [], states = [];
  globalThis.fetch = async url => {
    urls.push(String(url));
    return { ok: true, json: async () => ({ok: true, version: 'v1', total: documents.length,
      results: [{slug: 'body', score: 1, snippet: '末尾独有词', match: 'body', order: 0}]}) };
  };
  try {
    const c = s.createRemoteClient({documents:documents.map(d=>({...d,text:''})),apiUrl:'https://example.com/api/search',version:'v1',onResult:r=>results.push(slugs(r)),onStatus:x=>states.push(x)});
    c.search('末尾独有词', 'all');
    await new Promise(r=>setTimeout(r,10));
    assert.deepEqual(results.at(-1),['body']);
    assert.equal(urls.length,1);
    assert.ok(urls[0].includes('/api/search?'));
    c.search('末尾独有词', 'all');
    assert.equal(urls.length,1);
    c.search('付费转化率', 'title');
    assert.deepEqual(results.at(-1),['title']);
    assert.equal(urls.length,1);
    assert.ok(states.includes('searching'));
  } finally {globalThis.fetch=actualFetch;}
});

test('加载失败可重试，不永久缓存失败结果', async () => {
  const s = engine();
  assert.equal(typeof s.createClient, 'function');
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    if (calls === 1) throw new Error('离线');
    return { ok: true, json: async () => ({ version: 1, documents }) };
  };
  const states = [];
  try {
    const client = s.createClient({ documents, indexUrl: 'https://example.com/index.json', onStatus: x => states.push(x), onResult() {} });
    await assert.rejects(client.warm(), /离线/);
    assert.equal(states.at(-1), 'error');
    await client.warm();
    assert.equal(calls, 2);
    assert.equal(states.at(-1), 'ready');
  } finally { globalThis.fetch = originalFetch; }
});
