#!/usr/bin/env python3
"""
Đo Recall@K của bước tìm kiếm: căn cứ đúng có nằm trong top K chunk tìm được không.

Đầu vào: questions.csv (UTF-8), mỗi câu hỏi một dòng:
    id,question,gold_items
    Q01,CAD/CAM冠用材料(Ⅲ)の算定要件は？,M015-2
    Q02,...,A222-2;M000-2          <- nhiều căn cứ thì cách nhau bằng ;
  gold_items do chuyên gia ghi: mã mục (hoặc số trang) chứa căn cứ đúng.

Chạy thật (gọi Azure AI Search, cùng cấu hình tìm kiếm mà agent dùng):
    pip install azure-search-documents azure-identity
    export SEARCH_ENDPOINT=https://<ten>.search.windows.net SEARCH_INDEX=hoken-chunks SEARCH_KEY=...
    python eval_retrieval.py questions.csv --k 5

Chạy thử không cần Azure (dùng kết quả tìm kiếm đã lưu sẵn):
    python eval_retrieval.py questions.csv --from-json saved_results.json

Kết quả: in bảng tổng hợp + ghi retrieval_report.csv (từng câu: trúng không, ở hạng mấy, top K là gì).
"""
import argparse
import csv
import json
import os
import sys

# Trường trong index dùng để so với gold_items. Đổi thành "page_from" nếu chấm theo trang.
MATCH_FIELD = "item_code"


def search_azure(question, k):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.models import VectorizableTextQuery

    client = SearchClient(os.environ["SEARCH_ENDPOINT"], os.environ["SEARCH_INDEX"],
                          AzureKeyCredential(os.environ["SEARCH_KEY"]))
    results = client.search(
        search_text=question,                                   # tìm theo từ khoá
        vector_queries=[VectorizableTextQuery(text=question,    # tìm theo nghĩa (index tự tạo embedding)
                                              k_nearest_neighbors=50, fields="content_vector")],
        query_type="semantic", semantic_configuration_name="default",   # xếp hạng lại
        top=k, select=["id", MATCH_FIELD, "page_from", "section"],
    )
    return [{"id": r["id"], "match": str(r.get(MATCH_FIELD, "")), "page": r.get("page_from"),
             "section": r.get("section", "")} for r in results]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions_csv")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--from-json", help="kết quả đã lưu: {question_id: [{id, match, ...}, ...]}")
    ap.add_argument("--save-json", help="lưu kết quả tìm kiếm để chạy lại không tốn API")
    args = ap.parse_args()

    with open(args.questions_csv, encoding="utf-8-sig") as f:
        questions = list(csv.DictReader(f))
    saved = json.load(open(args.from_json, encoding="utf-8")) if args.from_json else None
    all_results, rows = {}, []
    full_hit = any_hit = 0
    rr_sum = 0.0

    for q in questions:
        gold = [g.strip() for g in q["gold_items"].split(";") if g.strip()]
        hits = saved[q["id"]][: args.k] if saved is not None else search_azure(q["question"], args.k)
        all_results[q["id"]] = hits
        found = [h["match"] for h in hits]

        ranks = {g: (found.index(g) + 1 if g in found else None) for g in gold}
        got = [g for g, r in ranks.items() if r]
        is_full = len(got) == len(gold)          # đủ mọi căn cứ cần thiết
        is_any = len(got) > 0                    # có ít nhất 1 căn cứ
        first = min((r for r in ranks.values() if r), default=None)
        full_hit += is_full
        any_hit += is_any
        rr_sum += 1 / first if first else 0

        status = "ĐỦ" if is_full else ("THIẾU" if is_any else "TRƯỢT")
        rows.append([q["id"], q["question"], ";".join(gold), status,
                     ";".join(f"{g}@{r or '-'}" for g, r in ranks.items()), " | ".join(found)])

    n = len(questions)
    with open("retrieval_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "gold", "ket_qua", "hang_cua_tung_can_cu", f"top{args.k}_tim_duoc"])
        w.writerows(rows)
    if args.save_json:
        json.dump(all_results, open(args.save_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"Số câu: {n}")
    print(f"Recall@{args.k} (đủ mọi căn cứ)     : {full_hit / n:.1%}   ← chỉ số chính, ngưỡng ≥ 90%")
    print(f"Recall@{args.k} (ít nhất 1 căn cứ)  : {any_hit / n:.1%}")
    print(f"MRR (căn cứ đúng đứng hạng mấy) : {rr_sum / n:.3f}   (1.0 = luôn đứng đầu)")
    print("Câu TRƯỢT / THIẾU → lỗi loại B (tìm kiếm), hoặc A nếu căn cứ không có trong chunk nào.")
    print("Chi tiết: retrieval_report.csv")


if __name__ == "__main__":
    main()
