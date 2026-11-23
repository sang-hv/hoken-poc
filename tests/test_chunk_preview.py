"""Dòng tóm tắt của danh sách chunk (tab チャンク): bỏ rác markdown và mã mục + tiêu đề lặp ở đầu."""

from app.services.chunks import PREVIEW_CHARS, _preview


def test_strips_code_and_title_prefix():
    title = "ポストクラウン（1歯につき）"
    assert _preview(f"M017{title}\n1前歯1,200点", "M017", title) == "1前歯1,200点"
    # có / không có khoảng trắng giữa mã và tiêu đề
    assert _preview("M017 ポストクラウン（1歯につき） 1前歯", "M017", "ポストクラウン（1歯につき）") == "1前歯"


def test_title_prefix_matches_after_nfkc():
    # văn bản dùng ngoặc nửa角, tiêu đề dùng ngoặc toàn角
    assert _preview("M017ポストクラウン(1歯につき) 1前歯", "M017", "ポストクラウン（1歯につき）") == "1前歯"


def test_drops_markdown_table_noise_and_comments():
    text = "M016 乳歯冠\n| 列1 | 列2 | 列3 |\n|---|:---:|---|\n| 1 | 乳歯金属冠の場合 | 200点 |\n<!-- figure: p3 -->"
    assert _preview(text, "M016", "乳歯冠") == "1 乳歯金属冠の場合 200点"


def test_keeps_text_when_prefix_absent():
    assert _preview("# 見出し\n- 本文です", "A000", "初診料") == "見出し 本文です"


def test_keeps_hyphenated_words_and_limits_length():
    assert _preview("M015-2 を算定", "", "") == "M015-2 を算定"
    assert len(_preview("あ" * 500)) == PREVIEW_CHARS


def test_drops_code_blocks():
    text = "はい いいえ\n```mermaid\nflowchart TD\n  A-->B\n```\n図は算定の流れ"
    assert _preview(text) == "はい いいえ 図は算定の流れ"
    assert _preview("本文\n```mermaid\nflowchart TD") == "本文"
