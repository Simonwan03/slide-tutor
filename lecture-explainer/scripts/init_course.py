"""扫描课程目录里的课件 PDF，生成或补全 course.json。

讲次先按 PDF 创建日期排序（没有日期的按文件名），模型再根据打印出来的标题判断顺序是否合理，需要时直接改 course.json。

用法：
    python init_course.py <课程目录> [--name 课程名]
- 课程目录下有 lectures/ 子目录时扫描它；没有时扫描课程目录本身，并在 course.json 里写 "lectures_dir": "."
- 还没有 course.json：生成一份
- 已有 course.json：不改动已登记的讲次，只把还没登记的 PDF 按日期追加在后面
最后打印每一讲的编号、日期、页数、文件名和标题，供模型确认顺序。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pymupdf

import common

DEFAULTS = {"explain_language": "zh", "keep_terms_in": "en"}


def natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def pdf_info(path: Path) -> dict:
    """创建日期（YYYY-MM-DD，可能为空）、页数、标题。"""
    try:
        with pymupdf.open(path) as doc:
            meta = doc.metadata or {}
            m = re.match(r"D:(\d{4})(\d{2})(\d{2})", meta.get("creationDate") or "")
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
            title = (meta.get("title") or "").strip()
            if not title and doc.page_count:
                lines = [l.strip() for l in doc[0].get_text().splitlines() if l.strip()]
                title = lines[0] if lines else ""
            return {"date": date, "pages": doc.page_count, "title": title}
    except Exception as e:  # 损坏或加密的文件照样列出来，交给 extract.py 报具体错误
        return {"date": "", "pages": 0, "title": f"（无法读取：{e}）"}


def find_lectures_dir(course_dir: Path) -> tuple[Path, str | None]:
    sub = course_dir / "lectures"
    if sub.is_dir():
        return sub, None
    return course_dir, "."


def next_id(existing: list[str]) -> str:
    nums = [int(m.group(1)) for i in existing if (m := re.fullmatch(r"L(\d+)", i))]
    return f"L{(max(nums) if nums else 0) + 1:02d}"


def init_course(course_dir: Path, name: str | None = None) -> tuple[dict, list[str]]:
    """返回 (course.json 内容, 本次新登记的讲次编号)。"""
    if not course_dir.is_dir():
        raise common.CourseError(f"课程目录不存在：{course_dir}")
    path = course_dir / "course.json"
    if path.is_file():
        course = common.load_course(course_dir)
        lec_dir = course_dir / course.get("lectures_dir", "lectures")
    else:
        lec_dir, lectures_dir = find_lectures_dir(course_dir)
        course = {"name": name or course_dir.resolve().name, **DEFAULTS, "lectures": []}
        if lectures_dir:
            course["lectures_dir"] = lectures_dir

    known = {lec["file"] for lec in course["lectures"]}
    new_files = sorted((p for p in lec_dir.glob("*.pdf") if p.name not in known), key=lambda p: natural_key(p.name))
    if not new_files and not course["lectures"]:
        raise common.CourseError(f"{lec_dir} 里没有找到 PDF 课件")
    infos = {p.name: pdf_info(p) for p in new_files}
    # 有日期的按日期排在前面，没有日期的按文件名排在后面
    new_files.sort(key=lambda p: (infos[p.name]["date"] == "", infos[p.name]["date"], natural_key(p.name)))

    added = []
    for p in new_files:
        lid = next_id([lec["id"] for lec in course["lectures"]])
        course["lectures"].append({"id": lid, "file": p.name})
        added.append(lid)
    if added or not path.is_file():
        common.write_json(path, course)
    return course, added


def main(argv: list[str] | None = None) -> int:
    common.setup_stdio()
    parser = argparse.ArgumentParser(description="生成或补全 course.json")
    parser.add_argument("course_dir", type=Path)
    parser.add_argument("--name", help="课程名（只在第一次生成时使用，默认取文件夹名）")
    args = parser.parse_args(argv)
    try:
        course, added = init_course(args.course_dir, args.name)
    except common.CourseError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    lec_dir = args.course_dir / course.get("lectures_dir", "lectures")
    print(f"课程：{course['name']}（{len(course['lectures'])} 讲，新登记 {len(added)} 讲）")
    for lec in course["lectures"]:
        info = pdf_info(lec_dir / lec["file"]) if (lec_dir / lec["file"]).is_file() else {"date": "", "pages": 0, "title": "（文件不存在）"}
        mark = "  新" if lec["id"] in added else ""
        print(f"{lec['id']} | {info['date'] or '无日期'} | {info['pages']} 页 | {lec['file']} | {info['title']}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
