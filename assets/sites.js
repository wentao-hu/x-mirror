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

  /* 多选与批量复制：选中链接按空格分隔 */
  var checkAll = doc.getElementById('sites-check-all');
  var countEl = doc.getElementById('sites-selected-count');
  var copyBtn = doc.getElementById('sites-copy');
  var openBtn = doc.getElementById('sites-open');
  var hintEl = doc.getElementById('sites-hint');

  function mainCards() {
    return Array.prototype.slice.call(doc.querySelectorAll('#sites .site-card[data-slug]'));
  }

  function selectedCards() {
    return mainCards().filter(function (card) {
      var cb = card.querySelector('.site-check');
      return cb && cb.checked;
    });
  }

  function cardUrl(card) {
    var a = card.querySelector('.site-main');
    return a ? a.getAttribute('href') : '';
  }

  function refreshSelection() {
    var total = mainCards().length;
    var n = selectedCards().length;
    if (countEl) countEl.textContent = '已选 ' + n + ' 个';
    if (copyBtn) copyBtn.disabled = n === 0;
    if (openBtn) openBtn.disabled = n === 0;
    if (checkAll) {
      checkAll.checked = total > 0 && n === total;
      checkAll.indeterminate = n > 0 && n < total;
    }
  }

  /* 置顶区是主卡片的克隆，按 slug 全文档同步选中态 */
  function setSlugSelected(slug, checked) {
    var list = doc.querySelectorAll('.site-card[data-slug="' + slug + '"]');
    Array.prototype.forEach.call(list, function (card) {
      var cb = card.querySelector('.site-check');
      if (cb) cb.checked = checked;
      card.classList.toggle('is-selected', checked);
    });
    refreshSelection();
  }

  doc.addEventListener('change', function (e) {
    var cb = e.target;
    if (!cb || !cb.classList || !cb.classList.contains('site-check')) return;
    var card = cb.closest ? cb.closest('.site-card') : null;
    if (!card) return;
    setSlugSelected(card.dataset.slug, cb.checked);
  });

  if (checkAll) {
    checkAll.addEventListener('change', function () {
      mainCards().forEach(function (card) {
        var cb = card.querySelector('.site-check');
        if (cb) cb.checked = checkAll.checked;
        card.classList.toggle('is-selected', checkAll.checked);
      });
      refreshSelection();
    });
  }

  function copyText(text) {
    if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = doc.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      doc.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = doc.execCommand('copy'); } catch (err) { ok = false; }
      doc.body.removeChild(ta);
      if (ok) resolve(); else reject(new Error('copy failed'));
    });
  }

  if (openBtn) {
    var openTimer = 0;
    openBtn.addEventListener('click', function () {
      var urls = selectedCards().map(cardUrl).filter(Boolean);
      if (!urls.length) return;
      /* Chrome 一次点击只放行一个弹窗；返回 null 即被拦截，需引导用户允许本站弹窗 */
      var blocked = 0;
      urls.forEach(function (url) {
        var win = global.open(url, '_blank');
        if (win) {
          try { win.opener = null; } catch (e) { /* ignore */ }
        } else {
          blocked++;
        }
      });
      if (hintEl) {
        hintEl.textContent = '浏览器拦截了 ' + blocked +
          ' 个标签页：点地址栏右侧的弹窗图标，允许本站弹窗后，再点一次「全部打开」即可。';
        hintEl.hidden = blocked === 0;
      }
      openBtn.classList.add('on');
      openBtn.textContent = '已打开 ' + (urls.length - blocked) + ' 个';
      global.clearTimeout(openTimer);
      openTimer = global.setTimeout(function () {
        openBtn.classList.remove('on');
        openBtn.textContent = '全部打开';
        refreshSelection();
      }, 1800);
    });
  }

  if (copyBtn) {
    var copyTimer = 0;
    copyBtn.addEventListener('click', function () {
      var urls = selectedCards().map(cardUrl).filter(Boolean);
      if (!urls.length) return;
      copyText(urls.join(' ')).then(function () {
        copyBtn.classList.add('on');
        copyBtn.textContent = '已复制 ' + urls.length + ' 个链接';
        global.clearTimeout(copyTimer);
        copyTimer = global.setTimeout(function () {
          copyBtn.classList.remove('on');
          copyBtn.textContent = '复制链接';
          refreshSelection();
        }, 1800);
      }, function () {
        copyBtn.textContent = '复制失败';
        global.setTimeout(function () { copyBtn.textContent = '复制链接'; }, 1800);
      });
    });
  }
})(window);
