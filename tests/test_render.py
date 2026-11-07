from __future__ import annotations

import re

import pytest

import common
import render
from conftest import make_course


def seg(text, src=None, **extra):
    return {"text": text, "src": src or {"type": "supplement"}, **extra}


def slide(*pages):
    return {"type": "slide", "pages": list(pages)}


# ---- 句子合并 ----

def test_group_segments_merges_same_source():
    runs = render.group_segments([
        seg("第一句。", slide(3)), seg("第二句。", slide(3)),
        seg("补充一。"), seg("补充二。"),
        seg("没把握。", status="unverified"),
        seg("Another sentence.", slide(3)), seg("And more.", slide(3)),
    ])
    assert [r["text"] for r in runs] == ["第一句。第二句。", "补充一。补充二。", "没把握。", "Another sentence. And more."]
    assert [r["unverified"] for r in runs] == [False, False, True, False]


def test_group_segments_tail_and_display():
    runs = render.group_segments([seg("中文句子。"), seg("公式 $$a=b$$", slide(1)), seg("ends with $x$", slide(2))])
    assert (runs[0]["head"], runs[0]["tail"]) == ("中文句子", "。")
    assert runs[1]["display_end"] and runs[1]["tail"] == ""
    assert (runs[2]["head"], runs[2]["tail"]) == ("ends with $x$", "")


# ---- 整讲渲染 ----

def page_entry(no, title=""):
    return {"page": no, "title": title, "text": f"text {no}", "image": f"img/p{no:03d}.png", "size": [1265, 949], "blank": False}


@pytest.fixture
def lecture(tmp_course):
    """L01 共 6 页，3 节：s01 讲第 1–2 页（已写），s02 讲第 3–4 页（还没写），s03 第 5–6 页（第 6 页跳过）。"""
    make_course(tmp_course, {"L01": "a.pdf", "L02": "b.pdf"})
    work = common.work_dir(tmp_course, "L01")
    common.write_json(work / "pages.json", {"page_count": 6, "pages": [page_entry(n, f"Title {n}" if n != 2 else "") for n in range(1, 7)]})
    common.write_json(common.work_dir(tmp_course, "L02") / "pages.json", {"page_count": 20, "pages": []})
    common.write_json(work / "outline.json", {"lecture": "L01", "skip": [6], "sections": [
        {"id": "s01", "title": "第一节（One）", "pages": [1, 2]},
        {"id": "s02", "title": "第二节（Two）", "pages": [3, 4]},
        {"id": "s03", "title": "第三节（Three）", "pages": [5, 6]},
    ]})
    units = [{"id": u, "section": u, "pages": p, "input": f"sections/{u}.input.json", "output": f"sections/{u}.json"}
             for u, p in (("s01", [1, 2]), ("s02", [3, 4]), ("s03", [5]))]
    common.write_json(work / "units.json", {"skip": [6], "units": units})
    for u in units:
        common.write_json(work / u["input"], {"unit": u["id"], "section": {"id": u["section"]},
                                              "output_file": str(work / u["output"]), "pages": [{"page": p} for p in u["pages"]]})
    return tmp_course, work


def full_unit():
    """第 1 页用到所有 block 类型；第 2 页是印着答案的习题。"""
    return {
        "lecture": "L01", "unit": "s01", "section": "s01", "section_summary": "本节小结。",
        "pages": [
            {"page": 1, "kind": "formula", "gist": "第一页概括", "terms": [
                {"term": "selection", "aliases": ["选择"], "kind": "term", "definition": "按条件选行", "page": 1}],
             "blocks": [
                {"kind": "explain", "title": "讲解", "segments": [
                    seg("课件上写的。", slide(1)), seg("同一页的另一句。", slide(1)),
                    seg("<script>alert(1)</script> 要转义。"),
                    seg("之前学过。", {"type": "memory", "lecture": "L02", "page": 15}),
                    seg("没把握。", status="unverified")]},
                {"kind": "derivation", "title": "推导", "steps": [
                    {"math": "\\sigma_{a>1}(R)", "why": "先选出行", "src": slide(1)}]},
                {"kind": "table", "title": "结果", "caption": "自拟数据", "header": ["a", "b"], "rows": [["1", "2"]], "src": {"type": "supplement"}},
                {"kind": "code", "title": "SQL", "lang": "sql", "code": "SELECT * FROM R WHERE a > 1", "src": slide(1)},
                {"kind": "pitfall", "title": "课件可能有误：括号", "segments": [seg("少了一个括号。")]},
             ]},
            {"page": 2, "kind": "exercise", "gist": "习题页", "blocks": [
                {"kind": "exercise", "title": "习题 1", "answer_on_slide": True,
                 "analysis": [seg("题目要找 X。", slide(2))],
                 "hints": [[seg("先想 Y。")], [seg("再想 Z。")]],
                 "solution": [{"kind": "explain", "title": "解答", "segments": [seg("答案是 W。")]}]},
            ]},
        ],
    }


def test_render_full_lecture(lecture):
    course_dir, work = lecture
    common.write_json(work / "sections" / "s01.json", full_unit())
    out, counts = render.render_lecture(course_dir, "L01")
    html = out.read_text(encoding="utf-8")

    assert out == common.lecture_dir(course_dir, "L01") / "index.html"
    assert counts == {"total": 6, "explained": 2, "missing": 3, "skipped": 1, "errors": 0, "unverified": 1}

    # 每一页都有锚点和课件图，三节都在目录里
    for n in range(1, 7):
        assert f'id="p{n}"' in html and f'src="img/p{n:03d}.png"' in html
    for title in ("第一节（One）", "第二节（Two）", "第三节（Three）"):
        assert title in html
    assert "本节小结。" in html
    assert "这一页还没有讲解" in html and "这一页不需要讲解" in html

    # 相同来源的相邻句子合并，只显示一次标签
    assert "课件上写的。同一页的另一句" in html
    # 模型文字一律转义
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # 来源标签
    assert '<a href="#p1" data-page="1">p.1</a>' in html
    assert 'href="../L02/index.html#p15"' in html and "L02 p.15" in html
    assert "⚠ 待核实" in html and "seg-unv" in html
    # 各种 block
    assert 'data-tex="\\sigma_{a&gt;1}(R)"' in html
    assert "<th>a</th>" in html and "<td>1</td>" in html and "自拟数据" in html
    assert '<code class="language-sql">SELECT * FROM R WHERE a &gt; 1</code>' in html
    assert "block-erratum" in html and "勘误" in html
    # 一页超过 3 个 block 时有页内目录
    assert 'class="page-toc"' in html and 'href="#p1-b2"' in html
    # 习题：提示默认隐藏，解答默认隐藏，课件图先遮住
    assert html.count('<li hidden><span class="hint-label">') == 2
    assert '<div class="solution" hidden>' in html
    assert 'class="slides is-hidden"' in html and "这页课件印着答案" in html
    assert 'data-key="lecture-explainer:Test Course:L01:p2-b1"' in html
    # 术语表
    assert "<strong>selection</strong>" in html and "按条件选行" in html
    # 没有书签标题的页在目录里用 gist
    assert ">习题页</span>" in html
    # 目录可以收起
    assert 'id="toggle-toc"' in html and "toc-hidden" in html
    # 依赖固定版本
    assert "katex@0.16.11" in html and "highlight.js/11.9.0" in html


def test_lecture_title(lecture):
    course_dir, work = lecture
    out, _ = render.render_lecture(course_dir, "L01")
    assert "<h1>Title 1</h1>" in out.read_text(encoding="utf-8")       # 没写 title 时用第 1 页的书签
    outline = common.read_json(work / "outline.json")
    outline["title"] = "整讲标题（Lecture Title）"
    common.write_json(work / "outline.json", outline)
    out, _ = render.render_lecture(course_dir, "L01")
    assert "<h1>整讲标题（Lecture Title）</h1>" in out.read_text(encoding="utf-8")


def test_reading_time():
    blocks = [
        {"kind": "explain", "title": "t", "segments": [seg("一" * 300)]},
        {"kind": "exercise", "title": "e", "analysis": [seg("二" * 50)], "hints": [[seg("三" * 50)]],
         "solution": [{"kind": "explain", "title": "s", "segments": [seg("四" * 999)]}]},
    ]
    assert render.reading_chars(blocks) == 400          # 收起的解答不算
    assert render.reading_minutes(700, 8) == 4          # 700 字 2 分钟 + 8 页课件 2 分钟
    assert render.reading_minutes(0, 0) == 1


def test_reading_time_shown(lecture):
    course_dir, work = lecture
    common.write_json(work / "sections" / "s01.json", full_unit())
    out, _ = render.render_lecture(course_dir, "L01")
    html = out.read_text(encoding="utf-8")
    assert "预计阅读约 <strong>1 分钟</strong>" in html and "课件 2 页" in html and "还有 3 页没讲解" in html


def test_range_group_renders_as_one_row(lecture):
    course_dir, work = lecture
    data = full_unit()
    first = data["pages"].pop(0)
    del first["page"]
    first["range"] = [1, 2]                      # 第 1、2 页合在一起讲
    data["pages"] = [first]
    common.write_json(work / "sections" / "s01.json", data)
    _, counts = render.render_lecture(course_dir, "L01")
    html = (common.lecture_dir(course_dir, "L01") / "index.html").read_text(encoding="utf-8")
    assert counts["explained"] == 2
    assert html.count('class="page state-explained multi"') == 1
    assert 'id="p1" data-page="1"' in html and 'id="p2" data-page="2"' in html
    assert "第 1–2 页" in html and ">p.2</span>" in html
    # 目录里两页都单独列出，没有书签标题的第 2 页用这一组的 gist
    assert 'href="#p2" data-page="2" title="第一页概括"' in html


def test_page_level_errors_are_flagged(lecture):
    course_dir, work = lecture
    data = full_unit()
    data["pages"][0]["blocks"][0]["segments"][0]["text"] = "公式 $\\sigma_{a$ 写错了。"
    common.write_json(work / "sections" / "s01.json", data)
    _, counts = render.render_lecture(course_dir, "L01")
    html = (common.lecture_dir(course_dir, "L01") / "index.html").read_text(encoding="utf-8")
    assert counts["errors"] == 1
    assert "这部分讲解没有通过校验" in html and "[E6]" in html
    assert re.search(r'class="toc-page state-explained has-issues" href="#p1"', html)
    # 页级错误不影响内容显示
    assert "第一页概括" in html


def test_structural_errors_hide_unit(lecture):
    course_dir, work = lecture
    data = full_unit()
    del data["pages"][0]["blocks"][0]["segments"][0]["src"]
    common.write_json(work / "sections" / "s01.json", data)
    _, counts = render.render_lecture(course_dir, "L01")
    html = (common.lecture_dir(course_dir, "L01") / "index.html").read_text(encoding="utf-8")
    assert counts["explained"] == 0 and counts["errors"] == 2
    assert "讲解文件格式有误" in html and "[E3]" in html
    assert "第一页概括" not in html


def test_standalone_embeds_images(lecture):
    import pymupdf
    course_dir, work = lecture
    common.write_json(work / "sections" / "s01.json", full_unit())
    img_dir = common.lecture_dir(course_dir, "L01") / "img"
    img_dir.mkdir(parents=True)
    for n in range(1, 7):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.set_rect(pix.irect, (255, 255, 255))
        pix.save(img_dir / f"p{n:03d}.png")

    out, _ = render.render_lecture(course_dir, "L01", standalone=True)
    assert out.name == "L01-standalone.html"
    assert (out.parent / "index.html").is_file()   # 普通版照样生成
    html = out.read_text(encoding="utf-8")
    assert html.count('src="data:image/') == 6
    assert 'src="img/' not in html and 'href="img/' not in html
    # 印着答案的页没有链接时，点击图片本身来显示
    assert 'class="slides is-hidden"' in html


def test_main(lecture, capsys, tmp_path):
    course_dir, work = lecture
    common.write_json(work / "sections" / "s01.json", full_unit())
    assert render.main([str(course_dir), "L01"]) == 0
    out = capsys.readouterr().out
    assert "共 6 页，已讲解 2 页，还没讲解 3 页，跳过 1 页，待核实 1 处" in out

    make_course(tmp_path / "empty", {"L01": "a.pdf"})
    assert render.main([str(tmp_path / "empty"), "L01"]) == 1
    assert "extract.py" in capsys.readouterr().err
