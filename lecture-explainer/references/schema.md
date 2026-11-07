# 讲解 JSON 格式

每个讲解单元写一个 JSON 文件，路径是输入包里的 `output_file`。格式的权威定义是 `scripts/schema/section.schema.json`，本文是它的说明和完整示例。

## 顶层

```json
{
  "lecture": "L03",
  "unit": "s05",
  "section": "s05",
  "section_summary": "……",
  "pages": [ 讲解组, … ]
}
```

| 字段 | 说明 |
|---|---|
| `lecture` | 讲次编号，照抄输入包 |
| `unit` | 讲解单元编号，照抄输入包（可能是 `s02-2` 这样的块编号） |
| `section` | 所属节编号，照抄输入包里的 `section.id` |
| `section_summary` | 本单元讲了什么，两三句话。下一个单元会读到它，用来衔接 |
| `pages` | 讲解组的列表，按页码顺序排列。输入包 `pages` 里的每一页都要恰好落在一个组里 |

## 讲解组

单独讲一页时写 `page`，连续几页合在一起讲时写 `range`，两者只能有一个：

```json
{"page": 31, "kind": "text", "gist": "……", "blocks": [ … ]}
{"range": [35, 36], "kind": "formula", "gist": "……", "blocks": [ … ]}
```

| 字段 | 说明 |
|---|---|
| `page` | 单独讲的那一页 |
| `range` | `[第一页, 最后一页]`，两端都包含，最多 4 页，必须是本单元里连续的页 |
| `kind` | 这一组的主要内容类型：`text` 文字为主、`formula` 公式、`table` 表格、`figure` 示意图或图片、`code` 代码、`exercise` 习题、`divider` 课程标题页或节分隔页 |
| `gist` | 一句话概括这一组在讲什么 |
| `blocks` | 讲解内容，通常 1 到 3 个 block，按阅读顺序排列 |
| `terms` | 本组定义的术语，可省略（见下文） |

## block

每个 block 都有 `kind` 和 `title`。`title` 是简短的小标题，会成为组内目录的条目。

### 文字类：`explain`、`figure`、`example`、`pitfall`

```json
{"kind": "explain", "title": "两种写法的区别", "segments": [ segment, … ]}
```

- `explain`：一般讲解
- `figure`：讲图（示意图、表格结构）
- `example`：用示例数据举例
- `pitfall`：常见误解、容易错的地方、课件里会误导人的错误

### `derivation`：推导

```json
{
  "kind": "derivation",
  "title": "关系代数写法从里往外读",
  "steps": [
    {"math": "\\sigma_{color='red'}(Boats)", "why": "先从 Boats 中选出红色的船", "src": {"type": "slide", "pages": [36]}}
  ]
}
```

- `math`：这一步的式子，直接写 LaTeX，不要加 `$`
- `why`：这一步做了什么、为什么成立，可以含行内公式 `$…$`；它是你的解释，渲染时一律按解释显示
- 每一步都有自己的 `src`，指的是 `math` 里的式子从哪来：原样出现在课件上（包括作为更大式子里连续的一段）标 `slide`，改写或推出来的标 `supplement`

### `table`：表格

```json
{
  "kind": "table",
  "title": "选出评分高于 7 的水手",
  "caption": "第 8 页实例 S2 上 $\\sigma_{rating>7}$ 的结果",
  "header": ["sid", "sname", "rating", "age"],
  "rows": [["28", "yuppy", "9", "35.0"], ["58", "rusty", "10", "35.0"]],
  "src": {"type": "supplement"}
}
```

- 所有单元格都是字符串，每行的列数和 `header` 一样；单元格里可以用行内公式
- `caption` 可省略，可以含行内公式
- `src` 指的是表里的数据：照抄课件标 `slide`，算出来或自拟的标 `supplement`

### `code`：代码

```json
{
  "kind": "code",
  "title": "SQL 写法",
  "lang": "sql",
  "code": "SELECT S.sname\nFROM Sailors S\nWHERE S.rating > 7",
  "src": {"type": "slide", "pages": [16]}
}
```

- `code` 原样保留换行和缩进
- 需要解释时放在后面的 `explain` block 里

### `exercise`：习题

```json
{
  "kind": "exercise",
  "title": "习题：找出预订过所有红船的水手",
  "answer_on_slide": false,
  "analysis": [ segment, … ],
  "hints": [ [ segment, … ], [ segment, … ] ],
  "solution": [ block, … ]
}
```

- `answer_on_slide`：课件上印着答案时写 `true`，网页会先遮住课件原图；没有答案时写 `false` 或省略
- `analysis`：题目解析，直接显示
- `hints`：逐级提示，每条提示是一个 segment 列表，点一次展开一条
- `solution`：完整解答，默认隐藏；里面可以放 `explain`、`derivation`、`table`、`code` 等 block，但不能再嵌套 `exercise`

## segment 和 src

segment 是一句话加它的来源：

```json
{"text": "这两页都在找评分高于 7、并且预订过红色船的水手。", "src": {"type": "slide", "pages": [35, 36]}}
```

`src` 有三种：

| 写法 | 含义 |
|---|---|
| `{"type": "slide", "pages": [36]}` | 内容能在这些页上直接看到 |
| `{"type": "supplement"}` | 课件上没有，是你补充的 |
| `{"type": "memory", "lecture": "L02", "page": 15}` | 之前讲次的内容（跨讲次记忆实现之前不要用） |

任何 segment、推导步骤、表格、代码都可以加 `"status": "unverified"`，表示你没把握，需要核实。

## terms

```json
"terms": [
  {"term": "tuple relational calculus", "aliases": ["TRC", "元组关系演算"], "kind": "term", "definition": "用带量词的逻辑公式描述查询结果中元组应满足的条件", "page": 33}
]
```

- 只列在本组被定义或正式介绍、值得记住的术语或概念；`page` 写定义所在的那一页
- `term` 用课件里的英文原名；`aliases` 放缩写和中文译名
- `kind`：`term` 是名词定义，`concept` 是更大的知识点（定理、方法、算法）
- `definition` 用中文，一两句话

## 完整示例

篇幅也照这个来：每组只讲要点，几句话说清楚就够。

```json
{
  "lecture": "L03",
  "unit": "s05",
  "section": "s05",
  "section_summary": "本节介绍关系演算（relational calculus），重点是元组关系演算（TRC）只描述结果满足的条件，不规定计算步骤。",
  "pages": [
    {
      "range": [35, 36],
      "kind": "formula",
      "gist": "同一个查询的关系代数写法和 TRC 写法，第 36 页是 TRC 的简写",
      "blocks": [
        {
          "kind": "explain",
          "title": "两种写法的区别",
          "segments": [
            {"text": "这两页都在找评分高于 7、并且预订过红色船的水手。", "src": {"type": "slide", "pages": [35, 36]}},
            {"text": "关系代数写的是计算步骤，TRC 只写结果要满足的条件，这是两者最大的区别。", "src": {"type": "supplement"}},
            {"text": "课件里加下划线的等式就是连接条件。", "src": {"type": "slide", "pages": [36]}}
          ]
        },
        {
          "kind": "derivation",
          "title": "关系代数写法从里往外读",
          "steps": [
            {"math": "\\sigma_{color='red'}(Boats) \\bowtie Reserves", "why": "先选出红船，再和 Reserves 连接，得到红船的预订记录", "src": {"type": "slide", "pages": [36]}},
            {"math": "\\pi_{sname}\\big(\\ldots \\bowtie \\sigma_{rating>7}(Sailors)\\big)", "why": "再连接评分高于 7 的水手，最后只保留名字", "src": {"type": "supplement"}}
          ]
        }
      ],
      "terms": []
    },
    {
      "page": 49,
      "kind": "exercise",
      "gist": "习题：用关系代数找出预订过所有红船的水手",
      "blocks": [
        {
          "kind": "exercise",
          "title": "习题：找出预订过所有红船的水手",
          "analysis": [
            {"text": "题目里的“所有”提示要用除法（division），除法在第 20 页讲过。", "src": {"type": "slide", "pages": [20]}}
          ],
          "hints": [
            [{"text": "先想清楚两个关系：每个水手预订过哪些船，以及所有红船有哪些。", "src": {"type": "supplement"}}],
            [{"text": "除法 $A/B$ 返回的是：和 $B$ 中每一个元组都配对出现过的那些值。", "src": {"type": "slide", "pages": [20]}}]
          ],
          "solution": [
            {
              "kind": "derivation",
              "title": "用除法写出来",
              "steps": [
                {"math": "\\pi_{sid,bid}(Reserves) \\,/\\, \\pi_{bid}(\\sigma_{color='red'}(Boats))", "why": "商就是预订过全部红船的水手 sid", "src": {"type": "supplement"}},
                {"math": "\\pi_{sname}\\big((\\ldots) \\bowtie Sailors\\big)", "why": "再和 Sailors 连接，取出名字", "src": {"type": "supplement"}}
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

示例里第 49 页的题目只是示意，用来展示格式。
