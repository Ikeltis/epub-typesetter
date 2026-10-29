# SE 手册第 7 章（第 1–757 行）对照：分节、标题、献辞、题记、诗歌

来源：`_book_src/se_manual/7-high-level-structural-patterns.rst` 第 1–757 行（Sectioning / Headers / Dedications / Epigraphs / Poetry）。
对照对象：`guide/02` §4（section 与标题层级）、`guide/03` §6（标题数值）、`guide/04` T2/T3/T6/T7/T9、`guide/07` 的 SEM/STR/TYP 条目、`rebuild.py` 现状（每章 h1、平级、不拆 hgroup、无 poem 输出）。
条目编号沿用手册章节号（子章节标题接在其前一节条目之后继续编号，如 Headers 共 8 条，故「Parts of a section title」为 7.2.9）。

## 先说明三个贯穿全文的判断

1. **hgroup 的实际代价**：HTML 中 `hgroup` 内只有 `h1–h6` 被当作标题，其内 `p` 不是标题。对「第一章　开端」若拆成 `h`=「第一章」+ `p`=「开端」，目录文字、读屏的标题列表、阅读器大纲都只剩「第一章」，题名丢失。SE 的英文章节多为「罗马数字 + 标题」，目录常只列数字，所以 SE 能接受；中文书的题名承载主要信息，不能接受。因此中文「序号 + 题名」**默认不拆 hgroup**，保持一个 h 内的完整文本（现状），只在存在**真正的副标题**时用 hgroup。
2. **中文序号不是 label + ordinal**：「第一章」「第三回」「卷二」是「第 + 数 + 章」的环缀结构，没有「label 在前、ordinal 在后」的两件套，也没有 `z3998:roman`。不拆 label；序号整体视为 ordinal，可选标 `z3998:ordinal`。
3. **整页垂直居中不进基线**：SE 用 `vh` + flex 做献辞、题记整页居中。`guide/03` §2/§3 明确分页模型下 `vh` 参照系因阅读系统而异，基线样式不依赖。改用与章首下沉同一思路（`%` margin，相对宽度）。

---

## 一、Sectioning

### SE 7.1.1　`<body>` 的直接子元素只能是 section / article / nav
- SE 原规则：`body` 下只允许 `section`、`article`、`nav`，不放裸 `div`、`p`、`h1`。
- 我们现状：02 §1.1 骨架、§4.1 第 1 条「每个文件一个根 `<section>`」；nav 文件根为 `nav`；rebuild.py 输出 `body > section`。「body 直接子元素类型」没有检测项。
- 结论：已一致
- 理由：原则相同。差别只在检测：输入书里常见 `body > div` 或多个并列根节点。
- 落地：guide/07 SEM-011 增一句「`body` 直接子元素不是 section/article/nav（或存在多个根）→ warning」，修复 auto：单个根 `div` 且含标题时改标签为 `section`（`div`→`section` 只改标签），多根时包一层 `section`。

### SE 7.1.2　部/卷/书/章/小章等主要结构划分放在 `<section>` 中
- SE 原规则：大型作品的结构划分用 `section`，各级嵌套（书→部→章）。
- 我们现状：02 §4.1 第 1 条、§4.2 示例；02 §3 表只列 `part`、`chapter`；02 §6.2 表有 `division`，但 §3 的「部→章→节」流程没有用到它。
- 结论：修改后采用
- 理由：基本一致；补一点中文的分级：「部/卷」用 `part`，部/卷之下的「编、辑、篇、集」等中间层、或章内划分用 `division`（EPUB 词表里 `division` 正是此意）。
- 落地：02 §3 第 8 行「正文」备注与 §6.2 `division` 行加注「中文：编/辑/篇/集等介于部与章之间的层」；SEM-010 的 epub:type 判定表同步。

### SE 7.1.3　集合中的单项（如诗集中的一首）用 `<article>`
- SE 原规则：大集合里的独立单项用 `article`，不用 `section`。
- 我们现状：02 §4.1 第 4 条「`article` 仅用于可独立流通的内容块（如杂志中独立文章）」；T9 的诗词只有 `div.poem`，没有「诗集」模式。
- 结论：修改后采用
- 理由：HTML 对 `article` 的定义（自成一体的作品）正好覆盖诗集、词选、格言集、书信集中的单首/单篇，与厂商无关。限定为「短小单项集合」，长篇单篇仍是 `section` + chapter。
- 落地：02 §4.1 第 4 条改为「`article` 用于可独立流通的块：杂志文章，以及诗词曲选、箴言、短札等集合中的单项」；04 T9 新增「诗集模式」子模板（见 7.1.3.1 与 7.2.10.8）。

### SE 7.1.3.1　极短作品的集合全部放在一个文件，用 `break-after: page` 分页
- SE 原规则：诗集这类极短单项全放同一文件，`article, section{break-after: page}` 让每项另起一页。
- 我们现状：02 §2.1「一章一文件」、§2.2 拆分阈值 256 KB、拆分点优先「章 > 节 > 段」；03 §2 `break-*` 只用于 `avoid` 和少数必要的 always/page。
- 结论：修改后采用
- 理由：「短单项合一文件」采用：一首诗一个文件会产生数百个几 KB 的碎文件，正是 02 §2.2 反向「过碎」的情形。「每项强制另起一页」不默认：绝句、小令占半页，强制分页浪费且各阅读系统对 `break-after` 支持不一；改为可配置。
- 落地：02 §2.1 加例外「短单项集合（诗词曲选、箴言集）可合一文件，每项一个 `article`」；02 §2.2 拆分时优先按「卷/辑」边界；配置项 `poem.page_break`（默认 off，开启时写 `article{break-after:page;page-break-after:always}`，属 L2，失效即降级）。guide/07 STR-014「一个文档内 `count(//h1)>1`」对这种文件改为统计 h1 之外的 `article` 数，避免误报。

### SE 7.1.4　有标题的 section/article，首个子元素是 h1–h6、hgroup 或 header
- SE 原规则：标题放在最前面，可以是裸 `h`、`hgroup`，或含标题的 `header`。
- 我们现状：02 §4.1 第 1 条「下为标题」、T2 示例 h1 紧跟 section 开始；未提 `hgroup`/`header`。
- 结论：修改后采用
- 理由：「标题在最前」已一致。允许 `header`（标题 + 署名/题记组合）和 `hgroup`（标题 + 副标题）两种包装，供识别时容忍、修复时使用。
- 落地：02 §4.1 第 1 条补「标题块可以是 `h*`、`hgroup`（仅主标题 + 副标题）、`header`（标题 + 署名/题记）」；07 SEM-011 的 XPath 把「首个子元素」放宽到这三种。

### SE 7.1.5 / 7.1.5.1　可重组性（Recomposability）与 `data-parent`
- SE 原规则：整本书能拼回一个结构正确的 HTML5 文件；跨文件的子 section 用 `data-parent="父 id"` 指向其父 section。例：book-1.xhtml → part-1-2.xhtml → chapter-1-2-3.xhtml，每文件一个 section，标题层级按全书层级（h2/h3/h4）。
- 我们现状：02 §4.1 第 3 条「层级与目录深度一一对应：部 h1→章 h2…」、§2.1 部标题页自成文件；没有「重组」的概念，也没有 `data-parent`。02 §2.2 第 2 条要求拆分后「被切走的小节顶层 section 继续存在」，却没有记录它原来的父级。
- 结论：修改后采用
- 理由：可重组性作为目标采用，用标准手段保证：全书统一的标题层级 + nav 嵌套层级即可复原结构。`data-parent` 是合法的 `data-*` 属性，不违背标准，但除 SE 自家工具外没人读，不要求输入书具备。我们自己拆文件时写它是有用的（拆分、合并、回写时能定位父节点）。
- 落地：(a) 07 新增 STR 检查「每个内容文档首标题层级 = 其在 nav 中的深度」（nav 嵌套与 `h` 数字一致，不一致 warning、auto 修标题数字）；(b) 02 §2.2 第 2 条加「拆分产生的新文件，顶层 section 写 `data-parent`=原父 section id（若无 id 则补稳定 id）；输入书已有 `data-parent` 时保留并校验：目标 id 存在、在 spine 前部、层级=父层级+1」；(c) 02 附一个三文件示例（部页 `part-01.xhtml`、章页 `chapter-001.xhtml`），中文版：部 `h1`「第一部」、章 `h2`。code：splitter 实现时写入，rebuild 本身不拆文件，暂无改动。

---

## 二、Headers

### SE 7.2.1　h1–h6 只用于进目录的结构划分，不用于非目录内容（如章内短诗的诗题）
- SE 原规则：结构划分标题才用 `h`；章内的小诗题不是结构成分，用 `header > p` 等，不用 `h`。
- 我们现状：04 T3「无编号小标题不要用加粗 `p`，用 `h3/h4`……只作视觉分段不进目录，仍用标题标签（目录收录范围由 nav 决定）」；T9 诗题用 `p.poem-title`；07 SEM-008「标题标签滥用」。
- 结论：不采用（修改后部分采用）
- 理由：与现有立场冲突，属于有意取舍：T3 的立场是「小标题就是标题，进不进目录由 nav 决定」，对读屏用户导航更友好，且「用 p 冒充标题」正是 TYP-006 要抓的毛病。SE 的做法对应「章内小诗题」这一个特例，我们已经用 `p.poem-title` 处理，两者不矛盾。另：「不进目录的内容不要用 `h`」不作为强制规则。
- 落地：04 T9 注意事项加一句：「章内引用的诗（`blockquote` 引诗，见 7.5.5）的诗题用 `p.poem-title`，不用 `h*`；诗集中作为独立单项的诗（`article`）诗题用 `h*`，见 7.1.3」。T3 不改。

### SE 7.2.2　含 h 的 section 必然出现在目录中
- SE 原规则：有 `h1–h6` 的 section 就进 ToC；反过来不进 ToC 的不放 h。
- 我们现状：01 / T3 明确「目录收录范围由 nav 决定」；07 STR-010「正文中每个 h1/h2（及配置层级）都有目录项」。
- 结论：不采用
- 理由：SE 出版物专属（SE 自己生成目录，两者强耦合）。我们处理他人的书，目录范围可以是原书的选择（如不收书名页、版权页、节标题）。
- 落地：07 STR-010 补一条例外：`titlepage`、`copyright-page`、`halftitlepage` 等不进 nav 的文件，其标题不参与「h1/h2 必须有目录项」的差集；对应 epub:type 来自 02 §3 表中「进目录：否」列。

### SE 7.2.3　书名页的书名用 h1，其余（含半书名页）从 h2 起
- SE 原规则：书名页 h1，其他所有 section 从 h2 开始。
- 我们现状：02 §4.1 第 3 条：无「部」时章 h1；T2 章首 h1；03 §6.2 章首样式挂在 h1 上。
- 结论：不采用
- 理由：SE 出版物专属。我们不生成书名页（原则 4），且章 h1 已是基线（03 的数值体系、rebuild 都以 h1 为章）。
- 落地：07 SEM-006 的「全书各文件首标题层级的众数」统计里，把 `titlepage`、`halftitlepage`、`cover`、`copyright-page` 文件排除在外，不因其用 h1 或无标题报警。

### SE 7.2.4　h 的数字表示在全书中的层级，不是在单文件中的层级
- SE 原规则：`chapter-2-3.xhtml` 里的章标题在「第 2 部」之下，写 `h3`，不因为自己是文件内最高级就写 `h1`/`h2`。
- 我们现状：02 §4.1 第 3 条「以全书为单位统一约定：有部：部 h1→章 h2→节 h3；无部：章 h1→节 h2；不跳级」；03 §6.2「若书用 h1 作书名/篇名而以 h2 作章名，则给章名加 `.chapter-title`」；07 SEM-006。rebuild.py 现在每章 h1、平级，没处理部/章两级。
- 结论：已一致
- 理由：规则等价，而且我们给了「章首样式不挂 h1 而挂 `.chapter-title`」这一视觉解耦手段，比 SE 更完整。
- 落地：无文档改动。code 提醒：rebuild 识别到「部」页时，其下各章应输出 `h2` 并让 nav 嵌套（目前全 h1 平级，只适用于无部的书）；列入 rebuild 待办，不在本次文档修订范围。

### SE 7.2.5　每个 h 的直接父元素必须是 section / article / header / hgroup
- SE 原规则：标题不套在 `div` 里。
- 我们现状：无。T2 的「章号 + 章名」示例未涉及；输入书常有 `div.chapter-head > h1`。
- 结论：修改后采用
- 理由：可检测、可修复，且有助于「标题是 section 的第一个子节点」这一前提。但很多旧书的 `div` 包装带样式，不能无脑拆。
- 落地：07 SEM-011 旁增一条 P2 info：「`h*` 的父元素不是 section/article/header/hgroup」；修复 auto 仅限「`div` 只含标题（或标题+副标题/题记）且 `div` 紧邻 section 开头」时，把 `div` 改为 `header`（保留 class）；其余 suggest。

### SE 7.2.6 / 7.2.6.1 / 7.2.6.2　hgroup：一个 h 加若干 p，仅在需要组合多个标题成分时才出现
- SE 原规则：多个标题成分（序号+标题、标题+副标题）用 `hgroup`，里面只有一个 `h1–h6` 后跟 `p`；只有一个成分时不要 `hgroup`。
- 我们现状：02 §4.1 第 5 条副标题用 `p.subtitle`（可无 hgroup），第 7 条「章序号 + 章名保持在同一个 h1 内，视觉分行用 CSS；不要拆成两个」；T2「章号+章名两行」用 `h1 > span.title-num + span.title-name`。
- 结论：修改后采用
- 理由：见开头判断 1。「序号 + 题名」**不拆 hgroup**，保持现状（中文不适用 SE 的拆法）；「主标题 + 副标题」改用 `hgroup`，这样 `h` 内只有主标题，目录与大纲拿到的是干净的主标题文本，副标题 `p` 不污染。hgroup 内 `p` 的 role/语义用 `epub:type="subtitle"` + `role="doc-subtitle"`（均为标准词汇）。EpubCheck 对 `hgroup > h + p` 的接受度需实测。
- 落地：02 §4.1 第 5 条改写为：「副标题：`<hgroup><h1>主标题</h1><p epub:type="subtitle" role="doc-subtitle">副标题</p></hgroup>`；序号与题名不拆 hgroup」；T2 篇章页示例的 `h1.part-title + p.subtitle` 改为 hgroup 形式；07 新增 SEM 检查「`hgroup` 恰有一个 `h*`（居首）+ 至少一个 `p`；只含一个子元素的 `hgroup` 报警（auto：拆包）」。rebuild：识别到「标题 + 紧随的短副标题段（样式小于标题、居中）」时输出 hgroup，识别由 LLM 或规则判定 `is_subtitle`，置信度低则不拆。

### SE 7.2.7　标题遵循斜体规则；全外文标题不斜体但保留 xml:lang
- SE 原规则：标题里的斜体按常规规则（书名、外文等）；整个标题是外文时不斜体，但在父元素上写 `xml:lang`。
- 我们现状：中文无斜体（03 §10 的避免清单、T6/T7 用楷体区分）。02 §8.2 对外文只说「整段、整个书名、整句才标 lang」。
- 结论：修改后采用
- 理由：斜体部分不适用（中文）。保留的是「整标题为外文时 `lang` 写在标题元素上」，例如中文书里的英文章名；这可检测。
- 落地：02 §8.2 加一条「整个标题为外文时，`lang`+`xml:lang` 写在 `h*`（或 hgroup 的对应 `p`）上，不额外包 span」；07 现有语言标注检查（若无则新增 TXT/A11Y 条）加「标题字符全为拉丁字母但无 lang」info。

### SE 7.2.8　无标题内容的 section（题记页、非散文内容）加 `margin-top: 20vh`
- SE 原规则：没有任何 header 内容的 section，其容器上加 `margin-top: 20vh`，避免内容贴页顶。
- 我们现状：02 §4.1 第 4、8 条要求「section 必须有标题，无标题章节改用 div 或带 aria-label 的 section」；03 §3「章首下沉用 `%`，避免 `vh`」。
- 结论：修改后采用
- 理由：目的（无标题页不贴顶）采用，手段（`vh`）不采用，换成 03 的 `%` 体系；同时解决另一处冲突：SE 的无标题题记页/献辞页仍是 `section`（带 `epub:type`），我们要求无标题就用 div，两者不同。建议折中：带明确结构语义（`dedication`/`epigraph`/`preface` 等）的无标题页仍可用 `section`，但**必须**有 `aria-label`（满足 HTML 对 section 要有名称的要求，同时是标准手段）。**这是需要你决策的点之一。**
- 落地：02 §4.1 第 4、8 条改为「无标题但带结构语义的页（献词、题词、无题名的卷首语）用 `section epub:type=… role=doc-… aria-label="献词"`；无语义的纯样式块用 div」；04 新增类 `no-head`：`section.no-head{ margin-top:25%; }`（取值同 03 §6.2 章首下沉，属可调参数）；07 SEM-011 对无标题 section 的判定改为「无 h 且无 aria-label」才报；04 §0.2 类名表登记 `no-head`。

### SE 7.2.9　标题的组成部分（总述）
见下面 7.2.9.1–5。

### SE 7.2.9.1　Label：序号之前的部分，包在 `<span epub:type="se:label">` 中
- SE 原规则：「Book」「Canto」这类位于序号前的词，用 `se:label` 包起来。
- 我们现状：无；T2 用 `span.title-num`。
- 结论：不采用
- 理由：两层原因。`se:` 词汇违反原则 2（SE 自定义）；而且中文「第 X 章」是环缀，没有「label + 序号」两段（见开头判断 2）。西文书的「Chapter 1」在中文书里很少见，出现时照中文序号处理，整体当 ordinal。
- 落地：无。

### SE 7.2.9.2　Ordinal：包在 `<span epub:type="z3998:ordinal">`（罗马数字再加 `z3998:roman`）；可无 label 单独出现
- SE 原规则：序号用 `z3998:ordinal` 标记，罗马数字另加 `z3998:roman`；序号可单独作为 h 内容。
- 我们现状：无；T2 用 `span.title-num`。
- 结论：修改后采用
- 理由：`z3998:ordinal` 是 DAISY 标准词汇，允许（需 `epub:prefix` 声明，02 §5.7 已有声明方法）。不用 `z3998:roman`（中文是汉字数字、阿拉伯数字，无对应词）。作为**可选**增强，不是必须：序号在多数书里没有被机器消费，加了要声明前缀、增加复杂度。
- 落地：04 T2「章号+章名」示例的 `span.title-num` 可选加 `epub:type="z3998:ordinal"`，仅当文档已声明 z3998 前缀（同 02 §5.7 的声明规则）；07 TYP-007（标题序号连续）可借这个标记提取序号，没有标记时仍用正则。

### SE 7.2.9.3　含 label/ordinal 的 h 包装元素本身不是语义上的「标题」
- SE 原规则：只有 label+ordinal 的 h 不算 `title`；不要给它 `epub:type="title"`。
- 我们现状：02 §6.2 `title`「弃用倾向」；章标题 h 上不标 epub:type。
- 结论：已一致
- 理由：我们不在 h 上加 `title`。
- 落地：无。

### SE 7.2.9.4　Title：主标题；节可以有 label/ordinal 而没有 title，或反之
- SE 原规则：纯题名 `<h2 epub:type="title">…`；有序号时序号在 h、题名放 `p epub:type="title"`（见 7.2.10.3）。
- 我们现状：章标题一律 `<h1>第一章　开端</h1>`；单独题名 `<h1>开端</h1>`；序号和题名同 h 内用 span。
- 结论：修改后采用
- 理由：「纯题名 h」等同我们的现状；`epub:type="title"` 在 EPUB 词表里有但不必加（02 §6.2 已标「弃用倾向」）。「序号单独/题名单独/两者都有」三种组合的**识别**采用，输出形式按 7.2.10 的中文版本。
- 落地：04 T2 识别信号下补「三种组合：仅序号（`第五章`）、仅题名（`楔子`）、序号+题名」；输出形式见 7.2.10.1–.3。

### SE 7.2.9.5　Subtitle：副标题，`<p epub:type="subtitle">`
- SE 原规则：副标题放在 hgroup 里的 `p epub:type="subtitle"`。
- 我们现状：02 §4.1 第 5 条、T2 `p.subtitle`、03 §6.2 副标题 .9em 楷体。
- 结论：修改后采用
- 理由：同 7.2.6：改为放入 `hgroup`，其他不变（字号、字体）。
- 落地：与 7.2.6 同一处修改。

### SE 7.2.10.1　只有序号、没有标题：`<h2 epub:type="z3998:ordinal …">XI</h2>`
- SE 原规则：序号单独作为 h 内容并标 ordinal。
- 我们现状：T2 识别信号含「楔子|引子…」与「第X章」；输出 `<h1>第五章</h1>`。
- 结论：已一致
- 理由：形态相同（序号即 h 文本），中文不需要罗马数字标记；ordinal 标记为可选（7.2.9.2）。
- 落地：无。

### SE 7.2.10.2　只有标题、没有序号：`<h2 epub:type="title">…</h2>`
- SE 原规则：纯题名 h 加 `title`。
- 我们现状：`<h1>楔子</h1>`，不加 epub:type。
- 结论：已一致（不加 title 标记）
- 理由：见 7.2.9.4。
- 落地：无。

### SE 7.2.10.3　标题 + 序号：hgroup（h 为序号，p 为题名）
- SE 原规则：`<hgroup><h2 ordinal>XI</h2><p epub:type="title">…</p></hgroup>`。
- 我们现状：02 §4.1 第 7 条同一 h 内；T2 `h1 > span.title-num + span.title-name`。
- 结论：不采用
- 理由：中文不适用（见开头判断 1：hgroup 会让目录/读屏只拿到序号）。保持完整文本在 h 内。这是和 SE 最大的结构差别，需要你确认。
- 落地：T2 修一处小错：当前示例 `<span class="title-num">第一章</span><span class="title-name">侯门庶子</span>` 在 `display:block` 后没问题，但**纯文本/目录提取会得到「第一章侯门庶子」，序号与题名粘连**，违反 07 TYP-007「序号后不粘连标题文字」。改为两 span 之间保留一个全角空格文本节点：`<span class="title-num">第一章</span>　<span class="title-name">侯门庶子</span>`（块级化后空格折叠不影响视觉）。07 SEM 加检查：nav 条目文本 = h 的 `normalize-space(.)`，序号与题名之间必须有空白。rebuild：章标题含序号+题名时按此输出（目前输出的是整体 plain 文本 `h1`，行为一致，无需改）。

### SE 7.2.10.4　有标题和副标题、无序号：hgroup
- SE 原规则：`hgroup` 内 h（title）+ `p epub:type="subtitle"`。
- 我们现状：见 7.2.6。
- 结论：修改后采用
- 理由：同 7.2.6。「（一个司机的故事）」这种括号副题，原样保留括号，不由我们删除。
- 落地：同 7.2.6。

### SE 7.2.10.5　label + ordinal：`<h2><span se:label>Book</span> <span ordinal>II</span></h2>`
- SE 原规则：label 与 ordinal 都进 h。
- 我们现状：「第二卷」整体作 h 文本。
- 结论：不采用
- 理由：中文不适用 + `se:` 自定义词汇（同 7.2.9.1）。
- 落地：无。

### SE 7.2.10.6　label + ordinal + title：hgroup
- SE 原规则：h 含 label+ordinal，p 为 title。
- 我们现状：同 7.2.10.3。
- 结论：不采用
- 理由：同 7.2.10.3、7.2.9.1。
- 落地：无。

### SE 7.2.10.7　标题不唯一但目录需唯一：`<p hidden="hidden" epub:type="subtitle">` 写首句
- SE 原规则：多首都叫「Sonnet」的诗，在 hgroup 里放一个 `hidden` 的副标题，写诗的首行，供 ToC 区分。
- 我们现状：无。中文类似情形：诗集里多首《无题》、词牌相同的词（《浣溪沙》《念奴娇》）、乐府同题。
- 结论：修改后采用
- 理由：需求真实（目录里几十个「无题」不可用）。但 SE 的做法让 h 文本与目录文本不一致，与 07 STR-010「目录文字与目标标题文字一致」冲突；且 `hidden` 副标题进入 hgroup，读屏/部分阅读系统可能不读。折中：不改 h，目录文字写「无题（相见时难别亦难）」形式，STR-010 对「标题为重复题名」的情形放行，允许 nav 文字 = h 文字 + 括注。
- 落地：04 T9「诗集模式」加说明：同名诗词在 nav 里附首句括注；07 STR-010 增例外「h 文字重复出现且 nav 文字以 h 文字开头并带括注」；SEM 新增 info「同一文档/全书内同名 h 重复 ≥3 次，建议 nav 加首句区分」（auto：取诗首行生成，需用户确认）。不实现 `hidden` 副标题。

### SE 7.2.10.8　需要标题但不进目录的 section：`<header><p>…</p></header>`，CSS 小型大写居中
- SE 原规则：不进目录的标题（如章内小诗的诗题）用 `header > p`，样式 `font-variant: small-caps; text-align: center`。
- 我们现状：T9 `p.poem-title`（黑体）；T3 允许 h 而 nav 不收。
- 结论：不采用
- 理由：小型大写属英文专属（中文不适用）。结构上已有 `p.poem-title` 等价做法，不另加 `header`。
- 落地：无（与 7.2.1 合并处理）。

### SE 7.2.10.9　半书名页（无副标题）：`<h2 epub:type="fulltitle">Eugene Onegin</h2>`
- SE 原规则：半书名页的 h 标 `fulltitle`。
- 我们现状：02 §6.2 有 `halftitle`/`halftitlepage`/`fulltitle`；不生成。
- 结论：不采用
- 理由：SE 出版物专属 + 原则 4（不给书添加半书名页）。输入书已有半书名页时保留，不改结构。
- 落地：无。

### SE 7.2.10.10　半书名页有副标题：`hgroup epub:type="fulltitle"`
- SE 原规则：同上，用 hgroup。
- 我们现状：无。
- 结论：不采用
- 理由：同 7.2.10.9。
- 落地：无。

### SE 7.2.10.11　作者与主作者共享署名的标题：`<header><h2 epub:type="title">…</h2><p epub:type="contributors">…</p></header>`
- SE 原规则：标题与署名行放 `header`，署名 `p` 标 `contributors`。
- 我们现状：T9 诗题与作者为 `p.poem-title` + `p.poem-author`；T8 书信有落款类。没有标题署名的通用模式。
- 结论：修改后采用
- 理由：集合型作品（诗词选集、杂志文章、论文集）里「标题 + 署名」是常见需要。用标准 `header` 元素包标题与署名 `p.byline`；`contributors` 无前缀、不确定是否在 EPUB 结构词表里，不使用，只用 class（需核对词表后再决定是否标 epub:type）。
- 落地：04 T2/T9 加「集合单项头」：`<header><h2>登幽州台歌</h2><p class="byline">陈子昂</p></header>`；04 §0.2 登记 `byline`；07 暂不新增检查。

### SE 7.2.11 / 7.2.11.1–4　Bridgehead：章首摘要（散文或以破折号分隔的短语列表），斜体，限宽 60%，句末用句号
- SE 原规则：章标题后的摘要段，`se:bridgehead`，斜体、`max-width:60%`；系列短语用破折号连接，每段首字母大写（句式大小写），末句以句号等结尾。
- 我们现状：02 §6.2 有 `bridgehead`「桥接标题（不进目录的小标题）」；无章首摘要的模板。
- 结论：修改后采用
- 理由：需求在中文书里同样存在：译著里的章节提要、章回体的回前提要、教材的「本章导读/内容提要」。**但**不能用 `bridgehead`——EPUB 词表里 `bridgehead` 的含义（02 §6.2 所记）是不进层级的小标题，和 SE 自定义的 `se:bridgehead`（章摘要）不是一回事，且 SE 用的是 `se:` 前缀。不加 epub:type，只用 class。斜体不适用，改楷体；限宽 60% 对中文不必要；破折号用 `——` 且遵循 06 的破折号规则；句末标点遵循 06。
- 落地：04 T2 增一块「章首提要」：`<p class="chapter-summary">`，CSS `font-family` 楷体族、`text-indent:0`、`margin:0 2em 1.5em`、`font-size:.95em`；识别信号：紧随章标题的短段，文本含「本章」「导读」「提要」，或各分句以 `——`/`；` 分隔（中，进确认清单）；04 §0.2 登记 `chapter-summary`；02 §6.2 `bridgehead` 备注「不要用来标章摘要」。

---

## 三、Dedications

### SE 7.3.1　短献辞页面居中；高级阅读器垂直居中，其余水平居中加小的上边距
- SE 原规则：短献辞 `text-align:center`，容器内 `margin-top:3em; max-width:80%`；支持 flex 时用 `min-height:calc(98vh - 3em)` 垂直居中。SE 也说作者风格各异，可自由匹配（小型大写、字号、对齐）。
- 我们现状：04 T7 识别「献给……」「谨以此书献给」，「用 `epub:type="dedication"`，样式同卷首语居中」；02 §3 表 `dedication` / `doc-dedication`。
- 结论：修改后采用
- 理由：水平居中 + 上边距采用；垂直居中（`vh` + flex）不采用，理由见开头判断 3，且 03 §1.2 要求基线只依赖 L1。中文献辞也常右对齐或排在偏右下，故保持「匹配原书风格」的自由，由识别原书对齐方式决定居中/居右。
- 落地：04 T7 新增独立「献辞」小节：`<section epub:type="dedication" role="doc-dedication" aria-label="献词" class="no-head">`，CSS `section.dedication p{ text-align:center; text-indent:0; margin:0 2em .5em; }`，上边距用 `.no-head` 的 `%`（见 7.2.8）；原书右对齐则输出 `class="align-right"` 并保留；T7 现行「样式同卷首语居中」一句拆开，因为卷首语用楷体、献辞可随原书。

### SE 7.3.2　长篇散文式献辞按普通章节处理，无标题时加顶部边距
- SE 原规则：与正文章节排版一致，无 header 时加 margin-top。
- 我们现状：T7 未区分长短。
- 结论：采用
- 理由：简单一致。判据：献辞段数 ≥2 或总字数 >100 → 按正文版式（首行缩进 2em、两端对齐），仍带 `epub:type="dedication"`。
- 落地：04 T7 献辞小节加「长献辞：版式同正文，`class="no-head"` 保留上边距」；识别阈值写进 T7 识别信号（中）。

---

## 四、Epigraphs

### SE 7.4.1　所有题记通用 CSS：斜体、`hyphens:none`、cite 小型大写、`em/i` 回正体、cite 内的 `i` 斜体
- SE 原规则：题记整体斜体，强调反转为正体；`cite`（出处）正体小型大写；选择器用 `[epub|type~="epigraph"]`。
- 我们现状：T7 `blockquote.epigraph{margin:1em 0 2em 3em; font-size:.95em}`，`p{text-indent:0; text-align:left}`，出处 `p.attribution`；选择器用 class。
- 结论：不采用
- 理由：中文不适用（斜体、小型大写、`hyphens`）。选择器：`[epub|type~=...]` 需要 `@namespace epub`，在弱 CSS 阅读器上不可靠，T7 用 class 更稳，保持。中文区分题记的手段是楷体/仿宋 + 左缩进 + 字号略小，题记字体可补（见下）。
- 落地：04 T7 的 `blockquote.epigraph` 补 `font-family:"Kaiti SC","STKaiti","KaiTi",serif`（现状只给了缩进与字号，未指定字体，而 T6 引文、T9 诗词都指定了）；与 03 §8 角色字体栈一致。

### SE 7.4.2　题记通常斜体，例外按斜体规则
- SE 原规则：同上。
- 我们现状：无斜体。
- 结论：不采用
- 理由：中文不适用。
- 落地：无。

### SE 7.4.3　题记中引用戏剧：用标准戏剧格式，persona 去斜体
- SE 原规则：题记内的戏剧引文套用 7.6 格式，persona 正体。
- 我们现状：T11 剧本版式；题记内无专门说明。
- 结论：不采用
- 理由：中文不适用（没有斜体可去）；剧本引文的结构仍按 T11，样式在题记内不额外处理。
- 落地：无。

### SE 7.4.4　题记中的标题去斜体
- SE 原规则：题记里的 `h2` 正体。
- 我们现状：无。
- 结论：不采用
- 理由：中文不适用。
- 落地：无。

### SE 7.4.5.1　section header 中的题记：出处用 `<cite>`，不带前导破折号和句号
- SE 原规则：出处放 `cite`，不写 `—`，也不加句号；破折号由 CSS 或排版决定。错例是 `<cite>—Chaucer.</cite>`。
- 我们现状：T6/T7 出处为 `p.attribution`，文本含 `——`（T6：「其前的破折号属文本，写 `——`（偶数）」）；07 TXT 对破折号有规则。
- 结论：修改后采用
- 理由：「不带句号」采用：中文出处末尾不加句号，可检测可修复。「不写前导破折号、交给 CSS」不采用：中文出处前的 `——` 是出版习惯，且 03 §1.2 L0 规定信息放在文本里、不靠伪元素 `content`；用 CSS 生成会在去掉样式后丢失。`cite` 元素不采用：HTML 规定 `cite` 表示作品标题，出处里的人名不合规。
- 落地：04 T6/T7 注意事项加「出处末尾不加句号（`《古诗十九首》`、`——梁启超`）」；07 TXT 新增检查：`p.attribution`/`.source` 末字符为 `。` → warning（auto 删除）。破折号规则不动。

### SE 7.4.5.2　header 内题记的额外 CSS：`inline-block`/`display:table`、`max-width:80%`、`text-align:initial`、后续元素 `margin-top:3em`
- SE 原规则：让题记块居中，宽 80%，文字左起；题记后留 3em。
- 我们现状：T7 `margin:1em 0 2em 3em; font-size:.95em`，「不超过版心 2/3」；题记后间距为 2em。
- 结论：不采用
- 理由：其他原因：用 `inline-block`/`table` 居中是 SE 的版面选择；我们已有左缩进 3em 的方案，更简单，在弱 CSS 阅读器上降级为普通 `blockquote`。SE 此处结构要求（题记放在 `header` 内）也不强制，T2 篇章页示例中题记直接放在 section 内即可，识别时两种位置都接受。
- 落地：04 T7 识别信号补「题记可位于 `header` 内或紧跟标题之后」；其余不改。

### SE 7.4.6.1　整页题记：支持高级 CSS 的阅读器垂直居中，其余水平居中加小上边距
- SE 原规则：整页题记居中。
- 我们现状：02 §3 表「题词 front epigraph doc-epigraph 否；也可放在章首」；T7 只有章首题记模板。
- 结论：修改后采用
- 理由：整页题记（书首题词页）识别与模板采用，居中方式用 `%` 上边距（同 7.3.1），不垂直居中。
- 落地：04 T7 新增「整页题记」：`<section epub:type="epigraph" role="doc-epigraph" aria-label="题词" class="no-head"><blockquote>…</blockquote></section>`，CSS `section.epigraph-page > blockquote{ margin:0 2em 1.5em 3em; }` 配合 `.no-head`；02 §4.1 第 8 条同步（见 7.2.8）。

### SE 7.4.6.2　整页题记含多条引文时，用多个 `<blockquote>`
- SE 原规则：每条引文一个 blockquote。
- 我们现状：T7 未规定多条。
- 结论：采用
- 理由：语义清晰，与中文无冲突；每条各带自己的出处。
- 落地：04 T7 注意事项加「多条题记：每条一个 `blockquote.epigraph`，各带 `p.attribution`」；07 暂不新增检查。

### SE 7.4.6.3　整页题记的额外 CSS（flex 垂直居中、`min-height:calc(98vh - 3em)`、`> * + *{margin-top:3em}`）
- SE 原规则：同 7.4.6.1 的实现代码。
- 我们现状：无。
- 结论：不采用
- 理由：与厂商无关原则冲突：`vh`/`calc` 在分页模型阅读系统上行为不一致（03 §2/§3 已有结论）；改用 `%`。
- 落地：无（见 7.4.6.1）。

### SE 7.4.6.4　整页题记示例：`body epub:type="frontmatter"` > `section epub:type="epigraph"` > `blockquote`
- SE 原规则：示例结构。
- 我们现状：02 §3 说分区标记加在 `body`；题记文件角色为 `epigraph`。
- 结论：已一致
- 理由：我们的文件骨架与它一致，只多加 `role="doc-epigraph"`。
- 落地：无（骨架示例随 7.4.6.1 的新增模板一并给出）。

---

## 五、Poetry, verse, and songs

### SE 7.5.0　（导语）HTML 没有好的诗歌语义，借用无关元素
- SE 原规则：承认只能借用 `p`、`span`、`br`。
- 我们现状：02 §5.7 与 T9 有两套互相不一致的写法（见 7.5.1）。
- 结论：已一致
- 理由：认识相同。
- 落地：无。

### SE 7.5.1　一个诗节是一个 `<p>`，样式 `text-align:initial; text-indent:0`，相邻诗节 `p + p{margin-top:1em}`
- SE 原规则：诗节 = `p`；诗行 = 其中的 `span`（见 7.5.2）。
- 我们现状：**内部不一致**。02 §5.7：`p.stanza` 内 `span.line` + `br`。T9：`div.stanza > p`（**一行一个 `p`**）。03 §1.3：「诗句行用独立 `<p>` 而非 `<br/>`」，T9 注意事项「`<span>`+`<br/>` 只在拿不准时」。rebuild.py：无诗歌输出。
- 结论：修改后采用
- 理由：诗节 = `p` 的好处：去掉 CSS 后诗节边界仍然存在（`p` 间距），行由 `br` 保持换行；而 T9 的「`div.stanza` 内一行一 `p`」去掉 CSS 后所有行变成平级段落，诗节边界丢失，且把 `p`（段落）当作诗行使用，语义偏。中文诗每行较短，转换成本低。**这是需要你决策的点之二**：统一为 SE 结构，会改 T9 的全部 HTML 与 CSS 选择器，以及 02 §5.7。
- 落地：04 T9 的 HTML 全部改为 `div.poem > p.stanza > span.line + br`（词的两阕为两个 `p.stanza`）；02 §5.7 示例已是此结构，保留（统一以 02 为准）；03 §1.3 对应句子改为「诗节为 `p`，行用 `span.line`+`br`；丢样式后仍分行分节」；04 §0.2 类名 `stanza` 的元素改为 `p`，新增 `line`（`verse` 保留给自适应换行的半句 span）。检测/修复：07 TYP-011 诗歌判定后，若诗行为独立 `p` 且被 `div.stanza` 包裹（旧 T9 形态或外来书），修复 auto 转为诗节 `p`+行 `span`+`br`。

### SE 7.5.2　每个诗行是 `<span>`，`display:block; padding-left:1em; text-indent:-1em`（回行悬挂）
- SE 原规则：行 = `span`，块级，悬挂缩进 1em（长行折行后缩进）。
- 我们现状：T9 居左型 `div.poem-left p{padding-left:3em;text-indent:-1em}`（回行低格 1em）；词 `div.poem-ci p{padding-left:2em;text-indent:0}`（不悬挂）；居中型无悬挂。
- 结论：修改后采用
- 理由：悬挂缩进的思路已在 T9 居左型里有，换到 `span.line` 上；中文回行低格 1em 也是出版惯例。居中型不悬挂（换行仍居中）。
- 落地：04 T9 CSS：`p.stanza > span.line{ display:block; }`；居左型 `p.stanza > span.line{ padding-left:3em; text-indent:-1em; }`（保持现有数值：首行 2em，回行 3em）；居中型 `p.stanza{ text-align:center; }`；词型 `padding-left:2em; text-indent:0`。同时保留 `p.poem-title/-author/-preface` 现有规则。

### SE 7.5.3　每个行 span 后接 `<br/>`（末行除外），CSS 把 `span + br` 设 `display:none`
- SE 原规则：保证无 CSS 时仍分行；有 CSS 时隐藏 `br` 避免双倍换行。
- 我们现状：02 §5.7 有 `br`；03 §1.3 对 `<br/>` 一向谨慎；T9 CSS 无 `br` 处理。
- 结论：采用
- 理由：这是诗歌里 `br` 的正当用法（行间换行，保留去样式降级）。
- 落地：04 T9 CSS 加 `p.stanza > span.line + br{ display:none; }`；03 §10「应避免写法」中如有「禁用 br」的条文，补「诗行 `span`+`br` 例外」；07 TYP 中「`br` 滥用/连续 br」的检测对 `p.stanza` 内的 `br` 排除。

### SE 7.5.4　缩进行用 class `i1`、`i2`…，不用 nbsp，CSS 随级数递增
- SE 原规则：缩进行 `class="i1"`，逐级 `i2`、`i3`，各配 `padding-left` 与 `text-indent:-1em`。
- 我们现状：02 §5.7：「缩进的诗行用 `<span class="indent-1">`（CSS 控制），不要用全角空格缩进」。T9 无逐行缩进类。
- 结论：采用
- 理由：已有 02 的命名 `indent-1`；中文里用于现代诗的阶梯式分行、曲的衬字缩进、楚辞兮字句等。类名沿 02，不改成 `i1`。
- 落地：04 T9 CSS 补 `span.line.indent-1{ padding-left:Xem; }`、`indent-2`…（在各排版型基础缩进上递增 1em）；04 §0.2 登记 `line`、`indent-1`、`indent-2`；07 TYP-001 对「诗行行首空格/全角空格缩进」自动转换为 `indent-N`（N = 全角空格数，上限 3）。

### SE 7.5.5　节选在长篇作品中的诗/歌/韵文：包在 `<blockquote>` 中
- SE 原规则：嵌在小说等长作品里的诗，用 `blockquote` + `epub:type`，内部为诗节 p。
- 我们现状：T9 `div.poem-quote`「文中引诗」；T6 引文用 `blockquote`；T9 的文中引诗 CSS `div.poem-quote p{text-indent:2em}`。
- 结论：修改后采用
- 理由：引诗本质是块引用，用 `blockquote` 语义更准；`div.poem-quote` 只是样式容器。统一后继承 T6 的缩进与字体。
- 落地：04 T9 的 `div.poem-quote` 改为 `blockquote.poem-quote`（带 `epub:type="z3998:poem"` 或 `z3998:verse`，见 7.5.6），内部同 7.5.1 结构；T6 的 CSS 选择器 `div.poem-quote` 同步改。独立成篇的诗仍用 `div.poem`（或集合中的 `article`）。

### SE 7.5.6 / 7.5.6.1　语义标记：`z3998:poem` / `z3998:verse` / `z3998:song` / `z3998:hymn`，及各自使用约定
- SE 原规则：整首引用用 poem（再短也是）；片段用 verse；歌词（全部或部分）用 song；赞美诗用 hymn，拿不准用 song。
- 我们现状：02 §5.7 只给 `z3998:verse` 且要求声明 `epub:prefix`，不声明则只留 class；T9 无 epub:type。
- 结论：采用
- 理由：符合原则 2（`z3998:` 是允许的标准词汇，且需声明）。补中文的判定：整首古诗词曲 → `poem`（词、曲虽可歌也算 poem）；节选/残句 → `verse`；现代歌词、流行歌曲、民歌 → `song`；赞美诗、圣歌、佛偈颂（明示为诗偈的）→ `hymn`，不确定用 `song`。
- 落地：02 §5.7 增上述四类与中文判定表，并把示例的 `z3998:verse` 改为按整首/节选取值；02 §6.1 末尾「自定义值需带前缀并声明」处链接；04 T9 所有 HTML 示例的外层元素加 `epub:type`，并写明需先在 `html` 上声明 `epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/"`（未声明则整个省略，不要半声明）；07 SEM-010 检查：带 z3998 的 epub:type 必须有前缀声明（已有同类规则则扩充值域表）。rebuild：识别诗歌需要先做分类（TYP-011，目前不输出诗），属后续实现。

### SE 7.5.7　引诗省略行：竖省略号 `⋮`（U+22EE）放 `<span class="elision">`
- SE 原规则：诗歌有行被删时用单独一行的 `⋮` 表示，`span.elision` 带 margin；题记内正体。
- 我们现状：无。06 对省略号用 `……`（六点，偶数）。
- 结论：修改后采用
- 理由：需求采用，字符不采用：`⋮` 在中文字体里字形/覆盖不稳，且中文出版惯例是用单独一行的 `……` 表示省略若干行。
- 落地：04 T9 加「引诗省略」：被删的行写作 `<span class="line elision">……</span>`（`……` 遵循 06 §2.4），CSS `span.elision{ text-indent:0; padding-left:3em; }`；竖排时省略号由 03 §7.6 的竖排规则处理，不另写。

### SE 7.5.8　诗歌里的 hgroup > p，居中对齐校正 CSS
- SE 原规则：诗中 hgroup 内的 `p` 在居中型里重设 `text-align:center`。
- 我们现状：T9 用 `p.poem-title` / `p.poem-author`；无 hgroup。
- 结论：不采用
- 理由：其他：这是 SE 的 CSS 补丁，只为抵消 `[z3998:poem] p{text-align:initial}` 的副作用。我们的诗题/作者用独立 class，不会被 `.stanza` 规则影响，不需要补丁。
- 落地：无。采用 7.5.1 的新结构后，注意选择器 `p.stanza` 不要写成 `div.poem p`，否则会波及 `p.poem-title`（T9 现用 `div.poem p` 的写法，改写时同步修）。

### SE 7.5.9　诗歌示例（含 `.i2` 级别的 CSS 示范）
- SE 原规则：完整的 CSS + HTML 例（Alice 里的诗，行 `i1`，一句内含 `em`）。
- 我们现状：T9 有居中、居左、词、自适应四个示例，没有「现代诗阶梯缩进」和「引诗省略」的示例。
- 结论：修改后采用
- 理由：补两个中文示例即可，不是照搬。
- 落地：04 T9 补两个示例：①现代诗（居左，含 `indent-1/2`，非逐句标点）；②古诗节选 `blockquote.poem-quote` + `elision`；两例均用新结构。

---

## 汇总

### 数量（共 53 条有结论的条目；7.2.9 总述不计）
已一致 7 条、采用 5 条、修改后采用 24 条、不采用 17 条。

### 建议采用或修改后采用（需要落地）
- 7.1.2 `division` 用于「部/卷」与章之间的中文层级。
- 7.1.3 / 7.1.3.1 诗词曲选、箴言集等「短单项集合」合一文件，每项一个 `article`，`break-after:page` 做成可配置（默认关）。
- 7.1.4 标题块允许 `header` / `hgroup` 两种包装。
- 7.1.5 / 7.1.5.1 可重组性：新增「首标题层级 = nav 深度」检查；我们拆文件时写 `data-parent`。
- 7.2.5 标题的直接父元素检查（`div` 包标题时改 `header`）。
- 7.2.6 / 7.2.9.5 / 7.2.10.4 主标题 + 副标题用 `hgroup`（`p epub:type="subtitle"`）；序号 + 题名不拆。
- 7.2.7 整标题外文时在标题元素上标 `lang`。
- 7.2.8 无标题页：`section` + `aria-label` + `no-head` 类，`%` 代替 `vh`。
- 7.2.9.2 序号 `z3998:ordinal` 作为可选标记。
- 7.2.10.3 的小修（不属于 SE 条目但由其引出）：T2 章号与章名两 span 间补一个全角空格，防止纯文本粘连。
- 7.2.10.7 同名诗词的目录区分（nav 加首句括注，STR-010 放行）。
- 7.2.10.11 `header` 中放标题 + `p.byline`。
- 7.2.11 章首提要块 `p.chapter-summary`（不使用 `bridgehead`）。
- 7.3.1 / 7.3.2 献辞模板（短：居中/随原书；长：同正文），不做垂直居中。
- 7.4.5.1 出处末尾不加句号（检测+修复）。
- 7.4.6.1 / 7.4.6.2 整页题记模板；多条题记用多个 `blockquote`。
- 7.5.1–7.5.4 诗歌结构：诗节 `p.stanza` + `span.line` + `br`，逐行缩进 `indent-N`。
- 7.5.5 文中引诗用 `blockquote.poem-quote`。
- 7.5.6 `z3998:poem/verse/song/hymn` 及中文判定表（含前缀声明）。
- 7.5.7 / 7.5.9 引诗省略行用 `……`；补两个中文示例。
- 另：04 T7 题记补楷体字体（7.4.1 引出）。

### 与现有规范冲突、需要决策的点
1. **「序号 + 题名」是否拆 hgroup（7.2.10.3 / 7.2.10.6 / 7.2.6）**。我的建议：不拆，保持 `h1` 内完整文本，hgroup 只用于主标题 + 副标题。理由是 hgroup 下 `p` 不是标题，中文书的目录和读屏标题列表会只剩「第一章」。如果你想与 SE 完全一致，需要在 nav 生成时把 hgroup 内文本拼回，且读屏侧无法补救。
2. **无标题的结构页：`section` + `aria-label`，还是 `div`（7.2.8 / 7.3.1 / 7.4.6.1）**。现行 02 §4.1 第 4、8 条是后者；SE 是前者。建议改前者，条件是必须有 `aria-label`。需实测 EpubCheck / Nu 校验对无标题 section 的反应。
3. **诗歌结构统一（7.5.1）**：现行 02 §5.7（诗节 p + span.line + br）与 04 T9（`div.stanza` 内一行一 `p`）互相矛盾。建议统一到 02 的写法（诗节为 `p`），则 T9 的 HTML/CSS 全部重写，并改 03 §1.3 的一句话。
4. **7.2.2（含 h 即进目录）与 7.2.1（非目录内容不用 h）不采用**：保持「目录范围由 nav 决定」。只需你确认这是有意保留；影响是 STR-010 要加书名页/版权页例外。
5. **`data-parent`（7.1.5.1）**：建议只在我们自己拆分文件时写，不强制输入书。需确认是否接受这个自家用途的 data 属性。
6. **诗集模式是否默认每首另起一页（7.1.3.1）**：建议默认关，配置项 `poem.page_break`。
7. **出处前破折号不交给 CSS（7.4.5.1）**：保持文本里写 `——`，与 SE 做法相反，理由是 L0 信息不依赖 CSS。需确认。
8. **`epub:type="contributors"`、`label`/`ordinal` 是否属于 EPUB 结构词表**：我没有在本机核对词表原文，文中保守处理（不使用 `contributors`；序号用 DAISY 的 `z3998:ordinal`）。落地前请对照 EPUB Structural Semantics Vocabulary 当前版本核实。

### 代码（rebuild.py）相关待办
- 有「部」的书：章标题应降为 `h2`，nav 嵌套（现为全 h1 平级）。
- 副标题识别并输出 `hgroup`（需要判定规则/LLM）。
- 诗歌：目前没有任何诗歌输出；按本文 7.5.x 实现时直接采用新结构。
- 章标题「序号+题名」输出保持整体文本，序号与题名间保留一个空白字符。
