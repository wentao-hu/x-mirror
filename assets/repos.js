/* X Mirror · GitHub 仓库浏览：排序与置顶
 * 置顶状态复用 meta.js 的 localStorage + Cloudflare KV 同步；slug 统一加 `repo-` 前缀。
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var META = global.XMirrorMeta;
  if (!doc || !META) return;

  var PREFIX = 'repo-';
  var SORT_KEY = 'x-mirror-repos-sort-v1';
  var COLLAPSE_KEY = 'x-mirror-repos-pinned-collapsed-v1';
  var SORT_MODES = { updated: true, name: true };
  var list = doc.getElementById('repo-list');
  var sortButtons = Array.prototype.slice.call(doc.querySelectorAll('.repo-sort [data-sort]'));

  function cards() {
    return list ? Array.prototype.slice.call(list.querySelectorAll('.repo-card[data-slug]')) : [];
  }

  function byName(a, b) {
    return (a.dataset.name || '').localeCompare(b.dataset.name || '', 'en', { sensitivity: 'base' });
  }

  function sortCards(mode) {
    if (!list) return;
    var items = cards();
    items.sort(mode === 'name' ? byName : function (a, b) {
      var diff = (Date.parse(b.dataset.pushed || '') || 0) - (Date.parse(a.dataset.pushed || '') || 0);
      return diff || byName(a, b);
    });
    items.forEach(function (card) { list.appendChild(card); });
  }

  function setSort(mode) {
    sortButtons.forEach(function (btn) {
      var on = btn.dataset.sort === mode;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    sortCards(mode);
  }

  var sortMode = 'updated';
  try {
    var saved = global.localStorage.getItem(SORT_KEY);
    if (SORT_MODES[saved]) sortMode = saved;
  } catch (e) { /* ignore */ }
  setSort(sortMode);

  sortButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var next = SORT_MODES[btn.dataset.sort] ? btn.dataset.sort : 'updated';
      sortMode = next;
      setSort(next);
      try { global.localStorage.setItem(SORT_KEY, next); } catch (e) { /* ignore */ }
    });
  });

  function renderPins() {
    cards().forEach(function (card) {
      var btn = card.querySelector('.site-pin');
      if (!btn) return;
      var meta = META.get(card.dataset.slug);
      btn.classList.toggle('on', !!meta.pinned);
      btn.setAttribute('aria-pressed', meta.pinned ? 'true' : 'false');
      btn.title = meta.pinned ? '取消置顶' : '置顶';
    });
  }

  function renderPinnedSection() {
    var box = doc.getElementById('repos-pinned');
    var mount = doc.getElementById('repos-pinned-list');
    if (!box || !mount) return;

    /* 最新置顶的排前面；旧数据没有 pinnedAt 时回退到 updatedAt */
    var pinned = cards().filter(function (card) {
      return META.get(card.dataset.slug).pinned;
    }).sort(function (a, b) {
      var ma = META.get(a.dataset.slug), mb = META.get(b.dataset.slug);
      return (Date.parse(mb.pinnedAt || mb.updatedAt || 0) || 0) -
             (Date.parse(ma.pinnedAt || ma.updatedAt || 0) || 0);
    });

    mount.innerHTML = '';
    pinned.forEach(function (card) {
      var wrap = doc.createElement('div');
      wrap.className = 'pinned-item';

      var clone = card.cloneNode(true);
      clone.classList.add('pinned-card');
      var pinBtn = clone.querySelector('.site-pin');
      if (pinBtn) {
        pinBtn.classList.add('on');
        pinBtn.setAttribute('aria-pressed', 'true');
        pinBtn.title = '取消置顶';
        pinBtn.setAttribute('aria-label', '取消置顶');
      }

      wrap.appendChild(clone);
      mount.appendChild(wrap);
    });
    box.hidden = pinned.length === 0;
  }

  function renderAll() {
    renderPins();
    renderPinnedSection();
  }

  doc.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('.site-pin') : null;
    if (!btn) return;
    var card = btn.closest('.repo-card');
    if (!card) return;
    e.preventDefault();
    e.stopPropagation();
    var slug = card.dataset.slug;
    if (slug.indexOf(PREFIX) !== 0) return;
    META.setMeta(slug, { pinned: !META.get(slug).pinned });
    renderAll();
  });

  /* 置顶区折叠：状态存本机，不参与多端同步 */
  var pinnedBox = doc.getElementById('repos-pinned');
  var pinnedToggle = doc.getElementById('repos-pinned-toggle');

  function setCollapsed(collapsed) {
    if (!pinnedBox || !pinnedToggle) return;
    pinnedBox.classList.toggle('is-collapsed', collapsed);
    pinnedToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  if (pinnedBox && pinnedToggle) {
    var collapsed = false;
    try {
      collapsed = global.localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch (e) { /* ignore */ }
    setCollapsed(collapsed);

    function flipPinned() {
      collapsed = !collapsed;
      setCollapsed(collapsed);
      try {
        global.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
      } catch (e) { /* ignore */ }
    }

    pinnedToggle.addEventListener('click', flipPinned);
    pinnedToggle.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        flipPinned();
      }
    });
  }

  doc.addEventListener('xm-meta-refreshed', renderAll);
  META.ready.then(renderAll);
  renderAll();
})(window);
