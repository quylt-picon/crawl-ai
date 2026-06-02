"""
URL Health Check — Chiến thuật: curl_cffi (giả JA3) + harvest headers từ browser.

Ý tưởng:
  - Phase 1: kiểm tra nhanh tất cả URL bằng curl_cffi với impersonate='chrome'
           -> giả luôn TLS fingerprint + HTTP/2 fingerprint của Chrome, đủ để
           qua mặt phần lớn WAF chỉ check fingerprint (kể cả Akamai/Cloudflare).
  - Phase 2: URL nào vẫn bị WAF chặn (403/429/503) thì:
        (a) Mở browser thật bằng crawl4ai. Hook `before_goto` để gắn
            `page.on("request", ...)` và `await request.all_headers()` để
            cào headers + Cookie mà browser thực sự gửi sau JS challenge.
        (b) Replay bằng curl_cffi (vẫn impersonate='chrome') với headers + Cookie
            vừa cào. TLS fingerprint vẫn khớp Chrome, nay thêm Cookie WAF set.
        (c) URL nào harvest fail (vd PDF — browser không navigate được) thì
            mượn headers từ URL khác cùng host đã harvest thành công.

Log: mỗi URL có 1 uid ngắn (u1, u2 ...). Mỗi step nhỏ được log riêng kèm thời
gian thực hiện step đó. Có thể grep `[u3]` để xem hành trình của 1 URL.

Trạng thái: valid | dead | blocked | error
Chạy CLI: python -m app.services.health_check  (từ backend/)
"""

import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession

from crawl4ai import AsyncLogger, AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

TIMEOUT = 10.0                       # timeout HTTP (giây)
BLOCK_CODES = {403, 429, 503}        # mã HTTP nghi bị WAF chặn -> cần cào headers
IMPERSONATE = "chrome"               # giả Chrome (TLS + HTTP/2 + header order)
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "*",
    # User-Agent: để curl_cffi tự set khớp impersonate (tránh mismatch UA<->TLS).
}

# Pseudo-header HTTP/2 (bắt đầu bằng ':') và header tự-tính: curl_cffi cũng
# không cho/không nên truyền thủ công các header này.
_DROP_HEADERS = {"host", "content-length", "connection"}

URLS = [
    "https://www.panasonic.com/vn/consumer/home-appliances/fridge/prime-edition/NA-F85S11BRV.html",
    "https://www.panasonic.com/content/dam/Panasonic/vn/vi/Support/Operating-Installation-Instructions/Operating-Instructions-NA-F85S11BRV.pdf",
    "https://example.com",
    "https://httpbin.org/status/404",
    "https://docs.crawl4ai.com/",
    "https://khong-ton-tai-zzz-12345.com",
    "https://gscs-b2c.lge.com/open/downloadFile?fileId=q2f5mQNNPI26RHE03XRw",
    "https://gscs-manual.lge.com/DFZ/MFL71445907/en-gb/main.html?utm_source=lgweb&utm_medium=dotcom&utm_campaign=base&model=FV1412S3B.ABLPEVN&rdate=",
    "https://www.lg.com/vn/cham-soc-khong-khi/may-loc-khong-khi/as20gpbk10/",
]


# ---------- Logging: ContextVar-based để hỗ trợ concurrent jobs từ server ----------

# _uid_map_ctx: URL -> uid ngắn (u1, u2 ...). Isolated per asyncio Task.
_uid_map_ctx: ContextVar[dict[str, str]] = ContextVar("_uid_map", default={})

# _log_fn: khi được set (từ HTTP route), log events được emit dưới dạng dict
# thay vì print. Isolated per asyncio Task.
_log_fn: ContextVar = ContextVar("_log_fn", default=None)


def _uid(url: str | None) -> str:
    if url is None:
        return "----"
    return _uid_map_ctx.get().get(url, url[:8])


def log(url: str | None, step: str, msg: str = "", dt_ms: float | None = None) -> None:
    """Log 1 step.

    Format: `[uid] [  dt ms]  STEP-NAME       msg`
    Khi _log_fn được set (server mode), emit dict thay vì print.
    """
    fn = _log_fn.get()
    if fn is not None:
        fn({"type": "log", "url": url, "uid": _uid(url),
             "step": step, "message": msg, "dt_ms": dt_ms})
        return
    prefix = f"[{_uid(url):>4}]"
    timing = f" [{dt_ms:>7.1f}ms]" if dt_ms is not None else "             "
    print(f"  {prefix}{timing}  {step:<18} {msg}")


def section(title: str) -> None:
    """In tiêu đề phân đoạn rõ ràng."""
    fn = _log_fn.get()
    if fn is not None:
        fn({"type": "section", "url": None, "uid": "----",
             "step": "SECTION", "message": title, "dt_ms": None})
        return
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


@contextmanager
def timed(url: str | None, step: str, start_msg: str = ""):
    """Context manager: in step lúc bắt đầu + lúc kết thúc kèm thời gian."""
    log(url, f"{step}…", start_msg)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000
        log(url, f"{step}", "✓", dt_ms=dt)


def _host_of(url: str) -> str:
    """Trả về netloc của URL (vd 'www.panasonic.com')."""
    return urlparse(url).netloc


@dataclass
class HealthCheckResult:
    """Kết quả kiểm tra của 1 URL."""

    url: str
    status: str
    status_code: int | None
    response_time: float
    via: str = "http"          # http | http+harvested | http+host-headers | browser

    def __str__(self) -> str:
        code = self.status_code if self.status_code is not None else "-"
        return (f"[{self.status:7}] {code!s:>3}  {self.response_time*1000:6.0f}ms  "
                f"({self.via:18}) {self.url}")


def classify_http(status_code: int) -> str:
    """Phân loại theo mã HTTP."""
    if status_code < 400:
        return "valid"
    if status_code in BLOCK_CODES:
        return "blocked"
    return "dead"


async def check_http(
    session: AsyncSession,
    url: str,
    headers: dict | None = None,
    via: str = "http",
) -> HealthCheckResult:
    """Gọi 1 request bằng curl_cffi (TLS impersonate). Log từng step nhỏ + thời gian."""
    use_headers = headers or BROWSER_HEADERS
    log(url, "HTTP-START", f"HEAD {url}")
    log(url, "HTTP-CFG", f"headers={len(use_headers)} keys, via={via}, "
                          f"impersonate={IMPERSONATE}, timeout={TIMEOUT}s")
    log(url, "HTTP-HEADERS", f"keys: {sorted(use_headers.keys())}")
    t0 = time.perf_counter()
    try:
        response = await session.head(
            url,
            headers=use_headers,
            allow_redirects=True,
            timeout=TIMEOUT,
        )
        dt = time.perf_counter() - t0
        log(url, "HTTP-RESPONSE", f"response={vars(response)}")
        log(url, "HTTP-RECV", f"status={response.status_code}", dt_ms=dt * 1000)
        klass = classify_http(response.status_code)
        log(url, "HTTP-CLASS", f"-> {klass}")
        return HealthCheckResult(url, klass, response.status_code, dt, via=via)
    except Exception as e:
        dt = time.perf_counter() - t0
        log(url, "HTTP-ERROR", f"{type(e).__name__}: {e}", dt_ms=dt * 1000)
        return HealthCheckResult(url, "error", None, dt, via=via)


def _install_capture_hook(crawler: AsyncWebCrawler) -> dict[str, list[tuple[str, dict]]]:
    """Gắn hook before_goto vào crawler để bắt headers cho mọi URL được navigate.

    Trả về dict shared {target_url: [(req_url, headers), ...]} — được populate
    khi `arun(url=...)` chạy. Có thể chạy song song nhiều `arun` vì mỗi page
    đăng ký listener riêng và ghi vào key URL riêng của nó.
    """
    captured: dict[str, list[tuple[str, dict]]] = {}

    async def hook_before_goto(page, context, url, **kwargs):
        # Tạo slot trước khi navigate; nếu hook fire nhiều lần (vd retry) thì
        # vẫn cùng key URL nên list được append liên tục.
        captured.setdefault(url, [])
        log(url, "HOOK-ATTACH", "đã gắn page.on('request')")

        async def on_request(request):
            # Chỉ quan tâm document request (main HTML), bỏ qua css/js/img/xhr.
            if request.resource_type != "document":
                return
            t0 = time.perf_counter()
            try:
                # all_headers() là async — trả về ĐẦY ĐỦ headers gồm cả
                # accept-language, accept-encoding, sec-fetch-* mà
                # `request.headers` (sync) bỏ qua.
                headers = await request.all_headers()
            except Exception as e:
                log(url, "HOOK-FAIL", f"all_headers() lỗi: {e}")
                return
            dt = (time.perf_counter() - t0) * 1000
            captured[url].append((request.url, headers))
            has_cookie = "cookie" in headers
            log(url, "DOC-REQ",
                f"#{len(captured[url])} {request.url} "
                f"({len(headers)} headers{', có cookie' if has_cookie else ''})",
                dt_ms=dt)

        page.on("request", on_request)

    crawler.crawler_strategy.set_hook("before_goto", hook_before_goto)
    return captured


async def harvest_headers(
    crawler: AsyncWebCrawler,
    url: str,
    captured: dict[str, list[tuple[str, dict]]],
) -> dict | None:
    """Phase 2-a: navigate URL trong browser; trả headers của document request CUỐI CÙNG.

    Lấy request cuối (không phải request đầu) vì sau JS challenge / redirect,
    browser thường resend với Cookie do WAF set — bộ headers đó mới đầy đủ.
    """
    log(url, "HARVEST-START", url)
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # 'domcontentloaded' đợi DOM nạp xong (lâu hơn 'commit') để JS challenge
        # của WAF có cơ hội chạy & set Cookie -> request kế tiếp mới mang Cookie.
        wait_until="domcontentloaded",
        page_timeout=20_000,
        verbose=False,
    )

    # Step: arun browser navigate
    log(url, "BROWSER-NAV", "bắt đầu navigate (domcontentloaded)…")
    t_browser = time.perf_counter()
    try:
        r = await crawler.arun(url=url, config=run_cfg)
        ok = bool(r.success)
        dt_browser = (time.perf_counter() - t_browser) * 1000
        log(url, "BROWSER-NAV", f"success={ok}", dt_ms=dt_browser)
    except Exception as e:
        dt_browser = (time.perf_counter() - t_browser) * 1000
        log(url, "BROWSER-FAIL", f"{type(e).__name__}: {e}", dt_ms=dt_browser)

    # Step: kiểm captured events
    events = captured.get(url, [])
    log(url, "EVENTS", f"số doc requests đã bắt: {len(events)}")

    if not events:
        log(url, "HARVEST-FAIL", "không có document request nào")
        return None

    # Step: chọn request cuối
    final_req_url, final_headers = events[-1]
    log(url, "PICK-FINAL",
        f"chọn req cuối ({len(events)}/{len(events)}): {final_req_url}, "
        f"{len(final_headers)} headers thô")

    # Step: lọc pseudo-header
    t_filter = time.perf_counter()
    headers = {
        k: v for k, v in final_headers.items()
        if not k.startswith(":") and k.lower() not in _DROP_HEADERS
    }
    dt_filter = (time.perf_counter() - t_filter) * 1000
    dropped = len(final_headers) - len(headers)
    log(url, "FILTER", f"loại {dropped} pseudo/auto headers, còn {len(headers)}",
        dt_ms=dt_filter)
    log(url, "HARVEST-OK", f"keys={sorted(headers.keys())}")
    return headers


async def replay_blocked(
    session: AsyncSession,
    url: str,
    own_headers: dict | None,
    headers_by_host: dict[str, dict],
) -> HealthCheckResult:
    """Phase 2-b: replay bằng curl_cffi. Ưu tiên headers tự cào, fallback theo host."""
    if own_headers:
        log(url, "REPLAY-SRC", f"dùng headers tự cào ({len(own_headers)} keys)")
        return await check_http(session, url, headers=own_headers, via="http+harvested")

    host = _host_of(url)
    host_headers = headers_by_host.get(host)
    if host_headers:
        log(url, "REPLAY-SRC",
            f"mượn headers cùng host '{host}' ({len(host_headers)} keys)")
        return await check_http(session, url, headers=host_headers, via="http+host-headers")

    log(url, "REPLAY-SKIP", f"không có headers nào (host '{host}') -> giữ blocked")
    return HealthCheckResult(url, "blocked", None, 0.0, via="browser")


async def check_urls(urls: list[str]) -> list[HealthCheckResult]:
    """Chạy 2 Phase và gộp kết quả theo đúng thứ tự đầu vào."""
    # Gán uid ngắn + lưu vào ContextVar (isolated per Task, an toàn với concurrent jobs).
    uid_map = {u: f"u{i}" for i, u in enumerate(urls, 1)}
    _uid_map_ctx.set(uid_map)

    fn = _log_fn.get()
    if fn is not None:
        fn({"type": "legend", "url": None, "uid": "----", "step": "LEGEND",
             "message": "map uid <-> URL", "dt_ms": None,
             "uid_to_url": {v: k for k, v in uid_map.items()}})
    else:
        section("LEGEND — map uid <-> URL")
        for u, uid in uid_map.items():
            print(f"  [{uid:>4}] {u}")

    # curl_cffi: impersonate Chrome ở TLS + HTTP/2 + header order level.
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # --- Phase 1: curl_cffi với headers tĩnh ---
        section(f"PHASE-1 — curl_cffi quick check ({len(urls)} URL, "
                f"impersonate={IMPERSONATE})")
        t_p1 = time.perf_counter()
        results = await asyncio.gather(*(check_http(session, u) for u in urls))
        log(None, "PHASE-1-DONE", f"{len(urls)} URL xong",
            dt_ms=(time.perf_counter() - t_p1) * 1000)

        # --- Phase 2: cào headers + replay cho URL bị chặn ---
        blocked = [r.url for r in results if r.status == "blocked"]
        if not blocked:
            log(None, "PHASE-2-SKIP", "không có URL nào bị blocked, bỏ qua Phase 2")
            return list(results)

        section(f"PHASE-2 — harvest + replay ({len(blocked)} URL bị chặn)")
        for u in blocked:
            log(u, "BLOCKED", "sẽ harvest headers từ browser")

        browser_cfg = BrowserConfig(headless=True, text_mode=True, light_mode=True, verbose=False)
        log(None, "BROWSER-INIT", "khởi tạo AsyncWebCrawler (headless chrome)…")
        t_init = time.perf_counter()
        async with AsyncWebCrawler(config=browser_cfg, logger=AsyncLogger(verbose=False)) as crawler:
            log(None, "BROWSER-INIT", "sẵn sàng",
                dt_ms=(time.perf_counter() - t_init) * 1000)

            captured = _install_capture_hook(crawler)
            log(None, "HOOK-INSTALL", "before_goto + on('request') -> dict captured")

            # 2-a: harvest song song.
            section(f"PHASE-2a — harvest headers song song ({len(blocked)} URL)")
            t_2a = time.perf_counter()
            harvested = await asyncio.gather(
                *(harvest_headers(crawler, u, captured) for u in blocked)
            )
            log(None, "PHASE-2a-DONE",
                f"{sum(1 for h in harvested if h)}/{len(harvested)} URL harvest OK",
                dt_ms=(time.perf_counter() - t_2a) * 1000)

            # Xây cache headers theo host từ các harvest thành công.
            headers_by_host: dict[str, dict] = {}
            for u, h in zip(blocked, harvested):
                if h:
                    headers_by_host[_host_of(u)] = h
            log(None, "HOST-CACHE",
                f"cache headers cho {len(headers_by_host)} host: "
                f"{list(headers_by_host.keys())}")

            # 2-b: replay song song. URL harvest fail sẽ mượn headers cùng host.
            section(f"PHASE-2b — replay curl_cffi song song ({len(blocked)} URL)")
            t_2b = time.perf_counter()
            rechecked = await asyncio.gather(
                *(replay_blocked(session, u, h, headers_by_host)
                  for u, h in zip(blocked, harvested))
            )
            log(None, "PHASE-2b-DONE", f"{len(rechecked)} URL replay xong",
                dt_ms=(time.perf_counter() - t_2b) * 1000)

        patch = {r.url: r for r in rechecked}
        results = [patch.get(r.url, r) for r in results]

    return list(results)


async def _main() -> None:
    t_main = time.perf_counter()
    results = await check_urls(URLS)
    dt_main = (time.perf_counter() - t_main) * 1000

    section(f"KẾT QUẢ (tổng {dt_main:.0f}ms)")
    for result in results:
        print(result)


if __name__ == "__main__":
    asyncio.run(_main())
