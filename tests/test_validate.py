from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest

import common
import validate
from conftest import make_course

REFERENCES = Path(__file__).resolve().parents[1] / "lecture-explainer" / "references"


def schema_md_example() -> dict:
    """schema.md 里"完整示例"那一段 JSON：文档、schema 和校验规则必须保持一致。"""
    text = (REFERENCES / "schema.md").read_text(encoding="utf-8")
    block = text.split("## 完整示例", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)\n```", block, re.S).group(1))


def seg(text, src=None, **extra):
    return {"text": text, "src": src or {"type": "supplement"}, **extra}


def slide(*pages):
    return {"type": "slide", "pages": list(pages)}


def one_page(kind="text", blocks=None, page=36):
    """只有一页的最小讲解 JSON。"""
    data = schema_md_example()
    data["pages"] = [{"page": page, "kind": kind, "gist": "概括", "blocks": blocks or [
        {"kind": "explain", "title": "t", "segments": [seg("课件上的话。", slide(page)), seg("补充一句。")]}
    ]}]
    return data


@pytest.fixture
def unit(tmp_course):
    """L03 的一个单元 s05，待讲第 35、36、49 页，对应 schema.md 的示例；第 38 页被跳过。"""
    make_course(tmp_course, {"L02": "b.pdf", "L03": "a.pdf"})
    common.write_json(common.work_dir(tmp_course, "L02") / "pages.json", {"page_count": 40, "pages": []})
    work = common.work_dir(tmp_course, "L03")
    common.write_json(work / "pages.json", {"page_count": 58, "pages": []})
    common.write_json(work / "units.json", {"skip": [38, 58], "units": []})
    out = work / "sections" / "s05.json"
    common.write_json(work / "sections" / "s05.input.json", {
        "unit": "s05", "section": {"id": "s05"}, "output_file": str(out),
        "pages": [{"page": 35}, {"page": 36}, {"page": 49}],
    })
    return tmp_course, out


def run(course_dir, data, out, pages=(35, 36, 49)):
    common.write_json(out, data)
    packet_path = out.with_name("s05.input.json")
    packet = common.read_json(packet_path)
    packet["pages"] = [{"page": p} for p in pages]
    common.write_json(packet_path, packet)
    return validate.check_unit(course_dir, "L03", "s05")


def codes(issues):
    return sorted({i["code"] for i in issues})


# ---- schema 和文档示例 ----

def test_schema_is_valid_and_doc_example_passes():
    schema = common.read_json(validate.SECTION_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert validate.schema_issues(schema_md_example()) == []


def test_doc_example_has_no_issues_at_all(unit):
    """文档示例既不能报错，也不能有警告，否则说明规则有误报。"""
    course_dir, out = unit
    assert run(course_dir, schema_md_example(), out) == []
    assert validate.main([str(course_dir), "L03", "--unit", "s05"]) == 0


def test_missing_output(unit):
    course_dir, _ = unit
    issues = validate.check_unit(course_dir, "L03", "s05")
    assert codes(issues) == ["E2"] and "还没有写出" in issues[0]["msg"]


def test_invalid_json(unit):
    course_dir, out = unit
    out.write_text("{oops", encoding="utf-8")
    assert codes(validate.check_unit(course_dir, "L03", "s05")) == ["E1"]


# ---- E1 / E3 / E8：格式 ----

def test_missing_src_is_e3_with_page(unit):
    course_dir, out = unit
    data = schema_md_example()
    del data["pages"][0]["blocks"][0]["segments"][1]["src"]
    issues = run(course_dir, data, out)
    assert len(issues) == 1
    assert issues[0]["code"] == "E3" and issues[0]["page"] == 35
    assert "'src' is a required property" in issues[0]["msg"]


@pytest.mark.parametrize("mutate,code,expect", [
    (lambda d: d["pages"][0]["blocks"].append({"kind": "table", "title": "t", "header": ["a"], "rows": []}), "E3", "'src' is a required property"),
    (lambda d: d["pages"][0]["blocks"][0]["segments"][0].update(src={"type": "slide"}), "E1", "'pages' is a required property"),
    (lambda d: d["pages"][0]["blocks"][0]["segments"][0].update(src={"type": "web"}), "E1", "'web' is not one of"),
    (lambda d: d["pages"][0].update(kind="chart"), "E1", "'chart' is not one of"),
    (lambda d: d["pages"][1]["blocks"][0]["solution"].append(copy.deepcopy(d["pages"][1]["blocks"][0])), "E8", "should not be valid"),
    (lambda d: d["pages"][1]["blocks"][0].update(hints=[]), "E8", "should be non-empty"),
    (lambda d: d["pages"][1]["blocks"][0].pop("solution"), "E8", "'solution' is a required property"),
    (lambda d: d["pages"][0]["blocks"][0]["segments"][0].update(status="maybe"), "E1", "'unverified' was expected"),
])
def test_schema_errors(unit, mutate, code, expect):
    course_dir, out = unit
    data = schema_md_example()
    mutate(data)
    issues = run(course_dir, data, out)
    assert any(i["code"] == code and expect in i["msg"] for i in issues), issues


# ---- E2：覆盖 ----

def test_page_set_and_ids(unit):
    course_dir, out = unit
    data = schema_md_example()
    data["pages"] = data["pages"][:1]
    data["unit"] = "s04"
    msgs = [i["msg"] for i in run(course_dir, data, out)]
    assert any("缺少 [49]" in m for m in msgs)
    assert any("unit 应为 s05" in m for m in msgs)

    data = schema_md_example()
    data["pages"].reverse()
    assert any("顺序应为 [35, 36, 49]" in i["msg"] for i in run(course_dir, data, out))


# ---- E4 / E5：页码 ----

def test_slide_page_out_of_range(unit, capsys):
    course_dir, out = unit
    data = schema_md_example()
    data["pages"][1]["blocks"][0]["analysis"][0]["src"]["pages"] = [20, 99]
    issues = run(course_dir, data, out)
    assert [(i["code"], i["page"]) for i in issues] == [("E4", 49)]
    assert validate.main([str(course_dir), "L03", "--unit", "s05"]) == 1
    captured = capsys.readouterr()
    assert "1 处错误" in captured.out and "[E4] 第 49 页" in captured.err


@pytest.mark.parametrize("src,ok", [
    ({"type": "memory", "lecture": "L02", "page": 15}, True),
    ({"type": "memory", "lecture": "L09", "page": 15}, False),
    ({"type": "memory", "lecture": "L02", "page": 41}, False),
])
def test_memory_references(unit, src, ok):
    course_dir, out = unit
    data = one_page(blocks=[{"kind": "explain", "title": "t", "segments": [seg("之前讲过。", src), seg("课件。", slide(36))]}])
    issues = run(course_dir, data, out, pages=(36,))
    assert codes(issues) == ([] if ok else ["E5"])


# ---- E6：数学定界符 ----

@pytest.mark.parametrize("text,errors,regions", [
    ("a $x$ b", [], ["x"]),
    ("a $$x^2$$ b $y$", [], ["x^2", "y"]),
    ("价格是 \\$5，不是公式", [], []),
    ("$\\{a, b\\}$", [], ["\\{a, b\\}"]),
    ("$x", ["$ 没有配对"], []),
    ("$$x$", ["$$ 没有配对"], []),
])
def test_math_regions(text, errors, regions):
    got_regions, got_errors = validate.math_regions(text)
    assert got_errors == errors and got_regions == regions


@pytest.mark.parametrize("math,expect", [
    ("\\sigma_{rating>7}(S)", []),
    ("\\sigma_{rating>7(S)", ["少了 1 个 }"]),
    ("a}", ["多了一个 }"]),
    ("\\begin{aligned} a \\\\ b \\end{aligned}", []),
    ("\\begin{aligned} a", ["\\begin{aligned} 没有对应的 \\end"]),
    ("a \\end{cases}", ["\\end{cases} 没有对应的 \\begin"]),
])
def test_latex_issues(math, expect):
    assert validate.latex_issues(math) == expect


def table_block(rows, header=("sid", "sname", "rating", "age")):
    return {"kind": "table", "title": "示例表", "header": list(header), "rows": rows, "src": {"type": "supplement"}}


def test_math_errors_reported_per_field(unit):
    course_dir, out = unit
    data = schema_md_example()
    data["pages"][0]["blocks"][0]["segments"][0]["text"] = "这里 $\\sigma_{a$ 写错了。"
    data["pages"][0]["blocks"][1]["steps"][0]["math"] = "$\\sigma$"
    data["pages"][0]["blocks"].append(table_block([["$28", "yuppy", "9", "35.0"]]))
    msgs = [i["msg"] for i in run(course_dir, data, out) if i["code"] == "E6"]
    assert any(m.startswith("segment里") and "少了 1 个 }" in m for m in msgs)
    assert any(m.startswith("推导式子里不要写 $") for m in msgs)
    assert any(m.startswith("表格单元格里$ 没有配对") for m in msgs)


# ---- E7：表格 ----

def test_table_row_width(unit):
    course_dir, out = unit
    data = schema_md_example()
    data["pages"][0]["blocks"].append(table_block([["28", "yuppy", "9", "35.0"], ["31", "lubber", "8"]]))
    issues = run(course_dir, data, out)
    assert [(i["code"], i["page"]) for i in issues] == [("E7", 35)]
    assert "第 2 行有 3 列，表头有 4 列" in issues[0]["msg"]


# ---- 讲解组：几页合讲 ----

def test_range_groups(unit):
    course_dir, out = unit
    # 文档示例本身就是 [35, 36] 合讲加第 49 页单讲，前面已验证无错误；这里测错误情况
    data = schema_md_example()
    data["pages"][0]["range"] = [35, 37]                 # 第 37 页不属于本单元
    assert any("多出 [37]" in i["msg"] for i in run(course_dir, data, out))

    data = schema_md_example()
    data["pages"][0]["range"] = [36, 35]
    issues = run(course_dir, data, out)
    assert any(i["code"] == "E2" and "第一页大于最后一页" in i["msg"] for i in issues)

    data = schema_md_example()
    data["pages"][0]["page"] = 35                         # page 和 range 只能有一个
    assert codes(run(course_dir, data, out)) == ["E1"]


def test_w9_long_group(unit):
    course_dir, out = unit
    long_text = "这是一句很长的补充说明，" * 40 + "。"
    blocks = [{"kind": "explain", "title": "t", "segments": [seg("课件。", slide(36))] + [seg(long_text)] * 2}]
    issues = run(course_dir, one_page(blocks=blocks), out, pages=(36,))
    assert "W9" in codes(issues)
    # 习题不受篇幅限制
    data = schema_md_example()
    data["pages"][1]["blocks"][0]["solution"][0]["steps"][0]["why"] = long_text * 2
    assert "W9" not in codes(run(course_dir, data, out))


def test_w10_large_group(unit):
    course_dir, out = unit
    data = one_page()
    del data["pages"][0]["page"]
    data["pages"][0]["range"] = [30, 34]
    issues = run(course_dir, data, out, pages=(30, 31, 32, 33, 34))
    assert codes(issues) == ["W10"] and "合并了 5 页" in issues[0]["msg"]


# ---- 警告 ----

def test_w1_page_mentioned_but_not_cited(unit):
    course_dir, out = unit
    data = one_page(blocks=[{"kind": "explain", "title": "t", "segments": [
        seg("示例数据在第 8 页。", slide(36)),          # 说第 8 页却标第 36 页：警告
        seg("第 8 页的表。", slide(8)),                 # 一致：不警告
        seg("下一页（第 37 页）会讲 TRC。"),             # 补充里提到页码：不警告
        seg("见 p.36 和 p.12。", slide(36)),            # 英文写法也识别
    ]}])
    issues = [i for i in run(course_dir, data, out, pages=(36,)) if i["code"] == "W1"]
    assert len(issues) == 2
    assert "第 [8] 页" in issues[0]["msg"] and "第 [12] 页" in issues[1]["msg"]


def test_w1_cites_skipped_page(unit):
    course_dir, out = unit
    data = one_page(blocks=[{"kind": "explain", "title": "t", "segments": [seg("见第 38 页。", slide(38)), seg("课件。", slide(36))]}])
    issues = run(course_dir, data, out, pages=(36,))
    assert codes(issues) == ["W1"] and "被跳过" in issues[0]["msg"]


def test_w2_too_much_supplement(unit):
    course_dir, out = unit
    blocks = [{"kind": "explain", "title": "t", "segments": [seg(f"补充 {i}。") for i in range(10)] + [seg("课件。", slide(36))]}]
    assert codes(run(course_dir, one_page(blocks=blocks), out, pages=(36,))) == ["W2"]
    # 习题页、分隔页不检查
    assert codes(run(course_dir, one_page(kind="divider", blocks=blocks), out, pages=(36,))) == []


def test_w3_long_segment(unit):
    course_dir, out = unit
    blocks = [{"kind": "explain", "title": "t", "segments": [
        seg("第一句。第二句。第三句。", slide(36)),
        seg("数值 3.5 和 $a.b$ 不算句号。只有两句。"),
    ]}]
    issues = run(course_dir, one_page(blocks=blocks), out, pages=(36,))
    assert [i["code"] for i in issues] == ["W3"] and "第一句" in issues[0]["msg"]


def test_w4_short_visual_page(unit):
    course_dir, out = unit
    assert codes(run(course_dir, one_page(kind="formula"), out, pages=(36,))) == ["W4"]
    assert codes(run(course_dir, one_page(kind="text"), out, pages=(36,))) == []


def test_w6_hint_leaks_answer(unit):
    course_dir, out = unit
    data = schema_md_example()
    answer = data["pages"][1]["blocks"][0]["solution"][0]["steps"][-1]["math"]
    data["pages"][1]["blocks"][0]["hints"].append([seg(f"答案就是 ${answer}$。")])
    issues = run(course_dir, data, out)
    assert codes(issues) == ["W6"] and issues[0]["page"] == 49


def test_w7_chinese_in_math(unit):
    course_dir, out = unit
    blocks = [{"kind": "explain", "title": "t", "segments": [
        seg("价格 $5 和 $6 元。", slide(36)),               # 美元符号没转义：公式里出现中文
        seg("条件 $\\text{颜色} = red$ 没问题。"),
    ]}]
    issues = run(course_dir, one_page(blocks=blocks), out, pages=(36,))
    assert codes(issues) == ["W7"] and "5 和" in issues[0]["msg"]


# ---- 整讲检查 ----

@pytest.fixture
def lecture(tmp_course):
    """L01 有两个单元：s01 讲第 1–2 页，s02 讲第 3 页。"""
    make_course(tmp_course, {"L01": "a.pdf"})
    work = common.work_dir(tmp_course, "L01")
    common.write_json(work / "pages.json", {"page_count": 4, "pages": []})
    units = []
    for uid, pages in (("s01", [1, 2]), ("s02", [3])):
        units.append({"id": uid, "section": uid, "pages": pages,
                      "input": f"sections/{uid}.input.json", "output": f"sections/{uid}.json"})
        common.write_json(work / "sections" / f"{uid}.input.json", {
            "unit": uid, "section": {"id": uid}, "output_file": str(work / "sections" / f"{uid}.json"),
            "pages": [{"page": p} for p in pages],
        })
    common.write_json(work / "units.json", {"skip": [4], "units": units})
    return tmp_course, work


def write_unit(work, uid, pages):
    common.write_json(work / "sections" / f"{uid}.json", {
        "lecture": "L01", "unit": uid, "section": uid, "section_summary": "小结",
        "pages": [{"page": p, "kind": "text", "gist": "g", "blocks": [
            {"kind": "explain", "title": "t", "segments": [seg("课件。", slide(p))]}]} for p in pages],
    })


def test_lecture_report(lecture, capsys):
    course_dir, work = lecture
    write_unit(work, "s01", [1, 2])
    (work / "sections" / "s09.json").write_text("{}", encoding="utf-8")

    assert validate.main([str(course_dir), "L01"]) == 1
    report = common.read_json(work / "validate_report.json")
    assert [(u["id"], u["status"]) for u in report["units"]] == [("s01", "ok"), ("s02", "missing")]
    assert report["coverage"] == {"pages_to_explain": 3, "pages_passed": 2, "skip": [4]}
    assert report["errors"] == 1 and report["warnings"] == 1
    assert {i["code"] for i in report["issues"]} == {"E2", "W8"}
    out = capsys.readouterr().out
    assert "通过 1，有错误 0，未完成 1" in out and "已通过的页 2/3" in out

    write_unit(work, "s02", [3])
    (work / "sections" / "s09.json").unlink()
    assert validate.main([str(course_dir), "L01"]) == 0
    report = common.read_json(work / "validate_report.json")
    assert report["errors"] == 0 and report["warnings"] == 0
    assert report["coverage"]["pages_passed"] == 3


def test_lecture_needs_units(tmp_course, capsys):
    make_course(tmp_course, {"L01": "a.pdf"})
    assert validate.main([str(tmp_course), "L01"]) == 1
    assert "prepare.py" in capsys.readouterr().err
