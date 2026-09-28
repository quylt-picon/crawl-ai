# Đề bài thực hành AWS Bedrock — Trợ lý CSKH "MeoShop"

> Một kịch bản duy nhất, đơn giản nhưng chạm đủ 4 mảng nghiên cứu. Trọng tâm: xây **Flow** dùng được hết công dụng (phân loại, **điều kiện rẽ nhánh**, gọi tool, tra Knowledge Base, fallback) — chứ không chỉ "hỏi → tra KB → trả lời".

---

## Bối cảnh

MeoShop là shop bán hàng online. Bạn xây một **trợ lý CSKH** trả lời tin nhắn khách hàng. Khách có thể hỏi 3 nhóm việc khác nhau, và trợ lý phải **xử lý mỗi nhóm theo cách khác nhau** — đây là lý do cần Flow có điều kiện:

| Nhóm intent | Ví dụ câu hỏi | Cách xử lý |
|-------------|---------------|------------|
| `POLICY` | "Đổi trả trong bao lâu?", "Phí ship bao nhiêu?" | Tra **Knowledge Base** (file `meoshop-policies.md`) rồi trả lời kèm nguồn |
| `ORDER` | "Đơn ORD123 tới đâu rồi?" | Gọi **Lambda/tool** tra trạng thái đơn → sinh câu trả lời tự nhiên |
| `OTHER` | "Shop có tuyển nhân viên không?" | Trả lời lịch sự + chuyển hotline (không bịa) |

Ngoài ra cần một nhánh **fallback**: nếu Knowledge Base không tìm được thông tin (độ liên quan thấp), trợ lý phải nói "mình chưa có thông tin này" và đưa hotline — KHÔNG bịa.

---

## Phần A — Knowledge Base (Track 4)

**Làm:**
1. Upload file [knowledge-base/meoshop-policies.md](knowledge-base/meoshop-policies.md) lên S3.
2. Tạo Knowledge Base trên Bedrock, chọn vector store (OpenSearch Serverless để bắt đầu cho nhanh).
3. Chạy ingestion (chunking + embedding).
4. Test bằng `RetrieveAndGenerate`.

**Câu test (có đáp án trong tài liệu):**
- "Tôi được đổi trả trong bao nhiêu ngày?" → kỳ vọng: **7 ngày**.
- "Khi nào được miễn phí ship?" → kỳ vọng: **đơn từ 500.000đ**.
- "Bảo hành phụ kiện bao lâu?" → kỳ vọng: **3 tháng**.
- "100 điểm đổi được gì?" → kỳ vọng: **voucher 50.000đ**.

**Câu test fallback (KHÔNG có trong tài liệu):**
- "Shop có bán bảo hiểm xe máy không?" → kỳ vọng: thừa nhận không có thông tin, không bịa.

**Đánh giá:** retrieval đúng đoạn? câu trả lời đúng số liệu (faithfulness)? có trích nguồn (citation)? Câu ngoài tài liệu có bị bịa không?

---

## Phần B — Prompt Management (Track 2)

Tạo và lưu (có version) các prompt sau để Flow tái sử dụng:

### Prompt P1 — Phân loại intent
- **Instruction:**
  > Phân loại tin nhắn của khách hàng MeoShop vào đúng 1 nhãn: `POLICY`, `ORDER`, `OTHER`.
  > - `ORDER`: khách hỏi về một đơn hàng cụ thể (có mã đơn hoặc hỏi trạng thái giao hàng đơn của họ).
  > - `POLICY`: hỏi về chính sách chung (đổi trả, vận chuyển, thanh toán, bảo hành, tích điểm).
  > - `OTHER`: còn lại.
  > Chỉ trả về đúng một nhãn, viết hoa, không giải thích.
- **User template:** `Tin nhắn: {{message}}`
- **Kỳ vọng:** trả về đúng 1 từ trong 3 nhãn.

### Prompt P2 — Trích mã đơn hàng (dùng cho nhánh ORDER)
- **Instruction:**
  > Trích mã đơn hàng từ tin nhắn. Mã có dạng `ORD` + số. Trả về JSON: `{"order_id": "..."}`. Nếu không có, trả `{"order_id": null}`. Chỉ trả JSON.
- **User template:** `Tin nhắn: {{message}}`

### Prompt P3 — Soạn câu trả lời đơn hàng (sau khi có dữ liệu từ tool)
- **Instruction:**
  > Bạn là trợ lý CSKH MeoShop, giọng thân thiện. Dựa trên dữ liệu đơn hàng JSON dưới đây, viết câu trả lời ngắn (2–3 câu) cho khách. Nếu `status` là `not_found`, xin lỗi và đề nghị kiểm tra lại mã đơn.
- **User template:** `Dữ liệu đơn: {{order_data}}`

### Prompt P4 — Trả lời nhánh OTHER
- **Instruction:**
  > Khách hỏi việc ngoài phạm vi hỗ trợ tự động. Trả lời lịch sự, không bịa thông tin, và mời khách liên hệ hotline 1900 1234 (8h–21h). Tối đa 2 câu.
- **User template:** `Tin nhắn: {{message}}`

**Bài tập versioning:** tạo P1 version 1, rồi version 2 thêm vài ví dụ minh họa (few-shot), chạy cùng bộ test để xem accuracy có tăng không.

---

## Phần C — Flow dùng đủ công dụng (Track 2 — trọng tâm)

### Sơ đồ luồng

```
                       ┌─────────────────────────┐
        [Input: message] ─────────────────────────▶ Prompt P1 (Classify)
                                                          │ intent
                                                          ▼
                                                 ┌──── Condition ────┐
                                                 │   intent == ?     │
                          ┌──────────────────────┼───────────────────┼─────────────────────┐
                  intent==ORDER             intent==POLICY                       else (OTHER)
                          │                       │                                  │
                          ▼                       ▼                                  ▼
                   Prompt P2 (trích          Knowledge Base node               Prompt P4
                    order_id)                 (tra meoshop-policies)            (trả lời lịch sự)
                          │                       │                                  │
                          ▼                       ▼                                  │
                  Lambda: getOrderStatus    Condition #2:                           │
                  (tra trạng thái đơn)       KB score thấp / rỗng?                   │
                          │                  ┌────┴─────┐                            │
                          ▼              score thấp   score ok                      │
                   Prompt P3 (soạn        │            │                            │
                    câu trả lời)       Prompt fallback  trả lời + citation          │
                          │            (đưa hotline)    │                            │
                          └───────────────┴─────────────┴────────────────┬──────────┘
                                                                          ▼
                                                                  [Output: reply]
```

### Các node phải dùng (để "dùng hết công dụng" của Flow)
1. **Input node** — nhận `message`.
2. **Prompt node (P1)** — phân loại intent.
3. **Condition node #1** — rẽ 3 nhánh theo intent. *(Đây là phần nhiều demo bỏ qua.)*
4. **Prompt node (P2)** — trích `order_id` (nhánh ORDER).
5. **Lambda node** — `getOrderStatus`, giả lập:
   ```python
   def lambda_handler(event, context):
       order_id = event.get("order_id")
       fake_db = {"ORD123": "đang giao", "ORD999": "đã giao"}
       status = fake_db.get(order_id, "not_found")
       return {"order_id": order_id, "status": status}
   ```
6. **Prompt node (P3)** — biến dữ liệu đơn thành câu trả lời tự nhiên.
7. **Knowledge Base node** — nhánh POLICY.
8. **Condition node #2** — fallback khi KB không đủ tin cậy.
9. **Prompt node (P4)** — nhánh OTHER.
10. **Output node** — trả `reply`.

> Tùy chọn nâng cao (nếu muốn dùng thêm node): **Iterator + Collector** để xử lý khi khách hỏi nhiều câu trong 1 tin; **Agent node** thay cho nhánh ORDER nếu muốn reasoning động.

### Bộ test cho Flow (chạy end-to-end)
| # | Input | Nhánh kỳ vọng | Output kỳ vọng |
|---|-------|---------------|----------------|
| 1 | "Đơn ORD123 của tôi tới đâu rồi?" | ORDER → Lambda → P3 | Báo "đang giao", giọng thân thiện |
| 2 | "Đơn ORD555 sao rồi?" | ORDER → Lambda(not_found) → P3 | Xin lỗi, đề nghị kiểm tra lại mã |
| 3 | "Phí ship bao nhiêu?" | POLICY → KB | "30.000đ, miễn phí từ 500.000đ", có citation |
| 4 | "Đổi trả trong mấy ngày?" | POLICY → KB | "7 ngày" |
| 5 | "Shop có bán bảo hiểm xe máy không?" | POLICY → KB → fallback | Không bịa, đưa hotline |
| 6 | "Shop có tuyển nhân viên không?" | OTHER → P4 | Lịch sự, mời gọi hotline |

**Đánh giá Flow:** mỗi case rẽ **đúng nhánh** không? output đúng nội dung & đúng tông giọng không? Đặc biệt kiểm tra case 2 (not_found) và case 5 (fallback) — đây là 2 case chứng minh Flow xử lý điều kiện chứ không chỉ trả lời thẳng.

---

## Phần D — Evaluation, Monitoring & Trace (Track 3)

- **Evaluation:** Lập dataset JSONL ~20 dòng (gồm 6 case trên + biến thể) với nhãn/đáp án chuẩn. Đo accuracy phân loại P1 và độ đúng câu trả lời cuối.
- **Monitoring:** Bật Model Invocation Logging + dashboard token/latency. Chạy 6 case, xem mỗi case tốn bao nhiêu token & thời gian.
- **Trace:** Bật trace khi chạy Flow/Agent. Cố tình hỏi "ORD123 và phí ship cùng lúc" để xem Flow xử lý ra sao → dùng trace tìm bước nào quyết định sai, rồi chỉnh Prompt P1 hoặc thêm node Iterator.

**Đánh giá:** viết được "1 báo cáo điều tra" cho ít nhất 1 case lỗi: triệu chứng → đọc trace → bước hỏng → cách sửa.

---

## Tiêu chí "đạt" tổng thể
- 6/6 case của Flow rẽ đúng nhánh.
- Câu trả lời POLICY có citation và đúng số liệu trong tài liệu.
- Case ngoài tài liệu (case 5) **không bịa**.
- Phân loại intent (P1) accuracy ≥ 90% trên dataset đánh giá.
- Có dashboard token/latency và ít nhất 1 báo cáo điều tra bằng trace.
