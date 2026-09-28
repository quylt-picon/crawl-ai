# Kế hoạch nghiên cứu & thực nghiệm AWS Bedrock

> Mục tiêu: Nghiên cứu sâu (hands-on) các năng lực của AWS Bedrock theo 4 mảng — Core Capabilities, Flow/Prompt/Agent, Evaluation/Monitoring/Trace, Data Automation/Integration. Mỗi mục ghi rõ **Làm gì → Nghiên cứu gì → Thực nghiệm cụ thể → Kỳ vọng → Cách đánh giá → Deliverable**.

---

## Mục lục
- [Phase 0 — Chuẩn bị môi trường](#phase-0--chuẩn-bị-môi-trường)
- [Track 1 — Core Capabilities](#track-1--core-capabilities)
- [Track 2 — Flow, Prompt Management & Agent](#track-2--flow-prompt-management--agent)
- [Track 3 — Evaluation, Monitoring & Traceability](#track-3--evaluation-monitoring--traceability)
- [Track 4 — Data Automation & Integration](#track-4--data-automation--integration)
- [Timeline & Deliverable tổng hợp](#timeline--deliverable-tổng-hợp)

---

## Phase 0 — Chuẩn bị môi trường

**Làm gì:**
- Chọn Region đầy đủ tính năng nhất: `us-east-1` hoặc `us-west-2`.
- Bedrock Console → **Model access** → request access các model: Anthropic Claude (Opus/Sonnet/Haiku), Amazon Nova/Titan, Meta Llama, Mistral, Cohere.
- Tạo IAM user/role: `AmazonBedrockFullAccess` + quyền CloudWatch Logs + S3 (giai đoạn nghiên cứu).
- Cài AWS CLI v2 + `pip install boto3`.
- Bật **Budget alert** trong AWS Billing để kiểm soát chi phí token.

**Kiểm tra nhanh:**
```bash
# Liệt kê model đã có quyền
aws bedrock list-foundation-models --region us-east-1 \
  --query "modelSummaries[].modelId" --output table

# Test gọi model qua Converse API
aws bedrock-runtime converse \
  --region us-east-1 \
  --model-id anthropic.claude-3-5-sonnet-20241022-v2:0 \
  --messages '[{"role":"user","content":[{"text":"Xin chào, bạn là model gì?"}]}]'
```

**Kỳ vọng:** Lệnh trả về danh sách model + 1 câu trả lời từ model.
**Deliverable:** Script `boto3` gọi thử thành công (proof-of-access), tài khoản + model access sẵn sàng.

---

## Track 1 — Core Capabilities

### 1.1 Kiến trúc & mô hình hoạt động
**Nghiên cứu:** Bedrock là dịch vụ *serverless* — truy cập Foundation Model qua API, không quản lý hạ tầng.
**Sơ đồ cần vẽ:** `Client → Bedrock Runtime API (Converse/InvokeModel) → Foundation Model → Response`, kèm các nhánh: Guardrails, Knowledge Base, Agent.

### 1.2 Hai cách gọi model — code mẫu

**A. `InvokeModel` (format riêng theo từng provider):**
```python
import boto3, json
rt = boto3.client("bedrock-runtime", region_name="us-east-1")

resp = rt.invoke_model(
    modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "Tóm tắt lợi ích của serverless trong 3 gạch đầu dòng."}]
    })
)
print(json.loads(resp["body"].read())["content"][0]["text"])
```

**B. `Converse API` (interface thống nhất cho MỌI model — nên dùng làm chuẩn):**
```python
resp = rt.converse(
    modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
    messages=[{"role": "user", "content": [{"text": "Tóm tắt lợi ích của serverless trong 3 gạch đầu dòng."}]}],
    inferenceConfig={"maxTokens": 512, "temperature": 0.3},
)
print(resp["output"]["message"]["content"][0]["text"])
```

**Thực nghiệm:**
1. Chạy cùng 1 prompt qua cả 2 API → so sánh cấu trúc request/response.
2. Đổi `modelId` sang Nova/Llama với **cùng code Converse** → chứng minh tính thống nhất.
3. Test streaming (`converse_stream`).

### 1.3 Bảng so sánh model (mẫu để điền)

| Model | Provider | Context window | Giá input ($/1M tok) | Giá output ($/1M tok) | Latency (cảm nhận) | Use case phù hợp |
|-------|----------|----------------|----------------------|------------------------|--------------------|------------------|
| Claude Sonnet | Anthropic | | | | | reasoning, code |
| Claude Haiku | Anthropic | | | | | rẻ, nhanh, volume lớn |
| Nova Pro | Amazon | | | | | multimodal, giá tốt |
| Llama | Meta | | | | | open, tự host được |

**Cách đánh giá:** Cho 3–5 prompt chuẩn (1 tóm tắt, 1 reasoning, 1 code, 1 tiếng Việt) chạy qua từng model, chấm điểm 1–5 về: độ chính xác, độ trôi chảy tiếng Việt, latency, chi phí.

**Deliverable Track 1:** Tài liệu kiến trúc + sơ đồ, repo code 2 API, bảng so sánh model đã điền điểm, bảng On-Demand vs Provisioned Throughput.

---

## Track 2 — Flow, Prompt Management & Agent

> Đây là track trọng tâm — dưới đây có **prompt mẫu cụ thể để thử ngay**.

### 2.1 Prompt Management

**Làm gì:** Bedrock Console → **Prompt management** → Create prompt. Dùng biến `{{tên_biến}}`, lưu version, test trong Playground, rồi gọi qua API bằng ARN.

**Nghiên cứu:** versioning (draft vs published), cách deliver prompt qua ARN thay vì hardcode, so sánh nhiều version cạnh nhau.

#### Prompt mẫu #1 — Tóm tắt (Summarization)
- **System / Instruction:**
  > Bạn là trợ lý tóm tắt. Hãy tóm tắt đoạn văn dưới đây thành đúng 3 gạch đầu dòng, mỗi dòng tối đa 20 từ, giữ nguyên số liệu quan trọng. Trả lời bằng tiếng Việt.
- **User template:** `Văn bản: {{document}}`
- **Biến:** `document`
- **Input thử:** dán 1 đoạn ~300 từ (vd 1 đoạn tin tức).
- **Kỳ vọng:** Đúng 3 bullet, ngắn gọn, không bịa số liệu, giữ con số gốc.
- **Đánh giá (rubric 1–5):** (a) đúng định dạng 3 bullet? (b) không bỏ sót ý chính? (c) không bịa (hallucination)? (d) giữ đúng số liệu? → điểm trung bình ≥ 4 là đạt.

#### Prompt mẫu #2 — Phân loại (Classification) với biến
- **Instruction:**
  > Phân loại yêu cầu hỗ trợ của khách hàng vào đúng 1 nhãn: `BILLING`, `TECHNICAL`, `ACCOUNT`, `OTHER`. Chỉ trả về nhãn, không giải thích.
- **User template:** `Yêu cầu khách hàng: {{ticket}}`
- **Input thử:** `"Tôi bị tính phí 2 lần trong tháng này"` → kỳ vọng `BILLING`. `"App crash khi mở màn hình thanh toán"` → `TECHNICAL`.
- **Kỳ vọng:** Trả về đúng 1 nhãn, không kèm văn bản thừa.
- **Đánh giá:** Chạy 10–20 ticket có nhãn gốc (ground truth) → tính **accuracy**. Kiểm tra model có "đi lạc format" (trả thừa chữ) không.

#### Prompt mẫu #3 — Trích xuất JSON (Structured Extraction)
- **Instruction:**
  > Trích xuất thông tin từ email và trả về JSON đúng schema: `{"ten": string, "email": string, "cong_ty": string, "yeu_cau": string}`. Nếu thiếu trường, để giá trị null. Chỉ trả về JSON, không markdown.
- **User template:** `Email: {{email_body}}`
- **Input thử:** 1 email mẫu có tên + công ty + nội dung.
- **Kỳ vọng:** JSON hợp lệ, parse được bằng `json.loads`, đúng schema.
- **Đánh giá:** (a) JSON parse được không? (b) đúng tên trường? (c) điền đúng giá trị? Chạy 10 email → tỷ lệ JSON hợp lệ nên = 100%.

#### Thực nghiệm versioning
1. Tạo prompt #1, lưu **version 1**.
2. Sửa instruction (vd thêm "kèm 1 câu nhận định cuối"), lưu **version 2**.
3. Chạy cùng input qua v1 và v2 → so sánh, ghi nhận tác động.
- **Kỳ vọng:** Thấy rõ versioning giúp rollback và A/B prompt mà không đụng code.

**Gọi prompt đã lưu qua API:**
```python
resp = rt.converse(
    modelId="arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:prompt/<PROMPT_ID>",
    promptVariables={"document": {"text": "..."}}  # truyền biến
)
```

### 2.2 Bedrock Flows (Prompt Flows)

**Làm gì:** Visual builder → nối node: `Input → Prompt (tóm tắt) → Condition (độ dài) → Output`.
**Nghiên cứu các node:** Prompt, Condition, Lambda, Knowledge Base, Agent, Iterator, Collector. Versioning + alias. Gọi qua `InvokeFlow`.
**Thực nghiệm:** Xây flow "phân loại ticket → nếu BILLING thì sinh email xin lỗi + hoàn tiền, ngược lại sinh phản hồi kỹ thuật".
**Kỳ vọng:** Flow rẽ nhánh đúng theo nhãn; chạy được qua API.
**Đánh giá:** Cho 5 ticket đi qua flow → kiểm tra rẽ nhánh đúng 100%, output mỗi nhánh đúng tông giọng.

### 2.3 Agents

**Làm gì:** Tạo Agent với instruction + **Action Group** (OpenAPI schema + Lambda) + Knowledge Base.
**Nghiên cứu:** orchestration kiểu ReAct (reasoning → gọi tool → quan sát → lặp), session/memory, return-of-control.
**Thực nghiệm — use case "trợ lý tra cứu đơn hàng":**
- Instruction: *"Bạn là trợ lý CSKH. Khi khách hỏi trạng thái đơn, gọi tool `getOrderStatus`. Nếu khách hỏi chính sách, tra Knowledge Base."*
- Action Group: 1 Lambda giả lập trả `{"order_id": "...", "status": "shipping"}`.
- Câu test: `"Đơn ORD123 của tôi tới đâu rồi?"`
- **Kỳ vọng:** Agent tự nhận ra cần gọi `getOrderStatus`, truyền đúng `order_id`, trả lời tự nhiên.
- **Đánh giá:** Bật trace → kiểm tra agent có chọn đúng tool, truyền đúng tham số, và tổng hợp câu trả lời đúng không. Thử câu mơ hồ để xem agent có hỏi lại không.

**So sánh khi nào dùng cái gì:**
| Nhu cầu | Giải pháp |
|---------|-----------|
| 1 lần gọi, prompt cố định | Converse + Prompt Management |
| Pipeline nhiều bước, logic rẽ nhánh rõ ràng | Flow |
| Cần reasoning động + gọi tool/API tùy ngữ cảnh | Agent |

**Deliverable Track 2:** Tài liệu prompt + 3 prompt mẫu đã chấm điểm, 1 Flow demo (export config) + sơ đồ, 1 Agent demo chạy được + tài liệu orchestration, bảng "khi nào dùng Flow vs Agent vs gọi trực tiếp".

---

## Track 3 — Evaluation, Monitoring & Traceability

### 3.1 Evaluation
**Làm gì:** Bedrock Console → **Model evaluation** → tạo job (Automatic hoặc Human).
**Nghiên cứu:** metrics tự động (accuracy, robustness, toxicity), **LLM-as-a-judge**, **RAG evaluation** (relevance, faithfulness, answer correctness).
**Thực nghiệm:** Chuẩn bị dataset JSONL (prompt + câu trả lời chuẩn) ~20–50 mẫu, chạy 1 evaluation job, đọc report.
**Đánh giá:** Diễn giải được điểm số; xác định model nào tốt nhất cho use case theo data thực tế (không chỉ cảm tính).

### 3.2 Monitoring & Logging
**Làm gì:**
- Bật **Model Invocation Logging** → đẩy prompt + completion ra CloudWatch Logs / S3.
- Tạo CloudWatch dashboard theo dõi: `InvocationCount`, `InvocationLatency`, `InputTokenCount`, `OutputTokenCount`, `Throttles`, error rate.
- Bật **CloudTrail** cho audit control-plane (ai tạo/sửa agent, prompt...).

```bash
# Bật logging (ví dụ đẩy ra CloudWatch)
aws bedrock put-model-invocation-logging-configuration --region us-east-1 \
  --logging-config '{"cloudWatchConfig":{"logGroupName":"/bedrock/invocations","roleArn":"<ROLE_ARN>"}}'
```

**Kỳ vọng:** Mỗi lần gọi model có log đầy đủ; dashboard hiển thị token & latency real-time.
**Lưu ý:** Log chứa prompt/PII → cần mã hóa + giới hạn quyền truy cập.

### 3.3 Traceability (điểm cốt lõi để debug)
**Làm gì:** Với Agent, bật trace khi gọi:
```python
agent_rt = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
resp = agent_rt.invoke_agent(
    agentId="...", agentAliasId="...", sessionId="s1",
    inputText="Đơn ORD123 tới đâu rồi?",
    enableTrace=True,
)
# Duyệt resp["completion"] để đọc các trace event: orchestration, tool call, KB lookup
```
**Nghiên cứu:** đọc orchestration trace (từng bước reasoning), pre/post-processing trace, tool invocation trace.
**Thực nghiệm điều tra lỗi:** Cố tình tạo case sai (prompt mơ hồ / agent gọi nhầm tool) → dùng trace + log truy ngược nguyên nhân.
**Đánh giá:** Viết được "quy trình điều tra khi output sai" gồm các bước: xem trace → xác định bước hỏng (chọn tool sai? tham số sai? KB không trả về?) → đề xuất sửa (instruction / schema / chunking).

**Deliverable Track 3:** Checklist bật logging/monitoring + screenshot dashboard, 1 evaluation report mẫu + diễn giải, tài liệu quy trình điều tra output sai bằng trace.

---

## Track 4 — Data Automation & Integration

### 4.1 Bedrock Data Automation (BDA)
**Làm gì:** Tạo BDA project/blueprint, chạy thử trích xuất dữ liệu có cấu trúc từ document/image/audio/video.
**Thực nghiệm:** Input 1 PDF (vd hóa đơn) → output JSON các trường (số hóa đơn, ngày, tổng tiền).
**Kỳ vọng:** Output JSON đúng các trường định nghĩa trong blueprint.
**Đánh giá:** Chạy 5–10 file → tỷ lệ trích xuất đúng từng trường (field-level accuracy).

### 4.2 Knowledge Bases (RAG) — pipeline ingestion
**Làm gì:** Kết nối data source (S3 / web crawler / Confluence / SharePoint / Salesforce).
**Nghiên cứu pipeline:** ingestion → **chunking** → **embedding** → **vector store** (OpenSearch Serverless, Aurora pgvector, Pinecone, Redis). Test `RetrieveAndGenerate`.
```python
resp = agent_rt.retrieve_and_generate(
    input={"text": "Chính sách hoàn tiền trong bao lâu?"},
    retrieveAndGenerateConfiguration={
        "type": "KNOWLEDGE_BASE",
        "knowledgeBaseConfiguration": {
            "knowledgeBaseId": "<KB_ID>",
            "modelArn": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        },
    },
)
print(resp["output"]["text"])
```
**Kỳ vọng:** Câu trả lời dựa trên tài liệu đã ingest, kèm **citations** (nguồn).
**Đánh giá:** Cho 10 câu hỏi có đáp án trong tài liệu → đo: (a) retrieval đúng đoạn? (b) câu trả lời đúng (faithfulness)? (c) có trích nguồn? So sánh 2 cấu hình chunking khác nhau.

### 4.3 Integration & Automation
**Nghiên cứu:** ghép Bedrock với **Lambda, Step Functions, EventBridge** để tự động hóa pipeline; **Batch inference** cho khối lượng lớn.
**Thực nghiệm:** EventBridge bắt sự kiện "file mới vào S3" → Lambda gọi BDA/Bedrock → lưu kết quả.

**Deliverable Track 4:** Demo BDA (file → JSON), demo Knowledge Base end-to-end + sơ đồ pipeline, tài liệu kiến trúc tích hợp tự động + tiêu chí chọn vector store.

---

## Timeline & Deliverable tổng hợp

| Tuần | Track | Output chính |
|------|-------|--------------|
| 1 | Phase 0 + Track 1 | Setup, code 2 API, bảng so sánh model đã chấm điểm |
| 2 | Track 2 | 3 prompt mẫu + đánh giá, Flow demo, Agent demo |
| 3 | Track 3 | Dashboard monitoring, evaluation report, quy trình điều tra trace |
| 4 | Track 4 | BDA demo, Knowledge Base demo, kiến trúc tích hợp |

**Báo cáo cuối:** Tổng hợp kiến trúc, điểm mạnh/yếu, chi phí thực đo, và **khuyến nghị áp dụng cho dự án** + repo chứa toàn bộ code demo.

### Rubric đánh giá chung (dùng cho mọi thực nghiệm)
| Tiêu chí | Thang điểm 1–5 |
|----------|----------------|
| Đúng định dạng yêu cầu | 1 = sai hẳn → 5 = đúng tuyệt đối |
| Độ chính xác nội dung | 1 = sai/bịa → 5 = chính xác |
| Không hallucination | 1 = bịa nhiều → 5 = bám nguồn |
| Tiếng Việt tự nhiên | 1 = ngô nghê → 5 = trôi chảy |
| Latency | đo ms, càng thấp càng tốt |
| Chi phí | đo $/1000 lượt gọi |

> Quy ước: điểm trung bình ≥ 4/5 và JSON/format hợp lệ 100% (với prompt structured) thì coi là **đạt** cho production thử nghiệm.
