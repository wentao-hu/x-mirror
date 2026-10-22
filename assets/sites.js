/* X Mirror · 网站收藏置顶
 * 复用 meta.js 的 localStorage + Cloudflare KV 同步；slug 统一加 `site-` 前缀，
 * 与文章 slug 区分。置顶状态由 meta.js 按 updatedAt 做多端 last-write-wins。
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var META = global.XMirrorMeta;
  if (!doc || !META) return;

  var PREFIX = 'site-';

  function cards() {
    return Array.prototype.slice.call(doc.querySelectorAll('.site-card[data-slug]'));
  }

  function renderPins() {
    cards().forEach(function (card) {
      var slug = card.dataset.slug || '';
      if (slug.indexOf(PREFIX) !== 0) return;
      var btn = card.querySelector('.site-pin');
      if (!btn) return;
      var m = META.get(slug);
      btn.classList.toggle('on', !!m.pinned);
      btn.setAttribute('aria-pressed', m.pinned ? 'true' : 'false');
      btn.title = m.pinned ? '取消置顶' : '置顶';
    });
  }

  function renderPinnedSection() {
    var box = doc.getElementById('sites-pinned');
    var mount = doc.getElementById('sites-pinned-list');
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
      var slug = card.dataset.slug;
      var wrap = doc.createElement('div');
      wrap.className = 'pinned-item';

      var clone = card.cloneNode(true);
      clone.classList.add('pinned-card');
      var pinBtn = clone.querySelector('.site-pin');
      if (pinBtn) pinBtn.remove();

      var btn = doc.createElement('button');
      btn.type = 'button';
      btn.className = 'pin-remove';
      btn.textContent = '取消置顶';
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        META.setMeta(slug, { pinned: false });
        renderAll();
      });

      wrap.appendChild(clone);
      wrap.appendChild(btn);
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
    e.preventDefault();
    e.stopPropagation();
    var card = btn.closest('.site-card');
    if (!card) return;
    var slug = card.dataset.slug;
    META.setMeta(slug, { pinned: !META.get(slug).pinned });
    renderAll();
  });

  /* 置顶区折叠：状态存本机，不参与多端同步 */
  var COLLAPSE_KEY = 'x-mirror-sites-pinned-collapsed-v1';
  var pinnedBox = doc.getElementById('sites-pinned');
  var pinnedToggle = doc.getElementById('sites-pinned-toggle');

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
