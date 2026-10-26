/* X Mirror · 正文图片缩放
 * 每篇文章一个缩放级别；localStorage 立即可用，Cloudflare KV 跨设备同步。
 * 状态挂在 meta.js 的 imgZoom 字段上，复用其 last-write-wins 合并。
 */
(function (global) {
  'use strict';

  var doc = global.document;
  if (!doc) return;
  var META = global.XMirrorMeta;
  if (!META) return;

  var article = doc.querySelector('.article');
  var mount = doc.querySelector('[data-meta-mount][data-slug]');
  if (!article || !mount) return;
  var slug = mount.dataset.slug;
  if (!slug) return;

  var MIN = 0.5, MAX = 1.5, STEP = 0.1;
  var SHOW_DELAY = 400, HIDE_DELAY = 600;

  function clamp(value) {
    var n = Number(value);
    if (!isFinite(n)) return 1;
    n = Math.round(n * 10) / 10;
    return Math.min(MAX, Math.max(MIN, n));
  }

  var zoom = clamp(META.get(slug).imgZoom);
  var figures = Array.prototype.slice.call(article.querySelectorAll('figure.media'));
  var activeFigure = null;
  var showTimer = null;
  var hideTimer = null;
  var lastPointerType = 'mouse';
  var finePointer = global.matchMedia
    ? global.matchMedia('(hover: hover) and (pointer: fine)').matches
    : true;
  var coarsePointer = global.matchMedia
    ? global.matchMedia('(hover: none), (pointer: coarse)').matches
    : false;

  function controlsOf(fig) {
    return fig ? fig.querySelector('.img-zoom-controls') : null;
  }

  function setControlsVisible(fig, visible) {
    var controls = controlsOf(fig);
    if (!controls) return;
    if (visible && activeFigure && activeFigure !== fig) {
      var previous = controlsOf(activeFigure);
      if (previous) {
        previous.classList.remove('is-visible');
        previous.setAttribute('aria-hidden', 'true');
      }
    }
    controls.classList.toggle('is-visible', visible);
    controls.setAttribute('aria-hidden', visible ? 'false' : 'true');
    activeFigure = visible ? fig : (activeFigure === fig ? null : activeFigure);
  }

  function clearTimers() {
    if (showTimer) clearTimeout(showTimer);
    if (hideTimer) clearTimeout(hideTimer);
    showTimer = null;
    hideTimer = null;
  }

  function showNow(fig) {
    clearTimers();
    setControlsVisible(fig, true);
  }

  function scheduleShow(fig) {
    clearTimers();
    showTimer = setTimeout(function () { showNow(fig); }, SHOW_DELAY);
  }

  function scheduleHide(fig) {
    clearTimers();
    hideTimer = setTimeout(function () {
      if (activeFigure !== fig) return;
      if (fig.matches && fig.matches(':hover')) return;
      if (fig.contains(doc.activeElement)) return;
      setControlsVisible(fig, false);
    }, HIDE_DELAY);
  }

  function hideAll() {
    clearTimers();
    figures.forEach(function (fig) { setControlsVisible(fig, false); });
    activeFigure = null;
  }

  function paint() {
    article.style.setProperty('--img-zoom', zoom);
    Array.prototype.forEach.call(article.querySelectorAll('.img-zoom-value'), function (el) {
      el.textContent = Math.round(zoom * 100) + '%';
    });
  }

  function syncFromMeta() {
    var next = clamp(META.get(slug).imgZoom);
    if (next !== zoom) {
      zoom = next;
      paint();
    }
  }

  figures.forEach(function (fig) {
    if (fig.querySelector('.img-zoom-controls')) return;
    var box = doc.createElement('span');
    box.className = 'img-zoom-controls';
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', '图片缩放');
    box.setAttribute('aria-hidden', 'true');
    box.innerHTML =
      '<button type="button" class="img-zoom-btn" data-img-action="zoom" data-zoom="-1" aria-label="缩小图片" title="缩小">−</button>' +
      '<span class="img-zoom-value" aria-live="polite">100%</span>' +
      '<button type="button" class="img-zoom-btn" data-img-action="zoom" data-zoom="1" aria-label="放大图片" title="放大">+</button>' +
      '<button type="button" class="img-zoom-btn img-zoom-preview" data-img-action="preview" aria-label="预览图片" title="预览">↗</button>';
    fig.appendChild(box);
  });

  figures.forEach(function (fig) {
    fig.addEventListener('pointerenter', function (e) {
      if (!finePointer || e.pointerType === 'touch') return;
      scheduleShow(fig);
    });
    fig.addEventListener('pointerleave', function (e) {
      if (!finePointer || e.pointerType === 'touch') return;
      scheduleHide(fig);
    });
    fig.addEventListener('focusin', function () { showNow(fig); });
    fig.addEventListener('focusout', function (e) {
      if (e.relatedTarget && fig.contains(e.relatedTarget)) return;
      scheduleHide(fig);
    });
  });

  doc.addEventListener('pointerdown', function (e) {
    lastPointerType = e.pointerType || 'mouse';
  }, true);

  function isTouchActivation(e) {
    if (e.detail === 0) return false;
    return lastPointerType === 'touch' || lastPointerType === 'pen' || coarsePointer;
  }

  doc.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('figure.media')) return;
    hideAll();
  });

  article.addEventListener('click', function (e) {
    var action = e.target.closest ? e.target.closest('[data-img-action]') : null;
    if (!action) return;
    e.preventDefault();
    e.stopPropagation();
    var fig = action.closest('figure.media');
    if (action.dataset.imgAction === 'preview') {
      var link = fig ? fig.querySelector('.media-link') : null;
      var img = link ? link.querySelector('img') : null;
      if (link) {
        hideAll();
        openLightbox(link.getAttribute('href'), img ? img.alt : '');
      }
      return;
    }
    zoom = clamp(zoom + Number(action.dataset.zoom) * STEP);
    paint();
    META.setMeta(slug, { imgZoom: zoom });
    if (fig) showNow(fig);
  });

  /* ---------- 正文图片预览（点击图片外的区域关闭） ---------- */

  var lightbox = null;

  function ensureLightbox() {
    if (lightbox) return lightbox;
    lightbox = doc.createElement('div');
    lightbox.className = 'img-lightbox';
    lightbox.setAttribute('role', 'dialog');
    lightbox.setAttribute('aria-modal', 'true');
    lightbox.setAttribute('aria-label', '图片预览');
    lightbox.innerHTML =
      '<button type="button" class="img-lightbox-close" aria-label="关闭预览">×</button>' +
      '<img class="img-lightbox-img" alt="" />';
    doc.body.appendChild(lightbox);
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox || (e.target.classList && e.target.classList.contains('img-lightbox-close'))) {
        closeLightbox();
      }
    });
    return lightbox;
  }

  function openLightbox(href, alt) {
    var box = ensureLightbox();
    var img = box.querySelector('.img-lightbox-img');
    img.src = href;
    img.alt = alt || '';
    box.hidden = false;
    doc.body.classList.add('img-lightbox-open');
    requestAnimationFrame(function () {
      box.classList.add('is-open');
    });
  }

  function closeLightbox() {
    if (!lightbox || lightbox.hidden) return;
    lightbox.classList.remove('is-open');
    doc.body.classList.remove('img-lightbox-open');
    setTimeout(function () {
      if (lightbox && !lightbox.classList.contains('is-open')) {
        lightbox.hidden = true;
        lightbox.querySelector('.img-lightbox-img').src = '';
      }
    }, 200);
  }

  article.addEventListener('click', function (e) {
    var link = e.target.closest ? e.target.closest('.media-link') : null;
    if (!link || !article.contains(link)) return;
    e.preventDefault();
    var fig = link.closest('figure.media');
    if (fig && isTouchActivation(e)) {
      var controls = controlsOf(fig);
      setControlsVisible(fig, !(controls && controls.classList.contains('is-visible')));
      return;
    }
    var img = link.querySelector('img');
    hideAll();
    openLightbox(link.getAttribute('href'), img ? img.alt : '');
  });

  doc.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' || e.key === 'Esc') {
      if (lightbox && !lightbox.hidden) closeLightbox();
      else hideAll();
    }
  });

  doc.addEventListener('xm-meta-refreshed', syncFromMeta);
  META.ready.then(syncFromMeta);
  paint();
})(window);
