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
