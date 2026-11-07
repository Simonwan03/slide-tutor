# slide-tutor

一个 [Claude Code](https://claude.com/claude-code) skill：把课程课件 PDF 变成**左边课件原页、右边中文讲解**的 HTML 学习笔记。

A Claude Code skill that turns lecture-slide PDFs into a side-by-side study page: the original slide on the left, a concise Chinese explanation (English terms kept) on the right.

## 特点

- **只讲重点**：每页或每组相邻页讲 1–3 个要点，补上课件跳过的推导，解释图表、公式和代码；例子页、续页和前一页合在一起讲。
- **每句话都标来源**：`[课件 p.N]` 表示课件上有，`[补充]` 表示讲解补充的内容。点击标签会跳到对应的课件页。拿不准的地方标"待核实"。
- **交互式习题**：先给题目分析，再逐级给提示，完整解答默认隐藏。课件上印着答案的页先遮住。
- **方便阅读**：可跳转的目录、术语表、补充内容底色开关、浅色/深色主题，开头写着预计阅读时间。公式用 KaTeX，代码用 highlight.js。
- **可以发到手机上看**：`--standalone` 会生成一个单文件 HTML，课件图都嵌在里面。
- **模型和脚本分工**：模型看懂每页图片、切节、讲解。提取、校验、渲染由 Python 脚本完成。讲解先通过 JSON Schema 和一组规则检查（页码覆盖、来源、公式语法、提示是否泄露答案等），然后才会渲染成页面。

## 安装

需要 Claude Code，以及 Python 3.10 或更高版本。

把 `lecture-explainer/` 文件夹复制到个人 skill 目录或项目的 skill 目录：

```bash
# 个人：所有项目都能用
cp -r lecture-explainer ~/.claude/skills/

# 或只在某个项目里用
cp -r lecture-explainer <你的项目>/.claude/skills/
```

依赖（PyMuPDF、Jinja2、jsonschema）会在第一次使用时自动装进 `~/.lecture-explainer/venv`，大约需要 1 分钟，不会改动系统的 Python 环境。

## 使用

把一门课的课件 PDF 放在同一个文件夹里，例如：

```
my-course/
└── lectures/
    ├── Lec-Overview.pdf
    ├── Lec-SQL.pdf
    └── ...
```

然后在 Claude Code 里输入：

```
/lecture-explainer my-course L04
```

参数是课程目录（或某个 PDF）和讲次。讲次可以写编号、文件名或主题（如 `SQL`），不写时 Claude 会问你。

为了避免误触发（随口问一个课件上的问题，却启动了整讲讲解），这个 skill 设成了只能手动调用：Claude 不会自己启动它，必须输入 `/lecture-explainer`。

启动后 skill 会自动：

1. 生成 `course.json`，按 PDF 创建日期排出讲次顺序（L01、L02……）
2. 提取每页图片和文字
3. 把这一讲切成若干节
4. 用 subagent 并行讲解各节（同时最多 4 个）
5. 校验，然后生成 `my-course/output/<讲次>/index.html`

用浏览器打开 `index.html` 即可（需要联网加载 KaTeX 和 highlight.js）。中途中断了，在同一个对话里说"继续"，或者在新对话里再运行一次同样的命令，就会接着做，已完成的部分不会重做。

一讲 50–90 页大约需要 15–40 分钟。

## 开发

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest
```

测试只用代码合成的 PDF。

目录结构：

```
lecture-explainer/
├── SKILL.md                  # 给 Claude 的流程说明
├── scripts/
│   ├── lx.py                 # 统一入口：init / extract / prepare / validate / render / setup
│   ├── bootstrap.py          # 自动建虚拟环境、装依赖
│   ├── extract.py            # PDF → 每页图片 + 文字
│   ├── prepare.py            # 检查切节，生成每个讲解单元的输入包
│   ├── validate.py           # 讲解 JSON 的格式和规则检查
│   ├── render.py             # 讲解 JSON → HTML
│   └── schema/               # JSON Schema
├── references/               # 切节指南、讲解指南、JSON 格式说明
└── assets/template.html      # 页面模板
```

`PLAN.md` 是完整的设计文档和开发记录。

## 局限

- 目前主要在 PowerPoint 导出的 PDF 上测试过。Beamer、扫描版 PDF 还没有专门适配。
- 讲解由模型生成，可能出错。来源标签和"待核实"标记可以帮助判断哪些内容需要对照课件核实。
- 讲解语言目前是中文。

## 版权说明

本仓库只包含代码。请只对你有权使用的课件运行这个 skill，也不要公开发布由他人课件生成的页面，因为页面里有课件每一页的截图。

## License

[MIT](LICENSE)
