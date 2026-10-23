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

  function clamp(value) {
    var n = Number(value);
    if (!isFinite(n)) return 1;
    n = Math.round(n * 10) / 10;
    return Math.min(MAX, Math.max(MIN, n));
  }

  var zoom = clamp(META.get(slug).imgZoom);
  var figures = Array.prototype.slice.call(article.querySelectorAll('figure.media'));

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
    box.innerHTML =
      '<button type="button" class="img-zoom-btn" data-zoom="-1" aria-label="缩小图片" title="缩小">−</button>' +
      '<span class="img-zoom-value" aria-live="polite">100%</span>' +
      '<button type="button" class="img-zoom-btn" data-zoom="1" aria-label="放大图片" title="放大">+</button>';
    fig.appendChild(box);
  });

  article.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('.img-zoom-btn') : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    zoom = clamp(zoom + Number(btn.dataset.zoom) * STEP);
    paint();
    META.setMeta(slug, { imgZoom: zoom });
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
    var img = link.querySelector('img');
    openLightbox(link.getAttribute('href'), img ? img.alt : '');
  });

  doc.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' || e.key === 'Esc') closeLightbox();
  });

  doc.addEventListener('xm-meta-refreshed', syncFromMeta);
  META.ready.then(syncFromMeta);
  paint();
})(window);
