"""lecture-explainer 各脚本共用的小工具：路径约定、JSON 读写、hash。

课程目录结构：
    <course>/course.json
    <course>/lectures/<课件文件>       （course.json 的 lectures_dir 可以改成别的目录，"." 表示课程目录本身）
    <course>/output/<讲次>/img/        每页图片
    <course>/output/<讲次>/work/       中间产物（pages.json、outline.json 等）
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class CourseError(Exception):
    """课程目录或 course.json 有问题，脚本应当报错退出。"""


def setup_stdio() -> None:
    """Windows 控制台默认编码可能不是 UTF-8，统一改成 UTF-8，避免打印中文时报错。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    """先写临时文件再改名，中途失败不会留下写了一半的 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_course(course_dir: Path) -> dict:
    path = course_dir / "course.json"
    if not path.is_file():
        raise CourseError(f"找不到 {path}")
    try:
        course = read_json(path)
    except json.JSONDecodeError as e:
        raise CourseError(f"{path} 不是合法的 JSON：{e}") from e
    lectures = course.get("lectures")
    if not isinstance(lectures, list) or not lectures:
        raise CourseError(f"{path} 里没有 lectures 列表")
    for lec in lectures:
        if not isinstance(lec, dict) or "id" not in lec or "file" not in lec:
            raise CourseError(f"{path} 的 lectures 里每一项都要有 id 和 file：{lec!r}")
    return course


def lecture_ids(course: dict) -> list[str]:
    return [lec["id"] for lec in course["lectures"]]


def lecture_entry(course: dict, lecture_id: str) -> dict:
    for lec in course["lectures"]:
        if lec["id"] == lecture_id:
            return lec
    raise CourseError(f"course.json 里没有讲次 {lecture_id}，现有：{', '.join(lecture_ids(course))}")


def entry_pages(entry: dict) -> list[int]:
    """讲解组覆盖的页：单页写 page，几页合讲写 range: [第一页, 最后一页]。"""
    if "range" in entry:
        first, last = entry["range"]
        return list(range(first, last + 1))
    return [entry["page"]]


def entry_label(entry: dict) -> str:
    pages = entry_pages(entry)
    if not pages:
        return f"range {entry.get('range')}"
    return f"第 {pages[0]} 页" if len(pages) == 1 else f"第 {pages[0]}–{pages[-1]} 页"


def lectures_dir(course_dir: Path, course: dict) -> Path:
    """课件所在目录：默认是 <课程目录>/lectures，course.json 里的 lectures_dir 可以改（"." 表示课程目录本身）。"""
    return course_dir / course.get("lectures_dir", "lectures")


def lecture_pdf(course_dir: Path, course: dict, lecture_id: str) -> Path:
    path = lectures_dir(course_dir, course) / lecture_entry(course, lecture_id)["file"]
    if not path.is_file():
        raise CourseError(f"{lecture_id} 的课件文件不存在：{path}")
    return path


def lecture_dir(course_dir: Path, lecture_id: str) -> Path:
    return course_dir / "output" / lecture_id


def work_dir(course_dir: Path, lecture_id: str) -> Path:
    return lecture_dir(course_dir, lecture_id) / "work"
