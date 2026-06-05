"""Stability + link-quality report from the enriched 3-iteration results.

Reads output/preset_stability_enriched.json (produced by preset_link_check.py)
and writes:
  - output/preset_stability_report.xlsx   (Stability Matrix · Runs · Quality)
  - output/preset_stability_report.md       (human-readable)

Quality is judged per run by `verdict` (good / weak / bad / none); the report
shows how the verdict moves across the 3 iterations (stability) and what each
"best" link actually is (PDF / online manual vs product / support / index page
vs broken).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

IN_PATH = "output/preset_stability_enriched.json"
XLSX_PATH = "output/preset_stability_report.xlsx"
MD_PATH = "output/preset_stability_report.md"

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
FILL = {
    "good": PatternFill("solid", fgColor="C6EFCE"),
    "weak": PatternFill("solid", fgColor="FFEB9C"),
    "bad": PatternFill("solid", fgColor="FFC7CE"),
    "none": PatternFill("solid", fgColor="D9D9D9"),
}
EMOJI = {"good": "✅", "weak": "🟡", "bad": "❌", "none": "⚪"}


def load() -> list[dict[str, Any]]:
    with open(IN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def scenario_key(r: dict[str, Any]) -> tuple:
    return (r["function"], r["brand"], r["mode"], bool(r["with_site"]))


def scenario_label(r: dict[str, Any]) -> str:
    if r["function"] == "Product Manual Finder":
        return "Crawl (có site)"
    return f"{r['mode']} / {'có site' if r['with_site'] else 'không site'}"


def cell_text(r: dict[str, Any]) -> str:
    v = r.get("verdict", "none")
    kind = (r.get("verdict_detail") or {}).get("kind", "-")
    return f"{EMOJI[v]} {kind}"


def best_across(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    rank = {"good": 3, "weak": 2, "bad": 1, "none": 0}
    cand = [r for r in runs if r.get("verdict_detail")]
    if not cand:
        return None
    return max(cand, key=lambda r: rank[r["verdict"]])["verdict_detail"]


# ── grouping ──────────────────────────────────────────────────────────────────

def group_scenarios(runs: list[dict[str, Any]]) -> dict[tuple, list[dict[str, Any]]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in runs:
        groups.setdefault(scenario_key(r), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r.get("iteration", 0))
    return groups


def stability_of(verdicts: list[str]) -> str:
    s = set(verdicts)
    if len(s) == 1:
        return "Ổn định (tốt)" if verdicts[0] == "good" else f"Ổn định ({verdicts[0]})"
    return "⚠️ Dao động"


# ── Excel ─────────────────────────────────────────────────────────────────────

def _hdr(ws, n: int) -> None:
    for c in range(1, n + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _widths(ws, w: dict[int, int]) -> None:
    for c, x in w.items():
        ws.column_dimensions[get_column_letter(c)].width = x


# Order: per brand, crawl first then the 4 web-search combos.
COMBO_ORDER = [
    ("Product Manual Finder", "crawl", True),
    ("Web Search Finder", "SerpAPI", True),
    ("Web Search Finder", "SerpAPI", False),
    ("Web Search Finder", "Grounded", True),
    ("Web Search Finder", "Grounded", False),
]
BRAND_ORDER = ["Panasonic", "LG", "Sony"]


def ordered_scenarios(groups) -> list[tuple]:
    keys = []
    for brand in BRAND_ORDER:
        for fn, mode, site in COMBO_ORDER:
            k = (fn, brand, mode, site)
            if k in groups:
                keys.append(k)
    # append any leftover keys not covered
    for k in groups:
        if k not in keys:
            keys.append(k)
    return keys


def build_xlsx(runs: list[dict[str, Any]], n_iter: int) -> None:
    groups = group_scenarios(runs)
    keys = ordered_scenarios(groups)
    wb = Workbook()

    # ── Sheet 1: Stability Matrix ──
    ws = wb.active
    ws.title = "Stability Matrix"
    head = ["Hãng", "Chức năng", "Kịch bản"] + [f"Lần {i}" for i in range(1, n_iter + 1)] + [
        "#Good", "Ổn định?", "Link tốt nhất (ví dụ)", "Kind", "Ghi chú",
    ]
    ws.append(head)
    _hdr(ws, len(head))
    for k in keys:
        g = groups[k]
        fn, brand, mode, site = k
        verdicts = [r.get("verdict", "none") for r in g]
        best = best_across(g)
        row = [brand, "Crawl" if fn == "Product Manual Finder" else "Web Search",
               scenario_label(g[0])]
        row += [cell_text(r) for r in g]
        # pad if an iteration is missing
        row += [""] * (n_iter - len(g))
        row += [
            sum(1 for v in verdicts if v == "good"),
            stability_of(verdicts),
            (best or {}).get("url") or "—",
            (best or {}).get("kind") or "—",
            (best or {}).get("note") or "—",
        ]
        ws.append(row)
        r_idx = ws.max_row
        for j, r in enumerate(g):
            ws.cell(row=r_idx, column=4 + j).fill = FILL[r.get("verdict", "none")]
        ws.cell(row=r_idx, column=len(head) - 1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r_idx, column=len(head)).alignment = Alignment(wrap_text=True, vertical="top")
    _widths(ws, {1: 11, 2: 12, 3: 20, **{4 + i: 16 for i in range(n_iter)},
                 4 + n_iter: 7, 5 + n_iter: 16, 6 + n_iter: 50, 7 + n_iter: 14, 8 + n_iter: 50})

    # ── Sheet 2: Runs (chi tiết) ──
    ws2 = wb.create_sheet("Runs")
    h2 = ["Lần", "Chức năng", "Hãng", "Mode", "Site?", "Verdict", "Kind", "Trust",
          "HTTP", "#Manual", "Elapsed (s)", "Best URL", "Ghi chú"]
    ws2.append(h2)
    _hdr(ws2, len(h2))
    for r in sorted(runs, key=lambda r: (r["brand"], r["function"], r["mode"], not r["with_site"], r.get("iteration", 0))):
        vd = r.get("verdict_detail") or {}
        ws2.append([
            r.get("iteration"),
            "Crawl" if r["function"] == "Product Manual Finder" else "Web Search",
            r["brand"], r["mode"], "Có" if r["with_site"] else "Không",
            r.get("verdict", "none"), vd.get("kind", "—"), vd.get("trust", "—"),
            vd.get("status", "—"), len(r.get("link_checks") or []),
            r.get("elapsed_s"), vd.get("url") or "—", vd.get("note") or "—",
        ])
        ws2.cell(row=ws2.max_row, column=6).fill = FILL[r.get("verdict", "none")]
        ws2.cell(row=ws2.max_row, column=13).alignment = Alignment(wrap_text=True, vertical="top")
    _widths(ws2, {1: 5, 2: 12, 3: 11, 4: 10, 5: 7, 6: 9, 7: 14, 8: 11, 9: 7,
                  10: 9, 11: 11, 12: 55, 13: 50})

    # ── Sheet 3: Quality summary ──
    ws3 = wb.create_sheet("Quality")
    ws3.append(["Nhóm", "good", "weak", "bad", "none", "Tổng", "Tỉ lệ good"])
    _hdr(ws3, 7)

    def add_group(name: str, items: list[dict[str, Any]]) -> None:
        c = Counter(r.get("verdict", "none") for r in items)
        tot = len(items)
        good = c.get("good", 0)
        ws3.append([name, good, c.get("weak", 0), c.get("bad", 0), c.get("none", 0),
                    tot, f"{good}/{tot}" if tot else "—"])

    add_group("TẤT CẢ", runs)
    add_group("Crawl (Product Manual Finder)", [r for r in runs if r["function"] == "Product Manual Finder"])
    add_group("Web Search — tất cả", [r for r in runs if r["function"] == "Web Search Finder"])
    add_group("Web Search — SerpAPI", [r for r in runs if r["mode"] == "SerpAPI"])
    add_group("Web Search — Grounded", [r for r in runs if r["mode"] == "Grounded"])
    add_group("Web Search — có site", [r for r in runs if r["function"] == "Web Search Finder" and r["with_site"]])
    add_group("Web Search — không site", [r for r in runs if r["function"] == "Web Search Finder" and not r["with_site"]])
    for it in sorted({r.get("iteration") for r in runs}):
        add_group(f"Lần chạy {it}", [r for r in runs if r.get("iteration") == it])
    _widths(ws3, {1: 34, 2: 8, 3: 8, 4: 8, 5: 8, 6: 8, 7: 12})

    wb.save(XLSX_PATH)
    print(f"wrote {XLSX_PATH}")


# ── Markdown ──────────────────────────────────────────────────────────────────

def build_md(runs: list[dict[str, Any]], n_iter: int) -> None:
    groups = group_scenarios(runs)
    keys = ordered_scenarios(groups)
    L: list[str] = []
    A = L.append

    model = next((r.get("model") for r in runs if r.get("model")), "gemini (backend default)")

    A("# Báo cáo độ ổn định & chất lượng link — Product Manual Finder vs Web Search Finder\n")
    A(f"- **Số lần lặp:** {n_iter} · **Tổng run:** {len(runs)} ({len(runs)//n_iter}/lần)")
    A("- **Hãng:** Panasonic `NA-F85S11BRV` · LG `FV1412S3B` · Sony `WF-1000XM6`")
    A(f"- **Model web-search:** `{model}` · **Backend:** `localhost:8080`")
    A("- **Lưu ý:** mỗi link manual được *fetch thật* để kiểm tra HTTP status, content-type và domain.\n")

    A("## Tiêu chí chất lượng link\n")
    A("| Mức | Ý nghĩa |")
    A("|-----|---------|")
    A("| ✅ **good** | Link **mở được** và là **tài liệu thật** (file PDF / trang xem sách HD trực tuyến chuyên dụng) trên **domain chính hãng** |")
    A("| 🟡 **weak** | Mở được nhưng **chưa phải sách HD chi tiết**: trang sản phẩm / trang hỗ trợ / trang danh sách HD; hoặc tài liệu nằm trên **domain ngoài chính hãng**; hoặc nội dung dán inline; hoặc không xác minh được (403/timeout) |")
    A("| ❌ **bad** | Link **hỏng** (404 / 5xx / chết) |")
    A("| ⚪ **none** | Không trả về tài liệu nào |\n")

    # ── Overview per iteration ──
    A("## 1. Tổng quan theo từng lần chạy\n")
    A("| Lần | ✅ good | 🟡 weak | ❌ bad | ⚪ none | Tỉ lệ good |")
    A("|-----|--------|---------|--------|---------|-----------|")
    for it in range(1, n_iter + 1):
        items = [r for r in runs if r.get("iteration") == it]
        c = Counter(r.get("verdict", "none") for r in items)
        tot = len(items)
        A(f"| {it} | {c.get('good',0)} | {c.get('weak',0)} | {c.get('bad',0)} | "
          f"{c.get('none',0)} | {c.get('good',0)}/{tot} |")
    A("")

    # ── Stability matrix per brand ──
    A("## 2. Ma trận ổn định (verdict qua các lần)\n")
    A("Mỗi ô = `verdict` + loại link tốt nhất của lần đó.\n")
    for brand in BRAND_ORDER:
        bkeys = [k for k in keys if k[1] == brand]
        if not bkeys:
            continue
        A(f"### {brand}\n")
        A("| Kịch bản | " + " | ".join(f"Lần {i}" for i in range(1, n_iter + 1)) + " | #Good | Ổn định? |")
        A("|----------|" + "|".join(["--------"] * n_iter) + "|-------|---------|")
        for k in bkeys:
            g = groups[k]
            verdicts = [r.get("verdict", "none") for r in g]
            cells = [cell_text(r) for r in g] + [""] * (n_iter - len(g))
            A(f"| {scenario_label(g[0])} | " + " | ".join(cells) + " | "
              f"{sum(1 for v in verdicts if v=='good')} | {stability_of(verdicts)} |")
        A("")

    # ── Best link per scenario ──
    A("## 3. Link tốt nhất từng kịch bản (đã kiểm chứng)\n")
    A("| Hãng | Kịch bản | Mức | Kind | Ghi chú | URL |")
    A("|------|----------|-----|------|---------|-----|")
    for k in keys:
        g = groups[k]
        best = best_across(g)
        v = best_verdict(g)
        if best:
            url = _short(best.get("url") or "—")
            A(f"| {k[1]} | {scenario_label(g[0])} | {EMOJI[v]} {v} | {best.get('kind','—')} | "
              f"{_clip(best.get('note','—'))} | {url} |")
        else:
            A(f"| {k[1]} | {scenario_label(g[0])} | ⚪ none | — | Không tìm thấy tài liệu | — |")
    A("")

    # ── Quality summary ──
    A("## 4. Tổng hợp chất lượng\n")
    A("| Nhóm | ✅ good | 🟡 weak | ❌ bad | ⚪ none | Tỉ lệ good |")
    A("|------|--------|---------|--------|---------|-----------|")

    def qrow(name, items):
        c = Counter(r.get("verdict", "none") for r in items)
        tot = len(items)
        A(f"| {name} | {c.get('good',0)} | {c.get('weak',0)} | {c.get('bad',0)} | "
          f"{c.get('none',0)} | {c.get('good',0)}/{tot} |")

    qrow("Crawl (Product Manual Finder)", [r for r in runs if r["function"] == "Product Manual Finder"])
    qrow("Web Search — SerpAPI", [r for r in runs if r["mode"] == "SerpAPI"])
    qrow("Web Search — Grounded", [r for r in runs if r["mode"] == "Grounded"])
    qrow("Web Search — có site", [r for r in runs if r["function"] == "Web Search Finder" and r["with_site"]])
    qrow("Web Search — không site", [r for r in runs if r["function"] == "Web Search Finder" and not r["with_site"]])
    A("")

    # ── Observations (computed) ──
    A("## 5. Nhận xét\n")
    unstable = []
    for k in keys:
        g = groups[k]
        verdicts = [r.get("verdict", "none") for r in g]
        if len(set(verdicts)) > 1:
            unstable.append((k, verdicts))
    n_scen = len(keys)
    A(f"- **Độ ổn định:** {n_scen - len(unstable)}/{n_scen} kịch bản cho verdict **giống nhau** cả {n_iter} lần; "
      f"{len(unstable)}/{n_scen} kịch bản **dao động** giữa các lần.")
    if unstable:
        for k, verdicts in unstable:
            A(f"  - {k[1]} · {scenario_label(groups[k][0])}: {' → '.join(EMOJI[v]+v for v in verdicts)}")
    # good rate per function
    def good_rate(items):
        tot = len(items)
        return f"{sum(1 for r in items if r.get('verdict')=='good')}/{tot}" if tot else "—"
    A(f"- **Chất lượng thật (good):** Crawl {good_rate([r for r in runs if r['function']=='Product Manual Finder'])}, "
      f"SerpAPI {good_rate([r for r in runs if r['mode']=='SerpAPI'])}, "
      f"Grounded {good_rate([r for r in runs if r['mode']=='Grounded'])} "
      "→ nhiều kết quả 'tìm thấy' thực chất chỉ là trang sản phẩm/hỗ trợ (🟡 weak), không phải sách HD chi tiết.")
    A("- **Khuyến nghị đọc báo cáo:** ưu tiên cột verdict + Kind thay vì chỉ 'tìm thấy'; "
      "kịch bản dao động cần chạy nhiều lần hoặc thêm bước xác minh link tự động.")
    A("")
    A("> Ghi chú: 403/timeout được xếp 🟡 (không xác minh được), có thể vẫn mở trong trình duyệt thật; "
      "kết quả phụ thuộc nội dung web + độ ổn định LLM/SerpAPI tại thời điểm chạy.")
    A("")

    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"wrote {MD_PATH}")


def best_verdict(g: list[dict[str, Any]]) -> str:
    rank = {"good": 3, "weak": 2, "bad": 1, "none": 0}
    return max((r.get("verdict", "none") for r in g), key=lambda v: rank[v])


def _short(url: str, n: int = 70) -> str:
    if not url or url == "—":
        return "—"
    url = url.replace("|", "%7C")
    return url if len(url) <= n else url[: n - 1] + "…"


def _clip(t: str, n: int = 60) -> str:
    t = (t or "").replace("\n", " ").replace("|", "/")
    return t if len(t) <= n else t[: n - 1] + "…"


if __name__ == "__main__":
    runs = load()
    n_iter = max((r.get("iteration", 1) for r in runs), default=1)
    build_xlsx(runs, n_iter)
    build_md(runs, n_iter)
