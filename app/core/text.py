"""Xử lý chữ tiếng Nhật dùng chung: chuẩn hoá, tách từ khoá cho tìm kiếm, nhận diện mã mục."""

from __future__ import annotations

import re
import unicodedata

# Cụm kanji / katakana / chữ-số liên tiếp (tách tại hiragana và dấu câu).
_TERM_RE = re.compile(r"[一-鿿㐀-䶿゠-ヿｦ-ﾟA-Za-z0-9ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\-－ー]{2,}")
_STOP = {"について", "とは", "ですか", "ください"}


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def keyword_terms(query: str, max_terms: int = 12) -> list[str]:
    """Từ khoá để tìm theo chuỗi con (pg_bigm LIKE / match_phrase). Dài trước, không trùng."""
    q = nfkc(query)
    terms = [t.strip("-ー") for t in _TERM_RE.findall(q)]
    out: list[str] = []
    for t in sorted(set(terms), key=len, reverse=True):
        if len(t) >= 2 and t not in _STOP and t not in out:
            out.append(t)
    return out[:max_terms]


def keyword_score(content: str, terms: list[str]) -> float:
    c = nfkc(content)
    return float(sum(len(t) for t in terms if t in c))


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion — gộp hạng của tìm theo vector và theo từ khoá."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores
