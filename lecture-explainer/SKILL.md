---
name: lecture-explainer
description: 把课程课件 PDF（PowerPoint 或 Beamer 导出）逐页讲解成"左边课件原页、右边中文讲解"的 HTML 学习笔记：补全老师跳过的推导，解释图表、公式和代码，每句话标注来源（课件第几页，还是讲解补充），习题给逐级提示、答案默认隐藏。当用户想看懂、预习或复习课件，要讲解 lecture slides、课件、PPT，或者为某门课生成讲义、学习笔记时使用。
allowed-tools: Bash(python *lx.py*) Bash(py -3 *lx.py*) Bash(python3 *lx.py*)
---

# 课件讲解（lecture-explainer）

把一讲课件 PDF 变成 `<课程目录>/output/<讲次>/index.html`：左边课件原页，右边逐页讲解。

分工：看懂课件、切节、讲解由你和 subagent 完成；提取、校验、渲染由脚本完成。不要绕过脚本自己生成图片或 HTML。

## 运行脚本

所有脚本都通过一个入口运行，下文把这条命令简写为 `LX`：

```
python "${CLAUDE_SKILL_DIR}/scripts/lx.py" <子命令> ...
```

- `python` 不存在时依次换成 `py -3`、`python3`。
- 第一次运行会自动建虚拟环境、装依赖（约 1 分钟），之后很快。
- 输出里出现"需要 Python 3.10"或"安装依赖失败"时，把输出原样告诉用户并停下。不要自己去装 Python。
- 路径里有空格时加引号。

## 开始之前

告诉用户：一讲 50 到 90 页大约需要 20 到 40 分钟；中途中断也没关系，再说一次"继续讲解"就会接着做，已完成的部分不会重做。

## 第 1 步：确定课程目录和讲次

- **课程目录**是存放一门课所有课件的文件夹。里面有 `lectures/` 子目录时课件放在那里，没有时课件直接放在课程目录里。用户只给了一个 PDF 时，用它所在的文件夹作课程目录。
- 运行 `LX init <课程目录>`。没有 `course.json` 时会生成一份，讲次按 PDF 创建日期排序；已有时只把新增的 PDF 追加在后面。它会打印每一讲的编号、日期、页数、文件名和标题。
- 看一眼顺序是否合理，例如概述、导论应该在最前面。不合理时直接修改 `course.json` 里 `lectures` 的顺序，按新顺序重新编号 L01、L02……。只有这门课还没有任何 `output/` 时才能重新编号。顺序的事不要问用户。
- 根据用户的话确定讲哪一讲（编号、文件名或主题都可以），对不上时再问。

## 第 2 步：提取

```
LX extract <课程目录> <讲次>
```

生成每页图片和 `work/pages.json`、`work/titles.txt`。课件没变时自动跳过。报错（文件不存在、有密码）时告诉用户并停下。

## 第 3 步：切节（你来做）

- `work/outline.json` 已存在、并且 `LX prepare <课程目录> <讲次>` 能通过时，跳过这一步。
- 否则读 `references/outline-guide.md`，按它的要求读 `work/titles.txt`，写出 `work/outline.json`。
- 运行 `LX prepare <课程目录> <讲次>`。报错时按提示修改 `outline.json`，直到通过。通过后它会生成 `work/units.json` 和每个讲解单元的输入包。

## 第 4 步：逐单元讲解（交给 subagent）

1. 读 `work/units.json`。对每个单元运行 `LX validate <课程目录> <讲次> --unit <单元>`，第一行显示"通过"的单元已经完成，跳过。
2. 剩下的单元按顺序启动 subagent，同时最多 4 个在跑：有一个结束就补上下一个，不用等同一批的其他单元。启动每个单元前先运行 `LX prepare <课程目录> <讲次> --unit <单元>`：上一单元已经写完时，输入包会带上它的小结用来衔接；还没写完也不用等，直接启动。
3. 给每个 subagent 的指令如下。把尖括号换成实际值，路径一律写绝对路径（subagent 的工作目录不一定是课程所在的目录）：

   > 你负责课件讲解 skill 的一个讲解单元。输入包是 `<课程目录>/output/<讲次>/work/sections/<单元>.input.json`。先读输入包，再读它 `read_first` 里列出的两份指南，严格照做。写完后运行 `python "${CLAUDE_SKILL_DIR}/scripts/lx.py" validate <课程目录> <讲次> --unit <单元>`，有错就改，直到第一行显示"通过"。只写输入包里的 `output_file`，不要改其他任何文件。最后用一两句话报告：是否通过，哪些地方看不清或拿不准。

4. 每个 subagent 结束后，你自己再跑一次 `validate --unit` 确认。没通过的，把错误发回给同一个 subagent 修改，最多两轮；仍不通过就记下来，继续做后面的单元。
5. 不能用 subagent 时，自己按同样的指令一个单元一个单元地做。

## 第 5 步：检查整讲并生成页面

```
LX validate <课程目录> <讲次>
LX render <课程目录> <讲次>
```

第一条检查整讲并写 `work/validate_report.json`。第二条生成 `index.html`；还没讲完或没通过校验的页也会照常生成，页面上会标出来。

## 第 6 步：向用户报告

- `index.html` 的完整路径，告诉用户直接用浏览器打开
- 讲解了多少页、跳过了哪些页、有几处"待核实"（`render` 的输出里有）
- 没通过校验的单元或页（如果有）
- 如果这次生成了 `course.json`，说明定下的讲次顺序

用户想在手机上看、或者要把页面发给别人时，运行 `LX render <课程目录> <讲次> --standalone`，另外生成 `<讲次>-standalone.html`：课件图都嵌在这一个文件里，不需要旁边的 `img/` 文件夹。

## 重做某一部分

- **重新切节**：删掉 `work/outline.json`，从第 3 步开始；`validate` 会用 W8 提示旧的单元讲解文件，把它们删掉。
- **重讲某个单元**：删掉 `work/sections/<单元>.json`，再做第 4 步。
- **课件换了新版本**：从第 2 步开始，`extract` 会发现 PDF 变了并重新提取；之后重新切节。

## 参考文件

- `references/outline-guide.md`：切节规则，第 3 步读
- `references/explain-guide.md`、`references/schema.md`：讲解规则和 JSON 格式。subagent 会读；你在第 4 步自己讲解时也要读
