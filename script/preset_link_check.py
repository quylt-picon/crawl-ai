"""Verify the QUALITY of every manual link the harness returned.

"Found" is not enough: a returned URL might be a 404, a non-official site, a
product page, or a manuals *index* — not the final detailed manual. This script
fetches every manual URL (cached/deduped), inspects HTTP status + content-type +
final domain, and classifies each into:

  kind:    pdf | online_manual | support_page | product_page | manual_index |
           html_other | inline | broken | blocked | unreachable | none
  quality: good  — verified working PDF / dedicated online manual on an OFFICIAL domain
           weak  — works but is a product/support/index page, OR non-official,
                   OR inline text, OR could not be verified (403/timeout)
           bad   — broken (404 / 5xx / dead)

Each run is annotated with `link_checks` (per-entry) + a single `verdict`
(best quality across its entries). Reads output/preset_stability_results.json,
writes output/preset_stability_enriched.json.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlparse

import requests

IN_PATH = "output/preset_stability_results.json"
OUT_PATH = "output/preset_stability_enriched.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Domains that count as the official manufacturer source, per brand.
OFFICIAL: dict[str, tuple[str, ...]] = {
    "Panasonic": ("panasonic.com", "panasonic.net"),
    "LG": ("lg.com", "lge.com"),
    "Sony": ("sony.com", "sony.net", "sony.com.vn"),
}

# Hosts that ARE the detailed online manual viewer (not a landing/support page).
ONLINE_MANUAL_HOSTS = (
    "helpguide.sony.net",
    "gscs-manual.lge.com",
    "rd1.sony.net",
)

QUALITY_RANK = {"good": 3, "weak": 2, "bad": 1, "none": 0}

_cache: dict[str, dict[str, Any]] = {}


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def _browser_headers(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Referer": origin + "/",
    }


def _fetch(url: str) -> dict[str, Any]:
    """GET (stream, headers only) so we don't download big PDFs. Cached per URL.

    Uses browser-like headers and one Google-referer retry to cut down on false
    403s; many manufacturer sites still block non-JS clients regardless, so a
    403/429 is reported as 'blocked / unverified' rather than 'broken'."""
    if url in _cache:
        return _cache[url]
    info: dict[str, Any] = {"status": None, "content_type": "", "final_url": url, "error": None}
    with requests.Session() as s:
        for attempt in range(2):
            headers = _browser_headers(url)
            if attempt == 1:  # retry as if arriving from a Google search
                headers["Referer"] = "https://www.google.com/"
                headers["Sec-Fetch-Site"] = "cross-site"
            try:
                resp = s.get(url, stream=True, allow_redirects=True, timeout=25, headers=headers)
                info["status"] = resp.status_code
                info["content_type"] = (
                    resp.headers.get("Content-Type") or ""
                ).split(";")[0].strip().lower()
                info["final_url"] = resp.url
                resp.close()
                info["error"] = None
                if resp.status_code not in (403, 405, 429):
                    break
            except Exception as exc:  # noqa: BLE001 — timeout / connection / SSL
                info["error"] = f"{type(exc).__name__}: {exc}"[:120]
    _cache[url] = info
    return info


def _sub_html(path: str) -> str:
    p = path.lower()
    if any(k in p for k in ("/manual", "manuals", "operating-instruction", "owner")):
        return "manual_index"
    if any(k in p for k in ("/support", "tro-giup", "ho-tro", "/cs-", "/res/")):
        return "support_page"
    if any(k in p for k in ("/product", "/consumer", "/electronics", "washing-machine", "headphone")):
        return "product_page"
    return "html_other"


def classify(entry: dict[str, Any], brand: str) -> dict[str, Any]:
    etype = entry.get("type")
    url = (entry.get("url") or "").strip()
    label = entry.get("label") or ""

    if etype == "inline" or (not url and entry.get("content")):
        return {
            "kind": "inline", "quality": "weak", "trust": "n/a",
            "status": None, "url": None, "label": label,
            "note": "Nội dung dán trực tiếp, không có link gốc để kiểm chứng",
        }
    if not url:
        return {"kind": "none", "quality": "bad", "trust": "n/a", "status": None,
                "url": None, "label": label, "note": "Không có URL"}

    f = _fetch(url)
    final = f["final_url"] or url
    host = _host(final)
    official_suffixes = OFFICIAL.get(brand, ())
    is_official = any(host == s or host.endswith("." + s) for s in official_suffixes)
    trust = "official" if is_official else "third-party"
    status = f["status"]
    ctype = f["content_type"]
    path = urlparse(final).path

    # Infer what the link IS (from URL/content-type) regardless of HTTP status,
    # so a bot-blocked official PDF is still labelled "pdf", just unverified.
    is_pdf = "pdf" in ctype or path.lower().endswith(".pdf") or ".pdf" in final.lower()
    is_manual_host = any(host == h or host.endswith("." + h) for h in ONLINE_MANUAL_HOSTS)
    if is_pdf:
        kind = "pdf"
    elif is_manual_host:
        kind = "online_manual"
    elif "octet-stream" in ctype or "downloadfile" in final.lower() or "download" in path.lower():
        kind = "file_download"
    else:
        kind = _sub_html(path)

    is_doc = kind in ("pdf", "online_manual", "file_download")
    human = {
        "pdf": "File PDF (sách hướng dẫn)",
        "online_manual": "Trang xem sách HD trực tuyến",
        "file_download": "File tải về (tài liệu)",
        "support_page": "Trang hỗ trợ/sản phẩm (chứa link tải, chưa phải sách HD chi tiết)",
        "product_page": "Trang sản phẩm (chưa phải sách hướng dẫn)",
        "manual_index": "Trang danh sách/tổng hợp hướng dẫn (chưa vào tài liệu chi tiết)",
        "html_other": "Trang HTML chưa xác định là sách hướng dẫn chi tiết",
    }.get(kind, kind)

    # ── transport / status → quality ──
    if f["error"]:
        return {"kind": kind, "quality": "weak", "trust": trust, "status": None, "verified": False,
                "url": final, "label": label,
                "note": f"{human} — không truy cập được để xác minh ({f['error']})"}
    if status in (401, 403, 429):
        return {"kind": kind, "quality": "weak", "trust": trust, "status": status, "verified": False,
                "url": final, "label": label,
                "note": f"{human} — chưa xác minh được (HTTP {status}, site chặn bot; có thể vẫn mở trong trình duyệt)"}
    if status is None or status >= 400:
        return {"kind": "broken", "quality": "bad", "trust": trust, "status": status, "verified": True,
                "url": final, "label": label, "note": f"Link hỏng — HTTP {status}"}

    # ── 2xx: verified ──
    if is_doc:
        quality = "good" if is_official else "weak"
        note = (f"{human} — đã xác minh (HTTP {status}, {ctype or '?'})"
                if is_official else f"{human} nhưng domain ngoài chính hãng (HTTP {status})")
    else:
        quality = "weak"
        note = f"{human} — HTTP {status}" + ("" if is_official else " · domain ngoài chính hãng")

    return {"kind": kind, "quality": quality, "trust": trust, "status": status, "verified": True,
            "url": final, "label": label, "note": note}


def manual_entries(run: dict[str, Any]) -> list[dict[str, Any]]:
    result = run.get("result") or {}
    manual = result.get("manual") or {}
    entries = manual.get("manuals") or []
    if not entries and (manual.get("url") or manual.get("content")):
        entries = [{"type": manual.get("type"), "url": manual.get("url"),
                    "content": manual.get("content")}]
    if not entries and run.get("manuals"):
        entries = run["manuals"]
    return entries


def main() -> None:
    with open(IN_PATH, encoding="utf-8") as fh:
        runs = json.load(fh)

    for i, run in enumerate(runs, start=1):
        brand = run["brand"]
        entries = manual_entries(run)
        checks = [classify(e, brand) for e in entries]
        run["link_checks"] = checks
        if not checks:
            run["verdict"] = "none"
            run["verdict_detail"] = None
        else:
            best = max(checks, key=lambda c: QUALITY_RANK[c["quality"]])
            run["verdict"] = best["quality"]
            run["verdict_detail"] = best
        vd = run["verdict_detail"]
        tag = f"it{run.get('iteration')} {run['function'][:4]} {brand:9} {run['mode']:8} {'site' if run['with_site'] else 'no':4}"
        print(f"[{i:2}/{len(runs)}] {tag} → {run['verdict'].upper():5} "
              f"({(vd or {}).get('kind','-')})", flush=True)

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(runs, fh, ensure_ascii=False, indent=2)
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
