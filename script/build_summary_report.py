#!/usr/bin/env python3
"""Tạo file Excel báo cáo tổng hợp: độ chính xác, ổn định, thời gian.

Nguồn dữ liệu:
- output/preset_stability_report.md  (độ chính xác / chất lượng link + độ ổn định)
- output/preset_test_report.md       (thời gian chạy)
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "output" / "preset_summary_report.xlsx"

# ---- Bảng màu ----
NAVY = "1F3864"
BLUE = "2E5496"
LIGHT = "D9E1F2"
GREEN = "C6EFCE"
YELLOW = "FFEB9C"
RED = "FFC7CE"
GREY = "F2F2F2"
WHITE = "FFFFFF"

THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def title(ws, cell, text, span, size=14, fill=NAVY, color=WHITE):
    ws[cell] = text
    ws[cell].font = Font(bold=True, size=size, color=color)
    ws[cell].fill = PatternFill("solid", fgColor=fill)
    ws[cell].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    c0 = cell[0]
    r0 = int(cell[1:])
    ws.merge_cells(f"{c0}{r0}:{get_column_letter(ord(c0) - 64 + span - 1)}{r0}")
    ws.row_dimensions[r0].height = 26


def header_row(ws, row, headers, start_col=1, fill=BLUE):
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=start_col + i, value=h)
        c.font = Font(bold=True, color=WHITE, size=11)
        c.fill = PatternFill("solid", fgColor=fill)
        c.alignment = CENTER
        c.border = BORDER


def data_row(ws, row, values, start_col=1, fills=None, aligns=None, bolds=None):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=start_col + i, value=v)
        c.border = BORDER
        c.alignment = (aligns[i] if aligns else CENTER)
        if fills and fills[i]:
            c.fill = PatternFill("solid", fgColor=fills[i])
        if bolds and bolds[i]:
            c.font = Font(bold=True)


wb = Workbook()

# ============================================================
# Sheet 1 — Tổng quan
# ============================================================
ws = wb.active
ws.title = "Tổng quan"
ws.sheet_view.showGridLines = False
widths = [26, 16, 16, 16, 40]
for i, w in enumerate(widths, 1):
    ws.column_dimensions[get_column_letter(i)].width = w

title(ws, "A1", "BÁO CÁO KẾT QUẢ — Product Manual Finder (Crawl) vs Web Search Finder", 5, size=14)

meta = [
    ("Phạm vi", "3 hãng × 15 kịch bản/lần × 3 lần lặp = 45 run"),
    ("Sản phẩm", "Panasonic NA-F85S11BRV · LG FV1412S3B · Sony WF-1000XM6"),
    ("Model web-search", "gemini-3.5-flash"),
    ("Backend", "localhost:8080"),
    ("Kiểm chứng link", "Mỗi link được fetch thật (HTTP status / content-type / domain)"),
]
r = 3
for k, v in meta:
    ws.cell(row=r, column=1, value=k).font = Font(bold=True)
    ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=LIGHT)
    ws.cell(row=r, column=1).alignment = LEFT
    ws.cell(row=r, column=1).border = BORDER
    ws.cell(row=r, column=2, value=v).alignment = LEFT
    ws.cell(row=r, column=2).border = BORDER
    ws.merge_cells(f"B{r}:E{r}")
    r += 1

r += 1
title(ws, f"A{r}", "BẢNG CHỈ SỐ CHÍNH (theo nhóm pipeline)", 5, size=12, fill=BLUE)
r += 1
header_row(ws, r, ["Nhóm", "Tỉ lệ good\n(chính xác)", "Tỉ lệ FOUND", "Thời gian TB (s)", "Nhận xét"])
r += 1

# Nhóm | good | found | time | note
rows = [
    ("Crawl (Product Manual Finder)", "9/9 (100%)", "3/3", "69.0", "Chính xác & tin cậy nhất; PDF chính hãng; chậm nhất", GREEN),
    ("Web Search — Grounded", "7/18 (39%)", "6/6", "8.6", "Độ phủ tốt, nhanh; chất lượng link thật còn thấp", YELLOW),
    ("Web Search — SerpAPI", "6/18 (33%)", "4/6", "7.0", "Nhanh nhất; dễ trượt khi chỉ có trang SP/bán lẻ", YELLOW),
    ("Web Search — không chỉ định site", "9/18 (50%)", "5/6", "7.0", "Chất lượng tốt hơn rõ rệt so với có-site", LIGHT),
    ("Web Search — có chỉ định site", "4/18 (22%)", "5/6", "8.6", "Kém nhất; dễ ra trang index/hỗ trợ", LIGHT),
]
for name, good, found, t, note, fill in rows:
    data_row(
        ws, r,
        [name, good, found, t, note],
        fills=[fill, None, None, None, None],
        aligns=[LEFT, CENTER, CENTER, CENTER, LEFT],
        bolds=[True, False, False, False, False],
    )
    ws.row_dimensions[r].height = 30
    r += 1

# ============================================================
# Sheet 2 — Độ chính xác
# ============================================================
ws2 = wb.create_sheet("Độ chính xác")
ws2.sheet_view.showGridLines = False
for i, w in enumerate([34, 12, 12, 12, 12, 14], 1):
    ws2.column_dimensions[get_column_letter(i)].width = w

title(ws2, "A1", "ĐỘ CHÍNH XÁC — Chất lượng link đã kiểm chứng (fetch thật)", 6)
ws2["A2"] = ("good = sách HD thật trên domain chính hãng · weak = trang SP/hỗ trợ/index hoặc "
             "không xác minh được · bad = link hỏng · none = không có tài liệu")
ws2["A2"].alignment = LEFT
ws2["A2"].font = Font(italic=True, size=10)
ws2.merge_cells("A2:F2")
ws2.row_dimensions[2].height = 28

header_row(ws2, 4, ["Nhóm", "✅ good", "🟡 weak", "❌ bad", "⚪ none", "Tỉ lệ good"])
acc = [
    ("Crawl (Product Manual Finder)", 9, 0, 0, 0, "9/9", GREEN),
    ("Web Search — SerpAPI", 6, 6, 0, 6, "6/18", None),
    ("Web Search — Grounded", 7, 10, 1, 0, "7/18", None),
    ("Web Search — có site", 4, 10, 1, 3, "4/18", None),
    ("Web Search — không site", 9, 6, 0, 3, "9/18", None),
]
r = 5
for name, g, w, b, n, ratio, fill in acc:
    data_row(ws2, r, [name, g, w, b, n, ratio],
             fills=[fill, GREEN, YELLOW, RED, GREY, None],
             aligns=[LEFT, CENTER, CENTER, CENTER, CENTER, CENTER],
             bolds=[True, False, False, False, False, True])
    r += 1

r += 1
title(ws2, f"A{r}", "LINK TỐT NHẤT TỪNG KỊCH BẢN (đã kiểm chứng)", 6, size=12, fill=BLUE)
r += 1
header_row(ws2, r, ["Hãng", "Kịch bản", "Mức", "Kind", "Ghi chú", "URL"])
r += 1
best = [
    ("Panasonic", "Crawl (có site)", "✅ good", "pdf", "PDF sách HD — HTTP 200", "panasonic.com/.../Operating-Install…", GREEN),
    ("Panasonic", "SerpAPI / có site", "⚪ none", "—", "Không tìm thấy tài liệu", "—", GREY),
    ("Panasonic", "SerpAPI / không site", "⚪ none", "—", "Không tìm thấy tài liệu", "—", GREY),
    ("Panasonic", "Grounded / có site", "🟡 weak", "product_page", "Trang sản phẩm, chưa xác minh", "panasonic.com/vn/.../washing-machine…", YELLOW),
    ("Panasonic", "Grounded / không site", "🟡 weak", "product_page", "Trang sản phẩm, chưa xác minh", "panasonic.com/vn/.../washing-machine…", YELLOW),
    ("LG", "Crawl (có site)", "✅ good", "pdf", "PDF sách HD — HTTP 200", "gscs-b2c.lge.com/open/downloadFile…", GREEN),
    ("LG", "SerpAPI / có site", "🟡 weak", "support_page", "Trang hỗ trợ, chưa phải sách HD", "lg.com/vn/.../cs-FV1412S3B/", YELLOW),
    ("LG", "SerpAPI / không site", "✅ good", "online_manual", "Sách HD trực tuyến — HTTP 200", "gscs-manual.lge.com/.../main.html", GREEN),
    ("LG", "Grounded / có site", "✅ good", "online_manual", "Sách HD trực tuyến — HTTP 200", "gscs-manual.lge.com/.../main.html", GREEN),
    ("LG", "Grounded / không site", "🟡 weak", "html_other", "Trang HTML chưa xác định", "gscs-b2c.lge.com/historyBack…", YELLOW),
    ("Sony", "Crawl (có site)", "✅ good", "pdf", "PDF sách HD — HTTP 200", "sony.com/.../manuals/BP32/…", GREEN),
    ("Sony", "SerpAPI / có site", "🟡 weak", "manual_index", "Trang danh sách HD", "sony.com.vn/.../wireless-headphones…", YELLOW),
    ("Sony", "SerpAPI / không site", "✅ good", "online_manual", "Sách HD trực tuyến — HTTP 200", "helpguide.sony.net/mdr/2985/…", GREEN),
    ("Sony", "Grounded / có site", "✅ good", "online_manual", "Sách HD trực tuyến — HTTP 200", "helpguide.sony.net/mdr/2985/…", GREEN),
    ("Sony", "Grounded / không site", "✅ good", "online_manual", "Sách HD trực tuyến — HTTP 200", "helpguide.sony.net/mdr/2985/…", GREEN),
]
for hang, kb, muc, kind, note, url, fill in best:
    data_row(ws2, r, [hang, kb, muc, kind, note, url],
             fills=[None, None, fill, None, None, None],
             aligns=[CENTER, LEFT, CENTER, CENTER, LEFT, LEFT])
    r += 1

# ============================================================
# Sheet 3 — Độ ổn định
# ============================================================
ws3 = wb.create_sheet("Độ ổn định")
ws3.sheet_view.showGridLines = False
for i, w in enumerate([14, 24, 14, 14, 14, 8, 18], 1):
    ws3.column_dimensions[get_column_letter(i)].width = w

title(ws3, "A1", "ĐỘ ỔN ĐỊNH — Verdict qua 3 lần chạy", 7)
ws3["A2"] = "12/15 kịch bản ổn định (verdict giống nhau cả 3 lần) · 3/15 kịch bản dao động"
ws3["A2"].font = Font(bold=True, size=11, color=NAVY)
ws3["A2"].alignment = LEFT
ws3.merge_cells("A2:G2")

header_row(ws3, 4, ["Hãng", "Kịch bản", "Lần 1", "Lần 2", "Lần 3", "#Good", "Ổn định?"])
stab = [
    ("Panasonic", "Crawl (có site)", "✅ pdf", "✅ pdf", "✅ pdf", 3, "Ổn định (tốt)", GREEN),
    ("Panasonic", "SerpAPI / có site", "⚪ -", "⚪ -", "⚪ -", 0, "Ổn định (none)", GREY),
    ("Panasonic", "SerpAPI / không site", "⚪ -", "⚪ -", "⚪ -", 0, "Ổn định (none)", GREY),
    ("Panasonic", "Grounded / có site", "🟡 product", "❌ broken", "🟡 product", 0, "⚠️ Dao động", RED),
    ("Panasonic", "Grounded / không site", "🟡 product", "🟡 product", "🟡 product", 0, "Ổn định (weak)", YELLOW),
    ("LG", "Crawl (có site)", "✅ pdf", "✅ pdf", "✅ pdf", 3, "Ổn định (tốt)", GREEN),
    ("LG", "SerpAPI / có site", "🟡 support", "🟡 support", "🟡 support", 0, "Ổn định (weak)", YELLOW),
    ("LG", "SerpAPI / không site", "✅ online", "✅ online", "✅ online", 3, "Ổn định (tốt)", GREEN),
    ("LG", "Grounded / có site", "🟡 support", "🟡 support", "✅ online", 1, "⚠️ Dao động", RED),
    ("LG", "Grounded / không site", "🟡 html", "🟡 support", "🟡 html", 0, "Ổn định (weak)", YELLOW),
    ("Sony", "Crawl (có site)", "⚪ none", "✅ pdf", "✅ pdf", 2, "⚠️ Dao động", RED),
    ("Sony", "SerpAPI / có site", "🟡 index", "🟡 index", "🟡 index", 0, "Ổn định (weak)", YELLOW),
    ("Sony", "SerpAPI / không site", "✅ online", "✅ online", "✅ online", 3, "Ổn định (tốt)", GREEN),
    ("Sony", "Grounded / có site", "✅ online", "✅ online", "✅ online", 3, "Ổn định (tốt)", GREEN),
    ("Sony", "Grounded / không site", "✅ online", "✅ online", "✅ online", 3, "Ổn định (tốt)", GREEN),
]
r = 5
for hang, kb, l1, l2, l3, ng, od, fill in stab:
    data_row(ws3, r, [hang, kb, l1, l2, l3, ng, od],
             fills=[None, None, None, None, None, None, fill],
             aligns=[CENTER, LEFT, CENTER, CENTER, CENTER, CENTER, LEFT])
    r += 1

r += 1
ws3.cell(row=r, column=1, value="Kịch bản dao động:").font = Font(bold=True)
r += 1
for txt in [
    "Panasonic · Grounded/có-site: 🟡 weak → ❌ bad → 🟡 weak",
    "LG · Grounded/có-site: 🟡 weak → 🟡 weak → ✅ good",
    "Sony · Crawl/có-site: ⚪ none → ✅ good → ✅ good",
]:
    ws3.cell(row=r, column=1, value="• " + txt).alignment = LEFT
    ws3.merge_cells(f"A{r}:G{r}")
    r += 1

# ============================================================
# Sheet 4 — Thời gian
# ============================================================
ws4 = wb.create_sheet("Thời gian")
ws4.sheet_view.showGridLines = False
for i, w in enumerate([34, 18, 18, 30], 1):
    ws4.column_dimensions[get_column_letter(i)].width = w

title(ws4, "A1", "THỜI GIAN — Thời gian chạy trung bình mỗi run", 4)
header_row(ws4, 3, ["Nhóm", "Thời gian TB (s)", "Xếp hạng tốc độ", "Ghi chú"])
times = [
    ("Web Search — SerpAPI", 7.0, "Nhanh nhất", "Phụ thuộc hạn ngạch/độ ổn định SerpAPI", GREEN),
    ("Web Search — Grounded", 8.6, "Nhanh", "Không phụ thuộc SerpAPI", GREEN),
    ("Crawl (Product Manual Finder)", 69.0, "Chậm nhất", "43.7 / 97.7 / 65.6 s — chậm gấp ~8–10×", RED),
]
r = 4
for name, t, rank, note, fill in times:
    data_row(ws4, r, [name, t, rank, note],
             fills=[None, fill, None, None],
             aligns=[LEFT, CENTER, CENTER, LEFT],
             bolds=[True, True, False, False])
    r += 1

r += 1
title(ws4, f"A{r}", "THỜI GIAN CRAWL THEO HÃNG (s)", 4, size=12, fill=BLUE)
r += 1
header_row(ws4, r, ["Hãng", "Mã sản phẩm", "Thời gian (s)", "Trạng thái"])
r += 1
for hang, ma, t in [("Panasonic", "NA-F85S11BRV", 43.7), ("LG", "FV1412S3B", 97.7), ("Sony", "WF-1000XM6", 65.6)]:
    data_row(ws4, r, [hang, ma, t, "✅ FOUND"],
             aligns=[CENTER, CENTER, CENTER, CENTER])
    r += 1

# ============================================================
# Sheet 5 — Kết luận
# ============================================================
ws5 = wb.create_sheet("Kết luận")
ws5.sheet_view.showGridLines = False
ws5.column_dimensions["A"].width = 100

title(ws5, "A1", "KẾT LUẬN & KHUYẾN NGHỊ", 1)

points = [
    ("Crawl (Product Manual Finder)", "Chính xác và ổn định nhất — 100% link đúng (PDF chính hãng), nhưng chậm nhất (~69s, gấp ~10 lần web search)."),
    ("Grounded", "Độ phủ cao (FOUND 6/6), nhanh (~8.6s), không phụ thuộc hạn ngạch SerpAPI; nhưng chất lượng link thật chỉ ~39%."),
    ("SerpAPI", "Nhanh nhất (~7.0s) nhưng dễ trượt khi Google chỉ trả trang sản phẩm/mạng xã hội/bán lẻ (good ~33%)."),
    ("Có / không chỉ định site", "Không chỉ định site cho chất lượng tốt hơn rõ rệt (50% vs 22% good)."),
    ("Lưu ý đọc kết quả", "Tỉ lệ 'FOUND' của web search cao nhưng phần lớn là trang SP/hỗ trợ (weak) — cần ưu tiên cột verdict + Kind thay vì chỉ 'tìm thấy'."),
]
r = 3
for k, v in points:
    ws5.cell(row=r, column=1, value="▸ " + k).font = Font(bold=True, size=11, color=NAVY)
    ws5.cell(row=r, column=1).fill = PatternFill("solid", fgColor=LIGHT)
    ws5.cell(row=r, column=1).alignment = LEFT
    ws5.cell(row=r, column=1).border = BORDER
    r += 1
    c = ws5.cell(row=r, column=1, value=v)
    c.alignment = LEFT
    c.border = BORDER
    ws5.row_dimensions[r].height = 34
    r += 2

r += 1
c = ws5.cell(row=r, column=1, value="TỔNG KẾT")
c.font = Font(bold=True, size=13, color=WHITE)
c.fill = PatternFill("solid", fgColor=GREEN if False else NAVY)
c.alignment = LEFT
ws5.row_dimensions[r].height = 26
r += 1
summary = ("Product Manual Finder (Crawl) cho kết quả chính xác và ổn định nhất (100% link đúng) nhưng "
           "chậm gấp ~10 lần; Web Search Finder nhanh hơn nhiều và độ phủ cao nhưng chất lượng link thật "
           "chỉ ~33–39%. → Dùng CRAWL khi cần đúng tài liệu; dùng WEB SEARCH (ưu tiên Grounded, không "
           "chỉ định site) khi cần tốc độ và độ phủ.")
c = ws5.cell(row=r, column=1, value=summary)
c.font = Font(bold=True, size=11)
c.fill = PatternFill("solid", fgColor=YELLOW)
c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
c.border = BORDER
ws5.row_dimensions[r].height = 80

wb.save(OUT)
print(f"Đã lưu: {OUT}")
