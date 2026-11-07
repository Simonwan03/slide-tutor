"""lecture-explainer 所有脚本的统一入口。只用标准库。

每次运行先确保依赖已装好（第一次会自动建虚拟环境并安装，约 1 分钟），再用那个环境里的 Python 运行对应的脚本。
这样调用方只需要记住一条命令，权限规则也只需要一条。

用法：
    python lx.py setup                              只准备运行环境
    python lx.py init     <课程目录> [--name 课程名]   生成或补全 course.json
    python lx.py extract  <课程目录> [讲次 ...]        提取每页图片、标题、文字
    python lx.py prepare  <课程目录> <讲次> [--unit U] 校验大纲，生成讲解单元的输入包
    python lx.py validate <课程目录> <讲次> [--unit U] 检查讲解
    python lx.py render   <课程目录> <讲次>            生成 HTML
退出码和对应脚本一致；环境准备失败时为 1 或 2。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import bootstrap

SCRIPTS_DIR = Path(__file__).resolve().parent
COMMANDS = {
    "init": "init_course.py",
    "extract": "extract.py",
    "prepare": "prepare.py",
    "validate": "validate.py",
    "render": "render.py",
}


def main(argv: list[str] | None = None) -> int:
    bootstrap.setup_stdio()
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in {"setup", *COMMANDS} or args[0] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    command, rest = args[0], args[1:]
    code, python = bootstrap.ensure()
    if code != 0:
        return code
    if command == "setup":
        print("运行环境已就绪")
        return 0
    sys.stdout.flush()
    return subprocess.call([str(python), str(SCRIPTS_DIR / COMMANDS[command]), *rest])


if __name__ == "__main__":
    sys.exit(main())
