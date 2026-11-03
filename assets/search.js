/* 全文匹配引擎：浏览器、Web Worker 与 Node 测试共用，不依赖第三方库。 */
(function (global) {
  'use strict';

  function normalize(value) {
    return String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function tokens(query) {
    return Array.from(new Set(normalize(query).split(' ').filter(Boolean)));
  }

  function prepare(documents) {
    return documents.map(function (doc) {
      return {
        slug: doc.slug, title: doc.title || '', metadata: doc.metadata || '', text: doc.text || '',
        titleNorm: normalize(doc.title), metaNorm: normalize(doc.metadata), textNorm: normalize(doc.text)
      };
    });
  }

  // 只在 Unicode 归一化改变长度时创建映射；片段保留原文而非变小写后的副本。
  function offsetMap(text) {
    var units = typeof Intl.Segmenter === 'function'
      ? Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text), function (x) {
        return { text: x.segment, index: x.index };
      })
      : Array.from(text.matchAll(/\P{M}\p{M}*|\p{M}+/gu), function (x) {
        return { text: x[0], index: x.index };
      });
    var normalized = '', starts = [], ends = [];
    units.forEach(function (unit) {
      var value = unit.text.normalize('NFKC').toLowerCase().replace(/\s/g, ' ');
      for (var i = 0; i < value.length; i++) {
        if (value[i] === ' ' && (!normalized || normalized.endsWith(' '))) continue;
        normalized += value[i];
        starts.push(unit.index);
        ends.push(unit.index + unit.text.length);
      }
    });
    return { text: normalized.trimEnd(), starts: starts, ends: ends };
  }

  function rawRange(text, normalized, start, end, owner) {
    // ASCII、常见中文及全角字符归一化不改变字符位置；其他字符懒建并复用映射。
    var stable = owner && owner.stableOffsets;
    if (stable === undefined) {
      stable = text.length === normalized.length && (text.toLowerCase() === normalized
        || /^[\x20-\x7e⺀-鿿！-～]*$/.test(text));
      if (owner) owner.stableOffsets = stable;
    }
    if (stable) return [start, end];
    var map = owner && owner.offsets;
    if (!map) { map = offsetMap(text); if (owner) owner.offsets = map; }
    return [map.starts[start] || 0, map.ends[end - 1] || text.length];
  }

  function snippet(doc, terms) {
    var first = -1, length = 0;
    terms.forEach(function (term) {
      var at = doc.textNorm.indexOf(term);
      if (at >= 0 && (first < 0 || at < first)) { first = at; length = term.length; }
    });
    if (first < 0) return '';
    // 先直接在原文找已命中的词，只有兼容字符本身命中时才需要整篇位置映射。
    var lower = doc.text.toLowerCase();
    var direct = lower.indexOf(doc.textNorm.slice(first, first + length));
    var range = direct >= 0 && lower.length === doc.text.length
      ? [direct, direct + length] : rawRange(doc.text, doc.textNorm, first, first + length, doc);
    var start = Math.max(0, range[0] - 36);
    var end = Math.min(doc.text.length, Math.max(start + 140, range[1]));
    return (start ? '…' : '') + doc.text.slice(start, end) + (end < doc.text.length ? '…' : '');
  }

  function search(documents, query, scope) {
    var terms = tokens(query), phrase = normalize(query), results = [];
    documents.forEach(function (doc, index) {
      var titleHits = 0, metaHits = 0;
      var pass = terms.every(function (term) {
        if (doc.titleNorm.includes(term)) { titleHits++; return true; }
        if (scope === 'title') return false;
        if (doc.metaNorm.includes(term)) { metaHits++; return true; }
        return doc.textNorm.includes(term);
      });
      if (!pass) return;
      var tier = !terms.length ? 0 : titleHits ? 3 : metaHits ? 2 : 1;
      results.push({
        slug: doc.slug,
        score: tier + (terms.length ? titleHits / terms.length * 0.5 + metaHits / terms.length * 0.1 : 0)
          + (phrase && doc.titleNorm === phrase ? 0.2 : 0),
        snippet: scope === 'title' || !terms.length ? '' : snippet(doc, terms),
        match: titleHits ? 'title' : metaHits ? 'metadata' : 'body',
        order: index
      });
    });
    return results.sort(function (a, b) { return b.score - a.score || a.order - b.order; });
  }

  // 返回文本分段，调用者用 textContent / createTextNode，绝不 innerHTML 注入正文。
  function highlight(text, query) {
    var normalized = normalize(text), ranges = [], offsets = {};
    tokens(query).forEach(function (term) {
      var pos = 0, at;
      while ((at = normalized.indexOf(term, pos)) >= 0) {
        ranges.push(rawRange(text, normalized, at, at + term.length, offsets));
        pos = at + term.length;
      }
    });
    ranges.sort(function (a, b) { return a[0] - b[0]; });
    var merged = [];
    ranges.forEach(function (range) {
      var last = merged[merged.length - 1];
      if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
      else merged.push(range.slice());
    });
    var parts = [], cursor = 0;
    merged.forEach(function (range) {
      if (range[0] > cursor) parts.push({ text: text.slice(cursor, range[0]), match: false });
      parts.push({ text: text.slice(range[0], range[1]), match: true });
      cursor = range[1];
    });
    if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false });
    return parts;
  }

  function validate(payload, expectedSlugs) {
    if (!payload || payload.version !== 1 || !Array.isArray(payload.documents)) {
      throw new Error('全文索引格式错误');
    }
    var slugs = new Set();
    payload.documents.forEach(function (doc) {
      if (!doc || ['slug', 'title', 'metadata', 'text'].some(function (key) {
        return typeof doc[key] !== 'string';
      }) || slugs.has(doc.slug)) throw new Error('全文索引条目不完整或重复');
      slugs.add(doc.slug);
    });
    if (slugs.size !== expectedSlugs.length || expectedSlugs.some(function (slug) { return !slugs.has(slug); })) {
      throw new Error('首页与全文索引版本不一致，请刷新页面');
    }
    return payload.documents;
  }

  function fetchIndex(url, expectedSlugs) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 15000);
    return global.fetch(url, { signal: controller.signal }).then(function (res) {
      if (!res.ok) throw new Error('全文索引 HTTP ' + res.status);
      return res.json();
    }).then(function (payload) {
      return prepare(validate(payload, expectedSlugs));
    }).finally(function () { clearTimeout(timer); });
  }

  function createClient(options) {
    var light = prepare(options.documents), expected = light.map(function (doc) { return doc.slug; });
    var full = null, worker = null, loadPromise = null, serial = 0, workerDisabled = false;
    var state = 'idle', current = null;
    function status(value) { state = value; options.onStatus(value); }
    function deliver(rows, request) {
      if (request.id === serial) options.onResult(rows, request.query, request.scope);
    }
    function readySearch(request) {
      if (request.id !== serial) return;
      if (worker) worker.postMessage({ type: 'search', request: request });
      else setTimeout(function () {
        if (request.id === serial) deliver(search(full, request.query, request.scope), request);
      }, 0);
    }
    function startWorker() {
      return new Promise(function (resolve, reject) {
        var active = new global.Worker(options.workerUrl);
        worker = active;
        var initialized = false;
        var timer = setTimeout(function () { fail(new Error('搜索 Worker 启动超时')); }, 16000);
        function fail(error) {
          clearTimeout(timer);
          active.terminate();
          if (worker === active) worker = null;
          workerDisabled = true;
          if (!initialized) reject(error);
          else {
            loadPromise = null;
            status('error');
            if (current) deliver(search(light, current.query, current.scope), current);
          }
        }
        active.onerror = function () { fail(new Error('搜索 Worker 不可用')); };
        active.onmessage = function (event) {
          var data = event.data;
          if (data.type === 'ready') { initialized = true; clearTimeout(timer); resolve(); }
          else if (data.type === 'result') deliver(data.results, data.request);
          else if (data.type === 'error') fail(new Error(data.message));
        };
        active.postMessage({ type: 'init', engineUrl: options.engineUrl, indexUrl: options.indexUrl, slugs: expected });
      });
    }
    function warm() {
      if (loadPromise) return loadPromise;
      status('loading');
      function fallback() {
        return fetchIndex(options.indexUrl, expected).then(function (docs) { full = docs; });
      }
      var loading = !workerDisabled && typeof global.Worker === 'function' && options.workerUrl
        ? startWorker().catch(fallback) : fallback();
      loadPromise = loading.then(function () {
        status('ready');
        if (current && normalize(current.query) && current.scope === 'all') readySearch(current);
      }, function (error) {
        loadPromise = null;
        status('error');
        throw error;
      });
      return loadPromise;
    }
    function run(query, scope) {
      var request = { id: ++serial, query: query, scope: scope };
      current = request;
      if (!normalize(query) || scope === 'title') {
        deliver(search(light, query, scope), request);
        return;
      }
      if (state === 'ready') readySearch(request);
      else {
        deliver(search(light, query, scope), request);
        warm().catch(function () { /* 状态与重试交给界面；加载成功后统一补全当前查询 */ });
      }
    }
    return { warm: warm, search: run };
  }

  function createRemoteClient(options) {
    var light = prepare(options.documents), cache = new Map(), serial = 0, controller = null;
    var fallback = null;
    function run(query, scope) {
      var id = ++serial;
      if (controller) controller.abort();
      if (fallback) { fallback.search(query, scope); return; }
      if (!normalize(query) || scope === 'title') {
        options.onStatus('ready');
        options.onResult(search(light, query, scope), query, scope);
        return;
      }
      var key = normalize(query) + '\n' + scope;
      if (cache.has(key)) {
        options.onStatus('ready');
        options.onResult(cache.get(key), query, scope);
        return;
      }
      options.onStatus('searching');
      options.onResult(search(light, query, scope), query, scope);
      controller = new AbortController();
      var active = controller;
      var timer = setTimeout(function () { active.abort(); }, 15000);
      var url = new URL(options.apiUrl);
      url.searchParams.set('q', query);
      url.searchParams.set('scope', scope);
      url.searchParams.set('v', options.version);
      global.fetch(url.href, { signal: active.signal }).then(function (res) {
        if (!res.ok) throw new Error('搜索 HTTP ' + res.status);
        return res.json();
      }).then(function (data) {
        if (!data.ok || data.version !== options.version || data.total !== light.length || !Array.isArray(data.results)) {
          throw new Error('搜索结果与首页版本不一致');
        }
        if (id !== serial) return;
        cache.set(key, data.results);
        options.onStatus('ready');
        options.onResult(data.results, query, scope);
      }).catch(function () {
        if (id !== serial) return;
        // 云端不可用时仍保留完整搜索能力，不把失败当无结果。
        fallback = createClient(options);
        fallback.search(query, scope);
      }).finally(function () { clearTimeout(timer); });
    }
    return {
      search: run,
      warm: function () {
        if (fallback) return fallback.warm();
        return Promise.resolve();
      }
    };
  }

  var api = {
    normalize: normalize, prepare: prepare, search: search, highlight: highlight,
    validate: validate, fetchIndex: fetchIndex, createClient: createClient, createRemoteClient: createRemoteClient
  };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else global.XMirrorSearch = api;
})(typeof self !== 'undefined' ? self : globalThis);
