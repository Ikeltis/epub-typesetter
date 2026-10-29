# 03 CSS 与中文排版规范

> 基准：EPUB 3.3 及配套规范；目标是「任何符合 EPUB 3 的阅读系统（RS）」，不针对具体阅读器。
> 标记：【补】= 书外补充；【需实测】= 支持情况无把握，上线前须在真实 RS 上验证；无标记的数值规则来自原书或其明确推论。
> 相关文件：容器/OPF/导航见 `01_容器包文档与导航.md`；语义标签与 `epub:type` 见 `02_内容文档与语义结构.md`；样式模板见 `04_排版样式模板库.md`；字体嵌入/子集化/授权、图片规格见 `05_图片与字体资源.md`；标点、空格、引号等文本层规范化见 `06_中文文本规范化.md`。

---

## 1. 设计哲学：层叠、用户覆盖与渐进增强

### 1.1 谁覆盖谁

EPUB 是重排（reflowable）媒介：版面由 RS 在运行时根据屏幕、字号、用户设置计算，作者无法也不应该控制「一页放几行」。样式来源由低到高：

1. RS 内置默认样式（各家差异很大：段距、标题字号、列表缩进、链接色都不同）；
2. 作者样式（本书的 CSS：外链 `<link>`、`<style>`、内联 `style=""`）；
3. 用户设置（字体、字号、行距、页边距、主题色/夜间模式、「使用书籍自带样式」开关）。

要点：

- 用户设置**通常凌驾于作者样式之上**。典型实现（如 Readium CSS 一类）把用户设置作为额外样式表或 `!important` 声明注入，开启后会覆盖作者的 `font-family`、`font-size`、`line-height`、`text-align`、颜色等【补，实现因 RS 而异】。EPUB 3.3 的 RS 规范也允许 RS 提供用户样式并覆盖作者样式。
- 因此作者样式的角色是「**默认值与结构提示**」，而不是「最终外观」。不要与用户设置对抗：不写 `!important`（尤其是 `font-*`、`line-height`、`color`、`background`），不写死 px，不写死颜色。
- 同源内的优先级仍按 CSS 层叠：内联 > `#id` > `.class`/属性/伪类 > 元素；同优先级后写者胜；`<style>` 须在 `<link>` 之后才压过外链。工具做样式合并必须按特异性（specificity）判断，不能只看文件顺序。
- 全书一个主样式表（`stylesheet.css`）；字体声明可独立 `fonts.css`；不用 `@import`（被忽略的风险，且被引入文件也须在 manifest 中登记）。

### 1.2 渐进增强：三层模型

| 层 | 内容 | 失效后果 | 规则 |
|---|---|---|---|
| L0 结构 | 语义 HTML：h1–h6、p、blockquote、ol/ul、figure/figcaption、table、ruby、aside | 无（零 CSS 也可读） | 信息全部放在 DOM 与文本里，不放进 CSS |
| L1 基线 | CSS 2.1 级属性：margin、text-indent、text-align、font-size(em)、line-height、border、float | 外观退回 RS 默认，仍可读 | 保证关键排版（缩进、段距、标题层级）只依赖 L1 |
| L2 增强 | `line-break`、`text-emphasis`、`ruby-*`、`writing-mode`、`text-combine-upright`、`text-wrap`、`break-*`、`rgba()`、`@media`、`:lang()` | 退回 L1 外观，**不得造成内容丢失或错位** | 每条 L2 声明必须能「失效即降级」 |

判定「L2 声明是否合格」的三问：① 被忽略后文字还在、顺序对、可读吗？② 有没有把含义仅靠颜色/伪元素 `content` 表达？③ 有没有因它被忽略而出现重叠或溢出？任一为否则改写。

### 1.3 CSS 支持很弱（或被用户关闭作者样式）时的保底清单

- 缩进/段距丢失 → 段落仍是独立 `<p>`，RS 默认通常有段距；**禁止**用 `<br/>` 堆叠分段、用全角空格/`&nbsp;` 做缩进、用空 `<p>` 做空行。
- 标题样式丢失 → 仍是 `h1–h6`，目录与导航不受影响；**禁止**用加粗 `<p>` 冒充标题。
- 诗/信/引文的缩进丢失 → 仍是 `blockquote`/成组 `p`，行与行仍分行；诗句行用独立 `<p>` 而非 `<br/>` 时，丢样式也不会连成一片。
- 图注丢失居中 → `figure/figcaption` 仍在 DOM 中相邻。
- 注释：默认做成书末尾注文件（04 §4.12），弹注不可用时点注号跳到书末、↩ 返回；注文**不得 `display:none` 隐藏**。
- 所有图片必须有 `alt`；重要信息不做成纯图片。
- 颜色、背景、`::before/::after` 只做装饰。

---

## 2. EPUB 3.3 对 CSS 的要求与限制【补】

> 以下按我对规范的理解整理，措辞强度（MUST/SHOULD）以 EPUB 3.3 Core / Reading Systems 原文为准，落地前对照核实。

| 主题 | 现状与策略 |
|---|---|
| CSS 的地位 | `text/css` 是核心媒体类型；XHTML 内容文档可用外链、`<style>`、内联。RS 须支持 CSS，但**不保证支持每个属性**（尤其较新的 CSS3/4 属性）。策略：L1 打底，L2 增强（§1.2）。 |
| `-epub-` 前缀 | EPUB 3.0.x 曾定义一批带 `-epub-` 前缀的属性（如 `-epub-writing-mode`、`-epub-text-emphasis`、`-epub-hyphens`、`-epub-line-break`、`-epub-word-break`、`-epub-text-orientation`、`-epub-text-combine`）。这些属性后来在标准 CSS 中以无前缀形式落地，3.2 之后规范不再把前缀版作为必需。策略：**新输出只写无前缀标准属性**；对已有的 `-epub-*`/`-webkit-*` 声明，保留并补写无前缀版本（无前缀写在最后）；不新增 `-epub-`。`-webkit-` 仅为旧 WebKit 系 RS 保留（`writing-mode`、`text-emphasis`、`hyphens`、`text-combine` 等），现代 RS 忽略它无害。 |
| `direction` / `unicode-bidi` | 规范要求（或强烈建议）文字方向通过 HTML `dir` 属性与 `<bdo>` 控制，作者不应用这两个 CSS 属性。工具发现应改写为 `dir`（详见 02）。竖排用 `writing-mode`，不是 `direction`。 |
| `position` | 规范未全面禁止，但在重排内容中 `absolute/fixed` 把元素移出文档流，字号或屏宽一变就重叠/截断，且各 RS 分页（多列）模型对定位元素处理不一致。策略：正文流内**不使用** `position:absolute/fixed`；`relative` 仅允许微调行内元素（如上标位置）且需配套降级；需要「居中/下沉」用 margin（章首见 §6）；封面用整页图片或 SVG（见 04）。 |
| 脚本 | JS 只在「脚本化内容文档」中被允许，RS 可以不执行（多数电子墨水设备不执行）。策略：**排版不依赖 JS**；不用 `:hover`/`:target`/`:checked`/`animation` 承载信息；清理时可移除动画。 |
| 视口单位与 100% 高度 | 分页由 RS 用多列或自有分页实现，`vh`/`vw`、`height:100%` 的参照系因 RS 而异【需实测】。策略：文字相关尺寸不用 vh/vw；仅封面整页图允许 `max-height:100vh`（并有 SVG 方案，见 04）。 |
| 媒体查询 | `@media`（宽度、方向、`prefers-color-scheme`）是否被评估取决于 RS【需实测】。策略：只用于**增强**（如窄屏取消绕排、夜间模式图片处理），基线样式不放在 `@media` 里。 |
| 自定义属性 `var()` | 现代引擎支持，但旧阅读系统不支持，且用户样式注入机制可能与之冲突【需实测】。策略：输出样式表**不使用** `var()`、`@layer`、CSS 嵌套、`:has()`；可在软件内部用 token 渲染成展开后的样式表。 |
| 分页属性 | 同时写 `break-before/after/inside` 与旧名 `page-break-before/after/inside`（后者是前者的遗留别名，部分 RS 只认旧名）。只用于 `avoid`（标题后、图表内）与确有必要的 `always/page`（同文件内强制分页，极少用）。 |
| 其它 | `@font-face` 的 `url()` 与图片、字体须在 manifest 登记（见 01/05）；`@charset "UTF-8"` 可写；外部网络 `url()` 不允许依赖（离线）；`!important` 一律避免（§1.1）。 |

固定布局（FXL，`rendition:layout=pre-paginated`）有自己的一套（定位、像素尺寸合理），本规范**只覆盖重排版**。

---

## 3. 单位取舍表

| 用途 | 推荐 | 避免 | 理由 |
|---|---|---|---|
| 正文字号 | 不设，或 `1em`/`100%` | px、pt、关键字外的绝对值 | 跟随 RS/用户字号 |
| 标题、小字字号 | `em`（相对正文：1.5em、.875em） | px、pt、`rem` 混用 | 只改基准即整体缩放；`em` 会逐层复合，嵌套小字号元素要避免连乘（如 `.small` 里再套 `.small`） |
| 首行缩进 | `2em`（= 2 个汉字） | px、全角空格、`&nbsp;` | 汉字字面框 = 1em |
| 段距、块间距 | `em`（.35–1.5em） | px | 随字号缩放 |
| 行高 | **无单位数** `1.6` | `1.6em`、`160%`、px | 无单位按每个元素自身字号计算；`em/%` 会把父元素计算后的绝对值继承给子元素，小字号子元素行距被撑大 |
| 悬挂缩进 | `margin-left:Nem; text-indent:-Nem` | 空格对齐 | 可判定 |
| 图片宽 | `%`、`max-width:100%` | 固定 px 大图 | 屏宽、字号变化 |
| 表格宽 | `%` | px | 同上 |
| 边框、分隔线粗细 | `px`（1px、2px） | em | 线条无需随字号缩放，避免忽粗忽细 |
| 阴影偏移 | px | em | 同上 |
| 章首下沉 | `margin-top` 用 `%`（相对容器**宽度**） | 固定 px、`vh` | 屏宽自适应；这是少数有意利用 % margin 的场景 |
| 行内小图（生僻字图） | `height:1em` | px | 随字号 |
| `rem` | 谨慎：仅用于不应复合的场景 | 与 `em` 在同一层级混用 | 现代 RS 支持，但根字号被谁设定因 RS 而异【需实测】 |
| `ch` | 不用于中文 | — | `ch` 为「0」的宽度，约 .5em，对汉字无意义 |
| `ic`、`lh`、`rlh`、`vw/vh`、`calc()`、`clamp()` | 不依赖 | — | 支持不一致【需实测】；基线样式不用 |
| `pt`、`cm`、`mm`、`in` | 不用 | — | 绝对单位与字号设置脱钩 |

字号换算（原书表，基准小四 = 1em = 16px）备查：五号 .875em、小五 .75em、四号 1.2em、三号 1.4em、二号 1.8em、一号 2.2em。出版术语「号」只用于理解原书稿，输出一律 em。

---

## 4. reset 与基线样式

目的：抵消各 RS 默认样式的差异，使后续所有数值（缩进、段距、标题）以同一起点计算。原则：**只 reset 后面会重设的属性**，不一刀切（不全局去掉链接颜色与下划线，正文链接需要可辨识）。

| 项 | 基线 | 说明 |
|---|---|---|
| `box-sizing` | `border-box` | 使 `width:% + padding` 可预期 |
| `html, body` | `margin:0; padding:0` | **页边距交给 RS**（RS 自带可调边距）。双重留白在小屏上浪费行宽。书中 `body{padding:.5em}` 仅在 RS 无边距时有意义，不作默认。 |
| `p` | `margin:0; text-indent:2em` | 缩进模式（见 §5） |
| `h1–h6` | `margin` 显式设；`font-weight` 显式设；`text-indent:0` | 避免 RS 默认粗体、`2em` 上下距、缩进叠加 |
| `ul, ol` | `margin:.5em 0; padding-left:2em` | 各 RS 默认缩进（40px、1.5em、有的为 margin-left）不一 |
| `blockquote, figure, dd` | 显式 `margin` | RS 默认 `margin:1em 40px` 之类 |
| `img` | `max-width:100%; height:auto; border:0` | |
| `table` | `border-collapse:collapse; border-spacing:0` | |
| `sup, sub` | `line-height:0; font-size:.7em` | 防止上标撑开行距；`smaller` 在个别 RS 过小 |
| `hr` | 显式 `border`、`margin` | |
| 行内元素 | `b/strong`、`i/em`、`u`、`s` 的外观显式设（§7.7） | |

---

## 5. 中文正文量化规则

| 项 | 默认值 | 允许范围 | 违例处理 |
|---|---|---|---|
| 正文字号 | 不设（`1em`） | 1em | 带 px/pt 的正文字号 → 改 em 或删除 |
| 小字号（注释、图注、表格） | .875em（表 .9em、图注 .9em） | .8–.95em | 不得大于正文；脚注/注文 ≥ .8em，再小会难读 |
| 行高 `line-height` | **1.6**（无单位） | 1.5–1.8；书/诗/引文/信 ≥ 1.4；含 ruby 的段 ≥ 2 | <1.4 报警；>2（非 ruby）报警；带单位 → 改无单位 |
| 首行缩进 `text-indent` | **2em** | 0 或 2em（偶见 1em 少儿书） | 非 0/2em 的值报告 |
| 段距（缩进模式） | **0** | 0 | — |
| 段距（无缩进模式） | .8em | .5–1em，且 `text-indent:0` | — |
| 「空一行」 | `margin-top:1.5em` | 1–2em | 用空 `<p>`、`<br/>` 做空行 → 改 margin |
| 对齐 | `text-align:justify` | justify / left | 见下 |
| 字距 `letter-spacing` | 正文 0 | 仅标题与儿童读物 ≤ .3em | 正文设字距 → 报告 |
| 孤行 | `orphans:2; widows:2` | 2 | 仅提示，RS 可忽略 |

**缩进与段距二选一**：段首缩进或加大段距，至少有一种（否则段落粘连）；同时具备（缩进 2em 且段距 ≥ .5em）视为冗余，浪费纵向空间。中文纸书传统 = 缩进 + 段距 0，本规范默认如此；网文式 = 无缩进 + 段距 .8em，作为「无缩进模式」主题选项（`p{text-indent:0;margin:.8em 0}`）。

**标题后首段**：中文出版惯例（与西文不同）是**标题后首段照常缩进**【补，参考中文排版需求 W3C clreq 一类惯例】。不缩进（`p.noindent`）只用于：① 原稿明确不缩进；② 引文/插图/表格打断后「接排」的同一段（原文续句）。笔记中「标题后、图后首段一律不缩进」的做法不作默认。

**两端对齐 `text-align:justify`**：

- 汉字按字间微调，效果好；含长英文/URL 的行会出现大空隙。对以西文为主的块、窄栏（表格内、悬挂缩进内）用 `text-align:left`（`.align-left`）。
- `text-justify`：**默认不设**（`auto`）。原书（及 Lithium 一类老阅读器）用的 `text-justify:inter-ideograph` 是旧草案值，现行 CSS Text 3 已无此值；而 `inter-character` 会把西文单词的字母也拉开，对中西混排有害。浏览器内核对 CJK 的 `auto` 已按字符分配间距【需实测】。
- 末行对齐：`text-align-last` 默认不设；仅表格竖表头（四字撑齐）等少数场景使用。
- 与 Standard Ebooks 的差异：SE 不设全局对齐，让阅读器的用户偏好决定；我们**保持** `body{text-align:justify}`，因为中文书惯例是两端对齐，用户在阅读器里仍可覆盖（08 决策 D10）。

**长行**：行过长（>40 字）降低可读性。是否限制 `max-width` 取决于 RS 的分栏策略，限制可能与分页冲突【需实测】，不作默认。

**分段防粘连**：RS 若丢失 CSS，缩进与段距同时消失 → 靠 DOM 里每段独立 `<p>`，见 §1.3。

---

## 6. 标题层级数值

### 6.1 规则

- 层级大小有序、轻重有序：同字体下 `h1 > h2 > h3 > h4 ≥ 正文`，相邻级字号差 ≥ .1em；不得倒置。
- 标题与正文比例：1.25 / 1.35 / 1.5 倍（对比越大越醒目，书籍反差不宜过强）；一级标题 ≤ 1.8em（竖直空间与换行考虑）。
- 标题字体用黑体族（无衬线）与宋体正文形成对比；标题 `font-weight:normal`（汉字合成粗体易糊；黑体本身已偏重）。多字重字体（如嵌入的思源黑体 SemiBold/Bold）可用 600/700。
- 标题 `text-indent:0`；默认左对齐，居中为变体（`.align-center`）。居中标题换行也居中。
- 副标题/引题字号**小于**主标题。
- 标题占行：章首（一级）占版面高度 ≤ 1/3；二级 2–3 行；三级 1–2 行；四级以下不占行。全书统一。
- 标题过长（> 版心宽 3/4）会换行：每行不少于 5 字、在语气处断、虚词不放行首。`text-wrap:balance` 可作增强（新版引擎支持，其余【需实测】）。
- 标题与后文更近（亲密性）：`margin-top ≥ 1.5 × margin-bottom`（章首除外）。
- 标题后不分页：`break-after:avoid`。

### 6.2 数值（章首与节内区分）

| 角色 | 选择器 | 字号 | margin（上 0 下） | 字体 |
|---|---|---|---|---|
| 章首标题（每文件第一个标题，章/篇/附录名） | `.chapter-title` | 1.5em | `25% 0 1.5em` | 黑体族 |
| 篇章页大标题 | `.part-title` | 1.8em | `35% 0 1em`，居中 | 黑体族 |
| 节标题（章内第一级） | `.section-title` | 1.3em | `2em 0 .8em` | 黑体族 |
| 小节标题（章内第二级） | `.subsection-title` | 1.15em | `1.6em 0 .6em` | 黑体族 |
| 四级 | `h4` | 1.05em | `1.3em 0 .4em` | 宋体（继承），粗体 |
| 五、六级 | `h5, h6` | 1em | `1em 0 .3em` | 继承，粗体 |
| 副标题 | `p.subtitle` | .9em | `-.8em 0 1.5em`（贴近主标题） | 楷体族 |

**章首 vs 节内**：章首的 `margin-top:25%`（相对容器宽度）是用 margin 实现的视觉下沉，只在「标题位于页面顶部」时合理。标题若出现在页中则留出大块空白。因此：

- **样式按角色类，不按标题数字**（2026-10-29 修订）：标题的数字只表达全书层级（04 §4.3：`h1` 只给书名页；无部时章 `h2`、节 `h3`；有部时部 `h2`、章 `h3`、节 `h4`），同一个角色在不同书里数字会不同。所以章、部、节、小节一律挂角色类 `.chapter-title` / `.part-title` / `.section-title` / `.subsection-title`，样式由类决定。
- 不带角色类的 `h1–h6` 只用下表「四级」以下的兜底样式，保证丢了类名也大小有序。
- 取值 25% 的依据：书为 30%；25% 在 360px 宽手机约 90px、平板 768px 约 190px，均不过半屏。范围 20–30%。
- 不要在同一文件中出现多个章首标题（每文件一个，见 02）。
- 章名带序号：整体放在一个标题里，序号与章名之间一个全角空格：`<h2 class="chapter-title">第一章　侯门庶子</h2>`。需要分两行显示时用 `span.title-num` / `span.title-name` 并设 `display:block`，全角空格保留在两个 span 之间（04 §4.3，08 决策 D1）。

---

## 7. CJK 专项

### 7.1 避头尾与 `line-break`

禁排规则（原书，对 `。？！，、；：` 等点号、引号括号书名号、省略号破折号）：

| 符号 | 规则 |
|---|---|
| `。？！，、；：` 及闭括号/闭引号/闭书名号 | 不可排行首 |
| 开引号 `“‘「『`、开括号 `（`、开书名号 `《` | 不可排行尾 |
| `……`、`——` | 不可排行首；各占 2 字，不可拆开（偶数个 `…`/`—`，不用单个） |
| 间隔号 `·` | 用全身 `·`（U+00B7）或 `・`，不排行首 |

实现分工：**避头尾由 RS 的排版引擎完成**，作者不能靠改文本避免（文本变一个字就全变）。作者能做的：

```css
body{ line-break:strict; word-break:normal; overflow-wrap:break-word; }
```

- `line-break:strict`：最严格的禁则集合（CSS Text 3 定义）；`normal` 对中文的避头尾已足够，差异主要在日文小假名与长音符，对中文影响小。写 `strict` 的理由是「明确声明意图」。不支持则按 RS 默认。旧的 `-webkit-line-break` 无需再写。
- `word-break:normal`：汉字本来可在任意两字之间断行。**原书的 `word-break:break-all` 会把英文单词拆开，不作默认**。含长 URL/长西文串的行内元素才加 `.break-all`（局部）。`word-break:keep-all` 是韩文用法，用在中文会禁止字间断行导致溢出，**禁用**。
- `overflow-wrap:break-word`：兜底，防止超长串撑破版面。
- `hyphens:manual`（旧 WebKit 加 `-webkit-hyphens`）：中文无意义，对西文关闭自动连字符，避免把英文词在奇怪位置加 `-`。
- `hanging-punctuation`（标点悬挂）：仅部分引擎支持，且与两端对齐的交互未充分验证【需实测】，不作默认。
- 文本层配合：连续标点成对（`……`、`——` 偶数个）、全角标点不被替换成半角（否则引擎不再识别为 CJK 标点而失去避头尾）——见 06。

### 7.2 标点挤压：`text-spacing-trim`【补，需实测】

背景：全角标点自带半个字宽的空白。连续标点（`。”`、`）。`、`，（`）与行首开括号处，中文排版要求「挤压」掉多余空白（开明式：句号、问号、叹号等全身，其余半身）。

- 原书结论：电子书不必处理，**保证中文用全角标点，挤压交给阅读器**。此结论仍成立。
- CSS Text 4 的 `text-spacing-trim` 提供控制：`normal`（默认，对相邻全角标点做挤压）、`space-all`（一律不挤压）、`trim-start`、`space-first`。Chromium 系较新版本已实现，其余引擎与 RS【需实测】。
- 策略：**默认不写该属性**（引擎默认即为启用挤压）。仅在需要「标点保持全宽对齐」的块（对照表、竖直对齐的诗行）可用 `text-spacing-trim:space-all`。
- 禁止靠手工半角空格、负 `letter-spacing` 去「挤」标点。

### 7.3 中西文混排与 `text-autospace`【补，需实测】

- 中文规范要求汉字与西文字母、数字之间有约 1/8–1/4 em 的间隔（不是整个半角空格）。CSS Text 4 的 `text-autospace`（`normal` ≈ `ideograph-alpha ideograph-numeric`）由引擎自动加此间隔；较新的 Chromium/WebKit 系有实现，其余【需实测】。
- 策略：文本里**不批量插入空格**（保留作者已有的；是否统一见 06）；样式表写 `text-autospace:normal` 作增强，不支持则忽略，退回「汉字西文紧贴」，仍可读。
- 西文字体：汉字字体含拉丁字形但往往不美观。**未嵌入字体时不强行指定西文字体**，由 RS 字体回落（字体回落以「字符」为单位）；嵌入字体时见 §8.4。
- 语言标注：以原书 `dc:language` 为准；需要新生成时简体写 `zh-Hans`、繁体写 `zh-Hant`（见 08 第 3 节）；大段西文用 `<span lang="en">`；`lang` 同时决定 CJK 字形（汉字「骨」「直」等地区字形差异）与连字符/断词策略，**缺失 `lang` 是常见错误**（02 检查）。
- 斜体：中文无真斜体，引擎合成的伪斜体难看。`<i>`、`<em>` 作用于汉字时，用楷体、着重号或黑体代替；西文（`lang="en"`、书名原文、学名、变量）保持斜体（§7.7）。
- 数字与单位：`10 kg`、`5 mm` 的空格保留；单位用正体；千位分隔符、小数点半身（见 06）。
- 数字用等宽/比例：表格数字列 `font-variant-numeric:tabular-nums`（支持则对齐，不支持无害）。

### 7.4 着重号 `text-emphasis`

中文着重号：横排在字**下**，竖排在字**右**。

```css
.dot{
  -webkit-text-emphasis:filled dot;          /* 旧 WebKit */
  -webkit-text-emphasis-position:under right;
  text-emphasis:filled dot;
  text-emphasis-position:under right;        /* 横排：下；竖排：右 */
}
```

- `under right` 在横排取「下」，竖排取「右」，一条声明两种书写模式都对。
- 降级：不支持则无着重号，文字仍在。若强调信息不可丢，同时保留 `<em>` 语义（RS/读屏可读出强调），不要只靠视觉。
- 默认 `em` 不画点（见默认样式表）；需要着重号的位置由软件识别（原书稿中的「着重点」）后加 `class="dot"`。专名号、书名号浪线：`text-decoration:underline wavy`（现代引擎支持，旧 RS 退回直线或无）【需实测】。
- 原书里加粗/变色作强调的，改为 `<em class="dot">` 或楷体，并报告（中文加粗滥用损伤版面）。

### 7.5 ruby 注音

结构（HTML5 标准，`<rb>` 已废弃，不写）：

```html
<ruby>床<rp>（</rp><rt>chuáng</rt><rp>）</rp></ruby>
```

```css
ruby{ ruby-align:center; ruby-position:over; }
rt{ font-size:.55em; font-weight:normal; text-indent:0; letter-spacing:0; line-height:1; }
/* 不要对 rp 设 display:none：不支持 ruby 的 RS 靠它显示括号降级 */
```

- 逐字一组：每字配自己的注音。多字词按词注音时用 `<ruby>中国<rt>zhōng guó</rt></ruby>`，但逐字更稳。
- `rt` 字号 .55em（书值；CSS 默认约 50%）。拼音字体须含带声调字母（ā á ǎ à ǖ ǘ ǚ ǜ），否则回落字体不一致；必要时嵌入子集字体（05）。
- 行高：含 ruby 的段 `line-height ≥ 2`，否则注音与上一行相碰；给整段加 `class="has-ruby"`（见 04）。
- 注音仅在 L2：不支持 ruby 的 RS 会把 `rt` 当正文，`rp` 括号让它读作「床（chuáng）」。
- `ruby-position`：横排 `over`；繁体台湾注音符号竖排时在右侧，`over` 在竖排即右侧。注音符号（ㄅㄆㄇ）排版从略。

### 7.6 竖排：`writing-mode` 与 `text-combine-upright`

竖排是**整本书**属性（不是段落变体）：

- OPF `<spine page-progression-direction="rtl">`（01）；
- CSS 在 `html` 上设 `writing-mode:vertical-rl`（`body` 继承），不要只设在 `p` 上。旧 RS 还要 `-webkit-writing-mode`、`-epub-writing-mode`（前缀写在无前缀之前）。

```css
html{ -epub-writing-mode:vertical-rl; -webkit-writing-mode:vertical-rl; writing-mode:vertical-rl; }
body{ text-orientation:mixed; }
.tcy{ -webkit-text-combine:horizontal; text-combine-upright:all; }   /* 横中横：2–4 位数字、「10月」 */
```

要点与对原书的更正：

1. **物理属性在竖排下含义改变**：`margin-top/bottom`、`padding-top`、`text-align:right`、`width/height` 仍是物理方向，但块方向变成水平。章首的 `margin-top:25%` 会变成「列首偏移」。竖排版须使用逻辑属性：`margin-block-start`、`margin-inline`、`padding-inline-start`、`text-align:start/end`、`max-inline-size`。竖排样式表独立成 `vertical.css`，在主样式表之后加载（04 §竖排）。
2. **缩进**：原书说「竖排不要缩进（缩进会每行换页）」是多看私有行为。标准 `text-indent:2em` 在竖排沿行方向（向下）缩进，**照常使用**【需实测】。
3. **标点**：竖排标点（句号逗号在字右上、引号竖形、省略号旋转）由字体的 `vert` 特性与引擎处理。**输入保持横排码位**：`「」『』`、`……`、`——`、`《》`；**不要手工替换成 `﹁﹂﹃﹄︙` 等竖排形式**（兼容码位依赖字体，且横竖切换时反向改写困难）。简体 `“”` 在竖排下字体常无竖形，竖排书统一用 `「」『』`（06 引号风格选项）。
4. **西文与数字**：`text-orientation:mixed`（默认）将西文旋转 90°；2–4 位数字、短缩写用 `.tcy` 横中横；长西文串在竖排下可读性差，建议改图或接受旋转。
5. **图片、表格**：竖排下宽高约束要重想；表格不建议竖排。
6. **着重号**用 `under right`（§7.4）；**注音**用 `over`（右侧）。
7. 双行夹注（小字双行）在 EPUB 中无法可靠实现，不做。
8. 浮动模拟竖排（`float:right; width:1em` 一字一列）是旧 RS 的变通写法，标点不会变形，**不采用**。

### 7.7 其他 CJK 文本样式

| 项 | 规则 |
|---|---|
| 斜体 | 汉字不用；`i`/`em` 斜体仅限西文（`lang="en"`、书名原文、学名、变量）；默认样式表中 `em` 对汉字取消斜体并改楷体 |
| 粗体 | 汉字合成粗体易糊。`strong` 允许（宋体族多有真粗体）；整段加粗改黑体类 |
| 下划线 | 用 CSS 类 `text-decoration`，不用 `<u>`；链接下划线保留 |
| 专名号 | 人名/地名下划线 `border-bottom:1px solid` 或 `text-decoration:underline`；书名号浪线 `underline wavy`（需实测） |
| 大小写 | 不依赖 `text-transform`，把大小写烘焙进文本 |
| 数字序号 | 不依赖 `list-style-type:cjk-ideographic`（RS 支持不一）；中文序号写成文本（`一、`），或用 `ol` 的阿拉伯数字 |

---

## 8. 字体

### 8.1 原则

1. **默认不指定正文字体**：`body` 不写 `font-family`，由 RS/用户选择（用户的字体偏好是最重要的阅读设置）。仅在嵌入字体或模板需要角色字体时才指定（标题、引文、诗、注文）。
2. 每个 `font-family` 末尾**必须有通用族**：`serif` 或 `sans-serif`（`monospace` 用于代码）。
3. 英文名优先于中文名（中文字体名在部分环境编码/匹配不稳），可附中文名作兜底。
4. 栈中不要写厂商私有字体名（本规范不收）。
5. 全书字体种类 ≤ 3–4 个角色（正文、标题、楷/仿宋、等宽）。

### 8.2 角色字体栈

不使用 CSS 变量，输出时展开：

| 角色 | 栈 |
|---|---|
| 黑体（标题、小标题、表头） | `"Source Han Sans SC","Noto Sans CJK SC","PingFang SC","Microsoft YaHei","SimHei",sans-serif` |
| 宋体（嵌入或需指定时的正文） | `"Source Han Serif SC","Noto Serif CJK SC","Songti SC","SimSun",serif` |
| 楷体（引文、图注、注文） | `"Kaiti SC","STKaiti","KaiTi",serif` |
| 仿宋（诗、前言、整段引文） | `"STFangsong","FangSong",serif` |
| 等宽 | `"Source Code Pro","SFMono-Regular","Menlo","Consolas","Courier New",monospace` |

- 各栈的系统字体可用性因平台而异：楷体、仿宋在 Android 与部分 RS 上可能缺失，此时回落到 `serif`（宋体族），**外观降级但可读**，不能把区分信息（如「这是引文」）只放在字体上，同时有缩进与左边距。
- 选字规则：正文衬线（宋体/明体）；标题、导语无衬线；仿宋用于标题下引文、古籍、整段文章；楷体用于少儿读物、短引文，不适合整书正文。不使用隶书、行楷、魏碑、艺术字（严肃书）。
- 不需要为「小标宋/大标宋」专门写栈：授权字体不可嵌入，系统常无；标题一律走黑体栈。
- 平台差异：`local()` 匹配的是字体**全名/PostScript 名**而非族名，书中的 `@font-face{font-family:"宋体";src:local(...)}` 别名法在各平台的命中不稳【需实测】。本规范用直接的 font-family 栈代替别名。

### 8.3 何时嵌入字体（CSS 侧）

嵌入、子集化、授权检查与 fsType 见 `05_图片与字体资源.md`，此处只列写法与触发条件。

| 情形 | 建议 |
|---|---|
| 一般小说/非虚构，用系统字体即可 | **不嵌入** |
| 含扩展区生僻字（U+3400–4DBF、U+20000 起）且系统字体不覆盖 | 嵌入**子集**字体作回落（仅含所用字符） |
| 拼音/注音（需带声调字母） | 系统字体可能不全 → 嵌入子集或检查覆盖 |
| 竖排标点需要 `vert` 字形且 RS 默认字体缺失 | 嵌入含 `vert` 的子集字体 |
| 品牌/设计强依赖的标题字体 | 嵌入子集（须授权允许） |
| 整本正文字体 | 若要「所见即所得」才嵌入；需知道用户选 RS 字体时可能不覆盖（取决于 RS「使用书籍字体」设置），体积也大 |

写法：

```css
/* 字体族名用不会与系统字体冲突的名字，不要叫「宋体」 */
@font-face{
  font-family:"Book Serif";
  src:url("../fonts/book-serif-subset.woff2") format("woff2"),
      url("../fonts/book-serif-subset.ttf") format("truetype");
  font-weight:400; font-style:normal;
}
body{ font-family:"Book Serif","Songti SC","SimSun",serif; }   /* 嵌入字体放最前，其后保留系统栈 */
```

- 格式：`woff2` 并附 `ttf/otf` 备选（`format()` 声明）；是否核心媒体类型见 05/01。
- 生僻字回落：把子集字体**附在 font-family 末尾**即可自动回落，不必给每个字包 `<span>`（`font-family:"宋体栈","Book Rare",serif`）。
- 子集字体与正文字体风格不协调是常见问题，只覆盖实际所需字符。

### 8.4 西文字体与标点码位冲突

中西混排常见做法是把西文字体放在栈首（拉丁字形更美）。但西文字体同样含有 `“ ” ‘ ’ — …`（U+2018–U+201D、U+2014、U+2026），栈首的西文字体会**抢走中文引号、破折号、省略号**，显示成窄的西文形状，破坏全角标点与挤压。解决：用 `unicode-range` 限制西文字体只管字母数字：

```css
@font-face{
  font-family:"Book Latin";
  src:local("Times New Roman"),local("Georgia"),url("../fonts/latin-subset.woff2") format("woff2");
  unicode-range:U+0020-007E,U+00A0-00FF,U+0100-024F;       /* 基本拉丁、拉丁1补、拉丁扩展，不含 U+2000–206F 标点 */
}
.mix{ font-family:"Book Latin","Book Serif","Songti SC",serif; }
```

`unicode-range` 对嵌入字体广泛支持，与 `local()` 联用的情况在 RS 里【需实测】。

---

## 9. 颜色与夜间模式

核心：**不为正文设置颜色和背景**。RS 的夜间/护眼主题通过覆盖或反转颜色实现；书里写死 `color:#000`、`background:#fff` 会导致夜间模式下「黑字黑底」或「白字白底」。

规则：

1. `body`、`p`、`h1–h6`、`li`、`td` **不设 `color`、`background`**。
2. 需要区分的装饰，用**不依赖颜色**的手段：字体、字号、缩进、`border`、`font-style`。
3. 必须用颜色的装饰（引用块底纹、表头底色、斑马纹）用半透明灰，对任意底色都可辨：`rgba(127,127,127,.12)`。边框用 `currentColor`（缺省即是）或 `rgba(127,127,127,.5)`。
4. 如果必须成对设色（如 callout 彩色底），**同时设 `color` 与 `background`**，对比度 ≥ 4.5:1（WCAG 2.x AA）【补】；不用纯黑/纯白，不用红字+绿底之类色盲冲突，不用颜色单独承载含义。
5. 链接颜色交给 RS；不做 `a{color:inherit;text-decoration:none}` 全局重置（仅目录、注释锚点可去下划线）。
6. 图片：线稿类透明 PNG 的黑线条在深色背景上消失，处理见 04 §插图。
7. 书中配色（暖白 `#f7f5f1`/近黑 `#221815`）仅作「纸色主题」候选，**由用户/主题选项而不是默认值引入**，并且成对写入 `body`。
8. 夜间模式增强可用 `@media (prefers-color-scheme: dark)`（是否被 RS 评估【需实测】），只用于 `img` 滤镜之类可降级的增强。
9. 原书的图注色 `#a52a2a`、词条色 `#069460` 不进默认样式表：用字体、大小区分。

---

## 10. 应避免的写法清单

| 写法 | 问题 | 替代 |
|---|---|---|
| `<br/>` 堆叠分段、空 `<p>` 空行、`<p>&nbsp;</p>` | 无语义，丢 CSS 后粘连，分页异常 | `margin-top`、独立 `<p>` |
| 全角空格/`&nbsp;`/`&emsp;` 做缩进 | 对齐不可调，用户改字号后错位 | `text-indent:2em` |
| `<font>`、`<center>`、`align=`、`<b><i><u>` 做外观 | 表现混入内容 | class + CSS；语义标签 `<strong>/<em>` |
| px/pt 做字号、缩进、行高 | 与用户字号设置脱钩 | em、无单位行高 |
| `!important` | 阻止用户设置/覆盖 | 提高特异性或调整顺序 |
| `position:absolute/fixed` 在流内 | 重叠、截断、分页异常 | margin、图片、float（限定场景） |
| 脚本、`:hover/:target` 承载信息 | RS 不一定执行 | 静态结构 |
| 正文写死 `color`/`background` | 夜间模式冲突 | 不写（§9） |
| `font-family` 写在 body 上强制正文字体（无嵌入） | 覆盖用户偏好；缺字体时回落不可控 | 不写 |
| `word-break:break-all` 全局、`keep-all` | 拆西文词；中文溢出 | `normal`；局部 `.break-all` |
| `text-justify:inter-ideograph` | 已废弃值 | 不写 |
| 对汉字用 `font-style:italic`、`font-weight:bold` 做强调 | 伪斜体、糊字 | 楷体、着重号、黑体类 |
| `rp{display:none}` | 破坏不支持 ruby 时的降级 | 不设 |
| `aside{display:none}` 隐藏注释 | 不支持弹注时注文丢失 | 保持可见，由 RS 处理弹注 |
| 用 `::before/::after` 的 `content` 生成序号、符号、文字 | 不可检索、读屏不读、RS 差异 | 写进文本 |
| 竖排使用物理 margin、手工替换竖排标点码位 | 方向错乱 | 逻辑属性；保持横排码位 |
| 用 `outline` 画框、`opacity` 做淡色、`column-*` 分栏 | RS 支持不一 | `border`、`rgba` 颜色；不分栏 |
| `border-collapse:collapse` 且依赖 1px 细线精确 | 个别 RS 双线 | 接受；或表格线只用 `border-top/left` 拼接 |
| `id` 选择器、复杂链式后代选择器、`:nth-child` 做关键样式 | 旧 RS 支持差，难维护 | class；斑马纹用显式 `.odd`。只出现一两次的特殊样式也不用 `#id`：出现 3 次及以上用 class，少于 3 次用「类 + 元素」结构选择器（08 决策 D9；SE 用 `#section-id`，不采用） |
| `@import`、外部 URL、`-epub-` 新增 | 离线/兼容 | 合并样式表；本地资源 |
| `vh/vw` 控制文字 | 分页模型下不稳定 | em |
| 厂商私有属性（任何 `duokan-*`、`zy-*` 等） | 非标准 | 删除（本规范不收） |

---

## 11. 推荐默认样式表（`stylesheet.css`）

用法与约定：

- 模板（04）只**追加**增量样式，选择器特异性不低于 (0,1,1)，不改本表已有规则。输出时按「使用到的模板才输出其 CSS」裁剪，本表始终全量输出。
- 不含 `!important`、`var()`、私有属性、颜色（装饰灰除外）。`[补]` = 书外规则；`[书]` = 数值来自原书。
- 类名：小写、连字符、英文，不以数字开头，不超过 3 个词；通用类（`noindent`、`gap`、`align-*`）可用于多种元素。

```css
@charset "UTF-8";

/* ===== 0. reset 与基线 ===== */
*{ box-sizing:border-box; }
html{ -webkit-text-size-adjust:100%; text-size-adjust:100%; }
html, body{ margin:0; padding:0; }               /* [补] 页边距交给阅读系统 */
body{
  line-height:1.6;                               /* [书1.4–1.7 → 1.6] 无单位 */
  text-align:justify;                            /* [书] 两端对齐；不写 text-justify，见 03 §5 */
  line-break:strict;                             /* [补] 避头尾，增强 */
  word-break:normal;                             /* [补] 书用 break-all，改局部 .break-all */
  overflow-wrap:break-word;                      /* [补] 长串兜底 */
  -webkit-hyphens:manual; hyphens:manual;        /* [补] 不对西文自动加连字符 */
  text-autospace:normal;                         /* [补，需实测] 中西文间距，不支持则忽略 */
}
/* 不设 font-family / font-size / color / background：交给阅读系统与用户 */

/* ===== 1. 段落 ===== */
p{ margin:0; text-indent:2em; orphans:2; widows:2; }   /* [书] 缩进2em；[补] 段距0（缩进与段距二选一） */
p.noindent{ text-indent:0; }                     /* 接排段、原稿无缩进段 */
p.gap{ margin-top:1.5em; }                       /* [书] 空一行，替代 <p><br/></p> */
.align-left  { text-align:left;   text-indent:0; }
.align-center{ text-align:center; text-indent:0; }
.align-right { text-align:right;  text-indent:0; }
.break-all{ word-break:break-all; }              /* 仅用于长 URL/长西文 span */
.no-break{ white-space:nowrap; }
.small{ font-size:.875em; }                      /* [书] 五号 */

/* ===== 2. 标题：样式按角色类，数字只表示层级（03 §6、04 §4.3） ===== */
h1, h2, h3, h4, h5, h6{
  font-weight:normal; text-indent:0; text-align:left; line-height:1.4;
  page-break-after:avoid; break-after:avoid;
  page-break-inside:avoid; break-inside:avoid;
}
h1, h2, h3{ font-family:"Source Han Sans SC","Noto Sans CJK SC","PingFang SC","Microsoft YaHei","SimHei",sans-serif; }
/* 兜底：没有角色类的标题按数字大小有序 */
h1{ margin:1.5em 0 1em; font-size:1.5em; }
h2{ margin:1.6em 0 .7em; font-size:1.25em; }
h3{ margin:1.4em 0 .6em; font-size:1.15em; }
h4{ margin:1.3em 0 .4em; font-size:1.05em; font-weight:bold; }
h5, h6{ margin:1em 0 .3em; font-size:1em; font-weight:bold; }
/* 角色类（优先于兜底，与层级数字无关） */
.part-title{ margin:35% 0 1em; font-size:1.8em; text-align:center; font-weight:normal; }
.chapter-title{ margin:25% 0 1.5em; font-size:1.5em; font-weight:normal; text-wrap:balance; }   /* [书30% → 25%]；text-wrap 需实测 */
.section-title{ margin:2em 0 .8em; font-size:1.3em; font-weight:normal; text-wrap:balance; }
.subsection-title{ margin:1.6em 0 .6em; font-size:1.15em; font-weight:normal; }
.part-title, .chapter-title, .section-title, .subsection-title{
  font-family:"Source Han Sans SC","Noto Sans CJK SC","PingFang SC","Microsoft YaHei","SimHei",sans-serif; }
.align-center.chapter-title, .align-center.section-title{ text-align:center; }
p.subtitle{ margin:-.8em 0 1.5em; font-size:.9em; text-indent:0; text-align:left;
  font-family:"Kaiti SC","STKaiti","KaiTi",serif; }                   /* 副标题小于主标题 */
.title-num, .title-name{ display:block; }        /* 两行显示时；两 span 之间保留全角空格 */

/* ===== 3. 引文 ===== */
blockquote{ margin:.75em 0 .75em 2em; padding:0; }            /* [书] 左2em，上下.75em */
blockquote p{ margin:.35em 0; line-height:1.5; text-indent:2em;
  font-family:"Kaiti SC","STKaiti","KaiTi",serif; }           /* [书] 楷体；行高≥1.4 */

/* ===== 4. 列表 ===== */
ul, ol{ margin:.5em 0; padding-left:2em; }
li{ margin:.2em 0; }
li p{ margin:.2em 0; text-indent:0; }

/* ===== 5. 图片、图注 ===== */
img{ max-width:100%; height:auto; border:0; }
figure{ margin:.8em 0; padding:0; text-align:center; text-indent:0;
  page-break-inside:avoid; break-inside:avoid; }
figure img{ display:block; margin:0 auto; }
img.w-100{ width:100%; } img.w-80{ width:80%; } img.w-60{ width:60%; }   /* [书] 100/80/60% */
figcaption{ margin:.6em 0 0; font-size:.9em; line-height:1.4; text-indent:0; text-align:center;
  font-family:"Kaiti SC","STKaiti","KaiTi",serif; }                      /* [书] 楷体 .9em；字号不大于正文 */

/* ===== 6. 表格（默认三线表；变体见 04） ===== */
table{ width:100%; margin:.8em 0; border-collapse:collapse; border-spacing:0;
  border-top:2px solid; border-bottom:2px solid; font-size:.9em; line-height:1.5; }
caption{ margin:0 0 .5em; font-size:.9em; text-align:center; text-indent:0; caption-side:top; }
th, td{ padding:.4em .5em; text-indent:0; text-align:left; vertical-align:middle; }
th{ font-weight:bold; border-bottom:1px solid; background:rgba(127,127,127,.12); }
td.num{ text-align:right; font-variant-numeric:tabular-nums; }
tr.odd{ background:rgba(127,127,127,.08); }      /* 斑马纹：显式 class，不用 :nth-child */

/* ===== 7. 行内 ===== */
em{ font-style:normal; font-family:"Kaiti SC","STKaiti","KaiTi",serif; }  /* 汉字无真斜体：楷体强调 */
i, cite{ font-style:normal; }                    /* 中文没有真斜体：默认正体，避免书名被硬拉斜 */
:lang(en) em, em:lang(en), :lang(en) i, i:lang(en), :lang(en) cite, cite:lang(en){
  font-style:italic; font-family:inherit; }      /* 只有标了西文 lang 的才斜体；外文 i/cite 须带 lang */
strong, b{ font-weight:bold; }
.dot{ -webkit-text-emphasis:filled dot; -webkit-text-emphasis-position:under right;
  text-emphasis:filled dot; text-emphasis-position:under right; font-style:normal; font-family:inherit; }
.heiti{ font-family:"Source Han Sans SC","Noto Sans CJK SC","PingFang SC","Microsoft YaHei","SimHei",sans-serif; }
.kaiti{ font-family:"Kaiti SC","STKaiti","KaiTi",serif; }
.fangsong{ font-family:"STFangsong","FangSong",serif; }
sup, sub{ font-size:.7em; line-height:0; }       /* [补] 勿依赖 smaller */
abbr{ text-decoration:none; }
u, ins{ text-decoration:underline; }
s, del{ text-decoration:line-through; }
ruby{ ruby-align:center; ruby-position:over; }
rt{ font-size:.55em; font-weight:normal; text-indent:0; letter-spacing:0; line-height:1; }   /* [书] .55em */
/* 注意：不设 rp{display:none}（降级括号） */
p.has-ruby{ line-height:2.2; }                   /* [补] 避免注音碰上一行 */
code, kbd, samp, pre{ font-family:"Source Code Pro","SFMono-Regular","Menlo","Consolas","Courier New",monospace;
  font-size:.85em; text-indent:0; }
pre{ margin:.8em 0; padding:.5em; white-space:pre-wrap; overflow-wrap:break-word; text-align:left;
  background:rgba(127,127,127,.1); }

/* ===== 8. 分隔、框 ===== */
hr{ margin:1.5em auto; width:30%; height:0; border:0; border-top:1px solid; }
p.sep{ margin:1.5em 0; text-indent:0; text-align:center; }    /* * * * 式分隔 */
aside.note-box{ margin:.8em 0; padding:.6em .8em; border-left:3px solid;
  background:rgba(127,127,127,.1); }
aside.note-box p{ text-indent:0; }

/* ===== 9. 分页保护 ===== */
p.page-break, .page-break{ page-break-before:always; break-before:page; }   /* 极少用 */
```

### 默认表的几处修订说明（相对原笔记 §E 草案）

1. 删去字体别名 `@font-face{local()}` 与全部厂商字体名（DK-、Song T、MYing Hei T 等），改直接字体栈。
2. 删去 `text-justify:inter-ideograph`、`-webkit-line-break`、全局 `word-break:break-all`、`rp{display:none}`、`aside` 隐藏要求、`color:#000`、图注 `#a52a2a`、词条 `#069460`。
3. 段距 `.5em` + 缩进 → 段距 0 + 缩进（二选一）；标题后首段保持缩进；`h1+p/blockquote+p/figure+p` 的无缩进规则取消，改显式 `.noindent`。
4. 章首与节内标题分开定义（`h1/.chapter-title` 下沉，`h2` 起 margin 小）；h2 不再默认 30% 下沉。
5. 行高 1.5 → 1.6，引文/诗/信 1.35 → ≥1.4（1.5）。
6. 表格默认三线表，斑马纹用 `.odd`；颜色改半透明灰；表宽 90% → 100%。
7. 页边距：`body padding .5em` → 0，交给 RS。

---

## 12. 对优化软件的含义

**可自动检测并修复（A）**

1. 单位：正文/小字 `px/pt` → em（`px/16`，`pt×4/3/16`）；`line-height` 带 `em/%` → 无单位；`text-indent` 近 2em 的值规整为 2em；图/表固定 px 宽 → `%`/`max-width:100%`。线宽 px 保留。
2. 删除 `!important`（先计算特异性确认不改变层叠结果；无法确认的报告）。
3. 删除/改写：`text-justify:inter-ideograph`、全局 `break-all`/`keep-all`、`rp{display:none}`、`outline`、`opacity`（→ `rgba`）、`column-*`、`text-shadow`、动画、私有属性（`duokan-*`/`zy-*`）、`position:absolute/fixed`（可转 margin 的转，其余报告）。
4. 前缀：补写无前缀标准属性；`-epub-*` 保留不新增；`-webkit-` 仅作旧 WebKit 补充。
5. 正文强制 `color`/`background` 删除；成对设色的装饰块保留并检查对比度。
6. 缩进模式一致性：同时 `text-indent:0` 与 `margin:0` 的正文段 → 补缩进；同时有缩进与 ≥.5em 段距 → 提示冗余。
7. 用空 `<p>`、`<br/>`、全角空格缩进的 → 转 `.gap`/CSS 缩进（先在 06/02 的文本层处理，再回到样式层）。
8. 重置样式表：注入 §11 基线；合并为单一样式表；删除未使用选择器；`id` 选择器 → class；`:nth-child` 斑马纹 → `.odd`。
9. 竖排书：检测 `writing-mode` 是否在 `html`/`body`；物理 margin → 逻辑属性；`page-progression-direction="rtl"` 一致性（01）。

**可自动检测，修复需确认（B）**

10. `lang` 缺失/不符（`zh-CN` vs 实际繁体）。
11. 汉字上的 `font-style:italic`/`<i>`、`font-weight:bold`：建议改楷体、`.dot` 或黑体类。
12. 标题层级：字号倒置、跳级（h1→h3）、同级样式不一致；章首标题出现在页中（非文件首）却带 25% margin。
13. 字体栈：缺通用族、嵌入字体未列在系统栈之前、拉丁字体抢占引号/破折号（缺 `unicode-range`）。
14. 行高 <1.4 或 >2（含 ruby 的段 <2）；注文字号 <.8em 或大于正文。
15. 含 ruby 的段落 → 加 `.has-ruby`。

**只报告（C）**

16. 夜间模式风险：写死的深/浅色、透明黑线图（04）。
17. 表格列数过多（>6 列）、过宽；长 URL 引起的溢出。
18. 使用了 L2 属性但无降级说明（如仅靠 `text-emphasis` 表达强调且无 `<em>`）。
19. 每条规则输出前后差异、命中数；规则幂等；高风险（标题章首识别、断行合并）默认只出建议。

---

修订记录：2026-10-29 参照 Standard Ebooks 修订（见 08）：语言码写法、斜体规则、一次性样式不用 id 选择器、保留两端对齐的说明；标题样式改为按角色类（`.part-title` / `.chapter-title` / `.section-title` / `.subsection-title`），数字只表示层级。
