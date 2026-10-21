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

    var pinned = cards().filter(function (card) {
      return META.get(card.dataset.slug).pinned;
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

  doc.addEventListener('xm-meta-refreshed', renderAll);
  META.ready.then(renderAll);
  renderAll();
})(window);
