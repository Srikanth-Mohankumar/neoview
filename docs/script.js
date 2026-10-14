/*
 * NeoView site: theme toggle, theme-aware screenshots, copy buttons.
 * Plain JS, no dependencies. Screenshot data lives in screens.js.
 */
(function () {
  'use strict';

  var root = document.documentElement;
  var STORAGE_KEY = 'neoview-theme';
  var darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function storedTheme() {
    try {
      var t = localStorage.getItem(STORAGE_KEY);
      return t === 'light' || t === 'dark' ? t : null;
    } catch (e) {
      return null;
    }
  }

  function currentTheme() {
    var t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return darkQuery && darkQuery.matches ? 'dark' : 'light';
  }

  /* ---------- Screenshots ---------- */

  var screens = Array.isArray(window.NEOVIEW_SCREENS) ? window.NEOVIEW_SCREENS : [];

  function screenById(id) {
    for (var i = 0; i < screens.length; i++) {
      if (screens[i].id === id) return screens[i];
    }
    return null;
  }

  function srcFor(entry, theme) {
    return theme === 'dark' && entry.dark ? entry.dark : entry.light;
  }

  function buildGallery() {
    var grid = document.querySelector('[data-gallery]');
    if (!grid || !screens.length) return;
    var frag = document.createDocumentFragment();
    screens.forEach(function (entry) {
      if (entry.hero) return; /* already shown large at the top of the page */
      var fig = document.createElement('figure');
      fig.className = 'shot';
      var link = document.createElement('a');
      link.setAttribute('data-screen-link', entry.id);
      var img = document.createElement('img');
      img.setAttribute('data-screen', entry.id);
      img.width = entry.width;
      img.height = entry.height;
      img.loading = 'lazy';
      img.decoding = 'async';
      img.alt = entry.alt || '';
      link.appendChild(img);
      var cap = document.createElement('figcaption');
      cap.textContent = entry.caption || '';
      fig.appendChild(link);
      fig.appendChild(cap);
      frag.appendChild(fig);
    });
    grid.textContent = '';
    grid.appendChild(frag);
  }

  function applyScreens(theme) {
    document.querySelectorAll('img[data-screen]').forEach(function (img) {
      var entry = screenById(img.getAttribute('data-screen'));
      if (!entry) return;
      var src = srcFor(entry, theme);
      if (img.getAttribute('src') !== src) img.setAttribute('src', src);
      if (entry.alt && img.closest('.shot') === null) img.alt = entry.alt;
    });
    document.querySelectorAll('a[data-screen-link]').forEach(function (a) {
      var entry = screenById(a.getAttribute('data-screen-link'));
      if (entry) a.href = srcFor(entry, theme);
    });
  }

  /* ---------- Theme toggle ---------- */

  var toggle = document.querySelector('.theme-toggle');

  function syncToggle(theme) {
    if (!toggle) return;
    var next = theme === 'dark' ? 'light' : 'dark';
    toggle.setAttribute('aria-label', 'Switch to ' + next + ' theme');
    toggle.setAttribute('title', 'Switch to ' + next + ' theme');
  }

  function setTheme(theme, remember) {
    root.setAttribute('data-theme', theme);
    if (remember) {
      try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) { /* ignore */ }
    }
    syncToggle(theme);
    applyScreens(theme);
  }

  if (toggle) {
    toggle.hidden = false;
    toggle.addEventListener('click', function () {
      setTheme(currentTheme() === 'dark' ? 'light' : 'dark', true);
    });
  }

  if (darkQuery) {
    var onSystemChange = function () {
      if (storedTheme()) return; /* an explicit choice wins */
      root.removeAttribute('data-theme');
      syncToggle(currentTheme());
      applyScreens(currentTheme());
    };
    if (darkQuery.addEventListener) darkQuery.addEventListener('change', onSystemChange);
    else if (darkQuery.addListener) darkQuery.addListener(onSystemChange);
  }

  /* ---------- Copy buttons ---------- */

  var status = document.createElement('p');
  status.className = 'visually-hidden';
  status.setAttribute('role', 'status');
  document.body.appendChild(status);

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) resolve(); else reject(new Error('copy failed'));
    });
  }

  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy');
      if (!text) {
        var code = btn.parentElement.querySelector('code');
        text = code ? code.textContent : '';
      }
      copyText(text).then(function () {
        btn.classList.add('copied');
        status.textContent = 'Copied to clipboard';
        window.setTimeout(function () {
          btn.classList.remove('copied');
          status.textContent = '';
        }, 1800);
      }, function () {
        status.textContent = 'Copy failed. Select the text and copy it manually.';
      });
    });
  });

  /* ---------- Init ---------- */

  buildGallery();
  setTheme(currentTheme(), false);
  if (!storedTheme()) root.removeAttribute('data-theme');
})();
