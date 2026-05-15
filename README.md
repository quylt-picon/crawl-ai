# Crawl4AI Local Demo

Demo [Crawl4AI](https://github.com/unclecode/crawl4ai) chạy local theo hướng venv.
URL mẫu: trang sản phẩm tủ lạnh Panasonic NR-YW590XJKV.

---

## Cấu trúc project

```
crawl-ai/
├── app/
│   ├── crawl_basic.py     # Crawl thuần, xuất Markdown
│   └── crawl_llm.py       # Crawl + Gemini LLM, xuất JSON
├── output/                # Kết quả crawl (tự sinh)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Local venv

### Yêu cầu
- Python ≥ 3.10

### Cài đặt

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
crawl4ai-setup          # Cài Playwright browsers (~92 MB, chỉ chạy 1 lần)
```

### Chạy

```bash
source venv/bin/activate

# Crawl thuần
python app/crawl_basic.py

# Crawl + LLM (cần .env có GEMINI_API_TOKEN)
cp .env.example .env    # điền key vào .env
python app/crawl_llm.py
```

---

## Cấu hình API key (chỉ cần cho crawl_llm.py)

```bash
cp .env.example .env
```

Mở `.env` và điền:

```
GEMINI_API_TOKEN=AIza...
```

Lấy key miễn phí tại: <https://aistudio.google.com/app/apikey>

---

## Output mẫu

### crawl_basic.py

```
[OK] Crawl thành công!
  Status code  : 200
  HTML length  : 490,295 chars
  Markdown len : 174,593 chars
  Links found  : internal=186, external=15
  Output       : output/panasonic_basic.md
```

### crawl_llm.py

```json
{
  "name": "Tủ lạnh Panasonic NR-YW590XJKV",
  "model": "NR-YW590XJKV",
  "category": "Tủ lạnh",
  "capacity": "590L",
  "key_features": ["Prime Fresh+", "Inverter", "..."],
  ...
}
```
