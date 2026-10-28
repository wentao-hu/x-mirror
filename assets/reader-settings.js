/* X Mirror · 阅读设置：字号 / 行高 / 行宽
 * 全局一份：localStorage 立即生效，Cloudflare KV 跨设备同步（last-write-wins）。
 * 行宽只对桌面有意义，移动端面板里隐藏这一项（CSS 控制），缩放在两端都生效。
 */
(function (global) {
  'use strict';

  var STORE_KEY = 'x-mirror-reader-v1';
  // GitHub Pages 没有 Pages Functions：与 meta.js 一样回落到 Cloudflare 的同名 API（已开 CORS）。
  var API_BASE = /(^|\.)github\.io$/i.test(global.location.hostname)
    ? 'https://x-mirror-af7.pages.dev/api'
    : '/api';
  var API_URL = API_BASE + '/reader-settings';
  var IS_FILE = global.location && global.location.protocol === 'file:';

  var FIELDS = {
    fs: { prop: '--reader-fs', min: 0.85, max: 1.5, label: '字号' },
    lh: { prop: '--reader-lh', min: 0.85, max: 1.3, label: '行高' },
    w: { prop: '--reader-w', min: 0.6, max: 1.2, label: '行宽' }
  };
  var KEYS = ['fs', 'lh', 'w'];

  var state = {
    settings: { fs: 1, lh: 1, w: 1 },
    updatedAt: null
  };
  var inputs = {};
  var putTimer = null;

  function nowISO() {
    return new Date().toISOString();
  }

  function parseTs(value) {
    var t = Date.parse(value || '');
    return isNaN(t) ? 0 : t;
  }

  function clamp(key, value) {
    var field = FIELDS[key];
    var n = Number(value);
    if (!isFinite(n)) return 1;
    n = Math.round(n * 100) / 100;
    return Math.min(field.max, Math.max(field.min, n));
  }

  function normalize(raw) {
    var out = {};
    KEYS.forEach(function (key) { out[key] = clamp(key, raw && raw[key]); });
    return out;
  }

  function apply() {
    var style = global.document.documentElement.style;
    KEYS.forEach(function (key) {
      style.setProperty(FIELDS[key].prop, String(state.settings[key]));
    });
  }

  function saveLocal() {
    try {
      global.localStorage.setItem(STORE_KEY, JSON.stringify({
        settings: state.settings,
        updatedAt: state.updatedAt
      }));
    } catch (e) { /* localStorage 不可用时只保留本次会话 */ }
  }

  function loadLocal() {
    try {
      var raw = JSON.parse(global.localStorage.getItem(STORE_KEY) || 'null');
      if (!raw || typeof raw !== 'object') return;
      state.settings = normalize(raw.settings);
      state.updatedAt = typeof raw.updatedAt === 'string' ? raw.updatedAt : null;
    } catch (e) { /* 隐私模式 / 非法 JSON：沿用默认值 */ }
  }

  /* ---------- 服务端同步 ---------- */

  function fetchServer() {
    if (IS_FILE || typeof global.fetch !== 'function') return Promise.resolve(null);
    var controller = typeof global.AbortController === 'function' ? new global.AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 8000) : null;
    var opts = { method: 'GET', headers: { Accept: 'application/json' }, cache: 'no-store' };
    if (controller) opts.signal = controller.signal;
    return global.fetch(API_URL, opts).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (data) {
      if (!data || data.ok !== true || !data.settings) throw new Error('bad payload');
      return {
        settings: normalize(data.settings),
        updatedAt: typeof data.updatedAt === 'string' ? data.updatedAt : null
      };
    }).catch(function () {
      return null;
    }).then(function (value) {
      if (timer) clearTimeout(timer);
      return value;
    });
  }

  function putServer() {
    if (IS_FILE || typeof global.fetch !== 'function') return;
    global.fetch(API_URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        fs: state.settings.fs,
        lh: state.settings.lh,
        w: state.settings.w,
        updatedAt: state.updatedAt
      })
    }).catch(function () { /* 离线：下次修改或打开页面时再补 */ });
  }

  function schedulePut() {
    if (IS_FILE) return;
    if (putTimer) clearTimeout(putTimer);
    putTimer = setTimeout(function () {
      putTimer = null;
      putServer();
    }, 600);
  }

  function syncFromServer() {
    fetchServer().then(function (server) {
      if (!server) return;
      var localTs = parseTs(state.updatedAt);
      var serverTs = parseTs(server.updatedAt);
      if (serverTs > localTs) {
        state.settings = server.settings;
        state.updatedAt = server.updatedAt;
        apply();
        syncInputs();
        saveLocal();
      } else if (localTs > serverTs) {
        putServer();
      }
    });
  }

  /* ---------- 面板 UI ---------- */

  function syncInputs() {
    KEYS.forEach(function (key) {
      if (inputs[key]) inputs[key].value = String(state.settings[key]);
    });
  }

  function commit(key, value) {
    state.settings[key] = clamp(key, value);
    state.updatedAt = nowISO();
    apply();
    saveLocal();
    schedulePut();
  }

  function wireInput(key, input) {
    // 输入过程中即时预览，但不回写输入框，避免打断用户正在输入的小数
    input.addEventListener('input', function () {
      var raw = input.value.trim();
      if (raw === '' || !isFinite(Number(raw))) return;
      commit(key, raw);
    });
    // 失焦/确认时把越界值吸附到区间边界
    input.addEventListener('change', function () {
      commit(key, input.value);
      input.value = String(state.settings[key]);
    });
  }

  function buildPanel(toggle) {
    var holder = toggle.parentNode;
    while (holder && holder !== global.document.body && !holder.classList.contains('reader-settings')) {
      holder = holder.parentNode;
    }
    if (!holder || holder === global.document.body) holder = toggle.parentNode;

    var panel = global.document.createElement('div');
    panel.className = 'reader-panel';
    panel.id = 'reader-panel';
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', '阅读设置');

    var title = global.document.createElement('div');
    title.className = 'reader-panel-title';
    title.textContent = '阅读设置';
    panel.appendChild(title);

    KEYS.forEach(function (key) {
      var field = FIELDS[key];
      var label = global.document.createElement('label');
      label.className = 'reader-field' + (key === 'w' ? ' reader-field--width' : '');

      var name = global.document.createElement('span');
      name.textContent = field.label;

      var input = global.document.createElement('input');
      input.type = 'number';
      input.step = '0.05';
      input.min = String(field.min);
      input.max = String(field.max);
      input.inputMode = 'decimal';
      input.value = String(state.settings[key]);
      input.setAttribute('data-reader-key', key);
      input.setAttribute('aria-label', field.label + '倍数');
      inputs[key] = input;
      wireInput(key, input);

      label.appendChild(name);
      label.appendChild(input);
      panel.appendChild(label);
    });

    var reset = global.document.createElement('button');
    reset.type = 'button';
    reset.className = 'reader-reset';
    reset.textContent = '恢复默认';
    reset.addEventListener('click', function () {
      KEYS.forEach(function (key) { state.settings[key] = 1; });
      state.updatedAt = nowISO();
      apply();
      syncInputs();
      saveLocal();
      schedulePut();
    });
    panel.appendChild(reset);

    holder.appendChild(panel);
    return panel;
  }

  function wireToggle(toggle, panel) {
    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(panel.hidden);
    });
    panel.addEventListener('click', function (e) { e.stopPropagation(); });
    global.document.addEventListener('click', function () {
      if (!panel.hidden) setOpen(false);
    });
    global.document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  function init() {
    loadLocal();
    apply();
    var toggle = global.document.querySelector('[data-reader-toggle]');
    if (toggle) {
      var panel = buildPanel(toggle);
      wireToggle(toggle, panel);
    }
    syncFromServer();
  }

  if (global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
