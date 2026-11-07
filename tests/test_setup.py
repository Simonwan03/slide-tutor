"""bootstrap.py、lx.py、init_course.py 的测试。不联网：真正的安装过程用假的 install 代替。"""

from __future__ import annotations

import json
import sys

import pytest

import bootstrap
import common
import extract
import init_course
import lx
from conftest import make_course, make_pdf


# ---- bootstrap ----

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LECTURE_EXPLAINER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LECTURE_EXPLAINER_PYTHON", raising=False)
    return tmp_path / "home"


def make_ready_env(req_hash):
    env = bootstrap.env_dir()
    py = bootstrap.env_python(env)
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    bootstrap.marker(env).write_text(req_hash, encoding="utf-8")
    return py


def test_override_python(monkeypatch):
    monkeypatch.setenv("LECTURE_EXPLAINER_PYTHON", sys.executable)
    assert bootstrap.ensure() == (0, bootstrap.Path(sys.executable))


def test_ready_env_skips_install(fake_home, monkeypatch):
    py = make_ready_env(bootstrap.requirements_hash())
    monkeypatch.setattr(bootstrap, "install", lambda *a: pytest.fail("不应该重新安装"))
    assert bootstrap.ensure() == (0, py)


def test_changed_requirements_reinstall(fake_home, monkeypatch, capsys):
    make_ready_env("old-hash")
    calls = []
    monkeypatch.setattr(bootstrap, "install", lambda env, h: calls.append(h))
    code, py = bootstrap.ensure()
    assert code == 0 and calls == [bootstrap.requirements_hash()]
    assert "正在准备运行环境" in capsys.readouterr().out


def test_install_failure(fake_home, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "install", lambda env, h: "安装依赖失败：network down")
    assert bootstrap.ensure() == (1, None)
    err = capsys.readouterr().err
    assert "network down" in err and "pip install -r" in err


def test_old_python(fake_home, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap.sys, "version_info", (3, 8, 10))
    assert bootstrap.ensure() == (2, None)
    assert "需要 Python 3.10" in capsys.readouterr().err


def test_bootstrap_main_prints_python(fake_home, capsys):
    py = make_ready_env(bootstrap.requirements_hash())
    assert bootstrap.main([]) == 0
    assert capsys.readouterr().out.strip().endswith(f"PYTHON={py}")


# ---- lx ----

def test_lx_usage(capsys):
    assert lx.main([]) == 2
    assert lx.main(["frobnicate"]) == 2
    assert "lx.py extract" in capsys.readouterr().err


def test_lx_runs_scripts(tmp_course, monkeypatch, capsys):
    monkeypatch.setenv("LECTURE_EXPLAINER_PYTHON", sys.executable)
    assert lx.main(["setup"]) == 0
    make_course(tmp_course, {"L01": "a.pdf"})
    make_pdf(tmp_course / "lectures" / "a.pdf", [{"texts": [(60, 100, "Hello", 20)]}])
    assert lx.main(["extract", str(tmp_course), "L01"]) == 0
    assert (common.work_dir(tmp_course, "L01") / "pages.json").is_file()
    # 子脚本的退出码原样传回
    assert lx.main(["prepare", str(tmp_course), "L01"]) == 1


def test_lx_stops_when_env_fails(fake_home, monkeypatch):
    monkeypatch.setattr(bootstrap, "install", lambda env, h: "boom")
    assert lx.main(["extract", "x"]) == 1


# ---- init_course ----

def pdf_with_date(path, date, title="T"):
    make_pdf(path, [{"texts": [(60, 100, title, 20)]}])
    import pymupdf
    doc = pymupdf.open(path)
    doc.set_metadata({"creationDate": f"D:{date}000000", "title": title})
    doc.saveIncr()
    doc.close()


def test_init_flat_folder_sorted_by_date(tmp_course, capsys):
    tmp_course.mkdir(parents=True)
    pdf_with_date(tmp_course / "b-sql.pdf", "20261015", "SQL")
    pdf_with_date(tmp_course / "a-algebra.pdf", "20261002", "Algebra")
    pdf_with_date(tmp_course / "z-overview.pdf", "20260925", "Overview")
    make_pdf(tmp_course / "notes 10.pdf", [{}])
    make_pdf(tmp_course / "notes 9.pdf", [{}])

    assert init_course.main([str(tmp_course), "--name", "数据库"]) == 0
    course = json.loads((tmp_course / "course.json").read_text(encoding="utf-8"))
    assert course["name"] == "数据库" and course["lectures_dir"] == "."
    assert course["explain_language"] == "zh"
    assert [(l["id"], l["file"]) for l in course["lectures"]] == [
        ("L01", "z-overview.pdf"), ("L02", "a-algebra.pdf"), ("L03", "b-sql.pdf"),
        ("L04", "notes 9.pdf"), ("L05", "notes 10.pdf"),   # 没有日期的按文件名自然排序，排在后面
    ]
    out = capsys.readouterr().out
    assert "L01 | 2026-09-25 | 1 页 | z-overview.pdf | Overview" in out

    # 讲次在课程目录本身时，extract 也能找到
    assert extract.extract_lecture(tmp_course, "L02")["page_count"] == 1
    assert common.read_json(common.work_dir(tmp_course, "L02") / "pages.json")["source"] == "a-algebra.pdf"


def test_init_appends_new_pdfs_only(tmp_course):
    make_course(tmp_course, {"L01": "old.pdf", "L07": "older.pdf"})
    make_pdf(tmp_course / "lectures" / "old.pdf", [{}])
    make_pdf(tmp_course / "lectures" / "new.pdf", [{}])
    course, added = init_course.init_course(tmp_course)
    assert added == ["L08"]
    assert [l["id"] for l in course["lectures"]] == ["L01", "L07", "L08"]
    assert "lectures_dir" not in course
    # 再跑一次没有新文件，什么都不变
    assert init_course.init_course(tmp_course)[1] == []


def test_init_errors(tmp_path, capsys):
    assert init_course.main([str(tmp_path / "nope")]) == 1
    (tmp_path / "empty").mkdir()
    assert init_course.main([str(tmp_path / "empty")]) == 1
    assert "没有找到 PDF" in capsys.readouterr().err
