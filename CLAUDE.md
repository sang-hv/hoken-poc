# 保険AI Bot — PoC (DEHA × Stransa)

Bot hỏi đáp về 点数 nha khoa (保険), sẽ tích hợp vào Apotool. Repo này là PoC.
Kiến trúc: `docs/HokenAIBot_Architecture_v3.png`. Kế hoạch và việc cần làm: `docs/PLAN.md`.

## Ràng buộc bắt buộc (không được vi phạm)
- **Mọi lời gọi LLM và AI đi tới Azure Japan East, deployment kiểu Standard (regional).**
  Không dùng Global Standard / Data Zone. Không gọi OpenAI, Anthropic hay dịch vụ nào khác để xử lý tài liệu.
- Phương án dự phòng duy nhất: Amazon Bedrock với inference profile `jp.` (Tokyo/Osaka). Chỉ dùng khi team yêu cầu.
- Repo và cloud session **chỉ chứa tài liệu công khai của MHLW** (厚労省). Không commit dữ liệu bệnh nhân,
  dữ liệu khách hàng hay câu hỏi khách gửi nếu chưa được duyệt.
- Không commit key hay endpoint thật. Cấu hình đọc từ biến môi trường (xem `.env.example`).
  Trong cloud session, key do network secret của environment gắn vào request, code không tự đọc key.
- Log không chép nội dung tài liệu: chỉ ghi docId, trang, mã mục, lý do.

## Phạm vi tài liệu
- 赤本 (R8) P536–691, 緑本 (R8) P372–423. Sách R8 chưa phát hành nên dùng tài liệu MHLW tương ứng.
- Câu trả lời phải kèm căn cứ: tên tài liệu, trang, mã mục.

## Pipeline (khu A)
1. Docling (CPU): layout, bảng, OCR; bỏ logo, con dấu, chữ ký.
2. Định tuyến theo grade trang + luật cứng: scan, bảng phức tạp, hình → bước 3.
3. Content Understanding (prebuilt-layout + figure analysis), GPT-5.x vision → nối trang → người review.
4. Cắt thô theo mã mục → LLM chunk ↔ kiểm tra luật (≤ 20 vòng) → confidence → người review → embedding → AI Search.

## Quy ước code
- Python 3.11, `uv` hoặc `pip`. Format bằng `ruff`. Test bằng `pytest`.
- `app/steps/*`: logic thuần, mỗi bước có hàm `handle(msg) -> list[next_msg]`.
  Không giữ trạng thái trong RAM giữa các bước.
- `app/adapters/*`: queue / blob / db sau interface. `app/runtime/*`: `worker` (VM) và `job` (Container Apps Job).
- Ghi kết quả theo khoá `docId + page + step`, để chạy lại thì ghi đè, không sinh bản trùng.
- Mỗi tính năng có lệnh CLI chạy được độc lập (`python -m app.main ...`), để chạy thử không cần UI.

## Đánh giá
- OCR: `eval/eval_cer.py` (CER + kiểm tra số 点). Ground truth nằm trong `data/gt/`.
- Retrieval: `eval/eval_retrieval.py` (Recall@K, MRR theo mã mục).
- Hỏi đáp: so câu trả lời với đáp án và căn cứ trong bộ câu hỏi; hỏi lại 3 lần để kiểm tra tính ổn định.
