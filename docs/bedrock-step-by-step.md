# Hướng dẫn step-by-step AWS Bedrock cho người mới — Bài "MeoShop"

> Đi kèm đề bài [bedrock-exercise.md](bedrock-exercise.md). File này hướng dẫn **bấm vào đâu, điền field nào** trên AWS Console. Tên menu/field giữ nguyên **tiếng Anh** đúng như trên màn hình, kèm giải thích tiếng Việt.
>
> ⚠️ Console AWS thay đổi giao diện khá thường xuyên. Nếu một nút đổi tên nhẹ (ví dụ "Create" ↔ "Create flow"), tìm nút có ý nghĩa tương đương ở cùng vị trí. Mọi tên field cốt lõi bên dưới vẫn đúng.

---

## Phần 0 — Chuẩn bị (BẮT BUỘC làm trước)

### 0.1. Chọn Region
1. Đăng nhập [AWS Console](https://console.aws.amazon.com/).
2. Góc **trên cùng bên phải**, bấm vào tên region hiện tại (ví dụ `Ohio`), chọn **US East (N. Virginia) us-east-1**.
   - Lý do: `us-east-1` có **đầy đủ** Flows, Prompt management, Knowledge Bases, Evaluations. Một số region thiếu tính năng → làm sẽ kẹt.
3. Từ giờ **luôn giữ nguyên region này** cho cả bài. S3 bucket, Lambda, KB phải **cùng region**.

### 0.2. Bật quyền dùng model (Model access)
Bedrock không cho gọi model nếu chưa "xin quyền". Làm 1 lần:
1. Thanh tìm kiếm trên cùng, gõ `Bedrock` → mở **Amazon Bedrock**.
2. Menu trái, kéo xuống nhóm cấu hình, bấm **Model access**.
3. Bấm nút **Modify model access** (hoặc **Enable specific models**).
4. Tick chọn tối thiểu các model sau:
   - **Amazon Titan Text Embeddings V2** (dùng cho Knowledge Base — bắt buộc).
   - **Anthropic → Claude 3.5 Sonnet** (hoặc **Claude 3.5 Haiku** cho rẻ/nhanh) — dùng để sinh câu trả lời và phân loại.
   - *(Tùy chọn)* **Amazon Nova Lite/Pro** nếu muốn so sánh.
5. Bấm **Next** → **Submit**.
6. Đợi cột **Access status** chuyển thành **Access granted** (thường vài giây–vài phút). Reload trang nếu cần.

> Nếu Claude hiện "Use case details required": điền form ngắn (tên công ty, mục đích = internal testing) → Submit, đợi duyệt.

---

## Phần A — Knowledge Base (Track 4)

### A.1. Tạo S3 bucket và upload file chính sách
1. Thanh tìm kiếm trên cùng → gõ `S3` → mở **Amazon S3**.
2. Bấm **Create bucket**.
3. Field **Bucket name**: đặt tên **toàn cầu duy nhất**, ví dụ `meoshop-kb-<tên-bạn>-2026` (chỉ chữ thường, số, dấu gạch ngang).
4. Field **AWS Region**: phải là **US East (N. Virginia) us-east-1**.
5. Các mục khác **để mặc định** (Block all public access vẫn **bật** — KB không cần public). Kéo xuống bấm **Create bucket**.
6. Bấm vào tên bucket vừa tạo → bấm **Upload** → **Add files** → chọn file [knowledge-base/meoshop-policies.md](knowledge-base/meoshop-policies.md) trên máy bạn → **Upload**.
7. Đợi **Status: Succeeded**.

### A.2. Tạo Knowledge Base
1. Quay lại **Amazon Bedrock**. Menu trái → **Knowledge Bases**.
2. Bấm **Create** → chọn **Knowledge Base with vector store**.

**Step 1 — Provide Knowledge Base details:**
3. Field **Knowledge Base name**: `meoshop-kb`.
4. Mục **IAM permissions**: chọn **Create and use a new service role** (Bedrock tự tạo role, đỡ phải config quyền).
5. Mục **Choose data source**: chọn **Amazon S3**.
6. Bấm **Next**.

**Step 2 — Configure data source:**
7. Field **Data source name**: `meoshop-policies`.
8. Field **S3 URI**: bấm **Browse S3** → chọn bucket `meoshop-kb-...` → tick file `meoshop-policies.md` → **Choose**. (Có thể chọn cả thư mục chứa file.)
9. Mở **Chunking and parsing configurations** (nếu thu gọn): ở **Chunking strategy** chọn **Default chunking** (đủ tốt cho bài này). *(Tùy chọn: chọn **Fixed-size chunking** với Max tokens ~300, Overlap ~20% nếu muốn kiểm soát.)*
10. Bấm **Next**.

**Step 3 — Select embeddings model and configure vector store:**
11. Mục **Embeddings model**: bấm **Select model** → chọn **Titan Text Embeddings v2**.
12. Mục **Vector database**: chọn **Quick create a new vector store - Recommended**.
    - Bên dưới chọn **Amazon OpenSearch Serverless** (mặc định). Bedrock sẽ tự tạo collection — không cần làm gì thêm.
13. Bấm **Next**.

**Step 4 — Review and create:**
14. Xem lại → bấm **Create Knowledge Base**.
15. Đợi banner báo tạo xong (tạo OpenSearch Serverless mất **vài phút**, kiên nhẫn).

### A.3. Sync (ingestion: chunk + embed)
1. Trong trang KB vừa tạo, kéo xuống mục **Data source**.
2. Tick chọn dòng `meoshop-policies` → bấm **Sync**.
3. Đợi cột trạng thái chuyển sang **Available** / lần sync gần nhất báo **Completed**. (Đây là bước chunking + embedding.)

> Mỗi lần bạn sửa/đăng lại file lên S3, phải bấm **Sync** lại thì KB mới cập nhật.

### A.4. Test bằng RetrieveAndGenerate (ngay trên console)
1. Vẫn ở trang KB, panel bên phải **Test Knowledge Base**.
2. Bấm **Select model** → chọn **Claude 3.5 Sonnet** (hoặc Haiku).
3. Đảm bảo toggle **Generate responses** đang **bật** (đây chính là chế độ *RetrieveAndGenerate*: vừa tra vừa sinh câu trả lời + trích nguồn). Nếu **tắt** → chỉ trả về đoạn văn (chế độ *Retrieve*, dùng để xem score).
4. Gõ lần lượt các câu test rồi xem đáp án + nguồn (**Source chunks / citations**):

| Câu hỏi | Kỳ vọng |
|---|---|
| Tôi được đổi trả trong bao nhiêu ngày? | **7 ngày** |
| Khi nào được miễn phí ship? | đơn từ **500.000đ** |
| Bảo hành phụ kiện bao lâu? | **3 tháng** |
| 100 điểm đổi được gì? | voucher **50.000đ** |
| Shop có bán bảo hiểm xe máy không? | **Không bịa** — thừa nhận không có thông tin |

5. Với mỗi câu, bấm vào số **citation** để xem đoạn nào trong file được trích → đánh giá *faithfulness* (đúng số liệu) và *citation* (có nguồn).

> 📌 **Ghi lại `Knowledge Base ID`** (dạng `XXXXXXXXXX`) ở đầu trang KB — sẽ cần khi gắn vào Flow.

---

## Phần B — Prompt Management (Track 2)

Tạo 4 prompt P1–P4 để Flow tái sử dụng. Làm **giống nhau** cho cả 4, chỉ khác nội dung.

### B.1. Tạo Prompt P1 — Phân loại intent
1. Bedrock → menu trái → **Prompt management** → bấm **Create prompt**.
2. Field **Name**: `meoshop-p1-classify`. Field **Description**: `Phan loai intent`. → **Create**.
3. Vào màn hình **Prompt builder**. Phần giữa là khung soạn prompt:
   - Khu **System instructions** (hoặc khung message đầu tiên): dán nội dung Instruction của P1:
     ```
     Phân loại tin nhắn của khách hàng MeoShop vào đúng 1 nhãn: POLICY, ORDER, OTHER.
     - ORDER: khách hỏi về một đơn hàng cụ thể (có mã đơn hoặc hỏi trạng thái giao hàng đơn của họ).
     - POLICY: hỏi về chính sách chung (đổi trả, vận chuyển, thanh toán, bảo hành, tích điểm).
     - OTHER: còn lại.
     Chỉ trả về đúng một nhãn, viết hoa, không giải thích.
     ```
   - Khu **User message** (Message): gõ `Tin nhắn: {{message}}`
     - Khi gõ `{{message}}`, Bedrock tự nhận diện và thêm biến vào mục **Variables** bên dưới. Đây là "ô trống" Flow sẽ điền vào.
4. Panel phải **Configurations**:
   - **Model**: bấm **Select model** → chọn **Claude 3.5 Sonnet** (hoặc Haiku — phân loại nên dùng Haiku cho rẻ/nhanh).
   - **Temperature**: để **0** (phân loại cần ổn định, không sáng tạo).
5. Bấm **Test** (panel phải) để thử nhanh: điền biến `message` = `Đơn ORD123 tới đâu rồi?` → **Run** → kỳ vọng ra `ORDER`.
6. Bấm **Save** (lưu vào **Working draft**).

### B.2. Versioning cho P1 (bài tập so sánh accuracy)
1. Sau khi P1 chạy ổn, bấm **Create version** (góc trên). → tạo **Version 1** (snapshot bất biến).
2. Quay lại **Working draft**, **thêm few-shot** vào System instructions, ví dụ thêm:
   ```
   Ví dụ:
   "Phí ship bao nhiêu?" -> POLICY
   "Đơn ORD500 giao chưa?" -> ORDER
   "Shop tuyển người không?" -> OTHER
   ```
3. **Save** → bấm **Create version** lần nữa → tạo **Version 2**.
4. Sau này chạy bộ test (Phần D) trên cả Version 1 và Version 2 để xem accuracy có tăng không.

> Trong Flow bạn có thể trỏ tới **Working draft** (luôn là bản mới nhất) hoặc một **Version** cố định.

### B.3. Tạo P2 — Trích mã đơn (lặp lại quy trình B.1)
- **Name**: `meoshop-p2-extract-order`.
- **System instructions**:
  ```
  Trích mã đơn hàng từ tin nhắn. Mã có dạng ORD + số. Trả về JSON: {"order_id": "..."}.
  Nếu không có, trả {"order_id": null}. Chỉ trả JSON.
  ```
- **User message**: `Tin nhắn: {{message}}`
- **Temperature**: 0.
- Save → (tùy) Create version.

### B.4. Tạo P3 — Soạn câu trả lời đơn hàng
- **Name**: `meoshop-p3-order-reply`.
- **System instructions**:
  ```
  Bạn là trợ lý CSKH MeoShop, giọng thân thiện. Dựa trên dữ liệu đơn hàng JSON dưới đây,
  viết câu trả lời ngắn (2–3 câu) cho khách. Nếu status là not_found, xin lỗi và đề nghị
  kiểm tra lại mã đơn.
  ```
- **User message**: `Dữ liệu đơn: {{order_data}}`  ← biến tên `order_data`.
- **Temperature**: ~0.5 (cho giọng tự nhiên).
- Save.

### B.5. Tạo P4 — Trả lời nhánh OTHER
- **Name**: `meoshop-p4-other`.
- **System instructions**:
  ```
  Khách hỏi việc ngoài phạm vi hỗ trợ tự động. Trả lời lịch sự, không bịa thông tin,
  và mời khách liên hệ hotline 1900 1234 (8h–21h). Tối đa 2 câu.
  ```
- **User message**: `Tin nhắn: {{message}}`
- Save.

---

## Phần C — Flow (Track 2, trọng tâm)

### C.1. Tạo Lambda `getOrderStatus` TRƯỚC (Flow cần gọi nó)
1. Thanh tìm kiếm trên cùng → `Lambda` → mở **AWS Lambda** (vẫn region us-east-1).
2. Bấm **Create function** → chọn **Author from scratch**.
3. Field **Function name**: `getOrderStatus`.
4. Field **Runtime**: chọn **Python 3.12** (hoặc bản 3.x mới nhất).
5. Để mặc định phần khác → bấm **Create function**.
6. Trong tab **Code**, xóa code mẫu, dán:
   ```python
   def lambda_handler(event, context):
       order_id = event.get("order_id")
       fake_db = {"ORD123": "đang giao", "ORD999": "đã giao"}
       status = fake_db.get(order_id, "not_found")
       return {"order_id": order_id, "status": status}
   ```
7. Bấm **Deploy** (Ctrl/Cmd+S không đủ, phải Deploy).
8. *(Test nhanh)* tab **Test** → **Create new event** → Event JSON:
   ```json
   { "order_id": "ORD123" }
   ```
   → **Test** → kỳ vọng output `{"order_id": "ORD123", "status": "đang giao"}`.
9. **Ghi lại ARN** của function (góc trên phải, dạng `arn:aws:lambda:us-east-1:...:function:getOrderStatus`).

> Cách Flow truyền dữ liệu vào Lambda: trong node Lambda của Flow bạn map input thành key `order_id`, Bedrock gửi cho Lambda dưới dạng `event`. Code trên đọc `event.get("order_id")` là khớp.

### C.2. Tạo Flow
1. Bedrock → menu trái → **Flows** → bấm **Create flow**.
2. Field **Name**: `meoshop-cskh-flow`. **Description**: tùy.
3. Mục **Service role**: chọn **Create and use a new service role** → đặt tên gợi ý hoặc để mặc định.
4. Bấm **Create**. → Vào **Flow builder** (canvas kéo thả).

Trên canvas đã có sẵn 2 node: **Flow input** và **Flow output**. Bên trái có panel **Nodes** để kéo node vào.

### C.3. Cấu hình Flow input
1. Bấm node **Flow input**.
2. Panel phải → mục **Output**: đảm bảo có 1 output. Đặt **Type** = **String** (hoặc Object). Để đơn giản dùng **Object** với 1 field `message`, **hoặc** dùng String và coi cả input là `message`.
   - **Khuyến nghị người mới**: để **Document/Object**, và khi test sẽ gửi JSON `{"message": "..."}`. Nếu thấy phức tạp, để **String** và cả flow nhận thẳng chuỗi `message`.

### C.4. Node P1 (Classify) + nối từ Input
1. Từ panel **Nodes** bên trái, kéo **Prompts** vào canvas.
2. Bấm node đó → panel phải:
   - **Node name**: `Classify`.
   - **Prompt**: chọn **Use a prompt from Prompt management** → **Select prompt** → chọn `meoshop-p1-classify` → chọn **Version** (Working draft hoặc Version 2).
   - Mục **Inputs**: sẽ hiện biến `message`. Để đó (sẽ nối ở bước sau).
3. **Nối dây**: kéo từ chấm tròn (output handle) của **Flow input** sang ô input `message` của node `Classify`.
   - Nếu Flow input là Object: bấm vào input `message` của Classify → ở **Expression** gõ `$.data.message` (lấy field message từ object đầu vào). Nếu Flow input là String: map thẳng output của Flow input.

### C.5. Condition node #1 (rẽ 3 nhánh theo intent)
1. Kéo **Condition** từ panel Nodes vào canvas.
2. Nối output của node `Classify` → input của **Condition** node.
3. Bấm node **Condition** → panel phải:
   - Mục **Input**: đặt tên `intent`, map từ output của `Classify` (kéo dây hoặc chọn).
   - Mục **Conditions**, bấm **Add condition** 2 lần để có nhánh:
     - Condition 1: **Name** = `is_order`, **Condition** (expression) = `intent == "ORDER"`
     - Condition 2: **Name** = `is_policy`, **Condition** = `intent == "POLICY"`
   - Nhánh còn lại tự động là **Default** (chính là `OTHER`).
4. Node Condition giờ có 3 cổng ra: `is_order`, `is_policy`, `default`.

> ⚠️ Model đôi khi trả `ORDER\n` kèm xuống dòng/khoảng trắng → so sánh `==` trượt. Khắc phục: trong P1 nhấn mạnh "chỉ trả đúng một từ"; hoặc đổi expression sang dạng chứa nếu console hỗ trợ. Test kỹ ở C.10.

### C.6. Nhánh ORDER: P2 → Lambda → P3
1. Kéo **Prompts** vào → đặt tên `ExtractOrder`, chọn prompt `meoshop-p2-extract-order`. Nối **cổng `is_order`** của Condition → input `message` của `ExtractOrder` (map lại từ Flow input message).
2. Kéo **AWS Lambda** vào → panel phải:
   - **Function**: chọn `getOrderStatus` từ dropdown.
   - **Inputs**: tạo input tên `order_id`. Map giá trị này từ output JSON của `ExtractOrder` (gõ expression `$.data.order_id` để bóc field `order_id` ra khỏi JSON mà P2 trả về).
   - Nối `ExtractOrder` → `Lambda`.
3. Kéo **Prompts** vào → đặt tên `OrderReply`, chọn prompt `meoshop-p3-order-reply`.
   - Input `order_data`: map từ **output của Lambda** (gắn cả object kết quả Lambda; nếu cần chuỗi, dùng expression `$.data`).
   - Nối `Lambda` → `OrderReply`.
4. Nối `OrderReply` → **Flow output** (sẽ gộp ở C.9).

#### ⚠️ Cấp quyền cho Flow gọi Lambda (rất hay quên)
Sau khi chọn Lambda trong node, Flow cần quyền `lambda:InvokeFunction` và Lambda cần resource policy cho phép Bedrock gọi. Nếu khi test báo lỗi quyền:
- **Cách 1 (console Lambda)**: vào Lambda `getOrderStatus` → tab **Configuration** → **Permissions** → mục **Resource-based policy statements** → **Add permissions** → chọn **AWS service**, Principal `bedrock.amazonaws.com`, Action `lambda:InvokeFunction`. Lưu.
- **Cách 2 (CLI)** — chạy trong terminal đã cấu hình AWS CLI:
  ```bash
  aws lambda add-permission \
    --function-name getOrderStatus \
    --statement-id bedrock-flow-invoke \
    --action lambda:InvokeFunction \
    --principal bedrock.amazonaws.com \
    --region us-east-1
  ```

### C.7. Nhánh POLICY: Knowledge Base → (fallback)
1. Kéo **Knowledge Base** từ panel Nodes vào → panel phải:
   - **Knowledge Base**: chọn `meoshop-kb` (ID đã ghi ở A.4).
   - Bật **Generate responses based on retrieved results** → **Select model** = Claude 3.5 Sonnet. (Như vậy node trả về câu trả lời + citations luôn.)
   - Input: tạo `retrievalQuery`/`query`, map từ Flow input `message`.
2. Nối **cổng `is_policy`** của Condition → input của KB node.

#### Condition #2 — fallback khi KB không đủ tin cậy (cách làm chạy được cho người mới)
Cách "đọc score" trực tiếp trong Condition node rất khó. Cách thực dụng và **đúng tinh thần đề bài**:
1. Trong KB node, **TẮT** Generate, chỉ lấy retrieval (hoặc giữ Generate nhưng thêm bước kiểm). Cách đơn giản nhất:
2. Thêm 1 **Prompts** node tên `PolicyAnswer` sau KB, chọn model Claude, với instruction:
   ```
   Chỉ trả lời dựa trên NGỮ CẢNH dưới đây. Nếu ngữ cảnh KHÔNG chứa thông tin để trả lời,
   chỉ in đúng: NO_INFO. Ngược lại trả lời ngắn gọn kèm số liệu.
   Ngữ cảnh: {{context}}
   Câu hỏi: {{question}}
   ```
   - `context` map từ output KB (retrieved results), `question` từ Flow input message.
3. Thêm **Condition** node #2 sau `PolicyAnswer`:
   - Input `ans` = output của `PolicyAnswer`.
   - Condition: **Name** = `no_info`, expression = `ans == "NO_INFO"`.
   - Cổng `no_info` → node **Prompts** `Fallback` (instruction: "Xin lỗi, mình chưa có thông tin này, vui lòng gọi hotline 1900 1234 (8h–21h)").
   - Cổng `default` → đi thẳng tới Output (câu trả lời + citation).

> Đây là pattern "sentinel NO_INFO" — đơn giản, chống bịa tốt. Cách "đo score" thật sự (threshold trên `score` của retrieval result) là phương án nâng cao, làm sau khi pattern này chạy ổn.

### C.8. Nhánh OTHER: P4
1. Kéo **Prompts** vào → tên `OtherReply`, chọn prompt `meoshop-p4-other`.
2. Nối **cổng `default`** của Condition #1 → input `message` của `OtherReply` (map từ Flow input message).

### C.9. Gom về Flow output
- Nối các đầu ra cuối cùng về node **Flow output**:
  - `OrderReply` → Flow output
  - `PolicyAnswer` (nhánh default của Condition #2) và `Fallback` → Flow output
  - `OtherReply` → Flow output
- Bấm node **Flow output**, đảm bảo **Type** = **String**.

### C.10. Lưu, Prepare, và Test Flow
1. Bấm **Save** (góc trên phải).
2. Bấm **Prepare** — bước này "biên dịch" flow; **bắt buộc** chạy lại mỗi khi sửa node. Nếu có dây nối sai/thiếu, **Prepare** sẽ báo lỗi đỏ ở node → sửa theo gợi ý.
3. Panel **Test** bên phải → nhập input rồi **Run**. Nếu Flow input là Object, nhập JSON:
   ```json
   { "message": "Đơn ORD123 của tôi tới đâu rồi?" }
   ```
   Nếu là String, nhập thẳng câu hỏi.
4. Chạy đủ **6 case** và đối chiếu nhánh + nội dung:

| # | Input | Nhánh kỳ vọng | Output kỳ vọng |
|---|---|---|---|
| 1 | Đơn ORD123 của tôi tới đâu rồi? | ORDER→Lambda→P3 | "đang giao", thân thiện |
| 2 | Đơn ORD555 sao rồi? | ORDER→Lambda(not_found)→P3 | Xin lỗi, đề nghị kiểm tra lại mã |
| 3 | Phí ship bao nhiêu? | POLICY→KB | 30.000đ, miễn phí từ 500.000đ + citation |
| 4 | Đổi trả trong mấy ngày? | POLICY→KB | 7 ngày |
| 5 | Shop có bán bảo hiểm xe máy không? | POLICY→KB→fallback | Không bịa, đưa hotline |
| 6 | Shop có tuyển nhân viên không? | OTHER→P4 | Lịch sự, mời hotline |

> Nếu một case rẽ sai nhánh → quay lại Condition #1, kiểm tra output thực tế của `Classify` (xem ở Trace, Phần D) rồi tinh chỉnh P1.

---

## Phần D — Evaluation, Monitoring & Trace (Track 3)

### D.1. Bật Model Invocation Logging (monitoring token/latency)
1. Bedrock → menu trái → **Settings**.
2. Mục **Model invocation logging** → bật toggle **Enabled**.
3. Chọn nơi lưu log:
   - Tick **CloudWatch Logs** → **Log group name**: tạo mới ví dụ `/bedrock/meoshop`.
   - *(Tùy chọn)* tick **S3** để lưu raw.
   - Mục **Logging data**: tick cả **Text**, **Image** nếu có.
4. Nếu hỏi **Service role**: chọn **Create and use a new role**.
5. Bấm **Save settings**.
6. Chạy lại 6 case của Flow để sinh log.
7. Xem số liệu: thanh tìm kiếm → `CloudWatch` → **Log groups** → `/bedrock/meoshop` để xem từng lần gọi (input/output tokens). Hoặc **CloudWatch → Metrics → Bedrock** để xem **InputTokenCount**, **OutputTokenCount**, **InvocationLatency** → bấm **Add to dashboard** tạo dashboard token/latency.

### D.2. Trace cho Flow (điều tra bước sai)
1. Trong **Flow builder**, panel **Test** có mục hiển thị **Trace** / từng bước node khi Run (mỗi node cho thấy input → output).
2. Bài tập điều tra: nhập câu **"ORD123 và phí ship cùng lúc"** → **Run** → xem trace:
   - Node `Classify` ra nhãn gì? (thường ra 1 nhãn duy nhất → flow chỉ xử lý 1 việc → đây là điểm "hỏng").
3. Viết **báo cáo điều tra** theo mẫu:
   - **Triệu chứng**: trả lời thiếu 1 trong 2 ý.
   - **Đọc trace**: node Classify trả `ORDER`, nhánh POLICY không chạy.
   - **Bước hỏng**: P1 chỉ phân 1 nhãn.
   - **Cách sửa**: (a) sửa P1 cho phép multi-intent + thêm node **Iterator** tách câu; hoặc (b) chấp nhận giới hạn, hướng dẫn khách hỏi từng việc.

> Trace đầy đủ nhất lấy qua API `InvokeFlow` với `enableTrace=true`, nhưng panel Test trên console đủ để làm bài tập này.

### D.3. Evaluation (đo accuracy phân loại + độ đúng câu trả lời)
**Cách A — Evaluation job trên Bedrock (RAG/Model evaluation):**
1. Chuẩn bị file **JSONL** ~20 dòng, mỗi dòng 1 mẫu, ví dụ (định dạng tùy loại job, đây là minh họa phân loại):
   ```json
   {"prompt": "Phí ship bao nhiêu?", "referenceResponse": "POLICY"}
   {"prompt": "Đơn ORD123 tới đâu?", "referenceResponse": "ORDER"}
   {"prompt": "Shop tuyển người không?", "referenceResponse": "OTHER"}
   ```
2. Upload file JSONL này lên S3 (giống A.1).
3. Bedrock → menu trái → **Evaluations** → **Create** → chọn **Model evaluation** (cho P1) hoặc **Knowledge Base evaluation/RAG** (cho câu trả lời POLICY).
4. Điền **Evaluation name**, chọn **Model**, ở **Dataset** trỏ tới **S3 URI** file JSONL, chọn metric (accuracy / faithfulness…), chọn **Service role** mới → **Create**.
5. Đợi job **Completed** → xem report accuracy.

**Cách B — Tự chấm tay (nhanh cho người mới):** chạy 20 dòng qua P1 (hoặc qua Flow), tự đếm số đúng/tổng → accuracy. Mục tiêu **≥ 90%**. So sánh P1 **Version 1** vs **Version 2** (few-shot) xem có cải thiện.

---

## Checklist "đạt" (đối chiếu cuối)
- [ ] 6/6 case Flow rẽ **đúng nhánh** (đặc biệt case 2 not_found và case 5 fallback).
- [ ] Câu trả lời POLICY có **citation** và **đúng số liệu**.
- [ ] Case 5 (bảo hiểm xe máy) **không bịa** → ra hotline.
- [ ] P1 accuracy **≥ 90%** trên dataset.
- [ ] Có **dashboard token/latency** (CloudWatch) + **≥1 báo cáo điều tra bằng trace**.

## Lỗi thường gặp
| Triệu chứng | Nguyên nhân & cách sửa |
|---|---|
| Model access báo "not granted" | Phần 0.2 chưa Submit hoặc sai region. |
| KB test không ra kết quả | Quên bấm **Sync** (A.3) hoặc file chưa lên S3. |
| Flow báo lỗi đỏ khi Prepare | Có node thiếu dây input/output → nối lại rồi **Prepare**. |
| Lambda node lỗi quyền | Chưa add resource-based policy cho `bedrock.amazonaws.com` (C.6). |
| Condition rẽ sai dù intent đúng | Output có `\n`/space → siết prompt P1, hoặc xem Trace để biết giá trị thực. |
| Sửa prompt nhưng Flow không đổi | Flow trỏ tới **Version** cố định, không phải **Working draft**; hoặc quên **Prepare**. |
