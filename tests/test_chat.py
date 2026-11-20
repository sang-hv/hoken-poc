"""Chat thử: dựng prompt có đánh số nguồn, đọc câu trả lời, chuyển CSKH khi không có căn cứ."""

from __future__ import annotations

import json

from app.adapters.memory import HashEmbedder, MemorySearch, ScriptedLLM
from app.domain.options import ChatOptions
from app.ports import IndexDoc, SearchHit
from app.services import chat


def _hit(i: int, code: str, content: str) -> SearchHit:
    return SearchHit(f"c{i}", "d1", "赤本", code, f"title {code}", 536, 537 if i == 2 else 536, content, 1.0 / i)


def test_build_messages_numbers_sources_and_trims_history():
    hits = [_hit(1, "M015-2", "CAD/CAM冠 1,200点"), _hit(2, "M016", "乳歯冠 200点")]
    history = [
        {"role": "user", "content": f"q{i}"} if i % 2 == 0 else {"role": "assistant", "content": f"a{i}"}
        for i in range(10)
    ]
    msgs = chat.build_messages("CAD/CAM冠は何点？", history, hits, ChatOptions(max_history=2))
    assert msgs[0].role == "system"
    assert [m.text for m in msgs[1:-1]] == ["q6", "a7", "q8", "a9"]  # 2 lượt gần nhất
    last = msgs[-1].text
    assert "[1] M015-2 title M015-2 (赤本 P536)" in last and "[2] M016 title M016 (赤本 P536-537)" in last
    assert last.endswith("Question: CAD/CAM冠は何点？")


def test_parse_answer():
    ok = chat.parse_answer(json.dumps({"answer": "1,200点です [1]", "cited": [1, 9], "handoff": False}), 2)
    assert ok == {"answer": "1,200点です [1]", "cited": [1], "handoff": False}
    assert chat.parse_answer('{"answer": "", "cited": [], "handoff": true}', 2)["handoff"] is True
    loose = chat.parse_answer("plain text citing [2] and [5]", 2)  # không phải JSON
    assert loose["cited"] == [2] and loose["handoff"] is False


def test_ask_answers_from_index_or_hands_off(container):
    c = container
    emb, search = HashEmbedder(32), MemorySearch()
    search.ensure(32)
    text = "M016 Metal crown 800 points per tooth"
    search.upsert([IndexDoc("c1", "d1", "Sample", "M016", "Metal crown", 1, 1, text, emb.embed([text])[0])])
    seen = {}

    def responder(messages, tier, json_mode):
        seen["user"] = messages[-1].text
        if "weather" in messages[-1].text:
            return json.dumps({"answer": "", "cited": [], "handoff": True})
        return json.dumps({"answer": "800 points [1]", "cited": [1], "handoff": False})

    c.config.overrides.update({"embedding": emb, "search": search, "llm": ScriptedLLM(responder)})
    r = chat.ask(c, "M016 Metal crown points?", [])
    assert r["answer"] == "800 points [1]" and r["cited"] == [1] and not r["handoff"]
    assert r["sources"][0]["item_code"] == "M016" and "[1] M016" in seen["user"]
    r2 = chat.ask(c, "weather tomorrow?", [])
    assert r2["handoff"] and r2["reason"] == "not_in_sources"

    empty = MemorySearch()
    empty.ensure(32)
    c.config.overrides["search"] = empty
    r3 = chat.ask(c, "anything", [])
    assert r3["handoff"] and r3["reason"] == "no_source" and r3["ms"]["llm"] == 0
