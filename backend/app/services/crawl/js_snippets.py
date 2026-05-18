"""Reusable browser-side JS snippets passed to Crawl4AI page-interaction.

Keeping them as module-level strings (a) makes them easy to unit test as
text, (b) avoids string-escaping noise in service code.
"""
from __future__ import annotations

# ---------------------------------------------------------------------- helpers

_JS_HELPERS = r"""
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const isVisible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const textOf = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
  const hasSvgIcon = (el) => !!el.querySelector(
    'svg, img[alt*="search" i], img[alt*="menu" i], i[class*="icon"], i[class*="search"], i[class*="menu"]'
  );
  const isSafeClickable = (el) => {
    if (el.tagName.toLowerCase() !== 'a') return true;
    const href = (el.getAttribute('href') || '').trim();
    return !href || href === '#' || href.startsWith('javascript:');
  };
"""

# Dismiss obvious cookie/consent banners. Limited to elements inside containers
# whose class/id mentions cookie/consent/gdpr — avoids clicking random buttons.
_DISMISS_COOKIES_JS = r"""
  const COOKIE_KEYWORDS = ['accept all', 'accept', 'agree', 'allow all', 'allow',
                           'consent', 'ok', 'got it', 'i understand', 'continue',
                           'đồng ý', 'chấp nhận', 'akzeptieren', 'aceptar', 'tout accepter'];
  try {
    const sels = [
      '[class*="cookie" i] button', '[class*="consent" i] button',
      '[id*="cookie" i] button', '[id*="consent" i] button',
      '[class*="gdpr" i] button', '[id*="gdpr" i] button',
      '[aria-label*="cookie" i]', '[aria-label*="consent" i]',
    ];
    const cands = Array.from(document.querySelectorAll(sels.join(','))).filter(isVisible);
    for (const el of cands.slice(0, 8)) {
      const t = textOf(el);
      if (!t) continue;
      if (COOKIE_KEYWORDS.some(k => t === k || t.startsWith(k + ' ') || t === (k + ' all'))) {
        try { el.click(); } catch (e) {}
      }
    }
  } catch (e) {}
  await sleep(400);
"""

# Standard trigger-click: only click buttons whose text/aria/class clearly
# names "search" or "menu" — conservative, ~6 clicks max.
_CLICK_TRIGGERS_STANDARD_JS = r"""
  const TRIGGER_KEYWORDS = ['search', 'menu', 'hamburger', 'navigation', 'open menu',
                            'mobile menu', 'tìm', 'tìm kiếm', 'mở menu'];
  const looksLikeTrigger = (el) => {
    const t = textOf(el);
    const al = (el.getAttribute('aria-label') || '').toLowerCase();
    const title = (el.getAttribute('title') || '').toLowerCase();
    const cls = (el.className || '').toString().toLowerCase();
    const id = (el.id || '').toLowerCase();
    const hay = `${t} ${al} ${title} ${cls} ${id}`;
    return TRIGGER_KEYWORDS.some(k => hay.includes(k));
  };
  try {
    const triggers = Array.from(document.querySelectorAll(
      'header button, header [role=button], header a, nav button, [role=navigation] button, ' +
      'button[aria-haspopup], a[aria-haspopup], [aria-controls]'
    )).filter(isVisible).filter(isSafeClickable);
    let clicked = 0;
    for (const el of triggers) {
      if (clicked >= 6) break;
      if (looksLikeTrigger(el)) {
        try {
          el.click();
          clicked += 1;
          await sleep(250);
        } catch (e) {}
      }
    }
  } catch (e) {}
"""

# Aggressive trigger-click: click ALL aria-haspopup/aria-controls in header/nav,
# plus any icon-only button in header — used on retry when standard mode found
# nothing useful. Up to ~18 clicks total, with longer waits.
_CLICK_TRIGGERS_AGGRESSIVE_JS = r"""
  try {
    const triggers = Array.from(document.querySelectorAll(
      'header button, header [role=button], nav button, [role=navigation] button, ' +
      'button[aria-haspopup], a[aria-haspopup], button[aria-controls], a[aria-controls]'
    )).filter(isVisible).filter(isSafeClickable);
    let clicked = 0;
    for (const el of triggers) {
      if (clicked >= 12) break;
      try {
        el.click();
        clicked += 1;
        await sleep(350);
      } catch (e) {}
    }
    // Also click any icon-only button (no visible text but has SVG/icon) in header.
    const iconBtns = Array.from(document.querySelectorAll('header button, header [role=button], header a'))
      .filter(isVisible)
      .filter(isSafeClickable)
      .filter(el => !textOf(el) && hasSvgIcon(el));
    for (const el of iconBtns.slice(0, 6)) {
      try { el.click(); await sleep(300); } catch (e) {}
    }
  } catch (e) {}
"""

# Scroll once: bottom → top, triggers most lazy headers/sticky nav.
_SCROLL_STANDARD_JS = r"""
  try {
    window.scrollTo({ top: document.body.scrollHeight });
    await sleep(500);
    window.scrollTo({ top: 0 });
    await sleep(300);
  } catch (e) {}
"""

# Scroll multi-pass: half → bottom → top with longer waits, for sites that
# lazy-load on multiple intersection thresholds.
_SCROLL_AGGRESSIVE_JS = r"""
  try {
    window.scrollTo({ top: document.body.scrollHeight / 2 });
    await sleep(450);
    window.scrollTo({ top: document.body.scrollHeight });
    await sleep(700);
    window.scrollTo({ top: 0 });
    await sleep(400);
  } catch (e) {}
"""


def _build_extract_core(input_limit: int, button_limit: int, nav_limit: int) -> str:
    """The shared extraction body — captures inputs/buttons/forms/links and
    writes them to `window.__crawl_ui_data__`. Limits differ per mode.
    """
    return rf"""
  const css = (el) => {{
    if (!el || !(el instanceof Element)) return null;
    if (el.id) return `#${{CSS.escape(el.id)}}`;
    if (el.getAttribute('name')) return `${{el.tagName.toLowerCase()}}[name="${{el.getAttribute('name')}}"]`;
    const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 2);
    let sel = el.tagName.toLowerCase();
    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
    return sel;
  }};

  // Walk up to 4 ancestors looking for a class/id hinting at a search context.
  const parentSearchHint = (el) => {{
    let p = el.parentElement;
    let depth = 0;
    while (p && depth < 4) {{
      const cls = (p.className || '').toString().toLowerCase();
      const id = (p.id || '').toLowerCase();
      if (/search|find|query|seek|tìm/.test(cls + ' ' + id)) {{
        return (cls || id).slice(0, 80);
      }}
      p = p.parentElement;
      depth += 1;
    }}
    return null;
  }};

  const inputs = Array.from(document.querySelectorAll('input, textarea')).slice(0, {input_limit}).map(el => ({{
    selector: css(el),
    type: el.getAttribute('type') || el.tagName.toLowerCase(),
    name: el.getAttribute('name'),
    id: el.id || null,
    placeholder: el.getAttribute('placeholder'),
    aria_label: el.getAttribute('aria-label'),
    role: el.getAttribute('role'),
    visible: isVisible(el),
    parent_hint: parentSearchHint(el),
  }}));

  const buttons = Array.from(document.querySelectorAll(
    'button, input[type=submit], a[role=button], [role=button]'
  )).slice(0, {button_limit}).map(el => ({{
    selector: css(el),
    text: (el.innerText || el.value || '').trim().slice(0, 80),
    type: el.getAttribute('type'),
    aria_label: el.getAttribute('aria-label'),
    aria_haspopup: el.getAttribute('aria-haspopup'),
    aria_controls: el.getAttribute('aria-controls'),
    has_icon: hasSvgIcon(el),
    visible: isVisible(el),
  }}));

  const forms = Array.from(document.querySelectorAll('form')).slice(0, 30).map(el => ({{
    selector: css(el),
    action: el.getAttribute('action'),
    method: el.getAttribute('method'),
    id: el.id || null,
    name: el.getAttribute('name'),
    role: el.getAttribute('role'),
  }}));

  // Collect from header / nav / footer separately so the LLM knows where a
  // candidate support link came from. Footer often has manuals/downloads.
  const collect = (selector, source) => Array.from(document.querySelectorAll(selector)).map(a => ({{
    href: a.href,
    text: (a.innerText || '').trim().slice(0, 80),
    source: source,
  }})).filter(x => x.href && x.text);
  const seen = new Set();
  const navs = [];
  for (const item of [
    ...collect('header a', 'header'),
    ...collect('nav a, [role=navigation] a', 'nav'),
    ...collect('footer a, [role=contentinfo] a', 'footer'),
  ]) {{
    const key = item.href + '|' + item.text;
    if (seen.has(key)) continue;
    seen.add(key);
    navs.push(item);
    if (navs.length >= {nav_limit}) break;
  }}

  window.__crawl_ui_data__ = {{
    inputs, buttons, forms, nav_links: navs,
    page_title: document.title, page_url: location.href
  }};
"""


def _wrap_async(body: str) -> str:
    return f"(async () => {{\n{body}\n}})();"


# Standard extraction: dismiss banners, click named search/menu triggers,
# scroll once, then capture UI with moderate limits.
EXTRACT_UI_JS = _wrap_async(
    _JS_HELPERS
    + _DISMISS_COOKIES_JS
    + _CLICK_TRIGGERS_STANDARD_JS
    + _SCROLL_STANDARD_JS
    + _build_extract_core(input_limit=120, button_limit=120, nav_limit=200)
)

# Aggressive extraction: click ALL plausible triggers in header/nav, multi-pass
# scroll, higher limits. Used as a retry when the standard pass yields no
# search box and no support URL.
AGGRESSIVE_EXTRACT_UI_JS = _wrap_async(
    _JS_HELPERS
    + _DISMISS_COOKIES_JS
    + _CLICK_TRIGGERS_AGGRESSIVE_JS
    + _SCROLL_AGGRESSIVE_JS
    + _build_extract_core(input_limit=200, button_limit=200, nav_limit=300)
)

# Expands tabs/accordions/"read more" toggles on product pages so the manual
# section is reachable in the rendered markdown.
EXPAND_SECTIONS_JS = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const KEYWORDS = ['support', 'manual', 'manuals', 'document', 'documents', 'download',
                    'downloads', 'instruction', 'instructions', 'guide', 'user guide',
                    'owner', 'specification', 'specs', 'tài liệu', 'hướng dẫn'];

  const isVisible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const matches = (text) => {
    const t = (text || '').toLowerCase();
    return KEYWORDS.some(k => t.includes(k));
  };

  const candidates = Array.from(document.querySelectorAll(
    'button, a, [role=tab], [role=button], summary, .accordion, .accordion-header, [aria-expanded]'
  )).filter(isVisible);

  let clicked = 0;
  for (const el of candidates) {
    const text = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
    const expanded = el.getAttribute('aria-expanded');
    const shouldClick = matches(text) || expanded === 'false';
    if (!shouldClick) continue;
    try {
      el.scrollIntoView({block: 'center'});
      el.click();
      clicked += 1;
      if (clicked >= 40) break;
      await sleep(120);
    } catch (e) { /* ignore */ }
  }

  // Open <details> elements.
  document.querySelectorAll('details').forEach(d => { try { d.open = true; } catch (e) {} });

  await sleep(600);
  window.__crawl_expanded_count__ = clicked;
})();
"""
