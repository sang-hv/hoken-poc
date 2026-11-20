"""Logic thuần: tiêu chí trang dễ (theo điểm Docling), nối trang, nối dòng, kiểm tra luật chunk."""

from __future__ import annotations

from app.domain.models import Page, PageFeatures, PageScores
from app.domain.options import ChunkOptions, RoutingOptions, StitchOptions
from app.steps import rules


def _page(**kw) -> Page:
    scores = PageScores(parse_score=0.95, layout_score=0.93, low_score=0.9, low_grade="excellent")
    p = Page(id="0001", doc_id="d", page=1, book_page=1, engine="docling", scores=scores, features=PageFeatures())
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_easy_page_needs_all_criteria():
    o = RoutingOptions()
    assert rules.decide_route(_page(), o) == ("easy", [])


def test_hard_reasons_follow_docling_grades():
    o = RoutingOptions()
    fair = _page(scores=PageScores(parse_score=0.95, layout_score=0.7, low_score=0.71, low_grade="fair"))
    assert rules.decide_route(fair, o) == ("hard", ["low_grade"])
    garbled = _page(scores=PageScores(parse_score=0.6, layout_score=0.9, low_score=0.62, low_grade="fair"))
    assert rules.decide_route(garbled, o)[1] == ["low_grade", "parse_score"]
    scanned = _page(
        scores=PageScores(layout_score=0.9, ocr_score=0.92, low_score=0.9, low_grade="excellent"),
        features=PageFeatures(has_text_layer=False),
    )
    assert rules.decide_route(scanned, o)[1] == ["ocr", "scanned"]
    table = _page(features=PageFeatures(n_tables=1, complex_tables=1, table_at_bottom=True))
    assert rules.decide_route(table, o)[1] == ["complex_table", "table_cross_page"]
    fig = _page(features=PageFeatures(n_figures=1, max_figure_area=0.2))
    assert rules.decide_route(fig, o)[1] == ["figure"]
    small_logo_only = _page(features=PageFeatures(n_figures=1, max_figure_area=0.01, removed={"logo": 1}))
    assert rules.decide_route(small_logo_only, o)[0] == "easy"


def test_overrides_and_missing_docling():
    o = RoutingOptions()
    assert rules.decide_route(_page(route_override="force_cu"), o) == ("hard", ["override_force_cu"])
    assert rules.decide_route(_page(engine="pdfium", route_override="skip_cu"), o)[0] == "easy"
    assert "no_docling" in rules.decide_route(_page(engine="pdfium"), o)[1]


def test_stitch_removes_repeated_header_and_page_numbers_and_flags_joins():
    pages = {
        1: "歯科点数表\nM015-2 CAD/CAM冠\n本文が次のページへ続く\n- 536 -",
        2: "歯科点数表\nつづきの文章。\n| a | b |\n|---|---|\n| 1 | 2 |\n537",
        3: "歯科点数表\n| a | b |\n|---|---|\n| 3 | 4 |\n538",
    }
    res = rules.stitch_pages(pages, StitchOptions())
    assert all("歯科点数表" not in t for t in res.texts.values())
    assert "536" not in res.texts[1] and "537" not in res.texts[2]
    assert res.continues_next[1] is True
    assert res.table_continues_next[2] is True


def test_assemble_lines_merges_continuation_and_drops_repeated_table_header():
    lines = rules.assemble_lines(
        [
            (536, "本文が次のページへ\n| a | b |\n|---|---|\n| 1 | 2 |", False, True),
            (537, "| a | b |\n|---|---|\n| 3 | 4 |\nおわり", False, False),
        ]
    )
    texts = [ln.text for ln in lines]
    assert texts.count("| a | b |") == 1 and "| 3 | 4 |" in texts
    assert lines[-1].page == 537


def test_join_wrapped_lines_keeps_list_items_and_tables():
    text = (
        "注1 区分番号M015-2に掲げるCAD/CAM冠は、別に厚生労働大臣が定める施設基準に適合しているも\n"
        "のとして届け出た保険医療機関において算定する。\n"
        "2 1以外の場合 1,000点\n"
        "| a | b |"
    )
    out = rules.join_wrapped_lines(text).split("\n")
    assert out[0].endswith("算定する。") and out[1] == "2 1以外の場合 1,000点" and out[2] == "| a | b |"
    # Số trang ở cuối trang không bị nối vào câu chưa kết thúc
    tail = rules.join_wrapped_lines("その製作に当たっては、支台築造の費用を別に算定することはできないものと\n- 538 -")
    assert tail.split("\n")[-1] == "- 538 -"


def test_validate_spans_rules():
    o = ChunkOptions(min_chars=1)
    sec = rules.Section(
        "M016",
        "",
        [rules.Line(t, 1) for t in ["M016 乳歯冠", "| a |", "| b |", "ただし、例外。", "次の文。"]],
    )
    ok = [rules.ChunkSpan(0, 3, "M016"), rules.ChunkSpan(4, 4, "M016")]
    assert rules.validate_spans(sec.lines, ok, o) == {}
    gap = [rules.ChunkSpan(0, 1, "M016"), rules.ChunkSpan(3, 4, "M016")]
    assert rules.validate_spans(sec.lines, gap, o) == {-1: ["coverage"]}
    split_table = [rules.ChunkSpan(0, 1, "M016"), rules.ChunkSpan(2, 4, "M016")]
    assert "table_split" in rules.validate_spans(sec.lines, split_table, o)[0]
    exc = [rules.ChunkSpan(0, 2, "M016"), rules.ChunkSpan(3, 4, "")]
    v = rules.validate_spans(sec.lines, exc, o)
    assert set(v[1]) == {"exception_separated", "no_item_code"}
    det = rules.deterministic_spans(sec, ChunkOptions(min_chars=1, max_chars=5))
    assert rules.hard_violations(rules.validate_spans(sec.lines, det, ChunkOptions(min_chars=1, max_chars=5))) == 0


def test_rough_sections_by_item_code():
    lines = [rules.Line(t, 1) for t in ["前文", "M015-2 CAD/CAM冠", "本文", "## 区分番号「A000」初診料", "本文2"]]
    secs = rules.rough_sections(lines, ChunkOptions())
    assert [s.item_code for s in secs] == ["", "M015-2", "A000"]
    assert secs[2].title == "初診料"


# ------------------------------------------------------------------ vùng confidence thấp
def _cu_raw(words):
    return {
        "result": {
            "contents": [
                {"markdown": "## M015 局部 1,250点", "pages": [{"width": 8.0, "height": 10.0, "words": words}]}
            ]
        }
    }


def test_parse_cu_source():
    assert rules.parse_cu_source("D(1,1,2,3,2,3,4,1,4)") == [(1, [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0])]
    assert rules.parse_cu_source("D(1,1,2,3,2,3,4,1,4);D(2,0,0,1,0,1,1,0,1)")[1][0] == 2
    assert rules.parse_cu_source("garbage") == [] and rules.parse_cu_source("D(1,a,b)") == []


def test_cu_low_words_normalizes_and_filters():
    words = [
        {
            "content": "1,250点",
            "confidence": 0.61,
            "source": "D(1,4,2,6,2,6,3,4,3)",
            "span": {"offset": 12, "length": 6},
        },
        {"content": "局部", "confidence": 0.95, "source": "D(1,1,2,2,2,2,3,1,3)"},
        {"content": "x", "confidence": 0.5, "source": ""},  # không có toạ độ → bỏ
    ]
    out = rules.cu_low_words(_cu_raw(words), 0.8)
    assert len(out) == 1
    b = out[0]
    assert b["source"] == "cu" and b["text"] == "1,250点" and b["confidence"] == 0.61
    assert b["bbox"] == [0.5, 0.2, 0.75, 0.3] and b["span"] == [12, 6]
    assert rules.cu_low_words({}, 0.8) == [] and rules.cu_low_words({"fake": True}, 0.8) == []


def test_low_confidence_boxes_merges_sorted_and_skips_removed():
    meta = {
        "elements": [
            {"label": "table", "bbox": [0, 0, 1, 0.5], "confidence": 0.7},
            {"label": "picture", "bbox": [0, 0, 0.1, 0.1], "confidence": 0.1, "removed": True},
            {"label": "text", "bbox": [0, 0.5, 1, 0.6], "confidence": 0.95},
            {"label": "text", "bbox": [0, 0.6, 1, 0.7]},
        ]
    }
    words = [{"content": "点", "confidence": 0.55, "source": "D(1,0,0,1,0,1,1,0,1)"}]
    out = rules.low_confidence_boxes(meta, _cu_raw(words), 0.8)
    assert [(b["source"], b["confidence"]) for b in out] == [("cu", 0.55), ("docling", 0.7)]


def test_docling_attach_confidence_and_page_confidences_without_docling():
    from types import SimpleNamespace as NS

    from app.steps.docling_engine import attach_confidence, page_confidences

    class Box:  # giống BoundingBox của Docling, đã ở gốc trên-trái
        def __init__(self, l, t, r, b):  # noqa: E741
            self.l, self.t, self.r, self.b = l, t, r, b

        def to_top_left_origin(self, page_height):
            return self

    cluster = NS(label="DocItemLabel.TABLE", bbox=Box(0, 0, 50, 50), confidence=0.66)
    cell = NS(from_ocr=True, confidence=0.4, text="1,250点", rect=None, bbox=Box(10, 60, 40, 70))
    clean = NS(from_ocr=True, confidence=0.999, text="ok", rect=None, bbox=Box(0, 80, 10, 90))
    res = NS(pages=[NS(page_no=0, predictions=NS(layout=NS(clusters=[cluster])), cells=[cell, clean])])
    clusters, cells = page_confidences(res, 1, 100.0, 100.0)
    assert clusters == [("table", [0.0, 0.0, 0.5, 0.5], 0.66)]
    assert cells == [{"label": "ocr_text", "bbox": [0.1, 0.6, 0.4, 0.7], "confidence": 0.4, "text": "1,250点"}]
    els = [{"label": "table", "bbox": [0.0, 0.0, 0.48, 0.5]}, {"label": "text", "bbox": [0.6, 0.6, 0.9, 0.9]}]
    attach_confidence(els, clusters)
    assert els[0]["confidence"] == 0.66 and "confidence" not in els[1]
    # API khác phiên bản → không vỡ, chỉ trả rỗng
    assert page_confidences(object(), 1, 100.0, 100.0) == ([], [])
