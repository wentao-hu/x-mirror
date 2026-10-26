(function () {
  var toc = document.querySelector('.toc');
  if (!toc) return;
  var openBtn = document.querySelector('.toc-open');
  var foldBtn = toc.querySelector('.toc-fold');
  var closeBtn = toc.querySelector('.toc-close');
  var WIDE = '(min-width: 1320px)';
  var POS_KEY = 'xmirror:toc-open-pos';
  var EDGE = 8;
  var DRAG_THRESHOLD = 4;
  var suppressClickUntil = 0;

  if (foldBtn) {
    foldBtn.addEventListener('click', function () {
      var folded = toc.classList.toggle('is-folded');
      foldBtn.textContent = folded ? '全展开' : '全折叠';
      foldBtn.setAttribute('aria-expanded', String(!folded));
    });
  }

  function wideMatch() {
    return window.matchMedia(WIDE).matches;
  }

  function clamp(n, min, max) {
    return Math.min(Math.max(n, min), Math.max(min, max));
  }

  function savedPos() {
    try {
      var raw = localStorage.getItem(POS_KEY);
      if (!raw) return null;
      var pos = JSON.parse(raw);
      if (typeof pos.left !== 'number' || typeof pos.top !== 'number') return null;
      return pos;
    } catch (e) {
      return null;
    }
  }

  function placeOpenBtn(left, top) {
    if (!openBtn) return;
    var w = openBtn.offsetWidth || 42;
    var h = openBtn.offsetHeight || 42;
    left = clamp(left, EDGE, Math.max(EDGE, window.innerWidth - w - EDGE));
    top = clamp(top, EDGE, Math.max(EDGE, window.innerHeight - h - EDGE));
    openBtn.style.left = left + 'px';
    openBtn.style.top = top + 'px';
    openBtn.style.right = 'auto';
  }

  function restorePos() {
    var pos = savedPos();
    if (pos) placeOpenBtn(pos.left, pos.top);
  }

  function savePos() {
    if (!openBtn || !openBtn.style.left) return;
    var left = parseFloat(openBtn.style.left);
    var top = parseFloat(openBtn.style.top);
    if (!isFinite(left) || !isFinite(top)) return;
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({ left: left, top: top }));
    } catch (e) {}
  }

  /* 拖动「目录」图标：松手后记住位置，未移动的点击仍然是打开目录 */
  var drag = null;
  if (openBtn) {
    openBtn.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0) return;
      var rect = openBtn.getBoundingClientRect();
      drag = {
        id: e.pointerId,
        x: e.clientX,
        y: e.clientY,
        left: rect.left,
        top: rect.top,
        moved: false
      };
      try { openBtn.setPointerCapture(e.pointerId); } catch (err) {}
    });

    openBtn.addEventListener('pointermove', function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.x;
      var dy = e.clientY - drag.y;
      if (!drag.moved && Math.sqrt(dx * dx + dy * dy) < DRAG_THRESHOLD) return;
      if (!drag.moved) {
        drag.moved = true;
        openBtn.classList.add('is-dragging');
      }
      e.preventDefault();
      placeOpenBtn(drag.left + dx, drag.top + dy);
    });

    function endDrag(e) {
      if (!drag || e.pointerId !== drag.id) return;
      var moved = drag.moved;
      drag = null;
      openBtn.classList.remove('is-dragging');
      if (moved) {
        suppressClickUntil = Date.now() + 350;
        savePos();
      }
    }

    openBtn.addEventListener('pointerup', endDrag);
    openBtn.addEventListener('pointercancel', endDrag);
  }

  /* 宽屏默认展开目录；关闭后保持折叠，只留图标按钮 */
  function syncWidth() {
    var wide = wideMatch();
    if (wide) {
      if (toc.dataset.userClosed) {
        toc.hidden = true;
        if (openBtn) openBtn.hidden = false;
      } else {
        toc.hidden = false;
        if (openBtn) openBtn.hidden = true;
      }
    } else if (toc.dataset.userOpen) {
      toc.hidden = false;
      if (openBtn) openBtn.hidden = true;
    } else {
      toc.hidden = true;
      if (openBtn) openBtn.hidden = false;
    }
    if (openBtn && !openBtn.hidden) restorePos();
  }

  if (closeBtn && openBtn) {
    closeBtn.addEventListener('click', function () {
      delete toc.dataset.userOpen;
      toc.dataset.userClosed = '1';
      toc.hidden = true;
      openBtn.hidden = false;
      restorePos();
      openBtn.focus();
    });
    openBtn.addEventListener('click', function (e) {
      if (Date.now() < suppressClickUntil) {
        e.preventDefault();
        return;
      }
      delete toc.dataset.userClosed;
      toc.dataset.userOpen = '1';
      toc.hidden = false;
      openBtn.hidden = true;
    });
  }

  syncWidth();
  window.addEventListener('resize', function () {
    syncWidth();
    if (openBtn && !openBtn.hidden && openBtn.style.left) {
      placeOpenBtn(parseFloat(openBtn.style.left), parseFloat(openBtn.style.top));
    }
  });
})();
