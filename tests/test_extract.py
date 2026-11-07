from __future__ import annotations

import pytest

import common
import extract
from conftest import PAGE_H, PAGE_W, make_course, make_pdf

PDF_NAME = "Lec Test (1) 测试.pdf"


def sample_pdf(path):
    """5 页：标题页、带表格数字和页码的页、空白页、只有矢量框的页、只有图片的页。"""
    pages = [
        {"texts": [(60, 100, "Intro", 32)]},
        {"texts": [(60, 100, "Table", 24), (100, 300, "2", 18), (690, 525, "2", 12)]},
        {},
        {"rect": (100, 100, 400, 300)},
        {"image": (100, 100, 300, 250)},
    ]
    toc = [
        [1, "Slide 1: Intro", 1],
        [1, "Slide 2: Example  Data", 2],
        [1, "Slide 3", 3],
        [1, "Slide 4", 4],
        [1, "Slide 5: Picture", 5],
    ]
    return make_pdf(path, pages, toc)


@pytest.fixture
def course(tmp_course):
    make_course(tmp_course, {"L01": PDF_NAME})
    sample_pdf(tmp_course / "lectures" / PDF_NAME)
    return tmp_course


# ---- 纯函数 ----

@pytest.mark.parametrize("w,h", [(720, 540), (960, 540), (363, 272), (2000, 100), (100, 100)])
def test_render_zoom_respects_limits(w, h):
    z = extract.render_zoom(w, h)
    pw, ph = w * z, h * z
    assert pw * ph <= extract.MAX_PIXELS * 1.001
    assert max(pw, ph) <= extract.MAX_EDGE * 1.001
    # 至少有一个上限被用满，说明没有白白缩小
    assert pw * ph >= extract.MAX_PIXELS * 0.99 or max(pw, ph) >= extract.MAX_EDGE * 0.99


@pytest.mark.parametrize("raw,expected", [
    ("Slide 36: Find sailors rated > 7", "Find sailors rated > 7"),
    ("Slide 35", ""),
    ("slide 3:  Finding answers  in one table", "Finding answers in one table"),
    ("Slide 2：中文标题", "中文标题"),
    ("Introduction", "Introduction"),
    ("Slides and more", "Slides and more"),
])
def test_clean_title(raw, expected):
    assert extract.clean_title(raw) == expected


def test_page_titles_uses_per_page_bookmarks():
    toc = [[1, f"Slide {i}: T{i}", i] for i in range(1, 11)]
    titles, source = extract.page_titles(toc, 10)
    assert source == "bookmarks"
    assert titles == [f"T{i}" for i in range(1, 11)]


def test_page_titles_ignores_section_bookmarks():
    # Beamer 风格：10 页只有 3 个按节的书签，不能当页标题
    toc = [[1, "Intro", 1], [1, "Method", 4], [2, "Details", 6]]
    titles, source = extract.page_titles(toc, 10)
    assert source == "none"
    assert titles == [""] * 10


def test_page_number_only_removed_at_page_edge():
    # 页脚处、数值等于页码：去掉
    assert extract.is_page_number("8", 0.95 * PAGE_H, 0.98 * PAGE_H, PAGE_H, 8)
    # 页面中间的表格数字，即使等于页码也保留
    assert not extract.is_page_number("8", 0.44 * PAGE_H, 0.48 * PAGE_H, PAGE_H, 8)
    # 页脚处但数值不等于页码（比如表格最后一行）：保留
    assert not extract.is_page_number("58", 0.95 * PAGE_H, 0.98 * PAGE_H, PAGE_H, 8)
    assert not extract.is_page_number("8a", 0.95 * PAGE_H, 0.98 * PAGE_H, PAGE_H, 8)


# ---- 整讲处理 ----

def test_extract_lecture_outputs(course):
    summary = extract.extract_lecture(course, "L01")
    assert summary["skipped"] is False
    assert summary["page_count"] == 5
    assert summary["titles_from"] == "bookmarks"
    assert summary["blank_pages"] == [3]

    out = common.lecture_dir(course, "L01")
    data = common.read_json(out / "work" / "pages.json")
    assert data["page_count"] == 5
    assert data["source"] == f"lectures/{PDF_NAME}"
    pages = data["pages"]
    assert [p["page"] for p in pages] == [1, 2, 3, 4, 5]
    assert [p["title"] for p in pages] == ["Intro", "Example Data", "", "", "Picture"]

    # 页码被去掉，页面中间同样是 "2" 的数字保留
    assert pages[1]["text"].splitlines() == ["Table", "2"]

    # 只有真正什么都没画的页才算空白
    assert [p["blank"] for p in pages] == [False, False, True, False, False]

    for p in pages:
        img = out / p["image"]
        assert img.is_file()
        w, h = p["size"]
        assert w * h <= extract.MAX_PIXELS * 1.01 and max(w, h) <= extract.MAX_EDGE
        assert abs(w / h - PAGE_W / PAGE_H) < 0.01

    titles = (out / "work" / "titles.txt").read_text(encoding="utf-8").splitlines()
    assert titles[0].startswith("# L01")
    body = [line for line in titles if not line.startswith("#")]
    assert len(body) == 5
    assert body[1] == "2 | Example Data | Table 2"
    assert body[2] == "3 | （空白页） |"


def test_no_bookmarks_leaves_titles_empty(tmp_course):
    make_course(tmp_course, {"L01": "a.pdf"})
    make_pdf(tmp_course / "lectures" / "a.pdf", [{"texts": [(60, 100, "Hello", 20)]}] * 3)
    summary = extract.extract_lecture(tmp_course, "L01")
    assert summary["titles_from"] == "none"
    data = common.read_json(common.work_dir(tmp_course, "L01") / "pages.json")
    assert all(p["title"] == "" for p in data["pages"])
    assert all(p["text"] == "Hello" for p in data["pages"])


def test_skips_when_up_to_date_and_redoes_when_changed(course):
    assert extract.extract_lecture(course, "L01")["skipped"] is False
    assert extract.extract_lecture(course, "L01")["skipped"] is True
    assert extract.extract_lecture(course, "L01", force=True)["skipped"] is False

    # 课件换成 3 页的新版本：重新处理，旧的多余图片被清掉
    make_pdf(course / "lectures" / PDF_NAME, [{"texts": [(60, 100, "New", 20)]}] * 3)
    summary = extract.extract_lecture(course, "L01")
    assert summary["skipped"] is False and summary["page_count"] == 3
    imgs = sorted(p.name for p in (common.lecture_dir(course, "L01") / "img").glob("*.png"))
    assert imgs == ["p001.png", "p002.png", "p003.png"]


def test_redoes_when_image_missing(course):
    extract.extract_lecture(course, "L01")
    (common.lecture_dir(course, "L01") / "img" / "p002.png").unlink()
    assert extract.extract_lecture(course, "L01")["skipped"] is False


def test_errors(tmp_course):
    with pytest.raises(common.CourseError, match="course.json"):
        extract.extract_lecture(tmp_course, "L01")

    make_course(tmp_course, {"L01": "missing.pdf", "L02": "locked.pdf"})
    with pytest.raises(common.CourseError, match="没有讲次 L09"):
        extract.extract_lecture(tmp_course, "L09")
    with pytest.raises(common.CourseError, match="不存在"):
        extract.extract_lecture(tmp_course, "L01")

    make_pdf(tmp_course / "lectures" / "locked.pdf", [{"texts": [(60, 100, "x", 12)]}], user_pw="secret")
    with pytest.raises(common.CourseError, match="密码"):
        extract.extract_lecture(tmp_course, "L02")


def test_main_cli(course, capsys):
    assert extract.main([str(course)]) == 0
    assert "L01：5 页" in capsys.readouterr().out
    assert extract.main([str(course), "L01"]) == 0
    assert "已是最新" in capsys.readouterr().out
    assert extract.main([str(course), "L09"]) == 1
    assert "没有讲次 L09" in capsys.readouterr().err
