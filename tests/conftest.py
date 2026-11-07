"""测试公共设置：把 skill 的 scripts 目录加进导入路径，并提供生成合成 PDF 的工具。

测试只用临时生成的合成 PDF，不依赖真实课件，所以可以公开、能在 CI 上跑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "lecture-explainer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

PAGE_W, PAGE_H = 720, 540  # PowerPoint 4:3 默认尺寸


def make_pdf(path: Path, pages: list[dict], toc: list | None = None, user_pw: str | None = None) -> Path:
    """按描述生成一份合成 PDF。

    pages 里每一项可以有：
        texts:  [(x, y, 文字, 字号), ...]   y 是基线位置
        rect:   (x0, y0, x1, y1)            画一个矩形框（矢量图形）
        image:  (x0, y0, x1, y1)            插一张纯色小图片
    """
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text, size in spec.get("texts", []):
            page.insert_text((x, y), text, fontsize=size)
        if "rect" in spec:
            page.draw_rect(pymupdf.Rect(*spec["rect"]), color=(0, 0, 0), width=1)
        if "image" in spec:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), False)
            pix.set_rect(pix.irect, (200, 30, 30))
            page.insert_image(pymupdf.Rect(*spec["image"]), pixmap=pix)
    if toc:
        doc.set_toc(toc)
    path.parent.mkdir(parents=True, exist_ok=True)
    if user_pw:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=user_pw + "-owner", user_pw=user_pw)
    else:
        doc.save(path)
    doc.close()
    return path


def make_course(course_dir: Path, lectures: dict[str, str]) -> Path:
    """写一个 course.json。lectures 是 {讲次编号: 文件名}。"""
    course_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "Test Course",
        "explain_language": "zh",
        "keep_terms_in": "en",
        "lectures": [{"id": lid, "file": name} for lid, name in lectures.items()],
    }
    (course_dir / "course.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return course_dir


@pytest.fixture
def tmp_course(tmp_path: Path) -> Path:
    """带空格、括号和中文的课程目录，顺便覆盖 Windows 路径问题。"""
    return tmp_path / "我的 课程 (1)"
