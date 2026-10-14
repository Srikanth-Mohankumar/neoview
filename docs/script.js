/*
 * NeoView site: theme toggle, theme-aware screenshots, copy buttons, feature clips,
 * demo chapters.
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

  /* ---------- Feature clips ---------- */

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var loops = Array.prototype.slice.call(document.querySelectorAll('video.loop'));

  function setPoster(video) {
    var poster = video.getAttribute('data-poster');
    if (poster && !video.getAttribute('poster')) video.setAttribute('poster', poster);
  }

  function addPauseButton(video) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'clip-toggle';
    function sync() {
      var paused = video.paused;
      btn.setAttribute('aria-label', paused ? 'Play clip' : 'Pause clip');
      btn.setAttribute('title', paused ? 'Play' : 'Pause');
      btn.classList.toggle('is-paused', paused);
    }
    btn.innerHTML = '<svg class="i-pause" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg>' +
      '<svg class="i-play" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z"/></svg>';
    btn.addEventListener('click', function () {
      if (video.paused) {
        video.setAttribute('data-user', 'play');
        video.play().catch(function () {});
      } else {
        video.setAttribute('data-user', 'pause');
        video.pause();
      }
    });
    video.addEventListener('play', sync);
    video.addEventListener('pause', sync);
    video.parentElement.appendChild(btn);
    sync();
  }

  if (loops.length) {
    loops.forEach(function (video) {
      video.removeAttribute('controls'); /* JS supplies a play/pause button instead */
      addPauseButton(video);
    });
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          var video = entry.target;
          if (entry.isIntersecting) {
            setPoster(video);
            if (!reduceMotion && video.getAttribute('data-user') !== 'pause') {
              video.play().catch(function () {});
            }
          } else if (!video.paused) {
            video.pause();
          }
        });
      }, { rootMargin: '200px 0px', threshold: 0.25 });
      loops.forEach(function (v) { io.observe(v); });
    } else {
      loops.forEach(setPoster);
    }
  }

  /* ---------- Demo chapters ---------- */

  var demo = document.getElementById('demo-video');
  if (demo) {
    var chapterButtons = Array.prototype.slice.call(document.querySelectorAll('.chapters [data-t]'));
    chapterButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var t = parseFloat(btn.getAttribute('data-t')) || 0;
        demo.preload = 'auto';
        var seek = function () {
          demo.currentTime = t + 0.05;
          demo.play().catch(function () {});
        };
        if (demo.readyState >= 1) seek();
        else {
          demo.addEventListener('loadedmetadata', seek, { once: true });
          demo.load();
        }
      });
    });
    demo.addEventListener('timeupdate', function () {
      var now = demo.currentTime;
      var current = null;
      chapterButtons.forEach(function (btn) {
        if (parseFloat(btn.getAttribute('data-t')) <= now + 0.1) current = btn;
      });
      chapterButtons.forEach(function (btn) {
        if (btn === current) btn.setAttribute('aria-current', 'true');
        else btn.removeAttribute('aria-current');
      });
    });
  }

  /* ---------- Init ---------- */

  buildGallery();
  setTheme(currentTheme(), false);
  if (!storedTheme()) root.removeAttribute('data-theme');
})();
