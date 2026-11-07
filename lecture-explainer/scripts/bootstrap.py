"""检查并自动安装 lecture-explainer 的 Python 依赖。只用标准库，在什么包都没装的 Python 上也能运行。

依赖装在专用的虚拟环境里（默认 ~/.lecture-explainer/venv，可用环境变量 LECTURE_EXPLAINER_HOME 改位置），
不污染全局 Python；环境放在 skill 文件夹外面，更新 skill 时不用重装。
requirements.txt 改动后会自动重装。

平时不用直接运行它：lx.py 每次都会先调用 ensure()。单独运行：
    python bootstrap.py           检查环境，需要时安装
    python bootstrap.py --force   强制重装
退出码：0 成功；1 安装失败；2 Python 版本太低。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

MIN_PYTHON = (3, 10)
REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"
CHECK_IMPORTS = "import pymupdf, jinja2, jsonschema"


def setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def home() -> Path:
    return Path(os.environ.get("LECTURE_EXPLAINER_HOME") or Path.home() / ".lecture-explainer")


def env_dir() -> Path:
    return home() / "venv"


def env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def marker(env: Path) -> Path:
    return env / ".requirements.sha256"


def is_ready(env: Path, req_hash: str) -> bool:
    m = marker(env)
    return env_python(env).is_file() and m.is_file() and m.read_text(encoding="utf-8").strip() == req_hash


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def install(env: Path, req_hash: str) -> str | None:
    """安装依赖，成功返回 None，失败返回错误说明。"""
    py = env_python(env)
    if not py.is_file():
        try:
            venv.create(env, with_pip=True, clear=True)
        except Exception as e:  # venv 可能因权限、磁盘等各种原因失败
            return f"创建虚拟环境失败：{e}"
    result = run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)])
    if result.returncode != 0:
        return "安装依赖失败：\n" + (result.stderr or result.stdout).strip()[-2000:]
    check = run([str(py), "-c", CHECK_IMPORTS])
    if check.returncode != 0:
        return "依赖装好了但无法导入：\n" + check.stderr.strip()[-2000:]
    marker(env).write_text(req_hash, encoding="utf-8")
    return None


def ensure(force: bool = False) -> tuple[int, Path | None]:
    """确保运行环境可用。返回 (退出码, 解释器路径)；失败时已把原因打印到 stderr。

    设置了环境变量 LECTURE_EXPLAINER_PYTHON 时直接用它指定的解释器（开发和测试用）。
    """
    override = os.environ.get("LECTURE_EXPLAINER_PYTHON")
    if override:
        return 0, Path(override)

    if sys.version_info < MIN_PYTHON:
        found = ".".join(map(str, sys.version_info[:3]))
        need = ".".join(map(str, MIN_PYTHON))
        print(f"需要 Python {need} 或更高版本，当前是 {found}。请从 https://www.python.org/downloads/ 安装新版本后再试。",
              file=sys.stderr)
        return 2, None

    env = env_dir()
    req_hash = requirements_hash()
    if not force and is_ready(env, req_hash):
        return 0, env_python(env)

    print(f"正在准备运行环境（第一次使用或依赖有更新），安装到 {env}，大约需要 1 分钟……", flush=True)
    error = install(env, req_hash)
    if error:
        print(error, file=sys.stderr)
        print("\n可以手动安装后重试：", file=sys.stderr)
        print(f'  "{sys.executable}" -m venv "{env}"', file=sys.stderr)
        print(f'  "{env_python(env)}" -m pip install -r "{REQUIREMENTS}"', file=sys.stderr)
        return 1, None
    print("运行环境已就绪", flush=True)
    return 0, env_python(env)


def main(argv: list[str] | None = None) -> int:
    setup_stdio()
    parser = argparse.ArgumentParser(description="检查并安装 lecture-explainer 的依赖")
    parser.add_argument("--force", action="store_true", help="强制重装")
    args = parser.parse_args(argv)
    code, py = ensure(force=args.force)
    if code == 0:
        print(f"PYTHON={py}")
    return code


if __name__ == "__main__":
    sys.exit(main())
