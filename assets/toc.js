(function () {
  var toc = document.querySelector('.toc');
  if (!toc) return;
  var openBtn = document.querySelector('.toc-open');
  var foldBtn = toc.querySelector('.toc-fold');
  var closeBtn = toc.querySelector('.toc-close');

  if (foldBtn) {
    foldBtn.addEventListener('click', function () {
      var folded = toc.classList.toggle('is-folded');
      foldBtn.textContent = folded ? '全展开' : '全折叠';
      foldBtn.setAttribute('aria-expanded', String(!folded));
    });
  }

  if (closeBtn && openBtn) {
    closeBtn.addEventListener('click', function () {
      toc.hidden = true;
      openBtn.hidden = false;
      openBtn.focus();
    });
    openBtn.addEventListener('click', function () {
      toc.hidden = false;
      openBtn.hidden = true;
    });
  }
})();
