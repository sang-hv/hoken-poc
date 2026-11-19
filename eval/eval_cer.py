#!/usr/bin/env python3
"""
Đo CER (Character Error Rate) và lỗi con số điểm (点数) của nhiều engine OCR
so với ground truth. Không cần thư viện ngoài.

Cấu trúc thư mục:
    data/
      gt/                     # ground truth: văn bản chuẩn, gõ tay & soát kỹ
        page_001.txt
        page_002.txt
      ocr/
        azure_di/             # mỗi engine 1 thư mục, tên file trùng với gt/
          page_001.md
        azure_cu/
          page_001.md
        yomitoku/
          page_001.md

Chạy:
    python eval_cer.py data            # in bảng tổng hợp + ghi report/
    python eval_cer.py data --show 20  # in thêm 20 lỗi đầu tiên mỗi trang
"""
import argparse
import csv
import html
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------- chuẩn hoá
def strip_markdown(text: str) -> str:
    """Bỏ phần định dạng mà engine thêm vào, chỉ giữ chữ để so."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)          # <!-- PageBreak --> ...
    text = re.sub(r"</?(td|th)[^>]*>", " ", text)                # ô bảng -> cách nhau
    text = re.sub(r"<[^>]+>", "", text)                          # thẻ HTML khác
    text = html.unescape(text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)    # tiêu đề #
    text = re.sub(r"(\*\*|__|`)", "", text)                      # đậm, code
    text = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", text, flags=re.M) # bullet
    return text


def normalize(text: str) -> str:
    """
    - Toàn chiều rộng -> nửa chiều rộng cho chữ/số/dấu ASCII (Ａ→A, ３→3, （→( )
    - Bỏ mọi khoảng trắng và xuống dòng
    - GIỮ NGUYÊN ký hiệu đặc biệt: Ⅲ, ①, ㊀, 留, 【】... vì đọc sai chúng là lỗi thật
    """
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        if ch.isspace():
            continue
        out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------- tính lỗi
def align(ref: str, hyp: str):
    """Levenshtein + truy vết: trả về số S, D, I và danh sách lỗi."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ri = ref[i - 1]
        row, prev = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)

    s = d = ins = 0
    errors = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                s += 1
                errors.append(("thay", i - 1, ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1
            errors.append(("thiếu", i - 1, ref[i - 1], ""))
            i -= 1
        else:
            ins += 1
            errors.append(("thừa", i, "", hyp[j - 1]))
            j -= 1
    errors.reverse()
    return s, d, ins, errors


POINT_RE = re.compile(r"(\d[\d,]*)点")


def point_values(text: str):
    return [v.replace(",", "") for v in POINT_RE.findall(text)]


def point_errors(ref: str, hyp: str):
    """So danh sách các con số 'xxx点' theo thứ tự. Mọi sai lệch = lỗi nghiêm trọng."""
    r, h = point_values(ref), point_values(hyp)
    _, _, _, errs = align_list(r, h)
    return len(r), errs


def align_list(ref, hyp):
    # tái dùng align() bằng cách ánh xạ mỗi giá trị thành 1 ký tự riêng
    vocab = {v: chr(0xE000 + k) for k, v in enumerate(dict.fromkeys(ref + hyp))}
    back = {c: v for v, c in vocab.items()}
    s, d, i, errs = align("".join(vocab[v] for v in ref), "".join(vocab[v] for v in hyp))
    errs = [(kind, pos, back.get(a, ""), back.get(b, "")) for kind, pos, a, b in errs]
    return s, d, i, errs


def context(ref: str, pos: int, width: int = 8) -> str:
    return ref[max(0, pos - width): pos] + "【" + ref[pos: pos + 1] + "】" + ref[pos + 1: pos + 1 + width]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--show", type=int, default=0, help="in N lỗi đầu tiên mỗi trang")
    args = ap.parse_args()

    root = Path(args.data_dir)
    gt_files = sorted((root / "gt").glob("*.txt"))
    engines = sorted(p for p in (root / "ocr").iterdir() if p.is_dir())
    if not gt_files or not engines:
        sys.exit("Không tìm thấy data/gt/*.txt hoặc data/ocr/<engine>/")

    report_dir = root / "report"
    report_dir.mkdir(exist_ok=True)
    page_rows, error_rows, summary = [], [], []

    for eng in engines:
        tot_n = tot_err = tot_pts = tot_pt_err = missing = 0
        for gt_path in gt_files:
            hyp_path = next((eng / (gt_path.stem + ext) for ext in (".md", ".txt")
                             if (eng / (gt_path.stem + ext)).exists()), None)
            ref = normalize(strip_markdown(gt_path.read_text(encoding="utf-8")))
            if hyp_path is None:
                missing += 1
                hyp = ""
            else:
                hyp = normalize(strip_markdown(hyp_path.read_text(encoding="utf-8")))

            s, d, i, errs = align(ref, hyp)
            n = len(ref)
            n_pts, pt_errs = point_errors(ref, hyp)
            cer = (s + d + i) / n if n else 0.0

            tot_n += n
            tot_err += s + d + i
            tot_pts += n_pts
            tot_pt_err += len(pt_errs)

            page_rows.append([eng.name, gt_path.stem, n, s, d, i, f"{cer:.2%}", n_pts, len(pt_errs)])
            for kind, pos, a, b in errs:
                error_rows.append([eng.name, gt_path.stem, kind, a, b, context(ref, pos)])
            for kind, _, a, b in pt_errs:
                error_rows.append([eng.name, gt_path.stem, "SỐ ĐIỂM " + kind, a + "点", b + "点", ""])

            if args.show and errs:
                print(f"\n[{eng.name}] {gt_path.stem}  CER={cer:.2%}")
                for kind, pos, a, b in errs[: args.show]:
                    print(f"   {kind:5} '{a}' -> '{b}'   …{context(ref, pos)}…")

        summary.append([eng.name, len(gt_files) - missing, tot_n,
                        f"{tot_err / tot_n:.2%}" if tot_n else "-", tot_pts, tot_pt_err])

    with open(report_dir / "per_page.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["engine", "page", "chars_gt", "S_thay", "D_thieu", "I_thua", "CER",
                    "so_diem_gt", "so_diem_sai"])
        w.writerows(page_rows)
    with open(report_dir / "errors.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["engine", "page", "loai", "gt", "ocr", "ngu_canh"])
        w.writerows(error_rows)

    print("\n=== TỔNG HỢP (CER tính gộp: tổng lỗi / tổng ký tự) ===")
    print(f"{'engine':<14}{'trang':>6}{'ký tự':>9}{'CER':>9}{'số điểm':>9}{'sai':>6}")
    for eng, pages, n, cer, pts, pt_err in summary:
        flag = "  ← có lỗi nghiêm trọng" if pt_err else ""
        print(f"{eng:<14}{pages:>6}{n:>9}{cer:>9}{pts:>9}{pt_err:>6}{flag}")
    print(f"\nChi tiết: {report_dir/'per_page.csv'}, {report_dir/'errors.csv'}")


if __name__ == "__main__":
    main()
