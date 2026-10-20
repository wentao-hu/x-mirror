/* X Mirror · 评分与已读
 * 数据源：Cloudflare Pages Function + KV（ARTICLE_META），localStorage 作为即时缓存。
 * 合并规则：按每条 slug 的 updatedAt（ISO）做 last-write-wins。
 */
(function (global) {
  'use strict';

  var META_KEY = 'x-mirror-meta-v1';
  var API_URL = '/api/meta';
  var IS_FILE = global.location && global.location.protocol === 'file:';
  var SLUG_RE = /^[a-z0-9][a-z0-9-]{0,79}$/;

  var state = {
    map: {},        // slug -> { rating, read, updatedAt }
    server: null,   // null=未返回，false=请求失败，true=已同步
    ready: false
  };

  /* ---------- 基础工具 ---------- */

  function nowISO() {
    return new Date().toISOString();
  }

  function parseTs(value) {
    var t = Date.parse(value || '');
    return isNaN(t) ? 0 : t;
  }

  function clampRating(value) {
    var n = Number(value);
    if (!isFinite(n)) return 0;
    n = Math.round(n);
    if (n < 0) return 0;
    if (n > 5) return 5;
    return n;
  }

  function norm(item) {
    item = item && typeof item === 'object' ? item : {};
    return {
      rating: clampRating(item.rating),
      read: item.read === true,
      updatedAt: typeof item.updatedAt === 'string' && !isNaN(Date.parse(item.updatedAt))
        ? new Date(item.updatedAt).toISOString()
        : null
    };
  }

  function loadLocal() {
    var out = {};
    try {
      var raw = global.localStorage.getItem(META_KEY);
      if (!raw) return out;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return out;
      Object.keys(parsed).forEach(function (slug) {
        if (SLUG_RE.test(slug)) out[slug] = norm(parsed[slug]);
      });
    } catch (e) { /* 隐私模式 / 非法 JSON：退回空表 */ }
    return out;
  }

  function saveLocal(map) {
    try {
      global.localStorage.setItem(META_KEY, JSON.stringify(map));
    } catch (e) { /* localStorage 不可用时只保留内存状态 */ }
  }

  /* 逐 slug 取 updatedAt 较新的一条；相同时间取 server（第二个参数）。 */
  function merge(a, b) {
    var out = {};
    var keys = Object.keys(a || {}).concat(Object.keys(b || {}));
    keys.forEach(function (slug) {
      if (!SLUG_RE.test(slug)) return;
      var x = a && a[slug] ? norm(a[slug]) : null;
      var y = b && b[slug] ? norm(b[slug]) : null;
      if (!x && !y) return;
      if (!x) { out[slug] = y; return; }
      if (!y) { out[slug] = x; return; }
      out[slug] = parseTs(y.updatedAt) >= parseTs(x.updatedAt) ? y : x;
    });
    return out;
  }

  function get(slug) {
    return norm(state.map[slug]);
  }

  /* ---------- 服务端 ---------- */

  function fetchServer() {
    if (IS_FILE || typeof global.fetch !== 'function') return Promise.resolve(null);
    return global.fetch(API_URL, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (data) {
      if (!data || data.ok !== true || !data.items || typeof data.items !== 'object') {
        throw new Error('bad payload');
      }
      var out = {};
      Object.keys(data.items).forEach(function (slug) {
        if (SLUG_RE.test(slug)) out[slug] = norm(data.items[slug]);
      });
      return out;
    }).catch(function () {
      return null;
    });
  }

  function putServer(slug, item) {
    return global.fetch(API_URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        slug: slug,
        rating: item.rating,
        read: item.read,
        updatedAt: item.updatedAt
      })
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  function putWithRetry(slug, item, retries) {
    return putServer(slug, item).catch(function (err) {
      if (retries <= 0) throw err;
      return new Promise(function (resolve) { setTimeout(resolve, 1200); })
        .then(function () { return putWithRetry(slug, item, retries - 1); });
    });
  }

  /* 本地比服务器新的条目，登录后静默补传（LWW 保证不会覆盖更新的数据）。 */
  function pushNewer(merged, server) {
    var queue = [];
    Object.keys(merged).forEach(function (slug) {
      var mine = merged[slug];
      var theirs = server[slug];
      if (!theirs || parseTs(mine.updatedAt) > parseTs(theirs.updatedAt)) queue.push(slug);
    });
    queue.slice(0, 50).forEach(function (slug) {
      putWithRetry(slug, merged[slug], 1).catch(function () { /* 下次打开再补 */ });
    });
  }

  var ready = (function () {
    state.map = loadLocal();
    if (IS_FILE) {
      state.server = false;
      state.ready = true;
      return Promise.resolve(state.map);
    }
    return fetchServer().then(function (server) {
      if (server === null) {
        state.server = false;
        state.ready = true;
        return state.map;
      }
      state.server = true;
      var local = state.map;          // 可能已包含 ready 之前的用户点击
      var merged = merge(local, server);
      state.map = merged;
      saveLocal(merged);
      state.ready = true;
      pushNewer(merged, server);
      return merged;
    });
  })();

  function setMeta(slug, patch) {
    slug = String(slug || '');
    if (!SLUG_RE.test(slug)) return Promise.resolve(false);
    patch = patch || {};
    var cur = get(slug);
    var next = norm({
      rating: patch.rating != null ? patch.rating : cur.rating,
      read: patch.read != null ? patch.read : cur.read,
      updatedAt: nowISO()
    });
    state.map[slug] = next;
    saveLocal(state.map);
    if (IS_FILE || typeof global.fetch !== 'function') return Promise.resolve(true);
    return putWithRetry(slug, next, 1).then(function () {
      return true;
    }, function () {
      return false;   // 本地已落盘，下次加载时 pushNewer 会补传
    });
  }

  /* ---------- 星级渲染 ---------- */

  function starsHtml(rating, interactive) {
    rating = clampRating(rating);
    var label = rating ? '评分 ' + rating + ' 星（共 5 星）' : '未评分';
    var i;
    if (!interactive) {
      var cells = '';
      for (i = 1; i <= 5; i++) {
        cells += '<span class="xr-star' + (i <= rating ? ' on' : '') + '" aria-hidden="true">★</span>';
      }
      return '<span class="xr-stars" role="img" aria-label="' + label + '">' + cells + '</span>';
    }
    var btns = '';
    for (i = 1; i <= 5; i++) {
      btns += '<button type="button" class="xr-star' + (i <= rating ? ' on' : '') +
        '" data-v="' + i + '" aria-label="设为 ' + i + ' 星"' +
        ' aria-pressed="' + (i <= rating ? 'true' : 'false') + '">★</button>';
    }
    return '<div class="xr-rating" role="group" aria-label="' + label +
      '，再次点击当前分数可清除">' + btns + '</div>';
  }

  /* ---------- 文章页控件 ---------- */

  function initPostControls(slug) {
    var mount = document.querySelector('[data-meta-mount]:not(.card-controls)');
    if (!mount) return;
    slug = slug || mount.dataset.slug;
    if (!SLUG_RE.test(String(slug || ''))) return;
    mount.dataset.slug = slug;
    if (mount.dataset.xmBound !== '1') {
      mount.dataset.xmBound = '1';
      bindPostEvents(mount);
    }
    renderPost(mount, slug);
    ready.then(function () { renderPost(mount, slug); });
  }

  function postNote() {
    if (IS_FILE) return '本地文件模式：评分与已读只保存在本机浏览器。';
    if (state.server === null) return '正在连接 Cloudflare KV…';
    if (state.server === false) return '暂未连上 Cloudflare，已存本机，联网后自动同步。';
    return '已保存到本机，并同步 Cloudflare KV。';
  }

  function renderPost(mount, slug) {
    var m = get(slug);
    var ratingText = m.rating ? m.rating + ' 星' : '未评分';
    mount.innerHTML =
      '<div class="pc-row">' +
        '<span class="pc-label">我的评分</span>' +
        starsHtml(m.rating, true) +
        '<span class="pc-rating-text">' + ratingText + '</span>' +
        (m.rating ? '<button type="button" class="pc-clear" data-act="clear">清除</button>' : '') +
      '</div>' +
      '<div class="pc-row">' +
        '<button type="button" class="pc-read' + (m.read ? ' on' : '') + '" data-act="read"' +
          ' aria-pressed="' + (m.read ? 'true' : 'false') + '">' +
          '<span class="pc-dot" aria-hidden="true"></span>' +
          (m.read ? '已读完' : '标记为已读完') +
        '</button>' +
      '</div>' +
      '<div class="pc-note" data-note>' + postNote() + '</div>';
  }

  /* ---------- 目录卡片控件（link_only 无详情页） ---------- */

  function renderCard(mount, slug) {
    var m = get(slug);
    mount.innerHTML =
      '<div class="cc-row">' +
        starsHtml(m.rating, true) +
        '<button type="button" class="pc-read' + (m.read ? ' on' : '') + '" data-act="read"' +
          ' aria-pressed="' + (m.read ? 'true' : 'false') + '">' +
          '<span class="pc-dot" aria-hidden="true"></span>' +
          (m.read ? '已读完' : '标记为已读完') +
        '</button>' +
      '</div>';
  }

  function initCardControls() {
    var mounts = document.querySelectorAll('.card-controls[data-meta-mount][data-slug]');
    Array.prototype.forEach.call(mounts, function (mount) {
      var slug = mount.dataset.slug;
      if (!SLUG_RE.test(String(slug || ''))) return;
      if (mount.dataset.xmBound !== '1') {
        mount.dataset.xmBound = '1';
        bindCardEvents(mount);
      }
      renderCard(mount, slug);
      ready.then(function () { renderCard(mount, slug); });
    });
  }

  function renderMetaMount(mount, slug) {
    if (mount.classList && mount.classList.contains('card-controls')) renderCard(mount, slug);
    else renderPost(mount, slug);
  }

  function paintStars(mount, n) {
    var stars = mount.querySelectorAll('.xr-rating .xr-star');
    for (var i = 0; i < stars.length; i++) {
      stars[i].classList.toggle('on', i < n);
    }
  }

  function applyPatch(mount, slug, patch) {
    var done = setMeta(slug, patch);  // 同步更新内存 + localStorage
    renderMetaMount(mount, slug);     // 立即按新值重绘（乐观 UI）
    if (mount.dispatchEvent && typeof global.CustomEvent === 'function') {
      mount.dispatchEvent(new global.CustomEvent('xm-meta-change', { bubbles: true }));
    }
    done.then(function (ok) {
      var note = mount.querySelector('[data-note]');
      if (!note || IS_FILE) return;
      note.textContent = ok
        ? '已保存到本机，并同步 Cloudflare KV。'
        : '已存本机；同步失败，联网后会补同步。';
    });
  }

  function bindPostEvents(mount) {
    mount.addEventListener('click', function (e) {
      var target = e.target.closest ? e.target.closest('[data-v],[data-act]') : null;
      if (!target || !mount.contains(target)) return;
      var slug = mount.dataset.slug;
      var m = get(slug);
      if (target.classList.contains('xr-star')) {
        var v = Number(target.dataset.v);
        applyPatch(mount, slug, { rating: v === m.rating ? 0 : v }); // 再点当前分数 = 清除
      } else if (target.dataset.act === 'read') {
        applyPatch(mount, slug, { read: !m.read });
      } else if (target.dataset.act === 'clear') {
        applyPatch(mount, slug, { rating: 0 });
      }
    });

    mount.addEventListener('mouseover', function (e) {
      var star = e.target.closest ? e.target.closest('.xr-star') : null;
      if (!star || !mount.contains(star)) return;
      paintStars(mount, Number(star.dataset.v));
    });

    mount.addEventListener('mouseout', function (e) {
      var star = e.target.closest ? e.target.closest('.xr-star') : null;
      if (!star || !mount.contains(star)) return;
      var to = e.relatedTarget;
      if (to && mount.contains(to) && to.closest && to.closest('.xr-star')) return;
      paintStars(mount, get(mount.dataset.slug).rating);
    });
  }

  function bindCardEvents(mount) {
    mount.addEventListener('click', function (e) {
      // 卡片上只有标题是链接；控件点击不得触发跳转/冒泡
      e.stopPropagation();
      var target = e.target.closest ? e.target.closest('[data-v],[data-act]') : null;
      if (!target || !mount.contains(target)) return;
      e.preventDefault();
      var slug = mount.dataset.slug;
      var m = get(slug);
      if (target.classList.contains('xr-star')) {
        var v = Number(target.dataset.v);
        applyPatch(mount, slug, { rating: v === m.rating ? 0 : v }); // 再点当前分数 = 清除
      } else if (target.dataset.act === 'read') {
        applyPatch(mount, slug, { read: !m.read });
      } else if (target.dataset.act === 'clear') {
        applyPatch(mount, slug, { rating: 0 });
      }
    });

    mount.addEventListener('mouseover', function (e) {
      var star = e.target.closest ? e.target.closest('.xr-star') : null;
      if (!star || !mount.contains(star)) return;
      paintStars(mount, Number(star.dataset.v));
    });

    mount.addEventListener('mouseout', function (e) {
      var star = e.target.closest ? e.target.closest('.xr-star') : null;
      if (!star || !mount.contains(star)) return;
      var to = e.relatedTarget;
      if (to && mount.contains(to) && to.closest && to.closest('.xr-star')) return;
      paintStars(mount, get(mount.dataset.slug).rating);
    });
  }

  /* ---------- 目录页筛选 / 排序 ---------- */

  function initIndexFilters() {
    var list = document.getElementById('list');
    if (!list || list.dataset.xmFiltersReady === '1') return;
    var cards = Array.prototype.slice.call(list.querySelectorAll('.card[data-slug]'));
    if (!cards.length) return;
    list.dataset.xmFiltersReady = '1';

    var COLLAPSED_KEY = 'x-mirror-collapsed-v1';
    var FILTER_OPEN_KEY = 'x-mirror-filter-open-v1';
    var TIME_WINDOWS = { '7d': 7 * 864e5, '30d': 30 * 864e5, '90d': 90 * 864e5 };

    var snapshot = Array.prototype.slice.call(list.children); // 原始顺序（含分类标题）
    var catHeads = Array.prototype.slice.call(list.querySelectorAll('.cat[data-cat]'));
    var statusEl = document.getElementById('meta-status');
    var countEl = document.getElementById('meta-count');
    var summaryEl = document.getElementById('filter-summary');
    var panel = document.getElementById('filter-panel');
    var toggle = document.getElementById('filter-toggle');
    var listActions = document.getElementById('list-actions');
    var ui = { term: '', cat: 'all', type: 'all', rating: 'all', read: 'all', time: 'all', sort: 'default' };

    function readJSON(key) {
      try {
        var raw = global.localStorage.getItem(key);
        var parsed = raw ? JSON.parse(raw) : null;
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (e) { return {}; }
    }
    function writeJSON(key, value) {
      try { global.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
    }
    function readFlag(key) {
      try { return global.localStorage.getItem(key) === '1'; } catch (e) { return false; }
    }
    function writeFlag(key, value) {
      try { global.localStorage.setItem(key, value ? '1' : '0'); } catch (e) { /* ignore */ }
    }

    var collapsed = readJSON(COLLAPSED_KEY);

    function metaFor(el) { return get(el.dataset.slug); }
    function originalIndex(el) { return snapshot.indexOf(el); }
    function catOf(el) { return el.dataset.cat || ''; }
    function publishedOf(el) {
      var t = Date.parse(el.dataset.published || '');
      return isNaN(t) ? 0 : t;
    }
    function filteringNow() {
      return !!(ui.term || '').trim() || ui.cat !== 'all' || ui.type !== 'all' ||
        ui.rating !== 'all' || ui.read !== 'all' || ui.time !== 'all';
    }
    function setCatCollapsed(cat, value) {
      collapsed[cat] = !!value;
      writeJSON(COLLAPSED_KEY, collapsed);
    }

    function updateFilterSummary() {
      if (!summaryEl) return;
      var parts = [];
      function add(bar, label, value) {
        if (value === 'all') return;
        var btn = bar ? bar.querySelector('button.active') : null;
        parts.push(label + '：' + (btn ? btn.textContent.trim() : value));
      }
      add(document.getElementById('filters'), '分类', ui.cat);
      add(document.querySelector('[data-meta-filter="type"]'), '类型', ui.type);
      add(document.querySelector('[data-meta-filter="rating"]'), '评分', ui.rating);
      add(document.querySelector('[data-meta-filter="read"]'), '阅读', ui.read);
      add(document.querySelector('[data-meta-filter="time"]'), '时间', ui.time);
      add(document.querySelector('[data-meta-filter="sort"]'), '排序', ui.sort === 'default' ? 'all' : ui.sort);
      summaryEl.textContent = parts.length ? parts.join(' · ') : '全部';
      if (toggle) toggle.classList.toggle('has-active', parts.length > 0);
    }

    function renderBadges() {
      cards.forEach(function (el) {
        // link_only 卡片自带可交互控件，跳过只读徽标，避免重复
        if (el.querySelector('.card-controls[data-meta-mount]')) return;
        var metaLine = el.querySelector('.cmeta');
        if (!metaLine) return;
        var box = metaLine.querySelector('.card-badges');
        if (!box) {
          box = document.createElement('span');
          box.className = 'card-badges';
          metaLine.appendChild(box);
        }
        var m = metaFor(el);
        box.innerHTML = starsHtml(m.rating, false) +
          (m.read ? '<span class="badge-read">已读</span>' : '');
      });
    }

    function sortedCards() {
      var arr = cards.slice();
      if (ui.sort === 'rating') {
        arr.sort(function (a, b) {
          return (metaFor(b).rating - metaFor(a).rating) || (originalIndex(a) - originalIndex(b));
        });
      } else if (ui.sort === 'unread') {
        arr.sort(function (a, b) {
          var ma = metaFor(a), mb = metaFor(b);
          if (ma.read !== mb.read) return ma.read ? 1 : -1;
          return (mb.rating - ma.rating) || (originalIndex(a) - originalIndex(b));
        });
      } else if (ui.sort === 'new') {
        arr.sort(function (a, b) {
          return (publishedOf(b) - publishedOf(a)) || (originalIndex(a) - originalIndex(b));
        });
      }
      return arr;
    }

    function apply() {
      var term = (ui.term || '').trim().toLowerCase();
      var now = Date.now();
      var filtering = filteringNow();

      cards.forEach(function (el) {
        var m = metaFor(el);
        var okCat = ui.cat === 'all' || catOf(el) === ui.cat;
        var okType = ui.type === 'all' || el.dataset.sourceType === ui.type;
        var okQ = !term || (el.dataset.q || '').toLowerCase().indexOf(term) >= 0;
        var okRating = ui.rating === 'all'
          ? true
          : (ui.rating === '0' ? m.rating === 0 : m.rating >= Number(ui.rating));
        var okRead = ui.read === 'all' ? true : (ui.read === 'yes' ? m.read : !m.read);
        var okTime = ui.time === 'all' ||
          (publishedOf(el) > 0 && now - publishedOf(el) <= TIME_WINDOWS[ui.time]);
        el._xmPass = okCat && okType && okQ && okRating && okRead && okTime;
        var folded = ui.sort === 'default' && !filtering && !!collapsed[catOf(el)];
        el._xmShow = el._xmPass && !folded;
        el.style.display = el._xmShow ? '' : 'none';
      });

      if (ui.sort === 'default') {
        snapshot.forEach(function (node) { list.appendChild(node); }); // 按原顺序归位
      } else {
        sortedCards().forEach(function (el) { list.appendChild(el); });
      }

      var shown = cards.filter(function (el) { return el._xmPass; }).length;
      catHeads.forEach(function (h) {
        var cat = h.dataset.cat || '';
        var folded = ui.sort === 'default' && !filtering && !!collapsed[cat];
        h.classList.toggle('is-collapsed', folded);
        h.classList.toggle('is-static', filtering);
        h.setAttribute('aria-expanded', folded ? 'false' : 'true');

        if (ui.sort !== 'default') { h.style.display = 'none'; return; }
        if (ui.cat !== 'all' && cat !== ui.cat) { h.style.display = 'none'; return; }

        var node = h.nextElementSibling;
        var total = 0, matched = 0;
        while (node && node.classList && node.classList.contains('card')) {
          total++;
          if (node._xmPass) matched++;
          node = node.nextElementSibling;
        }
        h.style.display = matched ? '' : 'none';
        var countNode = h.querySelector('.cat-count');
        if (countNode) countNode.textContent = filtering ? matched + ' / ' + total + ' 篇' : total + ' 篇';
      });

      if (listActions) listActions.style.display = (ui.sort === 'default' && !filtering) ? '' : 'none';
      if (countEl) {
        countEl.textContent = filtering ? '· 筛选命中 ' + shown + ' / ' + cards.length + ' 篇' : '';
      }
      if (statusEl) {
        statusEl.textContent = IS_FILE
          ? '本地文件模式：只读取本机浏览器里的评分与已读。'
          : (state.server === false
            ? '离线：正在使用本机缓存，联网后会自动同步。'
            : '评分与已读已从 Cloudflare KV 同步。');
      }
      updateFilterSummary();
    }

    function bindBar(bar, onPick) {
      if (!bar) return;
      bar.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('button') : null;
        if (!btn || !bar.contains(btn)) return;
        onPick(btn);
        Array.prototype.forEach.call(bar.querySelectorAll('button'), function (b) {
          b.classList.toggle('active', b === btn);
        });
        apply();
      });
    }

    bindBar(document.getElementById('filters'), function (btn) {
      ui.cat = btn.dataset.cat || 'all';
    });
    bindBar(document.querySelector('[data-meta-filter="type"]'), function (btn) {
      ui.type = btn.dataset.type || 'all';
    });
    bindBar(document.querySelector('[data-meta-filter="rating"]'), function (btn) {
      ui.rating = btn.dataset.rating || 'all';
    });
    bindBar(document.querySelector('[data-meta-filter="read"]'), function (btn) {
      ui.read = btn.dataset.read || 'all';
    });
    bindBar(document.querySelector('[data-meta-filter="time"]'), function (btn) {
      ui.time = btn.dataset.time || 'all';
    });
    bindBar(document.querySelector('[data-meta-filter="sort"]'), function (btn) {
      ui.sort = btn.dataset.sort || 'default';
    });

    var search = document.getElementById('q');
    if (search) {
      search.addEventListener('input', function () {
        ui.term = search.value;
        apply();
      });
    }

    function setPanelOpen(open, persist) {
      if (!panel || !toggle) return;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (persist) writeFlag(FILTER_OPEN_KEY, open);
    }
    setPanelOpen(readFlag(FILTER_OPEN_KEY), false);
    if (toggle && panel) {
      toggle.addEventListener('click', function () {
        setPanelOpen(panel.hidden, true);
      });
    }

    catHeads.forEach(function (h) {
      function flip() {
        if (filteringNow()) return;
        var cat = h.dataset.cat || '';
        setCatCollapsed(cat, !collapsed[cat]);
        apply();
      }
      h.addEventListener('click', flip);
      h.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          flip();
        }
      });
    });

    var expandAll = document.getElementById('expand-all');
    var collapseAll = document.getElementById('collapse-all');
    if (expandAll) {
      expandAll.addEventListener('click', function () {
        catHeads.forEach(function (h) { collapsed[h.dataset.cat || ''] = false; });
        writeJSON(COLLAPSED_KEY, collapsed);
        apply();
      });
    }
    if (collapseAll) {
      collapseAll.addEventListener('click', function () {
        catHeads.forEach(function (h) { collapsed[h.dataset.cat || ''] = true; });
        writeJSON(COLLAPSED_KEY, collapsed);
        apply();
      });
    }

    list.addEventListener('xm-meta-change', function () {
      renderBadges();
      apply();
    });

    renderBadges();
    apply();
    ready.then(function () {
      renderBadges();
      apply();
    });
  }

  /* ---------- 自动初始化 ---------- */

  function autoInit() {
    if (document.getElementById('list')) {
      initCardControls();
      if (document.querySelector('#list .card[data-slug]')) initIndexFilters();
      return;
    }
    var mount = document.querySelector('[data-meta-mount][data-slug]:not(.card-controls)');
    if (mount) initPostControls(mount.dataset.slug);
  }

  global.XMirrorMeta = {
    META_KEY: META_KEY,
    ready: ready,
    loadLocal: loadLocal,
    saveLocal: saveLocal,
    fetchServer: fetchServer,
    merge: function (a, b) { return merge(a, b); },
    get: get,
    setMeta: setMeta,
    starsHtml: starsHtml,
    initIndexFilters: initIndexFilters,
    initCardControls: initCardControls,
    initPostControls: initPostControls
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInit);
  } else {
    autoInit();
  }
})(window);
