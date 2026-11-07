from __future__ import annotations

import pytest

import common
import prepare
from conftest import make_course


def write_pages(course_dir, lecture_id, page_count, blank=()):
    pages = [
        {"page": n, "title": f"T{n}" if n % 5 else "", "text": f"text of page {n}",
         "image": f"img/p{n:03d}.png", "size": [1265, 949], "blank": n in blank}
        for n in range(1, page_count + 1)
    ]
    common.write_json(common.work_dir(course_dir, lecture_id) / "pages.json", {
        "extract_version": 1, "lecture": lecture_id, "page_count": page_count, "pages": pages,
    })


def write_outline(course_dir, lecture_id, sections, skip=()):
    common.write_json(common.work_dir(course_dir, lecture_id) / "outline.json", {
        "lecture": lecture_id,
        "sections": [{"id": f"s{i:02d}", "title": f"节{i}", "pages": list(r)} for i, r in enumerate(sections, 1)],
        "skip": list(skip),
    })


@pytest.fixture
def course(tmp_course):
    make_course(tmp_course, {"L01": "a.pdf"})
    write_pages(tmp_course, "L01", 30, blank=(17,))
    return tmp_course


def outline(sections, skip=(), lecture="L01"):
    return {
        "lecture": lecture,
        "sections": [{"id": f"s{i:02d}", "title": "x", "pages": list(r)} for i, r in enumerate(sections, 1)],
        "skip": list(skip),
    }


# ---- 大纲校验 ----

def test_valid_outline():
    assert prepare.check_outline(outline([(1, 4), (5, 20), (21, 30)], skip=[30]), "L01", 30) == []


@pytest.mark.parametrize("sections,skip,expect", [
    ([(1, 4), (6, 30)], [], "第 5–5 页不在任何一节里"),
    ([(1, 6), (5, 30)], [], "和前一节重叠"),
    ([(1, 4), (5, 20)], [], "应覆盖到最后一页 30"),
    ([(2, 30)], [], "第 1–1 页不在任何一节里"),
    ([(1, 4), (5, 31)], [], "超过总页数"),
    ([(1, 4), (5, 30)], [31], "skip 里的页码超过总页数"),
    ([(1, 4), (5, 30)], [1, 2, 3, 4], "s01 的所有页都被跳过了"),
    ([(5, 4)], [], "起始页 5 大于结束页 4"),
])
def test_invalid_outline(sections, skip, expect):
    errors = prepare.check_outline(outline(sections, skip), "L01", 30)
    assert any(expect in e for e in errors), errors


def test_schema_and_id_errors():
    bad = outline([(1, 30)])
    del bad["sections"][0]["title"]
    errors = prepare.check_outline(bad, "L01", 30)
    assert errors and errors[0].startswith("格式错误")

    wrong_ids = outline([(1, 10), (11, 30)])
    wrong_ids["sections"][1]["id"] = "s05"
    assert any("应为 s02" in e for e in prepare.check_outline(wrong_ids, "L01", 30))

    assert any("lecture 应为 L01" in e for e in prepare.check_outline(outline([(1, 30)], lecture="L02"), "L01", 30))


# ---- 切块 ----

@pytest.mark.parametrize("n,sizes", [(1, [1]), (10, [10]), (11, [6, 5]), (25, [9, 8, 8]), (30, [10, 10, 10])])
def test_split_chunks_sizes(n, sizes):
    chunks = prepare.split_chunks(list(range(1, n + 1)))
    assert [len(c) for c in chunks] == sizes
    assert [p for c in chunks for p in c] == list(range(1, n + 1))


def test_units_skip_pages_and_chunk_ids(course):
    # 第 17 页是空白页（自动跳过），第 30 页由模型标为跳过
    write_outline(course, "L01", [(1, 4), (5, 28), (29, 30)], skip=[30])
    summary = prepare.prepare_lecture(course, "L01")
    units = summary["units"]
    assert summary["skip"] == [17, 30]
    assert [u["id"] for u in units] == ["s01", "s02-1", "s02-2", "s02-3", "s03"]
    s02_pages = [p for u in units if u["section"] == "s02" for p in u["pages"]]
    assert s02_pages == [p for p in range(5, 29) if p != 17]
    assert all(len(u["pages"]) <= prepare.MAX_UNIT_PAGES for u in units)
    assert units[1]["chunk"] == {"index": 1, "total": 3}
    assert units[0]["chunk"] is None
    assert units[-1]["pages"] == [29]


def test_packets(course):
    write_outline(course, "L01", [(1, 4), (5, 30)], skip=[30])
    prepare.prepare_lecture(course, "L01")
    work = common.work_dir(course, "L01")

    units = common.read_json(work / "units.json")["units"]
    assert [u["id"] for u in units] == ["s01", "s02-1", "s02-2", "s02-3"]

    packet = common.read_json(work / "sections" / "s01.input.json")
    assert packet["unit"] == "s01"
    assert packet["explain_language"] == "zh"
    assert [p["page"] for p in packet["pages"]] == [1, 2, 3, 4]
    assert packet["pages"][0]["image"].endswith("p001.png")
    assert all(path.endswith(".md") for path in packet["read_first"])
    assert packet["output_file"].endswith("s01.json")
    assert packet["page_count"] == 30
    assert packet["image_dir"].endswith("img")
    assert packet["previous_unit"] is None
    # 大纲里没有标题的页用文字开头代替
    assert dict(packet["outline"][0]["page_titles"]) == {1: "T1", 2: "T2", 3: "T3", 4: "T4"}
    s02 = packet["outline"][1]["page_titles"]
    assert dict(s02)[5] == "（无标题）text of page 5"

    last = common.read_json(work / "sections" / "s02-3.input.json")
    assert last["skipped_pages_in_section"] == [17, 30]
    assert last["chunk"] == {"index": 3, "total": 3}


def test_refresh_unit_picks_up_previous_summary(course):
    write_outline(course, "L01", [(1, 4), (5, 30)])
    prepare.prepare_lecture(course, "L01")
    work = common.work_dir(course, "L01")
    assert common.read_json(work / "sections" / "s02-1.input.json")["previous_unit"] is None

    common.write_json(work / "sections" / "s01.json", {"section_summary": "第一节讲了 X。"})
    assert prepare.main([str(course), "L01", "--unit", "s02-1"]) == 0
    packet = common.read_json(work / "sections" / "s02-1.input.json")
    assert packet["previous_unit"] == {"unit": "s01", "summary": "第一节讲了 X。"}


def test_main_reports_outline_errors(course, capsys):
    write_outline(course, "L01", [(1, 4), (6, 30)])
    assert prepare.main([str(course), "L01"]) == 1
    err = capsys.readouterr().err
    assert "1 处问题" in err and "第 5–5 页" in err
    assert not (common.work_dir(course, "L01") / "units.json").exists()


def test_main_missing_inputs(tmp_course, capsys):
    make_course(tmp_course, {"L01": "a.pdf"})
    assert prepare.main([str(tmp_course), "L01"]) == 1
    assert "extract.py" in capsys.readouterr().err
    write_pages(tmp_course, "L01", 5)
    assert prepare.main([str(tmp_course), "L01"]) == 1
    assert "outline-guide.md" in capsys.readouterr().err
    write_outline(tmp_course, "L01", [(1, 5)])
    assert prepare.main([str(tmp_course), "L01", "--unit", "s09"]) == 1
    assert "没有讲解单元 s09" in capsys.readouterr().err
