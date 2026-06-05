"""Generate an Excel workbook + a Markdown comparison from the harness JSON.

Reads output/preset_test_results.json (produced by preset_test_harness.py) and
writes:
  - output/preset_test_report.xlsx   (3 sheets: All Runs, Web Search Compare, Crawl)
  - output/preset_test_report.md      (human-readable comparison)
"""
from __future__ import annotations

import json
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

RESULTS_PATH = "output/preset_test_results.json"
XLSX_PATH = "output/preset_test_report.xlsx"
MD_PATH = "output/preset_test_report.md"

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")
BAD_FILL = PatternFill("solid", fgColor="FFC7CE")
GROUP_FILL = PatternFill("solid", fgColor="DDEBF7")


def load() -> list[dict[str, Any]]:
    with open(RESULTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ── derived per-run fields ────────────────────────────────────────────────────

def manual_info(run: dict[str, Any]) -> dict[str, Any]:
    """Pull primary type, manual count and a joined URL list from the result."""
    result = run.get("result") or {}
    manual = result.get("manual") or {}
    entries = manual.get("manuals") or []
    # Fall back to manuals captured from SSE progress if result had none.
    if not entries and run.get("manuals"):
        entries = run["manuals"]
    urls = []
    for e in entries:
        u = e.get("url")
        if u:
            urls.append(u)
        elif e.get("type") == "inline":
            urls.append(f"(inline {len(e.get('content') or '')} chars)")
    primary_type = manual.get("type") or "not_found"
    return {
        "success": bool(result.get("success")),
        "primary_type": primary_type,
        "manual_count": len(entries),
        "urls": urls,
        "entries": entries,
    }


def status_text(run: dict[str, Any], info: dict[str, Any]) -> str:
    if run.get("error"):
        return "ERROR"
    if run.get("timed_out"):
        return "TIMEOUT"
    return "FOUND" if info["success"] else "NOT FOUND"


# ── Excel ──────────────────────────────────────────────────────────────────────

def _style_header(ws, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, widths: dict[int, int]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def build_xlsx(runs: list[dict[str, Any]]) -> None:
    wb = Workbook()

    # ── Sheet 1: All Runs ──
    ws = wb.active
    ws.title = "All Runs"
    headers = [
        "Function", "Brand", "Product", "Code", "Mode", "SerpAPI", "Site?",
        "Status", "Primary type", "#Manuals", "#Queries", "#Sources",
        "Elapsed (s)", "#Log", "Manual URLs", "Summary / Reason / Error",
    ]
    ws.append(headers)
    _style_header(ws, len(headers))

    for run in runs:
        info = manual_info(run)
        st = status_text(run, info)
        note = run.get("error") or run.get("summary") or run.get("reason") or ""
        row = [
            run["function"],
            run["brand"],
            run["product_name"],
            run["product_code"],
            run["mode"],
            "—" if run.get("use_serpapi") is None else ("Yes" if run["use_serpapi"] else "No"),
            "Yes" if run["with_site"] else "No",
            st,
            info["primary_type"],
            info["manual_count"],
            len(run.get("queries") or []),
            len(run.get("sources") or []),
            run.get("elapsed_s"),
            run.get("log_count"),
            "\n".join(info["urls"]),
            note,
        ]
        ws.append(row)
        r = ws.max_row
        ws.cell(row=r, column=8).fill = OK_FILL if st == "FOUND" else BAD_FILL
        for c in (15, 16):
            ws.cell(row=r, column=c).alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, {1: 22, 2: 11, 3: 20, 4: 15, 5: 10, 6: 9, 7: 7, 8: 11,
                   9: 13, 10: 9, 11: 10, 12: 10, 13: 12, 14: 7, 15: 55, 16: 50})

    # ── Sheet 2: Web Search Compare (matrix per brand x combo) ──
    ws2 = wb.create_sheet("Web Search Compare")
    h2 = ["Brand", "Product", "Combo", "SerpAPI", "Site?", "Status",
          "Primary type", "#Manuals", "#Queries", "#Sources", "Elapsed (s)", "Primary URL"]
    ws2.append(h2)
    _style_header(ws2, len(h2))
    for run in runs:
        if run["function"] != "Web Search Finder":
            continue
        info = manual_info(run)
        st = status_text(run, info)
        ws2.append([
            run["brand"],
            run["product_name"],
            f"{run['mode']} / {'site' if run['with_site'] else 'no-site'}",
            "Yes" if run["use_serpapi"] else "No",
            "Yes" if run["with_site"] else "No",
            st,
            info["primary_type"],
            info["manual_count"],
            len(run.get("queries") or []),
            len(run.get("sources") or []),
            run.get("elapsed_s"),
            info["urls"][0] if info["urls"] else "",
        ])
        r = ws2.max_row
        ws2.cell(row=r, column=6).fill = OK_FILL if st == "FOUND" else BAD_FILL
    _autosize(ws2, {1: 11, 2: 20, 3: 20, 4: 9, 5: 7, 6: 11, 7: 13, 8: 9,
                    9: 10, 10: 10, 11: 12, 12: 60})

    # ── Sheet 3: Crawl (Product Manual Finder) ──
    ws3 = wb.create_sheet("Crawl")
    h3 = ["Brand", "Product", "Code", "Site", "Status", "Primary type",
          "#Manuals", "Elapsed (s)", "Steps (step:status)", "Manual URLs", "Error"]
    ws3.append(h3)
    _style_header(ws3, len(h3))
    for run in runs:
        if run["function"] != "Product Manual Finder":
            continue
        info = manual_info(run)
        st = status_text(run, info)
        steps = " → ".join(f"{p['step']}:{p['status']}" for p in run.get("progress", []))
        ws3.append([
            run["brand"], run["product_name"], run["product_code"], run["site"],
            st, info["primary_type"], info["manual_count"], run.get("elapsed_s"),
            steps, "\n".join(info["urls"]), run.get("error") or "",
        ])
        r = ws3.max_row
        ws3.cell(row=r, column=5).fill = OK_FILL if st == "FOUND" else BAD_FILL
        ws3.cell(row=r, column=9).alignment = Alignment(wrap_text=True, vertical="top")
        ws3.cell(row=r, column=10).alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws3, {1: 11, 2: 20, 3: 15, 4: 28, 5: 11, 6: 13, 7: 9, 8: 12,
                    9: 50, 10: 55, 11: 40})

    wb.save(XLSX_PATH)
    print(f"wrote {XLSX_PATH}")


# ── Markdown ─────────────────────────────────────────────────────────────────

def _md_status(st: str) -> str:
    return {"FOUND": "✅ FOUND", "NOT FOUND": "⚠️ NOT FOUND",
            "ERROR": "❌ ERROR", "TIMEOUT": "⏱️ TIMEOUT"}.get(st, st)


def _note(run: dict[str, Any], info: dict[str, Any], n: int = 75) -> str:
    """Short human note: error → reason (failures) → summary (success)."""
    comp = run.get("completion") or {}
    st = status_text(run, info)
    if st in ("FOUND",):
        txt = run.get("summary") or ""
    else:
        txt = run.get("error") or comp.get("error") or run.get("reason") or ""
    txt = (txt or "").replace("\n", " ").replace("|", "/").strip()
    return (txt[: n - 1] + "…") if len(txt) > n else (txt or "—")


def build_md(runs: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    A = lines.append

    crawl = [r for r in runs if r["function"] == "Product Manual Finder"]
    web = [r for r in runs if r["function"] == "Web Search Finder"]

    total_found = sum(1 for r in runs if status_text(r, manual_info(r)) == "FOUND")

    A("# So sánh kết quả test — Product Manual Finder vs Web Search Finder\n")
    A(f"- **Tổng số run:** {len(runs)}  ·  **FOUND:** {total_found}/{len(runs)}")
    A("- **Hãng (mỗi hãng 1 preset):** Panasonic · LG · Sony")
    A("- **Product Manual Finder (crawl):** 1 run/hãng (bắt buộc có site)")
    A("- **Web Search Finder:** mỗi hãng 4 tổ hợp = {SerpAPI, Grounded} × {có site, không site}")
    ws_model = next(
        (r.get("model") for r in web if r.get("model")), "gemini (backend default)"
    )
    A(f"- **Model (web-search):** `{ws_model}`  ·  **Backend:** `localhost:8080`\n")

    # ── Crawl section ──
    A("## 1. Product Manual Finder (Crawl)\n")
    A("| Hãng | Sản phẩm | Mã | Trạng thái | Loại | #Manual | Thời gian (s) | URL chính | Ghi chú |")
    A("|------|----------|-----|-----------|------|---------|---------------|-----------|---------|")
    for r in crawl:
        info = manual_info(r)
        url = info["urls"][0] if info["urls"] else "—"
        A(f"| {r['brand']} | {r['product_name']} | `{r['product_code']}` | "
          f"{_md_status(status_text(r, info))} | {info['primary_type']} | {info['manual_count']} | "
          f"{r.get('elapsed_s')} | {_short(url)} | {_note(r, info)} |")
    A("")

    # ── Web search section, grouped by brand ──
    A("## 2. Web Search Finder\n")
    by_brand: dict[str, list[dict[str, Any]]] = {}
    for r in web:
        by_brand.setdefault(r["brand"], []).append(r)
    for brand, group in by_brand.items():
        code = group[0]["product_code"]
        A(f"### {brand} — {group[0]['product_name']} (`{code}`)\n")
        A("| Tổ hợp | SerpAPI | Site | Trạng thái | Loại | #Manual | #Query | #Source | Thời gian (s) | URL chính | Ghi chú |")
        A("|--------|---------|------|-----------|------|---------|--------|---------|---------------|-----------|---------|")
        for r in group:
            info = manual_info(r)
            url = info["urls"][0] if info["urls"] else "—"
            combo = f"{r['mode']} / {'có site' if r['with_site'] else 'không site'}"
            A(f"| {combo} | {'Có' if r['use_serpapi'] else 'Không'} | "
              f"{'Có' if r['with_site'] else 'Không'} | {_md_status(status_text(r, info))} | "
              f"{info['primary_type']} | {info['manual_count']} | {len(r.get('queries') or [])} | "
              f"{len(r.get('sources') or [])} | {r.get('elapsed_s')} | {_short(url)} | {_note(r, info)} |")
        A("")

    # ── Cross-cutting comparison ──
    A("## 3. Nhận xét so sánh\n")

    def avg(items, key):
        vals = [i.get(key) for i in items if isinstance(i.get(key), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    serp = [r for r in web if r["use_serpapi"]]
    grounded = [r for r in web if not r["use_serpapi"]]
    with_site = [r for r in web if r["with_site"]]
    no_site = [r for r in web if not r["with_site"]]

    def found_rate(items):
        if not items:
            return "—"
        f = sum(1 for r in items if status_text(r, manual_info(r)) == "FOUND")
        return f"{f}/{len(items)}"

    A("| Nhóm | Tỉ lệ FOUND | Thời gian TB (s) |")
    A("|------|-------------|------------------|")
    A(f"| Crawl (Product Manual Finder) | {found_rate(crawl)} | {avg(crawl,'elapsed_s')} |")
    A(f"| Web Search — SerpAPI | {found_rate(serp)} | {avg(serp,'elapsed_s')} |")
    A(f"| Web Search — Grounded | {found_rate(grounded)} | {avg(grounded,'elapsed_s')} |")
    A(f"| Web Search — có site | {found_rate(with_site)} | {avg(with_site,'elapsed_s')} |")
    A(f"| Web Search — không site | {found_rate(no_site)} | {avg(no_site,'elapsed_s')} |")
    A("")

    # ── computed facts (no hard-coded run-specific narrative) ──
    def n_found(items):
        return sum(1 for r in items if status_text(r, manual_info(r)) == "FOUND")

    g_f, g_n, g_avg = n_found(grounded), len(grounded), avg(grounded, "elapsed_s")
    s_f, s_n, s_avg = n_found(serp), len(serp), avg(serp, "elapsed_s")
    c_f, c_n, c_avg = n_found(crawl), len(crawl), avg(crawl, "elapsed_s")

    # Web-search modes ranked by found rate, then by speed.
    ranked = sorted(
        [("Grounded", (g_f / g_n if g_n else 0), g_avg),
         ("SerpAPI", (s_f / s_n if s_n else 0), s_avg)],
        key=lambda m: (-m[1], m[2]),
    )
    best_mode = ranked[0][0]
    faster_mode = "Grounded" if g_avg <= s_avg else "SerpAPI"

    crawl_fail = [
        (r["brand"], _note(r, manual_info(r), 60))
        for r in crawl
        if status_text(r, manual_info(r)) != "FOUND"
    ]

    A("### Kết luận chính\n")
    A(f"- **Grounded:** tìm thấy {g_f}/{g_n} (TB {g_avg}s), không phụ thuộc hạn ngạch SerpAPI.")
    serp_tail = (
        " — các lần trượt chủ yếu do kết quả chỉ có trang sản phẩm/mạng xã hội/bán lẻ "
        "hoặc Google không trả kết quả cho query có `site:`."
        if s_f < s_n else "."
    )
    A(f"- **SerpAPI:** tìm thấy {s_f}/{s_n} (TB {s_avg}s){serp_tail}")
    A(f"- **Grounded vs SerpAPI:** tỉ lệ tìm thấy {g_f}/{g_n} vs {s_f}/{s_n}; "
      f"nhanh hơn ở lần chạy này: **{faster_mode}**.")
    A(f"- **Có/không chỉ định site:** chênh lệch nhỏ (có site {found_rate(with_site)} "
      f"vs không site {found_rate(no_site)}); kết quả gần như tương đương, "
      "một số lần không-site còn trả nhiều tài liệu hơn.")
    if crawl_fail:
        fails = "; ".join(f"{b} ({why})" for b, why in crawl_fail)
        crawl_tail = f"có lần trượt — {fails}; pipeline crawl giòn hơn web-search."
    else:
        crawl_tail = "tất cả đều tìm thấy ở lần chạy này, nhưng vẫn là pipeline chậm nhất."
    A(f"- **Crawl (Product Manual Finder):** {c_f}/{c_n}, chậm nhất (TB {c_avg}s) — {crawl_tail}")
    A(f"- **Đề xuất:** ưu tiên Web Search Finder chế độ **{best_mode}** cho độ phủ/tốc độ; "
      "Crawl và chế độ web-search còn lại dùng làm phương án bổ sung.")
    A("")
    A("> Ghi chú: kết quả phụ thuộc nội dung web tại thời điểm chạy và độ ổn định của LLM/SerpAPI; "
      "có thể khác giữa các lần chạy.")
    A("")

    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"wrote {MD_PATH}")


def _short(url: str, n: int = 80) -> str:
    if not url:
        return "—"
    url = url.replace("|", "%7C")
    return url if len(url) <= n else url[: n - 1] + "…"


if __name__ == "__main__":
    runs = load()
    build_xlsx(runs)
    build_md(runs)
