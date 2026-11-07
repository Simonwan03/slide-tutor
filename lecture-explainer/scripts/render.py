"""阶段 7：把一讲的讲解渲染成一个 HTML 页面。

左边是课件原页，右边是讲解；左侧是"节 → 页"两级目录，右侧可以打开术语表。
没写完的单元、跳过的页、没通过校验的页都会照常显示课件原图，并在讲解位置给出说明，不会阻塞整讲的产出。

用法：
    python render.py <课程目录> <讲次>                输出 output/<讲次>/index.html，和同目录的 img/ 一起使用
    python render.py <课程目录> <讲次> --standalone   另外输出 output/<讲次>/<讲次>-standalone.html，
                                                     课件图内嵌在文件里，单独一个文件就能看，适合发到手机或发给别人
直接用浏览器打开即可（公式和代码高亮需要联网加载）。
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

import jinja2
import pymupdf

import common
import validate

# 单文件版的课件图：手机屏幕上课件图大约 1000 个物理像素宽，再大只是让文件变大
STANDALONE_WIDTH = 1000
STANDALONE_JPEG_QUALITY = 80

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets"
TEMPLATE_NAME = "template.html"

# 这些错误说明讲解文件结构不对，内容无法可靠地显示，整个单元改为显示错误说明
STRUCTURAL_CODES = {"E1", "E3", "E8"}

KIND_LABELS = {
    "text": "文字", "formula": "公式", "table": "表格", "figure": "图示",
    "code": "代码", "exercise": "习题", "divider": "分隔页",
}
BLOCK_LABELS = {
    "explain": "", "figure": "图解", "example": "例子", "pitfall": "注意",
    "derivation": "推导", "table": "表格", "code": "代码", "exercise": "习题",
}
CJK_END = re.compile(r"[　-〿＀-￯一-鿿]$")


# ---- 句子合并 ----

def source_key(item: dict) -> tuple:
    src = item["src"]
    return (src["type"], tuple(src.get("pages", ())), src.get("lecture"), src.get("page"), item.get("status"))


def join_text(left: str, right: str) -> str:
    """中文句子直接拼接，英文句子之间加空格。"""
    if not left:
        return right
    return left + ("" if CJK_END.search(left) else " ") + right


def group_segments(segments: list[dict]) -> list[dict]:
    """相邻且来源完全相同的句子合成一段，只在末尾显示一次来源标签，减少视觉噪音。"""
    runs: list[dict] = []
    for seg in segments:
        if runs and runs[-1]["key"] == source_key(seg):
            runs[-1]["text"] = join_text(runs[-1]["text"], seg["text"])
        else:
            runs.append({"key": source_key(seg), "text": seg["text"], "src": seg["src"],
                         "unverified": seg.get("status") == "unverified"})
    for run in runs:
        text = run["text"].rstrip()
        # 以独立公式结尾的句子，标签会被挤到下一行开头，看起来像属于下一句；改为单独一行靠右
        run["display_end"] = text.endswith("$$")
        # 其余情况把最后一个中文字或标点和标签粘在一起，标签就不会单独折到下一行开头
        if not run["display_end"] and CJK_END.search(text):
            run["head"], run["tail"] = text[:-1], text[-1]
        else:
            run["head"], run["tail"] = text, ""
    return runs


# ---- 讲解内容 ----

def block_model(block: dict, anchor: str) -> dict:
    kind = block["kind"]
    model = {"kind": kind, "title": block["title"], "anchor": anchor}
    if kind in validate.TEXT_BLOCK_KINDS:
        model["runs"] = group_segments(block["segments"])
        model["erratum"] = kind == "pitfall" and block["title"].startswith("课件可能有误")
    elif kind == "derivation":
        model["steps"] = [{"math": s["math"], "why": s["why"], "src": s["src"],
                           "unverified": s.get("status") == "unverified"} for s in block["steps"]]
    elif kind == "table":
        model.update(header=block["header"], rows=block["rows"], caption=block.get("caption", ""),
                     src=block["src"], unverified=block.get("status") == "unverified")
    elif kind == "code":
        model.update(lang=block["lang"], code=block["code"], src=block["src"],
                     unverified=block.get("status") == "unverified")
    elif kind == "exercise":
        model.update(
            answer_on_slide=bool(block.get("answer_on_slide")),
            analysis=group_segments(block["analysis"]),
            hints=[group_segments(h) for h in block["hints"]],
            solution=[block_model(b, f"{anchor}-s{i}") for i, b in enumerate(block["solution"], 1)],
        )
    return model


def nav_title(page: dict, explained: dict | None) -> str:
    if page["title"]:
        return page["title"]
    if explained:
        return explained["gist"]
    snippet = " ".join(page["text"].split())[:40]
    return snippet or "（无标题）"


# ---- 阅读时间 ----

READ_CHARS_PER_MINUTE = 350   # 带公式的中文讲解，比普通中文阅读慢一些
SECONDS_PER_SLIDE = 15        # 看一页课件图的时间


def reading_chars(node) -> int:
    """讲解里默认显示的文字量；习题的完整解答默认收起，不算在内。"""
    if isinstance(node, dict):
        total = sum(len(node[k]) for k in ("text", "why", "caption") if isinstance(node.get(k), str))
        return total + sum(reading_chars(v) for k, v in node.items() if k != "solution")
    if isinstance(node, list):
        return sum(reading_chars(v) for v in node)
    return 0


def reading_minutes(chars: int, slides: int) -> int:
    return max(1, round(chars / READ_CHARS_PER_MINUTE + slides * SECONDS_PER_SLIDE / 60))


# ---- 整讲数据 ----

def build_model(course_dir: Path, lecture_id: str) -> dict:
    course = common.load_course(course_dir)
    common.lecture_entry(course, lecture_id)
    work = common.work_dir(course_dir, lecture_id)
    for name in ("pages.json", "outline.json", "units.json"):
        if not (work / name).is_file():
            raise common.CourseError(f"找不到 {work / name}，请先运行 extract.py 和 prepare.py")
    pages_data = common.read_json(work / "pages.json")
    outline = common.read_json(work / "outline.json")
    units = common.read_json(work / "units.json")
    skip = set(units.get("skip", []))

    # 讲解组（一页或几页合讲）、每页的错误、每节的小结
    groups_by_first: dict[int, dict] = {}   # 组的第一页 → 讲解组
    page_errors: dict[int, list[str]] = {}
    unit_summaries: dict[str, list[str]] = {}
    bad_units: dict[int, list[str]] = {}
    for unit in units["units"]:
        out = work / unit["output"]
        if not out.is_file():
            continue
        issues = validate.check_unit(course_dir, lecture_id, unit["id"])
        errors = [i for i in issues if i["level"] == "error"]
        if any(i["code"] in STRUCTURAL_CODES for i in errors):
            msgs = [f"[{i['code']}] {i['msg']}" for i in errors]
            for p in unit["pages"]:
                bad_units[p] = msgs
            continue
        data = common.read_json(out)
        if data.get("section_summary"):
            unit_summaries.setdefault(unit["section"], []).append(data["section_summary"])
        for entry in data["pages"]:
            pages = common.entry_pages(entry)
            if pages and all(p in unit["pages"] for p in pages):
                groups_by_first[pages[0]] = entry
        for i in errors:
            if i.get("page"):
                page_errors.setdefault(i["page"], []).append(f"[{i['code']}] {i['msg']}")
            else:
                for p in unit["pages"]:
                    page_errors.setdefault(p, []).append(f"[{i['code']}] {i['msg']}")

    sections, terms, seen_terms = [], [], set()
    counts = {"total": pages_data["page_count"], "explained": 0, "missing": 0, "skipped": 0, "errors": 0, "unverified": 0}
    read_chars = 0
    by_no = {p["page"]: p for p in pages_data["pages"]}

    def slide(no: int) -> dict:
        page = by_no[no]
        return {"no": no, "image": page["image"], "image_link": page["image"], "size": page["size"]}

    def group(pages: list[int], state: str, entry: dict | None = None) -> dict:
        issues = []
        for p in pages:
            for m in page_errors.get(p, []) or bad_units.get(p, []):
                if m not in issues:
                    issues.append(m)
        g = {
            "first": pages[0], "pages": pages, "state": state,
            "label": f"第 {pages[0]} 页" if len(pages) == 1 else f"第 {pages[0]}–{pages[-1]} 页",
            "slides": [slide(p) for p in pages], "issues": issues,
            "kind": "", "kind_label": "", "gist": "", "blocks": [], "hide_slide": False,
        }
        if entry is not None:
            blocks = [block_model(b, f"p{pages[0]}-b{i}") for i, b in enumerate(entry["blocks"], 1)]
            g.update(kind=entry["kind"], kind_label=KIND_LABELS.get(entry["kind"], entry["kind"]),
                     gist=entry["gist"], blocks=blocks,
                     hide_slide=any(b["kind"] == "exercise" and b["answer_on_slide"] for b in blocks))
        return g

    for sec in outline["sections"]:
        start, end = sec["pages"]
        sec_groups, nav = [], []
        no = start
        while no <= end:
            entry = groups_by_first.get(no) if no not in bad_units else None
            if no in skip:
                g = group([no], "skip")
                counts["skipped"] += 1
            elif no in bad_units:
                g = group([no], "invalid")
                counts["errors"] += 1
            elif entry is None:
                g = group([no], "missing")
                counts["missing"] += 1
            else:
                g = group(common.entry_pages(entry), "explained", entry)
                counts["explained"] += len(g["pages"])
                read_chars += reading_chars(entry["blocks"])
                counts["unverified"] += sum(1 for n in validate.walk(entry["blocks"]) if n.get("status") == "unverified")
                if g["issues"]:
                    counts["errors"] += len(g["pages"])
                for term in entry.get("terms", []):
                    key = term["term"].casefold()
                    if key not in seen_terms:
                        seen_terms.add(key)
                        terms.append({**term, "aliases": term.get("aliases", []), "page": term.get("page", no)})
            sec_groups.append(g)
            for p in g["pages"]:
                nav.append({"no": p, "state": g["state"], "has_issues": bool(g["issues"]),
                            "nav_title": nav_title(by_no[p], entry)})
            no = g["pages"][-1] + 1
        sections.append({"id": sec["id"], "title": sec["title"], "groups": sec_groups, "nav": nav,
                         "summaries": unit_summaries.get(sec["id"], [])})

    terms.sort(key=lambda t: (t["page"], t["term"].casefold()))
    first = by_no.get(1, {})
    return {
        "course": course.get("name", ""),
        "lecture": {"id": lecture_id, "title": outline.get("title") or first.get("title") or lecture_id},
        "storage_key": f"lecture-explainer:{course.get('name', '')}:{lecture_id}",
        "sections": sections,
        "terms": terms,
        "counts": counts,
        "reading": {
            "chars": read_chars,
            "slides": counts["explained"],
            "minutes": reading_minutes(read_chars, counts["explained"]),
        },
    }


# ---- 渲染 ----

def environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )
    env.globals["block_labels"] = BLOCK_LABELS
    return env


def embed_image(path: Path) -> str:
    """把课件图缩到 STANDALONE_WIDTH 宽，转成 data URI；PNG 和 JPEG 哪个小用哪个。"""
    pix = pymupdf.Pixmap(str(path))
    if pix.width > STANDALONE_WIDTH:
        pix = pymupdf.Pixmap(pix, STANDALONE_WIDTH, round(pix.height * STANDALONE_WIDTH / pix.width), None)
    png = pix.tobytes("png")
    jpeg = pix.tobytes("jpeg", jpg_quality=STANDALONE_JPEG_QUALITY)
    data, mime = (jpeg, "image/jpeg") if len(jpeg) < len(png) else (png, "image/png")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def render_lecture(course_dir: Path, lecture_id: str, standalone: bool = False) -> tuple[Path, dict]:
    model = build_model(course_dir, lecture_id)
    template = environment().get_template(TEMPLATE_NAME)
    lecture_dir = common.lecture_dir(course_dir, lecture_id)
    out = lecture_dir / "index.html"
    common.write_text(out, template.render(**model))
    if standalone:
        for section in model["sections"]:
            for g in section["groups"]:
                for s in g["slides"]:
                    s["image"] = embed_image(lecture_dir / s["image"])
                    s["image_link"] = None   # 不再链接到单独的图片文件，也避免同一张图在文件里存两遍
        out = lecture_dir / f"{lecture_id}-standalone.html"
        common.write_text(out, template.render(**model))
    return out, model["counts"]


def main(argv: list[str] | None = None) -> int:
    common.setup_stdio()
    parser = argparse.ArgumentParser(description="把一讲的讲解渲染成 HTML")
    parser.add_argument("course_dir", type=Path)
    parser.add_argument("lecture")
    parser.add_argument("--standalone", action="store_true", help="另外生成课件图内嵌的单文件版本")
    args = parser.parse_args(argv)
    try:
        out, c = render_lecture(args.course_dir, args.lecture, args.standalone)
    except common.CourseError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    parts = [f"共 {c['total']} 页", f"已讲解 {c['explained']} 页"]
    if c["missing"]:
        parts.append(f"还没讲解 {c['missing']} 页")
    if c["skipped"]:
        parts.append(f"跳过 {c['skipped']} 页")
    if c["unverified"]:
        parts.append(f"待核实 {c['unverified']} 处")
    if c["errors"]:
        parts.append(f"有 {c['errors']} 页没通过校验（页面上已标红）")
    size = out.stat().st_size / 1024 / 1024
    print(f"已生成 {out}（{size:.1f} MB）：" + "，".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
