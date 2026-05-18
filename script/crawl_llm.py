"""
Script crawl kết hợp LLM (Gemini) để trích xuất thông tin sản phẩm có cấu trúc.
Đọc GEMINI_API_TOKEN từ biến môi trường hoặc file .env.

Chạy local: python app/crawl_llm.py
Chạy Docker: docker compose run crawl app/crawl_llm.py
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy

TARGET_URL = "https://www.panasonic.com/vn/consumer/home-appliances/fridge/prime-edition/NA-F85S11BRV.html"
OUTPUT_DIR = Path("output")


class ProductInfo(BaseModel):
    name: str = Field(..., description="Tên đầy đủ của sản phẩm")
    model: Optional[str] = Field(None, description="Mã model sản phẩm (ví dụ: NA-F85S11BRV)")
    category: Optional[str] = Field(None, description="Nhóm sản phẩm (ví dụ: Tủ lạnh)")
    capacity: Optional[str] = Field(None, description="Dung tích sản phẩm, nếu có")
    key_features: List[str] = Field(default_factory=list, description="Các tính năng nổi bật")
    technologies: List[str] = Field(default_factory=list, description="Công nghệ áp dụng")
    colors: List[str] = Field(default_factory=list, description="Các màu sắc có sẵn")
    energy_class: Optional[str] = Field(None, description="Phân loại năng lượng, nếu có")
    price: Optional[str] = Field(None, description="Giá bán (nếu hiển thị)")


async def main() -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_TOKEN")
    if not api_key:
        print("[FAIL] Thiếu GEMINI_API_TOKEN trong .env hoặc biến môi trường.")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)

    llm_cfg = LLMConfig(
        provider="gemini/gemini-2.5-flash",
        api_token=api_key,
    )

    extraction = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=ProductInfo.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Extract product information from website content according to schema."
            "Fields must be null or empty. Return valid JSON."
        ),
        chunk_token_threshold=4000,
        overlap_rate=0.0,
        apply_chunking=True,
        input_format="markdown",
        verbose=True,   # log từng chunk gửi lên LLM
    )

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True,   # log page load, JS console, network events
    )

    # ── Pha 1: Crawl (khong extraction) ─────────────────────────────────────
    crawl_run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=10,
        page_timeout=60_000,
    )

    print("\n── [1/2] CRAWL ─────────────────────────────────────────────────────")
    t0 = time.perf_counter()
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=TARGET_URL, config=crawl_run_cfg)
    t_crawl = time.perf_counter() - t0

    if not result.success:
        print(f"[FAIL] Crawl thất bại: {result.error_message}")
        return

    md = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown)
    print(f"  status={result.status_code} | html={len(result.html):,} chars | markdown={len(md):,} chars | {t_crawl:.2f}s")

    # ── Pha 2: LLM Extraction ────────────────────────────────────────────────
    # Đếm số chunk thực tế trước khi gửi LLM
    merged_chunks = extraction._merge(
        [md],
        extraction.chunk_token_threshold,
        overlap=int(extraction.chunk_token_threshold * extraction.overlap_rate),
    )
    print(f"\n── [2/2] LLM EXTRACTION ─── {len(merged_chunks)} chunk(s) → {llm_cfg.provider} ──")
    print("  verbose=True: mỗi dòng [LOG] là 1 chunk gửi tới LLM")

    t0 = time.perf_counter()
    extracted_blocks = extraction.run(url=TARGET_URL, sections=[md])
    t_extract = time.perf_counter() - t0

    print(f"\n  Extraction done: {t_extract:.2f}s | {len(extracted_blocks)} block(s) trả về")
    extraction.show_usage()

    # ── Lưu kết quả ──────────────────────────────────────────────────────────
    out_path = OUTPUT_DIR / "panasonic_llm.json"
    if extracted_blocks:
        data = extracted_blocks[0] if len(extracted_blocks) == 1 else extracted_blocks
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] Output: {out_path.resolve()}")
        print("\n── Kết quả trích xuất ──────────────────────────────────────────────")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("[WARN] Không có nội dung trích xuất.")


if __name__ == "__main__":
    asyncio.run(main())
