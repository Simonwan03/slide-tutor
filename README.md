# slide-tutor

**English** | [中文](README.zh-CN.md)

A [Claude Code](https://claude.com/claude-code) skill that turns lecture-slide PDFs into a side-by-side study page: the original slide on the left, a concise explanation on the right, and every sentence tagged with where it came from.

> The explanations are written in **Chinese**, with English technical terms kept as they are.

## What you get

One HTML page per lecture. Each row of the page looks like this:

| Left: the original slides | Right: the explanation |
|---|---|
| Slide 12 (image) | **Slides 12–13 · Example** |
| Slide 13 (image) | Key point one … `[课件 p.12]` |
| | A derivation the slide skipped … `[补充]` |
| | ▸ Hint 1 ▸ Hint 2 ▸ Show solution |

- **Only the key points.** Each slide, or group of adjacent slides, gets 1–3 points. Skipped derivations are filled in, and diagrams, formulas and code are explained. Example slides and "(contd.)" slides are explained together with the slide before them.
- **Every sentence has a source.**
  - `[课件 p.N]` means "on slide N". Click the tag to jump to that slide.
  - `[补充]` means "added by the explanation".
  - Anything the model is unsure about is marked "待核实" ("to verify").
- **Interactive exercises.** You get an analysis first, then hints one at a time, and the full solution stays hidden until you click. Slides that print the answer are covered.
- **Easy to read.**
  - A clickable table of contents and a glossary.
  - A toggle that highlights the added material.
  - Light and dark themes.
  - An estimated reading time at the top.
- **Readable on your phone.** You can export the page as a single HTML file with all slide images embedded.

## Quick start

### 1. Check what you need

- Claude Code, in the terminal, the desktop app or an IDE.
- Python 3.10 or newer. To check, run `python --version`; on Windows, `py -3 --version` also works.

You don't need to install anything else by hand. The Python packages (PyMuPDF, Jinja2, jsonschema) are installed automatically the first time you use the skill. They go into their own environment at `~/.lecture-explainer/venv`, so your system Python is left alone. This takes about a minute, once.

### 2. Install the skill

macOS / Linux:

```bash
git clone https://github.com/Simonwan03/slide-tutor.git
mkdir -p ~/.claude/skills
cp -r slide-tutor/lecture-explainer ~/.claude/skills/
```

Windows (PowerShell):

```powershell
git clone https://github.com/Simonwan03/slide-tutor.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse slide-tutor\lecture-explainer "$HOME\.claude\skills\"
```

To check that it worked, type `/lecture` in Claude Code. `/lecture-explainer` should appear in the list; if it doesn't, restart Claude Code.

> If you only want the skill in one project, copy the folder into `<your-project>/.claude/skills/` instead.

### 3. Put your slides in a folder

Put the PDFs of one course in a single folder. A `lectures/` subfolder is optional:

```
my-course/
└── lectures/
    ├── Lec-Overview.pdf
    ├── Lec-SQL.pdf
    └── ...
```

### 4. Run it

Open Claude Code in the folder that contains `my-course/`, then type:

```
/lecture-explainer my-course SQL
```

- **The first argument** is the course folder, or a single PDF.
- **The second argument** is the lecture to explain. You can give its number (`L04`), part of the file name, or the topic (`SQL`). If you leave it out, Claude asks you.

The skill then runs on its own:

1. It sorts the PDFs into lecture order (`L01`, `L02`, …) and saves the order in `my-course/course.json`.
2. It extracts each slide as an image, plus its text.
3. It splits the lecture into sections.
4. It explains the sections in parallel, with up to 4 subagents at once.
5. It checks the explanations and builds the page.

A 50–90 slide lecture takes about 15–40 minutes.

### 5. Open the result

```
my-course/
├── course.json            # lecture order (generated)
└── output/
    └── L04/
        ├── index.html     # ← open this in your browser
        ├── img/           # slide images
        └── work/          # intermediate files
```

The page needs an internet connection, because it loads KaTeX and highlight.js from a CDN.

## FAQ

**Why doesn't Claude start this skill on its own?**
This is on purpose. One run covers a whole lecture and uses roughly a million tokens. To keep a casual question about a slide from starting a full run, the skill only starts when you type `/lecture-explainer`.

**The run was interrupted. Do I start over?**
No. In the same conversation, say "continue". In a new conversation, run the same command again. Finished sections are not redone.

**How do I read it on my phone?**
In the same conversation, ask for the standalone version, for example "I want to read this on my phone". You get `L04-standalone.html` next to `index.html`. It is a single file with all images embedded, so you can send it to your phone.

**One section came out badly. Can I redo just that part?**
Yes. Delete `output/L04/work/sections/<section>.json` and run the command again. Only that section is rewritten.

**The lecture order is wrong.**
Edit the order in `course.json` before you generate any lecture.

**Which PDFs work?**
It is tested mainly on PDFs exported from PowerPoint. Beamer PDFs should work. Scanned PDFs aren't specially supported.

## Limitations

- The explanations are generated by a model and can be wrong. Use the source tags and the "待核实" marks to see what to check against the slides.
- Explanations are currently only in Chinese.

## Copyright

This repository contains code only. Only run the skill on slides you have the right to use, and don't publish pages generated from other people's slides: every page contains screenshots of all the slides.

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m pytest                       # macOS/Linux: .venv/bin/python
```

The tests use only PDFs generated by code.

The model reads the slides, splits the lecture into sections and writes the explanations. Python scripts do the extraction, checking and rendering. Each explanation must pass a JSON Schema plus a set of checks before it is rendered:

- every page is covered
- every sentence has a source
- the math syntax is valid
- hints don't give away the answer

```
lecture-explainer/
├── SKILL.md              # workflow instructions for Claude
├── scripts/
│   ├── lx.py             # single entry point: init / extract / prepare / validate / render / setup
│   ├── bootstrap.py      # creates the venv and installs dependencies
│   ├── extract.py        # PDF → slide images + text
│   ├── prepare.py        # checks the section outline, builds each unit's input
│   ├── validate.py       # checks the explanation JSON
│   ├── render.py         # explanation JSON → HTML
│   └── schema/           # JSON Schemas
├── references/           # guides for outlining and explaining, JSON format
└── assets/template.html  # page template
```

[PLAN.md](PLAN.md) holds the full design notes and the development log, in Chinese.

## License

[MIT](LICENSE)
