"""阶段 1：把一讲课件 PDF 变成模型和 HTML 都能用的材料。

只做三件事，看懂内容的事全部留给模型：
1. 每页渲染一张 PNG（给模型看，也放在 HTML 左栏）
2. 从 PDF 书签读每页标题
3. 提取每页文字（只去掉页脚页码和私有区字符，乱码不处理，模型以图片为准）

输出到 <课程目录>/output/<讲次>/：
    img/pNNN.png
    work/pages.json   每页的标题、文字、图片路径
    work/titles.txt   每页一行，给模型切节用

用法：
    python extract.py <课程目录> [讲次 ...] [--force]
不写讲次时处理 course.json 里的全部讲次。输入 PDF 和本脚本版本都没变时自动跳过，--force 强制重做。
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from pathlib import Path

import pymupdf

import common

# 改了提取逻辑就把版本号加 1，旧的 pages.json 会自动失效
EXTRACT_VERSION = 1

# Claude 看图时，超过约 120 万像素或长边超过 1568px 的图会被缩小，再大也没用。
# 4:3 的页面渲染出来约 1265×949，约 1600 token。
MAX_PIXELS = 1_200_000
MAX_EDGE = 1568

# 书签当作页标题的条件：至少这么大比例的页有自己的书签（PowerPoint 导出时一页一个）
PER_PAGE_TOC_RATIO = 0.8

# 页码只在页面上下边缘出现；表格里的数字也可能单独占一行，所以要同时看位置和数值
FOOTER_TOP = 0.90
HEADER_BOTTOM = 0.10

SLIDE_PREFIX = re.compile(r"^\s*slide\s+\d+\s*(?:[:：]\s*|$)", re.IGNORECASE)
PRIVATE_USE = re.compile("[-]")
DIGITS = re.compile(r"\d{1,4}")


def render_zoom(width_pt: float, height_pt: float) -> float:
    """渲染倍数：在不超过 MAX_PIXELS 和 MAX_EDGE 的前提下尽量大。"""
    zoom = math.sqrt(MAX_PIXELS / (width_pt * height_pt))
    return min(zoom, MAX_EDGE / max(width_pt, height_pt))


def clean_title(raw: str) -> str:
    """'Slide 36: Find sailors …' → 'Find sailors …'；只有 'Slide 35' 时返回空串。"""
    title = SLIDE_PREFIX.sub("", raw)
    return " ".join(title.split())


def page_titles(toc: list, page_count: int) -> tuple[list[str], str]:
    """返回每页标题，以及标题来源（'bookmarks' 或 'none'）。

    只有书签明显是"一页一个"时才当作页标题；Beamer 那种按节生成的书签不算，
    原始书签仍然会写进 pages.json，模型切节时可以参考。
    """
    first: dict[int, str] = {}
    for _level, title, page in toc:
        if 1 <= page <= page_count and page not in first:
            first[page] = title
    if page_count == 0 or len(first) < PER_PAGE_TOC_RATIO * page_count:
        return [""] * page_count, "none"
    return [clean_title(first.get(p, "")) for p in range(1, page_count + 1)], "bookmarks"


def is_page_number(line: str, y0: float, y1: float, page_height: float, page_no: int) -> bool:
    if not DIGITS.fullmatch(line) or int(line) != page_no:
        return False
    return y0 >= FOOTER_TOP * page_height or y1 <= HEADER_BOTTOM * page_height


def page_text(page: pymupdf.Page, page_no: int) -> str:
    height = page.rect.height
    out_lines: list[str] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = PRIVATE_USE.sub("", "".join(span["text"] for span in line["spans"])).strip()
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            if is_page_number(text, y0, y1, height, page_no):
                continue
            out_lines.append(text)
    return "\n".join(out_lines)


def is_blank(page: pymupdf.Page, text: str) -> bool:
    """真正什么都没画的页才算空白；只有主题装饰的页交给模型判断要不要跳过。"""
    return not text and not page.get_images() and not page.get_drawings()


def image_name(page_no: int, page_count: int) -> str:
    width = max(3, len(str(page_count)))
    return f"p{page_no:0{width}d}.png"


def up_to_date(pages_json: Path, out_dir: Path, sha: str) -> bool:
    if not pages_json.is_file():
        return False
    try:
        data = common.read_json(pages_json)
    except ValueError:
        return False
    if data.get("extract_version") != EXTRACT_VERSION or data.get("sha256") != sha:
        return False
    return all((out_dir / p["image"]).is_file() for p in data.get("pages", []))


def titles_txt(lecture_id: str, pdf_name: str, pages: list[dict]) -> str:
    lines = [
        f"# {lecture_id} {pdf_name}，共 {len(pages)} 页",
        "# 格式：页码 | 标题 | 文字前 80 字（标题为空表示书签里没有标题，请看文字或图片）",
    ]
    for p in pages:
        if p["blank"]:
            lines.append(f"{p['page']} | （空白页） |")
            continue
        snippet = " ".join(p["text"].split())[:80]
        lines.append(f"{p['page']} | {p['title']} | {snippet}")
    return "\n".join(lines) + "\n"


def extract_lecture(course_dir: Path, lecture_id: str, force: bool = False) -> dict:
    """处理一讲，返回摘要。已是最新时不重做，摘要里 skipped 为 True。"""
    course = common.load_course(course_dir)
    pdf = common.lecture_pdf(course_dir, course, lecture_id)
    out_dir = common.lecture_dir(course_dir, lecture_id)
    pages_json = common.work_dir(course_dir, lecture_id) / "pages.json"
    sha = common.sha256_file(pdf)

    if not force and up_to_date(pages_json, out_dir, sha):
        data = common.read_json(pages_json)
        return {"lecture": lecture_id, "skipped": True, "page_count": data["page_count"]}

    try:
        doc = pymupdf.open(pdf)
    except Exception as e:  # PyMuPDF 对损坏文件会抛各种异常
        raise common.CourseError(f"打不开 {pdf}：{e}") from e
    with doc:
        if not doc.is_pdf:
            raise common.CourseError(f"{pdf} 不是 PDF 文件")
        if doc.needs_pass:
            raise common.CourseError(f"{pdf} 有密码保护，请先去掉密码")

        page_count = doc.page_count
        toc = doc.get_toc()
        titles, titles_from = page_titles(toc, page_count)

        img_dir = out_dir / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        for old in img_dir.glob("p*.png"):
            old.unlink()

        pages = []
        for index, page in enumerate(doc):
            page_no = index + 1
            text = page_text(page, page_no)
            zoom = render_zoom(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            name = image_name(page_no, page_count)
            pix.save(img_dir / name)
            pages.append({
                "page": page_no,
                "title": titles[index],
                "text": text,
                "image": f"img/{name}",
                "size": [pix.width, pix.height],
                "blank": is_blank(page, text),
            })

    data = {
        "extract_version": EXTRACT_VERSION,
        "lecture": lecture_id,
        "source": Path(os.path.relpath(pdf, course_dir)).as_posix(),
        "sha256": sha,
        "page_count": page_count,
        "titles_from": titles_from,
        "toc": toc,
        "pages": pages,
    }
    work = common.work_dir(course_dir, lecture_id)
    common.write_json(pages_json, data)
    common.write_text(work / "titles.txt", titles_txt(lecture_id, pdf.name, pages))

    return {
        "lecture": lecture_id,
        "skipped": False,
        "page_count": page_count,
        "titles_from": titles_from,
        "titled_pages": sum(1 for p in pages if p["title"]),
        "blank_pages": [p["page"] for p in pages if p["blank"]],
        "no_text_layer": all(not p["text"] for p in pages),
    }


def describe(summary: dict, seconds: float) -> str:
    lid = summary["lecture"]
    if summary["skipped"]:
        return f"{lid}：已是最新，跳过（{summary['page_count']} 页）"
    parts = [f"{lid}：{summary['page_count']} 页"]
    if summary["titles_from"] == "bookmarks":
        parts.append(f"书签标题 {summary['titled_pages']}/{summary['page_count']} 页")
    else:
        parts.append("没有逐页书签，标题留空")
    if summary["blank_pages"]:
        parts.append(f"空白页 {summary['blank_pages']}")
    parts.append(f"{seconds:.1f} 秒")
    line = "，".join(parts)
    if summary["no_text_layer"]:
        line += "\n  注意：整份 PDF 没有文字层（可能是扫描版），讲解时模型只能看图片"
    return line


def main(argv: list[str] | None = None) -> int:
    common.setup_stdio()
    parser = argparse.ArgumentParser(description="阶段 1：渲染每页图片、读书签标题、提取文字")
    parser.add_argument("course_dir", type=Path, help="课程目录（含 course.json）")
    parser.add_argument("lectures", nargs="*", help="讲次编号，如 L03；不写则处理全部讲次")
    parser.add_argument("--force", action="store_true", help="即使已是最新也重做")
    args = parser.parse_args(argv)

    try:
        course = common.load_course(args.course_dir)
        ids = args.lectures or common.lecture_ids(course)
        for lecture_id in ids:
            start = time.perf_counter()
            summary = extract_lecture(args.course_dir, lecture_id, force=args.force)
            print(describe(summary, time.perf_counter() - start))
    except common.CourseError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
