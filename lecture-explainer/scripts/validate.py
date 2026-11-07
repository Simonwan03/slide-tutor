"""阶段 5a：讲解 JSON 的代码检查。

错误（必须修好）：
    E1 格式不符合 section.schema.json，或 lecture / unit / section 和输入包不一致
    E2 页面覆盖不对：单元里的页和输入包要求的不一致；整讲检查时还有单元没写
    E3 缺少来源（segment、推导步骤、表格、代码没有 src）
    E4 slide 引用的页码超出本讲页数
    E5 memory 引用的讲次或页码不存在
    E6 数学定界符不配对（$、$$、花括号、\\begin…\\end）
    E7 表格某一行的列数和表头不一致
    E8 习题结构不完整（没有提示或没有解答）
警告（不影响通过，值得看一眼）：
    W1 来源页码可能引错：句子里写的"第 N 页"不在来源页码里，或引用了被跳过的页
    W2 某页补充内容占比过高（习题页、分隔页除外）
    W3 一个 segment 超过两句话
    W4 公式、表格、示意图的讲解太短
    W5 新术语已经在课程记忆里（M6 实现）
    W6 习题提示里出现了解答的最终式子或代码，可能泄露答案
    W7 公式里有中文，可能是美元符号没转义，或中文应该放进 \\text{}
    W8 sections/ 里有不在 units.json 中的旧讲解文件（重新切节后留下的）
    W9 一组讲解太长，只讲重点（习题、分隔页除外）
    W10 一组合并了太多页

用法：
    python validate.py <课程目录> <讲次> --unit s03    检查一个单元，只打印结果
    python validate.py <课程目录> <讲次>               检查整讲，并写 work/validate_report.json
没有错误时退出码 0，有错误时退出码 1。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import jsonschema

import common

SECTION_SCHEMA = Path(__file__).resolve().parent / "schema" / "section.schema.json"

MAX_SUPPLEMENT_RATIO = 0.9      # W2
MAX_SENTENCES = 2               # W3
MIN_VISUAL_PAGE_CHARS = 80      # W4：只讲重点以后，公式、表格、示意图也至少要有几句话
MAX_GROUP_CHARS = 900           # W9：指南要求一组通常 100–400 字，难点 600 字左右
MAX_GROUP_PAGES = 4             # W10
MIN_LEAK_LENGTH = 8             # W6：太短的式子不算泄露

TEXT_BLOCK_KINDS = {"explain", "figure", "example", "pitfall"}
VISUAL_PAGE_KINDS = {"formula", "table", "figure"}
NO_RATIO_PAGE_KINDS = {"exercise", "divider"}
PAGE_MENTION = re.compile(r"第\s*(\d{1,4})\s*页|\bp\.\s*(\d{1,4})")
CJK = re.compile(r"[\u4e00-\u9fff]")
TEXT_COMMAND = re.compile(r"\\(?:text|mathrm|textbf|textit|operatorname)\{[^{}]*\}")
ENV = re.compile(r"\\(begin|end)\{([^{}]*)\}")
SENTENCE_END = re.compile(r"[。！？]|[.!?](?=\s+[A-Z\u4e00-\u9fff]|\s*$)")


def issue(code: str, msg: str, page: int | None = None, level: str | None = None) -> dict:
    return {"page": page, "code": code, "level": level or ("error" if code.startswith("E") else "warn"), "msg": msg}


# ---- E1 / E3 / E8：格式 ----

def schema_issues(data: Any) -> list[dict]:
    validator = jsonschema.Draft202012Validator(common.read_json(SECTION_SCHEMA))
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path))):
        path = list(err.absolute_path)
        page = None
        if len(path) >= 2 and path[0] == "pages" and isinstance(data, dict):
            try:
                pages = common.entry_pages(data["pages"][path[1]])
                page = pages[0] if pages else None
            except (IndexError, AttributeError, KeyError, TypeError, ValueError):
                page = None
        where = "/".join(map(str, path)) or "根"
        code = "E1"
        if err.validator == "required" and "'src'" in err.message:
            code = "E3"
        elif {"hints", "solution"} & set(map(str, path)) or (
                err.validator == "required" and ("'hints'" in err.message or "'solution'" in err.message)):
            code = "E8"
        out.append(issue(code, f"格式错误（位置 {where}）：{err.message}", page))
    return out


# ---- 遍历讲解内容 ----

def walk(node: Any) -> Iterator[dict]:
    """深度优先列出所有 dict。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def text_fields(page: dict) -> Iterator[tuple[str, str, bool]]:
    """列出一页里所有会显示出来的文字：(位置说明, 文字, 是否整段都是公式)。代码块不算。"""
    yield "gist", page["gist"], False
    for node in walk(page["blocks"]):
        if "title" in node and isinstance(node["title"], str):
            yield "小标题", node["title"], False
        if "text" in node and isinstance(node["text"], str):
            yield "segment", node["text"], False
        if "math" in node and isinstance(node["math"], str):
            yield "推导式子", node["math"], True
        if "why" in node and isinstance(node["why"], str):
            yield "推导说明", node["why"], False
        if "caption" in node and isinstance(node["caption"], str):
            yield "表格说明", node["caption"], False
        if "header" in node and isinstance(node["header"], list):
            for cell in node["header"]:
                yield "表头", cell, False
            for row in node.get("rows", []):
                for cell in row:
                    yield "表格单元格", cell, False


def segment_like(page: dict) -> Iterator[dict]:
    """所有带 src 的节点（segment、推导步骤、表格、代码）。"""
    for node in walk(page["blocks"]):
        if isinstance(node.get("src"), dict):
            yield node


# ---- E6：数学定界符 ----

def math_regions(text: str) -> tuple[list[str], list[str]]:
    """找出文字里的 $…$ 和 $$…$$，返回 (公式内容列表, 错误列表)。\\$ 是普通美元符号。"""
    regions, errors = [], []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c != "$":
            i += 1
            continue
        delim = "$$" if text.startswith("$$", i) else "$"
        start = j = i + len(delim)
        while j < n and not text.startswith(delim, j):
            j += 2 if text[j] == "\\" else 1
        if j >= n:
            errors.append(f"{delim} 没有配对")
            return regions, errors
        regions.append(text[start:j])
        i = j + len(delim)
    return regions, errors


def latex_issues(math: str) -> list[str]:
    """检查一段公式里的花括号和 \\begin…\\end 是否配对。"""
    errors, envs = [], []
    depth, i = 0, 0
    while i < len(math):
        c = math[i]
        if c == "\\":
            m = ENV.match(math, i)
            if m:
                if m.group(1) == "begin":
                    envs.append(m.group(2))
                elif not envs or envs[-1] != m.group(2):
                    errors.append(f"\\end{{{m.group(2)}}} 没有对应的 \\begin")
                else:
                    envs.pop()
                i = m.end()
            else:
                i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                errors.append("多了一个 }")
                depth = 0
        i += 1
    if depth > 0:
        errors.append(f"少了 {depth} 个 }}")
    for env in envs:
        errors.append(f"\\begin{{{env}}} 没有对应的 \\end")
    return errors


def math_issues(text: str, whole_is_math: bool) -> tuple[list[str], list[str]]:
    """返回 (错误, 公式内容列表)。"""
    if whole_is_math:
        errors = latex_issues(text)
        if re.search(r"(?<!\\)\$", text):
            errors.append("不要写 $，直接写 LaTeX")
        return errors, [text]
    regions, errors = math_regions(text)
    for region in regions:
        errors.extend(latex_issues(region))
    return errors, regions


def short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"


# ---- 单页检查 ----

def visible_chars(page: dict) -> int:
    total = 0
    for node in walk(page["blocks"]):
        for key in ("text", "why", "caption"):
            if isinstance(node.get(key), str):
                total += len(node[key])
    return total


def sentence_count(text: str) -> int:
    regions, _ = math_regions(text)
    for region in regions:
        text = text.replace(region, "")
    return len(SENTENCE_END.findall(text.strip()))


def normalize_answer(text: str) -> str:
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg|,|;|!|quad|qquad)", "", text)
    return re.sub(r"[\s${}]", "", text).lower()


def leak_issues(page: dict) -> list[dict]:
    out = []
    for node in walk(page["blocks"]):
        if node.get("kind") != "exercise" or "hints" not in node:
            continue
        hint_text = normalize_answer(" ".join(seg["text"] for hint in node["hints"] for seg in hint))
        answers = []
        for block in node["solution"]:
            if block.get("kind") == "derivation" and block.get("steps"):
                answers.append(block["steps"][-1]["math"])
            elif block.get("kind") == "code":
                answers.append(block["code"])
        for answer in answers:
            norm = normalize_answer(answer)
            if len(norm) >= MIN_LEAK_LENGTH and norm in hint_text:
                out.append(issue("W6", f"「{short(node['title'])}」的提示里出现了解答的最终结果：{short(answer)}",
                                 first_page(page)))
    return out


def first_page(entry: dict) -> int | None:
    pages = common.entry_pages(entry)
    return pages[0] if pages else None


def mentioned_pages(text: str) -> set[int]:
    return {int(a or b) for a, b in PAGE_MENTION.findall(text)}


def page_issues(page: dict, page_count: int, course: dict, course_dir: Path,
                skip: frozenset[int] = frozenset()) -> list[dict]:
    """检查一个讲解组（单页或几页合讲）。"""
    no = first_page(page)
    out: list[dict] = []

    for node in segment_like(page):
        src = node["src"]
        label = short(node.get("text") or node.get("why") or node.get("title", ""))
        if src["type"] == "slide":
            bad = [p for p in src["pages"] if p > page_count]
            if bad:
                out.append(issue("E4", f"引用的页码 {bad} 超过本讲总页数 {page_count}", no))
            skipped = [p for p in src["pages"] if p in skip]
            if skipped:
                out.append(issue("W1", f"引用了被跳过的第 {skipped} 页（如 Questions 页），请确认没有引错：{label}", no))
            said = mentioned_pages(node.get("text") or node.get("why") or "") - set(src["pages"])
            if said:
                out.append(issue("W1", f"句子里提到第 {sorted(said)} 页，来源却标的是 {src['pages']}，请确认没有引错：{label}", no))
        elif src["type"] == "memory":
            out.extend(memory_issues(src, no, course, course_dir))
        if node.get("text") and sentence_count(node["text"]) > MAX_SENTENCES:
            out.append(issue("W3", f"一个 segment 超过 {MAX_SENTENCES} 句话，请拆开：{short(node['text'])}", no))

    for where, text, whole in text_fields(page):
        errors, regions = math_issues(text, whole)
        for err in errors:
            out.append(issue("E6", f"{where}里{err}：{short(text)}", no))
        for region in regions:
            if CJK.search(TEXT_COMMAND.sub("", region)):
                out.append(issue("W7", f"{where}的公式里有中文，可能是 $ 没转义，或中文应放进 \\text{{}}：{short(region)}", no))

    for node in walk(page["blocks"]):
        if node.get("kind") == "table" and "header" in node:
            width = len(node["header"])
            for r, row in enumerate(node["rows"], 1):
                if len(row) != width:
                    out.append(issue("E7", f"表格「{short(node['title'])}」第 {r} 行有 {len(row)} 列，表头有 {width} 列", no))

    if page["kind"] not in NO_RATIO_PAGE_KINDS:
        kinds = Counter(node["src"]["type"] for node in segment_like(page))
        total = kinds["slide"] + kinds["supplement"]
        if total >= 3 and kinds["supplement"] / total > MAX_SUPPLEMENT_RATIO:
            out.append(issue("W2", f"补充内容占 {kinds['supplement'] / total:.0%}，请确认课件内容都讲到了", no))

    chars = visible_chars(page)
    if page["kind"] in VISUAL_PAGE_KINDS and chars < MIN_VISUAL_PAGE_CHARS:
        out.append(issue("W4", f"{page['kind']} 的讲解只有 {chars} 字，可能讲得太简略", no))
    if page["kind"] not in NO_RATIO_PAGE_KINDS and chars > MAX_GROUP_CHARS:
        out.append(issue("W9", f"{common.entry_label(page)}的讲解有 {chars} 字，超过 {MAX_GROUP_CHARS} 字；只讲重点，删掉复述和细枝末节", no))
    group_size = len(common.entry_pages(page))
    if group_size > MAX_GROUP_PAGES:
        out.append(issue("W10", f"{common.entry_label(page)}合并了 {group_size} 页，一组最多 {MAX_GROUP_PAGES} 页", no))

    out.extend(leak_issues(page))
    return out


def memory_issues(src: dict, page_no: int, course: dict, course_dir: Path) -> list[dict]:
    lecture = src["lecture"]
    if lecture not in common.lecture_ids(course):
        return [issue("E5", f"引用的讲次 {lecture} 不在 course.json 里", page_no)]
    pages_path = common.work_dir(course_dir, lecture) / "pages.json"
    if pages_path.is_file():
        count = common.read_json(pages_path)["page_count"]
        if src["page"] > count:
            return [issue("E5", f"引用的 {lecture} 第 {src['page']} 页超过该讲总页数 {count}", page_no)]
    return []


# ---- 单元检查 ----

def check_unit(course_dir: Path, lecture_id: str, unit_id: str) -> list[dict]:
    course = common.load_course(course_dir)
    work = common.work_dir(course_dir, lecture_id)
    packet_path = work / "sections" / f"{unit_id}.input.json"
    if not packet_path.is_file():
        raise common.CourseError(f"找不到输入包 {packet_path}，请先运行 prepare.py")
    packet = common.read_json(packet_path)
    out_path = Path(packet["output_file"])
    if not out_path.is_file():
        return [issue("E2", f"还没有写出讲解文件 {out_path}")]
    try:
        data = common.read_json(out_path)
    except ValueError as e:
        return [issue("E1", f"不是合法的 JSON：{e}")]

    issues = schema_issues(data)
    if issues:
        return issues

    for field, expected in (("lecture", lecture_id), ("unit", unit_id), ("section", packet["section"]["id"])):
        if data[field] != expected:
            issues.append(issue("E1", f"{field} 应为 {expected}，现在是 {data[field]}"))

    expected_pages = [p["page"] for p in packet["pages"]]
    got_pages = []
    for entry in data["pages"]:
        if "range" in entry and entry["range"][0] > entry["range"][1]:
            issues.append(issue("E2", f"range {entry['range']} 的第一页大于最后一页", entry["range"][0]))
        got_pages.extend(common.entry_pages(entry))
    if got_pages != expected_pages:
        missing = [p for p in expected_pages if p not in got_pages]
        extra = [p for p in got_pages if p not in expected_pages]
        dup = sorted({p for p in got_pages if got_pages.count(p) > 1})
        parts = []
        if missing:
            parts.append(f"缺少 {missing}")
        if extra:
            parts.append(f"多出 {extra}（一组只能包含本单元里连续的页，不能包含被跳过的页）")
        if dup:
            parts.append(f"重复 {dup}")
        if not parts:
            parts.append(f"顺序应为 {expected_pages}")
        issues.append(issue("E2", "页面和输入包不一致：" + "，".join(parts)))

    page_count = common.read_json(work / "pages.json")["page_count"]
    units_path = work / "units.json"
    skip = frozenset(common.read_json(units_path).get("skip", [])) if units_path.is_file() else frozenset()
    for page in data["pages"]:
        issues.extend(page_issues(page, page_count, course, course_dir, skip))
    return issues


# ---- 整讲检查 ----

def check_lecture(course_dir: Path, lecture_id: str) -> dict:
    work = common.work_dir(course_dir, lecture_id)
    units_path = work / "units.json"
    if not units_path.is_file():
        raise common.CourseError(f"找不到 {units_path}，请先运行 prepare.py")
    units_data = common.read_json(units_path)
    units = units_data["units"]

    report_units, issues = [], []
    to_explain = explained = 0
    for unit in units:
        to_explain += len(unit["pages"])
        unit_issues = check_unit(course_dir, lecture_id, unit["id"])
        for i in unit_issues:
            i["unit"] = unit["id"]
        issues.extend(unit_issues)
        errors = sum(1 for i in unit_issues if i["level"] == "error")
        missing = any(i["code"] == "E2" and "还没有写出" in i["msg"] for i in unit_issues)
        if not errors:
            explained += len(unit["pages"])
        report_units.append({
            "id": unit["id"],
            "pages": unit["pages"],
            "status": "missing" if missing else ("error" if errors else "ok"),
            "errors": errors,
            "warnings": sum(1 for i in unit_issues if i["level"] == "warn"),
        })

    known = {f"{u['id']}.json" for u in units} | {f"{u['id']}.input.json" for u in units}
    for path in sorted((work / "sections").glob("*.json")):
        if path.name not in known:
            issues.append({**issue("W8", f"sections/{path.name} 不属于当前的任何讲解单元，可能是重新切节后留下的旧文件"), "unit": None})

    return {
        "lecture": lecture_id,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": {"pages_to_explain": to_explain, "pages_passed": explained, "skip": units_data.get("skip", [])},
        "units": report_units,
        "errors": sum(1 for i in issues if i["level"] == "error"),
        "warnings": sum(1 for i in issues if i["level"] == "warn"),
        "issues": issues,
    }


# ---- 输出 ----

def print_issues(issues: list[dict], limit: int = 30) -> None:
    errors = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    for title, group, stream in (("错误", errors, sys.stderr), ("警告（不影响通过）", warns, sys.stdout)):
        if not group:
            continue
        sys.stdout.flush()
        print(f"{title} {len(group)} 处：", file=stream)
        for i in group[:limit]:
            where = f"第 {i['page']} 页 " if i.get("page") else ""
            unit = f"{i['unit']} " if i.get("unit") else ""
            print(f"  [{i['code']}] {unit}{where}{i['msg']}", file=stream)
        if len(group) > limit:
            print(f"  ……另有 {len(group) - limit} 处", file=stream)
        stream.flush()


def main(argv: list[str] | None = None) -> int:
    common.setup_stdio()
    parser = argparse.ArgumentParser(description="检查讲解 JSON")
    parser.add_argument("course_dir", type=Path)
    parser.add_argument("lecture")
    parser.add_argument("--unit", help="只检查这个讲解单元，如 s03 或 s02-1；不写则检查整讲并写报告")
    args = parser.parse_args(argv)
    try:
        if args.unit:
            issues = check_unit(args.course_dir, args.lecture, args.unit)
            errors = sum(1 for i in issues if i["level"] == "error")
            print(f"{args.lecture} {args.unit}：{'通过' if not errors else f'{errors} 处错误'}")
            print_issues(issues)
            return 1 if errors else 0
        report = check_lecture(args.course_dir, args.lecture)
    except common.CourseError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    common.write_json(common.work_dir(args.course_dir, args.lecture) / "validate_report.json", report)
    cov = report["coverage"]
    status = Counter(u["status"] for u in report["units"])
    print(f"{args.lecture}：{len(report['units'])} 个单元，通过 {status['ok']}，有错误 {status['error']}，未完成 {status['missing']}；"
          f"已通过的页 {cov['pages_passed']}/{cov['pages_to_explain']}；错误 {report['errors']}，警告 {report['warnings']}")
    print_issues(report["issues"])
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
