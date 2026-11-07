"""阶段 2 的校验 + 阶段 3：校验模型写的 outline.json，切块，生成每个讲解单元的输入包。

讲解单元是一节，或者一节里的一块：超过 MAX_UNIT_PAGES 页（不算跳过的页）的节会被平均切成几块。
处理一个单元的模型只需要读它的输入包和其中列出的图片。

用法：
    python prepare.py <课程目录> <讲次>               校验大纲，生成 units.json 和全部输入包
    python prepare.py <课程目录> <讲次> --unit s02-2   只重新生成某个单元的输入包（带上最新的上一单元小结）

输出到 <课程目录>/output/<讲次>/work/：
    units.json                     讲解单元列表，按讲解顺序
    sections/<单元>.input.json      每个单元的输入包
大纲有问题时逐条列出错误并以退出码 1 结束，什么都不写。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import jsonschema

import common

MAX_UNIT_PAGES = 10

SCRIPTS_DIR = Path(__file__).resolve().parent
REFERENCES_DIR = SCRIPTS_DIR.parent / "references"
OUTLINE_SCHEMA = SCRIPTS_DIR / "schema" / "outline.schema.json"
READ_FIRST = ["explain-guide.md", "schema.md"]


# ---- 大纲校验 ----

def check_outline(outline: dict, lecture_id: str, page_count: int) -> list[str]:
    """返回错误列表（中文，可以直接给模型看）；空列表表示通过。"""
    schema = common.read_json(OUTLINE_SCHEMA)
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(outline), key=lambda e: list(e.absolute_path))
    if schema_errors:
        return [f"格式错误（位置 {'/'.join(map(str, e.absolute_path)) or '根'}）：{e.message}" for e in schema_errors]

    errors: list[str] = []
    if outline["lecture"] != lecture_id:
        errors.append(f"lecture 应为 {lecture_id}，现在是 {outline['lecture']}")

    sections = outline["sections"]
    expected_next = 1
    for i, sec in enumerate(sections, 1):
        sid, (start, end) = sec["id"], sec["pages"]
        if sid != f"s{i:02d}":
            errors.append(f"第 {i} 节的 id 应为 s{i:02d}，现在是 {sid}")
        if start > end:
            errors.append(f"{sid} 的起始页 {start} 大于结束页 {end}")
        if start != expected_next:
            if start > expected_next:
                errors.append(f"第 {expected_next}–{start - 1} 页不在任何一节里（{sid} 从第 {start} 页开始）")
            else:
                errors.append(f"{sid} 从第 {start} 页开始，和前一节重叠（前一节到第 {expected_next - 1} 页）")
        if end > page_count:
            errors.append(f"{sid} 的结束页 {end} 超过总页数 {page_count}")
        expected_next = end + 1
    if sections and expected_next - 1 < page_count:
        errors.append(f"最后一节只到第 {expected_next - 1} 页，应覆盖到最后一页 {page_count}")

    bad_skip = [p for p in outline["skip"] if p > page_count]
    if bad_skip:
        errors.append(f"skip 里的页码超过总页数 {page_count}：{bad_skip}")

    if not errors:
        skip = set(outline["skip"])
        for sec in sections:
            start, end = sec["pages"]
            if all(p in skip for p in range(start, end + 1)):
                errors.append(f"{sec['id']} 的所有页都被跳过了，这一节没有可讲的内容")
    return errors


# ---- 切块 ----

def split_chunks(pages: list[int], max_pages: int = MAX_UNIT_PAGES) -> list[list[int]]:
    """把一节的待讲页平均切成若干块，每块不超过 max_pages 页，前面的块多分一页。"""
    if not pages:
        return []
    n = math.ceil(len(pages) / max_pages)
    base, extra = divmod(len(pages), n)
    chunks, i = [], 0
    for k in range(n):
        size = base + (1 if k < extra else 0)
        chunks.append(pages[i:i + size])
        i += size
    return chunks


def effective_skip(outline: dict, pages_data: dict) -> set[int]:
    """模型列出的跳过页，加上 extract.py 判定的空白页。"""
    return set(outline["skip"]) | {p["page"] for p in pages_data["pages"] if p["blank"]}


def build_units(outline: dict, skip: set[int]) -> list[dict]:
    units = []
    for sec in outline["sections"]:
        start, end = sec["pages"]
        todo = [p for p in range(start, end + 1) if p not in skip]
        chunks = split_chunks(todo)
        for k, chunk in enumerate(chunks, 1):
            single = len(chunks) == 1
            uid = sec["id"] if single else f"{sec['id']}-{k}"
            units.append({
                "id": uid,
                "section": sec["id"],
                "section_title": sec["title"],
                "pages": chunk,
                "chunk": None if single else {"index": k, "total": len(chunks)},
                "input": f"sections/{uid}.input.json",
                "output": f"sections/{uid}.json",
            })
    return units


# ---- 输入包 ----

def page_label(page: dict) -> str:
    """大纲里每页的简短说明：有标题用标题，没有就用文字开头。"""
    if page["title"]:
        return page["title"]
    snippet = " ".join(page["text"].split())[:60]
    return f"（无标题）{snippet}" if snippet else "（无标题）"


def previous_summary(work: Path, units: list[dict], index: int) -> dict | None:
    if index == 0:
        return None
    prev = units[index - 1]
    path = work / prev["output"]
    if not path.is_file():
        return None
    try:
        summary = common.read_json(path).get("section_summary")
    except ValueError:
        return None
    return {"unit": prev["id"], "summary": summary} if summary else None


def build_packet(course: dict, course_dir: Path, lecture_id: str, pages_data: dict,
                 outline: dict, skip: set[int], units: list[dict], index: int) -> dict:
    unit = units[index]
    out_dir = common.lecture_dir(course_dir, lecture_id).resolve()
    work = out_dir / "work"
    by_no = {p["page"]: p for p in pages_data["pages"]}
    section = next(s for s in outline["sections"] if s["id"] == unit["section"])
    start, end = section["pages"]

    return {
        "lecture": lecture_id,
        "course": course.get("name", ""),
        "explain_language": course.get("explain_language", "zh"),
        "keep_terms_in": course.get("keep_terms_in", "en"),
        "unit": unit["id"],
        "section": {"id": section["id"], "title": section["title"], "pages": section["pages"]},
        "chunk": unit["chunk"],
        "read_first": [str(REFERENCES_DIR / name) for name in READ_FIRST],
        "output_file": str(work / unit["output"]),
        "page_count": pages_data["page_count"],
        "image_dir": str(out_dir / "img"),
        "pages": [
            {
                "page": n,
                "title": by_no[n]["title"],
                "text": by_no[n]["text"],
                "image": str(out_dir / by_no[n]["image"]),
            }
            for n in unit["pages"]
        ],
        "skipped_pages_in_section": [p for p in range(start, end + 1) if p in skip],
        "previous_unit": previous_summary(work, units, index),
        "outline": [
            {
                "id": s["id"],
                "title": s["title"],
                "pages": s["pages"],
                "page_titles": [[n, page_label(by_no[n])] for n in range(s["pages"][0], s["pages"][1] + 1)],
            }
            for s in outline["sections"]
        ],
    }


def prepare_lecture(course_dir: Path, lecture_id: str, only_unit: str | None = None) -> dict:
    """校验大纲并写输入包。大纲有错时抛 OutlineError，带全部错误。"""
    course = common.load_course(course_dir)
    common.lecture_entry(course, lecture_id)
    work = common.work_dir(course_dir, lecture_id)
    pages_path = work / "pages.json"
    outline_path = work / "outline.json"
    if not pages_path.is_file():
        raise common.CourseError(f"找不到 {pages_path}，请先运行 extract.py")
    if not outline_path.is_file():
        raise common.CourseError(f"找不到 {outline_path}，请先按 outline-guide.md 切节")

    pages_data = common.read_json(pages_path)
    try:
        outline = common.read_json(outline_path)
    except ValueError as e:
        raise OutlineError([f"outline.json 不是合法的 JSON：{e}"]) from e
    errors = check_outline(outline, lecture_id, pages_data["page_count"])
    if errors:
        raise OutlineError(errors)

    skip = effective_skip(outline, pages_data)
    units = build_units(outline, skip)
    ids = [u["id"] for u in units]
    if only_unit is not None and only_unit not in ids:
        raise common.CourseError(f"没有讲解单元 {only_unit}，现有：{', '.join(ids)}")

    for i, unit in enumerate(units):
        if only_unit is None or unit["id"] == only_unit:
            packet = build_packet(course, course_dir, lecture_id, pages_data, outline, skip, units, i)
            common.write_json(work / unit["input"], packet)
    if only_unit is None:
        common.write_json(work / "units.json", {
            "lecture": lecture_id,
            "max_unit_pages": MAX_UNIT_PAGES,
            "skip": sorted(skip),
            "units": units,
        })
    return {"lecture": lecture_id, "sections": len(outline["sections"]), "units": units, "skip": sorted(skip)}


class OutlineError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def describe(summary: dict) -> str:
    units = summary["units"]
    parts = [f"{u['id']}({u['pages'][0]}-{u['pages'][-1]})" for u in units]
    line = f"{summary['lecture']}：{summary['sections']} 节，{len(units)} 个讲解单元：{' '.join(parts)}"
    if summary["skip"]:
        line += f"；跳过 {summary['skip']}"
    return line


def main(argv: list[str] | None = None) -> int:
    common.setup_stdio()
    parser = argparse.ArgumentParser(description="校验大纲，生成讲解单元的输入包")
    parser.add_argument("course_dir", type=Path)
    parser.add_argument("lecture")
    parser.add_argument("--unit", help="只重新生成这个单元的输入包")
    args = parser.parse_args(argv)
    try:
        summary = prepare_lecture(args.course_dir, args.lecture, args.unit)
    except OutlineError as e:
        print(f"{args.lecture} 的 outline.json 有 {len(e.errors)} 处问题，请修改后重新运行：", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except common.CourseError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if args.unit:
        print(f"{args.lecture}：已重新生成 {args.unit} 的输入包")
    else:
        print(describe(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
