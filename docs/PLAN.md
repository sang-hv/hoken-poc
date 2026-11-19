# Kế hoạch PoC — 保険AI Bot

Báo cáo: **Thứ Ba 24/11** (muộn nhất Thứ Tư 25/11). Khách báo cáo lên 西島 vào Thứ Năm 26/11.
Ngày làm việc còn lại: chiều Thứ Năm 19/11, Thứ Sáu 20/11, Thứ Hai 23/11, sáng Thứ Ba 24/11.

**Nguyên tắc:** trước buổi báo cáo chỉ làm phần chứng minh được bằng số đo (OCR, retrieval, độ chính xác câu trả lời).
Mọi thứ chạy bằng CLI, chưa cần UI, Container Apps hay Foundry Agent.

Mỗi task bên dưới vừa với **một cloud session của Claude Code**. Task nào không phụ thuộc nhau thì chạy song song.

---

## Giai đoạn 0 — Chuẩn bị (chiều 19/11)
- [ ] T0.1 Tạo repo GitHub private, push skeleton này, cài Claude GitHub App cho repo.
- [ ] T0.2 Azure Japan East: tạo deployment **Standard** cho GPT-5.x, GPT-5.x-mini và text-embedding-3-large. Kiểm tra quota.
      Chuyển default deployment của CU sang Standard. AI Search tier **Free** ở Japan East. Một Storage account.
- [ ] T0.3 Tạo cloud environment trên claude.ai/code:
      - Network: **Custom** + giữ danh sách mặc định, thêm domain `*.cognitiveservices.azure.com`, `*.openai.azure.com`,
        `*.services.ai.azure.com`, `*.search.windows.net`, `*.blob.core.windows.net`, `huggingface.co`, `*.hf.co`, `*.mhlw.go.jp`
      - Network secrets: key của Azure AI (`api-key` / `Ocp-Apim-Subscription-Key`), AI Search (`api-key`), Blob (SAS)
      - Biến môi trường: chỉ endpoint và tên deployment, không để key
- [ ] T0.4 Commit PDF MHLW (công khai) của phạm vi vào `data/raw/`, vì cloud session clone từ GitHub. Gõ ground truth cho 10 trang mẫu vào `data/gt/`
      (5 trang chữ, 3 trang bảng, 2 trang hình).

## Giai đoạn 1 — OCR (Thứ Sáu 20/11)
- [ ] T1.1 `steps/docling.py`: Docling CPU → markdown + JSON từng trang, grade trang, danh sách hình bị loại (logo, con dấu).
      **Đạt khi:** chạy hết phạm vi, mỗi trang ra một file, có báo cáo grade.
- [ ] T1.2 `steps/route.py`: luật định tuyến (grade, scan, bảng phức tạp, hình) → danh sách trang khó, kèm lý do.
- [ ] T1.3 `steps/cu.py`: gọi CU (prebuilt-layout + figure analysis) cho trang khó. Hình thì gọi GPT-5.x vision chuyển sang Mermaid hoặc bảng.
- [ ] T1.4 `steps/stitch.py`: bỏ header/footer, gộp đoạn bị ngắt trang, ghép bảng tràn trang, giữ mapping trang để trích dẫn.
- [ ] T1.5 Chạy `eval/eval_cer.py` trên 10 trang mẫu: so Docling, CU và kết quả sau định tuyến. Lỗi số 点 phải bằng 0.
      **Đạt khi:** có bảng CER theo loại trang; CER > 2% thì ghi rõ trang nào, vì sao.

## Giai đoạn 2 — Chunk, index, hỏi đáp (Thứ Hai 23/11)
- [ ] T2.1 `steps/chunk.py`: cắt thô theo mã mục → LLM refine ↔ validator (phủ 100%, không cắt bảng, có mã mục,
      điều kiện và ngoại lệ đi cùng nhau), tối đa 20 vòng. Ghi log tóm tắt mỗi vòng.
- [ ] T2.2 `steps/index.py`: embedding (1536 chiều để vừa tier Free 50 MB) → AI Search: hybrid + semantic.
      Tạo knowledge base Foundry IQ trên index này.
- [ ] T2.3 `scripts/ask.py`: retrieve → GPT-5.x (temperature 0, seed) → JSON `{status: answer|clarify|escalate, answer, citations}`.
      Kiểm tra citation có nằm trong các chunk đã lấy về. Không đủ căn cứ → `escalate`.
- [ ] T2.4 Đánh giá với 40 câu Stransa (cộng 60 câu AI sinh, nếu dùng):
      Recall@5 theo mã mục, đúng/sai câu trả lời, đúng căn cứ, tỉ lệ escalate,
      tính ổn định (hỏi lại mỗi câu 3 lần, có cache và không cache).

## Giai đoạn 3 — Báo cáo (Thứ Ba 24/11)
- [ ] T3.1 Báo cáo: số đo OCR / retrieval / câu trả lời, chi phí thực tế (từ usage), các câu sai và nguyên nhân,
      kiến trúc v3, rủi ro, câu hỏi còn mở (R6 vs R8, Azure hay Bedrock, ai review).
- [ ] T3.2 Cập nhật slide: thay sơ đồ, bỏ chữ "Global Standard" và "GPT-4.1".

---

## Sau buổi báo cáo (Phase 2, chưa làm bây giờ)
- Admin UI (ReactJS): upload, live log (SSE), review OCR và chunk, duyệt FAQ, bật/tắt.
- Chạy pipeline trên Container Apps Jobs + Storage Queue + Cosmos DB (chế độ `job`); trước đó chạy chế độ `worker`.
- Chat UI (ReactJS) nhúng Apotool → Bot API → Foundry Agent + Foundry IQ; chuyển người qua Cosmos + Logic Apps.
- Log audit (Log Analytics), App Configuration, Entra ID / Managed Identity.

## Câu hỏi cần chốt với khách
- Có được xử lý 40 câu hỏi Stransa ngoài Nhật không? Môi trường dev và Claude cloud session không ở Nhật.
  Nếu không, việc đánh giá chạy bằng script trên máy, kết quả chỉ ghi điểm số.
- Dùng Azure hay credit Bedrock (~$700, hết hạn cuối tháng 12)?
