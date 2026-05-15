"""
Script crawl đơn thuần (không dùng LLM).
Crawl 1 URL và xuất ra markdown + metadata.

Chạy local: python app/crawl_basic.py
Chạy Docker: docker compose run crawl app/crawl_basic.py
"""

import asyncio
import time
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

TARGET_URL = "https://www.panasonic.com/vn/consumer/home-appliances/fridge/prime-edition/nr-yw590xjkv.html"
OUTPUT_DIR = Path("output")


async def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True,   # log page load, JS console, network events
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=10,
        page_timeout=60_000,
    )

    t0 = time.perf_counter()
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=TARGET_URL, config=run_cfg)
    elapsed = time.perf_counter() - t0

    if not result.success:
        print(f"[FAIL] Crawl thất bại: {result.error_message}")
        return

    md_text = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown)
    md_path = OUTPUT_DIR / "panasonic_basic.md"
    md_path.write_text(md_text, encoding="utf-8")

    print("[OK] Crawl thành công!")
    print(f"  URL          : {result.url}")
    print(f"  Status code  : {result.status_code}")
    print(f"  Elapsed      : {elapsed:.2f}s")
    print(f"  HTML length  : {len(result.html):,} chars")
    print(f"  Markdown len : {len(md_text):,} chars")
    print(f"  Links found  : internal={len(result.links.get('internal', []))}, external={len(result.links.get('external', []))}")
    print(f"  Media images : {len(result.media.get('images', []))}")
    print(f"  Output       : {md_path.resolve()}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
