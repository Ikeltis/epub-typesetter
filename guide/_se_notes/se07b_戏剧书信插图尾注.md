# SE Manual of Style 第 7 章（758 行至结尾）对照笔记：戏剧、书信、插图、插图目录、尾注、术语表

> 范围：`_book_src/se_manual/7-high-level-structural-patterns.rst` 第 758 行至末尾（Plays and drama / Letters / Images / List of Illustrations / Endnotes / Glossaries）。
> 对照对象：`guide/04` T8 书信、T11 剧本、T12 插图、T13 图注、T16 注释；兼及 `guide/02` §7、`guide/05` §1.5、`guide/07`、`src/epub_typesetter/rebuild.py`。
> 说明：SE 的 `z3998:*` 来自 DAISY Z39.98 词表，属允许范围，用前须在 `<html>` 上声明 `epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/"`（02 §7 已有此要求）。`se:*` 一律不用。凡标【需核对】的词表项，落地前须对照 Z39.98 词表原文与 epubcheck 实测。

---

## A. 戏剧（Plays and drama）

### SE 7.A.1　对白用 `<table>`，每个 `<tr>` 是一段对白或一条独立舞台说明
- SE 原规则：戏剧对白用表格，左列角色名，右列台词；纯舞台说明占一行，左列为空 `<td/>`。
- 我们现状：guide/04 T11 用 `p.speaker-line` + `p.dialogue`（角色名独占一行），或「角色名＋全角空格＋台词」；没有表格方案，也没有 `epub:type`。
- 结论：不采用
- 理由：中文不适用 / 与厂商无关原则冲突。中文剧本的主流排法是「人名：台词」连排，回行要齐；双列表格在窄屏会挤压台词栏（SE 自己也要在 400px 以下把 td 改成 block）；表格还容易被部分阅读系统当成数据表。保持 p 结构，窄屏降级天然成立。
- 落地：无。T11 注意事项补一句「不用 table 排对白，原因同上」。

### SE 7.A.2　角色名用小型大写，永不斜体
- SE 原规则：persona 一律小型大写，即使上下文是斜体也不斜。
- 我们现状：T11 角色名无特殊字体；03 已禁用斜体、小型大写。
- 结论：不采用
- 理由：中文不适用。中文没有小型大写，也没有斜体。可以保留「角色名不被舞台说明字体（楷体）带走」这一点：舞台说明用楷体，角色名保持正文字体。
- 落地：T11 CSS 注释里写明 `.persona` 不继承 `.stage` 的楷体。

### SE 7.A.3　戏剧核心 CSS（表格宽度、列宽 20%、`td:first-child` 右对齐、400px 以下转 block）
- SE 原规则：一整套围绕 table 的 CSS，另有 `z3998:drama` 作用域，窄屏时把单元格转为块。
- 我们现状：T11 CSS 三条（`.stage`、`.speaker-line`、`.dialogue`），台词整体缩进 2em 以适应手机。
- 结论：不采用（表格 CSS）；其中「`z3998:drama` 作为样式作用域」这一点采用，见 7.A.12。
- 理由：中文不适用（依附于表格）。SE 的窄屏降级结果和我们的 p 结构本来就一样。
- 落地：无。

### SE 7.A.4　对白行：第一格 `z3998:persona`（不带结尾标点），第二格台词；单行台词不加块级子元素
- SE 原规则：角色名放 `<td epub:type="z3998:persona">`，不含冒号等结尾标点；台词放第二格。
- 我们现状：T11 用 class（`speaker-line`/`dialogue`），无 `epub:type`。「人名：台词」连排形式没有对应模板。
- 结论：修改后采用
- 理由：语义值（`z3998:persona`）符合我们的标准词汇原则，能被检测和修复；中文剧本最常见的是冒号连排，模板须覆盖。落地时角色名外包 `<span class="persona" epub:type="z3998:persona">`，冒号留在 span 外面，这样关掉 CSS 也读得通。
- 落地：
  1. guide/04 T11 增加变体 B：`<p class="dialogue"><span class="persona" epub:type="z3998:persona">张三</span>：台词</p>`；CSS 用悬挂缩进（`padding-left:Nem; text-indent:-Nem`，N 按最长角色名字数取，上限 4em）。识别信号：`^[^，。！？：\s]{1,6}[：:　]` 在连续多段出现，且角色名重复率高。
  2. 变体 A（角色名独占一行）给 `p.speaker-line` 里的名字同样加 `epub:type="z3998:persona"`。
  3. guide/07 新增检查：同一部剧本内，角色名写法一致（「铁梅/铁　梅」「李奶奶/奶奶」），不一致列入确认清单（LLM 判断是否同一人）。
  4. 角色名中间的全角空格（「铁　梅」，用于对齐）是排版用空格，应删除并用 CSS 对齐；与 06 的「去手工空格」规则协调，剧本内走例外或统一处理，需在 06 写明。

### SE 7.A.5　对白若是分行的诗体，台词格用 `z3998:verse` 并套诗歌结构
- SE 原规则：台词分行（诗体）时，该 `<td>` 带 `z3998:verse`，内部用 verse 结构。
- 我们现状：T9 诗词曲有完整结构；02 §5 的示例已用 `div.poem epub:type="z3998:verse"`。T11 里的唱词（`【西皮散板】`后的行）只当普通 dialogue 段。
- 结论：采用
- 理由：唱词、念白韵文是中文戏曲剧本的常见成分，复用 T9 结构合理。
- 落地：guide/04 T11 注意事项：台词里每行一句的唱词用 T9 的 `div.poem[epub:type~="z3998:verse"]`（每行一个 `p`）放在对应 `dialogue` 之后，曲牌名（`【西皮散板】`）归入舞台说明或角色行，不进诗行。

### SE 7.A.6　多人齐说用 `tr.together` + `rowspan`
- SE 原规则：多名角色同时说同一句话，使用 `together` 类和 `rowspan`，竖线连接。
- 我们现状：无。
- 结论：不采用
- 理由：中文不适用（依附于表格）。中文剧本里「众：」「合：」「同声：」本身就是一个角色名。
- 落地：无。识别时把「众/合/同/齐」当作普通角色名，不做特殊处理。

### SE 7.A.7　舞台说明用 `<i epub:type="z3998:stage-direction">`，括号用 CSS 伪元素生成
- SE 原规则：舞台说明包在斜体元素里，语义值 `z3998:stage-direction`，左右括号由 `::before/::after` 生成。
- 我们现状：T11 `p.stage` 用楷体、缩进 2em，括号写在正文里，无语义值。
- 结论：修改后采用
- 理由：语义值采用；`<i>` 不采用（中文无斜体）；括号**不用**伪元素生成，保留文本中的全角括号（`（）`/`〔〕`）：生成内容不进入文本，搜索、复制、读屏、字体子集化（05 §3）都会丢，且 06 已规定括号是文本层规范化对象。
- 落地：
  1. guide/04 T11：整段舞台说明 `<p class="stage" epub:type="z3998:stage-direction">（……）</p>`；行内插入 `<span class="stage" epub:type="z3998:stage-direction">（……）</span>`；字体沿用楷体，不加斜体。
  2. guide/04 §0.2 类名注册表：`stage` 的元素列写 `p/span`；新增 `persona`。
  3. guide/07 新增检查：舞台说明括号配对（全角括号，不混用半角）；括号被 CSS `content` 生成的情况报告（检测 `::before{content:"("}` 一类）。

### SE 7.A.8　外来版本补入的舞台说明加 `class="editorial"`，括号变方括号
- SE 原规则：从其他版本补进来的舞台说明带 `editorial` 类，括号用 `[ ]`。
- 我们现状：无。
- 结论：修改后采用
- 理由：中文校注本里「〔编者按〕」「〔此处原缺〕」确实常见，但这属版本批注，不是 SE 那种「合并版本」场景。只做识别，不做自动改写。
- 落地：guide/04 T11 注意事项：原书已用 `〔〕`、`［］` 标注的编者补入说明，加 `class="editorial"`，括号保留原字符；不自动生成。优先级低。

### SE 7.A.9　舞台说明中提到的角色名用 `<b epub:type="z3998:persona">`，所有格 's 一起包进去
- SE 原规则：舞台说明里提到角色名时包 persona；英文所有格 `’s` 含在内。
- 我们现状：无。
- 结论：修改后采用
- 理由：语义有用（可检测一致性），但 `<b>` 是表现性元素，我们用 `<span class="persona" epub:type="z3998:persona">`。中文没有所有格问题，「的」留在 span 外。
- 落地：guide/04 T11 注意事项一句；自动识别只在能由角色表（7.A.14）或对白说话人列表匹配时做，置信度中，列入报告。优先级低。

### SE 7.A.10　速记式舞台说明（`R. 3 E.`）用 `<abbr epub:type="z3998:stage-direction">` 小型大写
- SE 原规则：舞台方位缩写单独处理。
- 我们现状：无。
- 结论：不采用
- 理由：中文不适用（英文剧场方位缩写）。中文剧本的「台左/台右/上场门/下场门」是普通词，写在舞台说明里即可。
- 落地：无。

### SE 7.A.11　纯舞台说明行：第一格留空，第二格放说明；行内舞台说明的大小写与标点
- SE 原规则：纯舞台说明行是空 `<td/>` + 说明；行内舞台说明若独立成句则首字母大写、句末标点，若是从句内插话则小写、通常无句末标点。
- 我们现状：无（我们是 p 结构，无空格单元格）。
- 结论：修改后采用（仅标点部分）
- 理由：空 td 是表格产物，不采用。大小写规则中文不适用；标点思路可迁移：独立成句的舞台说明在括号内以句号结尾，句中插话括号内不加句末标点。这是排版习惯，不是硬规则，原书若不一致只报告，不改写。
- 落地：guide/06 PUN 系列加一条 C 级统计：括号内舞台说明句末标点两种写法并存时，列出少数派。guide/07 对应登记。

### SE 7.A.12　整部剧本：`body` 带 `z3998:drama`；幕是 `section`；幕首的场景说明放在表格之外；每幕可有幕标题和幕末说明
- SE 原规则：`<body epub:type="bodymatter z3998:fiction z3998:drama">`，幕为 `section`（`chapter z3998:scene`），幕内含对白表和顶层舞台说明 `<p>`。
- 我们现状：无剧本整体语义。
- 结论：修改后采用
- 理由：整体语义值有助于阅读系统与检测；SE 把「幕」标成 `z3998:scene` 是它自己的选择，**不照搬**：幕/场的对应值需对照 Z39.98 词表原文【需核对】，未核对前只标 `chapter`（幕）与 `z3998:scene`（场），不标未确认的词。`z3998:fiction` 与剧本无关，不加。
- 落地：
  1. guide/02 §8（`epub:type` 速查）加一行「剧本整体：`bodymatter z3998:drama`」，并说明须声明 `z3998` 前缀。
  2. guide/04 T11 识别信号补「全书 ≥70% 段落为对白/舞台说明 → 视为整部剧本」，置信度低，需用户确认。
  3. rebuild/semantic：识别到剧本时给 `body` 加 `z3998:drama` 并写入前缀声明；各幕保持 `section`。

### SE 7.A.13　角色表（dramatis personae）：`section[epub:type="z3998:dramatis-personae"]` 内放 `<ul>`，居中、斜体
- SE 原规则：登场人物表用无序列表；条目居中；斜体。
- 我们现状：无。
- 结论：修改后采用
- 理由：语义与结构采用；居中、斜体不采用。中文「人物表」常见格式是「角色名　身份说明」，左对齐或名与说明两列，不居中。
- 落地：guide/04 T11 增加子模板「人物表」：`<section epub:type="z3998:dramatis-personae"><h1>人物表</h1><ul><li><span class="persona" epub:type="z3998:persona">铁梅</span>　李玉和之女，十七岁</li>…</ul></section>`，`ul` 去圆点，名与说明间用全角空格。识别信号：剧本开头紧邻标题「人物表/登场人物/角色表/剧中人物」的短行列表。

---

## B. 书信（Letters）

### SE 7.B.1　书信包在 `<blockquote>`，语义 `z3998:letter`
- SE 原规则：书信用 blockquote 包裹，语义值 `z3998:letter`。
- 我们现状：T8 用 `div.letter`，无语义值；02 §5.5 规定 blockquote 只用于引用他人的话。
- 结论：修改后采用
- 理由：两条合起来：语义值 `z3998:letter` 采用；容器按场景分——小说、传记里被引用的信件用 `blockquote`（符合 02 §5.5 的「引用他人的话」），书信集中的整封信用 `div`/`section`。两种容器都带 `epub:type="z3998:letter"`。
- 落地：guide/04 T8：HTML 结构里加 `epub:type="z3998:letter"`，并增加「嵌入叙事的信件用 `blockquote.letter`」的说明；类名注册表 `letter` 的元素列改为 `div/blockquote`；guide/02 §8 速查表加一行。**需决策**：见汇总冲突点 1。

### SE 7.B.2　电报加 `class="telegram"`，小型大写
- SE 原规则：电报体加 `telegram` 类，全部小型大写。
- 我们现状：无。
- 结论：不采用
- 理由：中文不适用（小型大写）。中文电报没有对应的字体传统。
- 落地：无。

### SE 7.B.3　信头部分（地点、日期、称谓）包 `<header>`；blockquote 内的 header/footer 加 `role="presentation"`；只有称谓时省略 header
- SE 原规则：称谓之前的部分放 `<header>`；仅有称谓时不用。
- 我们现状：T8 是扁平 `p`，信头用 `h3.letter-title` + 日期 span；称谓、署名、日期用 class。
- 结论：不采用
- 理由：其他。header/footer 与 SE 的「右对齐 footer」绑在一起（见 7.B.8），而中文信的落款里祝颂语左对齐、署名与日期才右对齐；用 `header/footer` 分组再逐个覆盖对齐，反而更复杂。扁平 p 加 `epub:type` 已可检测、可修复。`role="presentation"` 的补丁也用不上（`header`/`footer` 嵌在 blockquote 内不构成页面级地标，需用 epubcheck/读屏实测确认）。
- 落地：无。

### SE 7.B.4　信头地点日期用 `se:letter.dateline`，日期用带机读值的 `<time>`
- SE 原规则：地点+日期放 `se:letter.dateline`，日期包 `<time datetime>`。
- 我们现状：T8 有 `p.date`、`.letter-date`，日期是纯文本。
- 结论：修改后采用
- 理由：`se:letter.dateline` 不采用（SE 自定义词汇）。标准词汇里没有对应值，用 class `dateline` 即可。`<time datetime>` 是标准 HTML，可采用，但中文日期常无年份（「二月五日」）、用民国/干支/农历纪年，只有能确定公历且置信度高时才加 `datetime`；无年份时可用 HTML 允许的 `--02-05` 形式。其余保持纯文本。
- 落地：
  1. guide/04 T8：日期类 `date` 保持；增加可选的 `<time datetime="1898-02-17">一八九八年二月十七日</time>`，说明何时加（见上）。
  2. guide/04 §0.2：`date` 的说明加「地点+日期合一行时用 `dateline`」。
  3. guide/06：数字与日期规则不变，`<time>` 内的文本仍按 06 处理，`datetime` 属性不碰。

### SE 7.B.5　称谓用 `z3998:salutation`；独立成行的称谓小型大写；行内称谓用 `<span>`/`<b>`
- SE 原规则：称谓标 `z3998:salutation`，独立行时小型大写，嵌在首行时用 span。
- 我们现状：T8 有 `p.salutation`（顶格），无语义值。
- 结论：修改后采用
- 理由：语义值采用；小型大写不采用（中文）。中文称谓几乎都独立成行（「西谛先生：」），嵌在首行的情况（「亲爱的妈妈，我今天……」）少见，可用 span。
- 落地：guide/04 T8：`p.salutation` 加 `epub:type="z3998:salutation"`；说明行内称谓用 `<span class="salutation" epub:type="z3998:salutation">`。guide/07 SEM-020（特殊块语义识别）里把书信的各部分语义值写进「修复」列。

### SE 7.B.6　称谓后的第一行不缩进
- SE 原规则：称谓之后第一行不缩进。
- 我们现状：T8：「正文仍缩进 2em」。
- 结论：不采用
- 理由：中文不适用。中文书信格式是称谓顶格、正文首行缩进 2em。
- 落地：无。

### SE 7.B.7　收信人名（信头 To: 一类）用 `z3998:recipient`；正式信函可放在文末 footer
- SE 原规则：非称谓形式的收信人名标 `z3998:recipient`。
- 我们现状：T8 有书信集标题 `h3.letter-title`（「致许家惺」「与X书」），无语义值。
- 结论：采用
- 理由：标准词汇，可检测（标题以「致/与/寄/复/答」开头）。
- 落地：guide/04 T8：`letter-title` 中的收信人名包 `<span epub:type="z3998:recipient">`；优先级低，仅在标题形态规整时自动做。

### SE 7.B.8　footer 放信末内容；footer 整体右对齐
- SE 原规则：祝颂、署名、附言放 `<footer>`；`footer{text-align:right}`。
- 我们现状：T8：`closing` 左对齐（顶格），`signature`、`date` 右对齐。
- 结论：不采用
- 理由：中文不适用。中文信末是「此致」缩进 2em 或顶格、「敬礼」顶格，两行都靠左，只有署名与日期靠右；整体右对齐会让祝颂语错位。
- 落地：无。

### SE 7.B.9　祝颂语 `z3998:valediction`；发信人 `z3998:sender`；签名 `z3998:signature`（小型大写）
- SE 原规则：三个语义值，签名小型大写。
- 我们现状：T8 用 `p.closing`、`p.signature`，无语义值。
- 结论：修改后采用
- 理由：语义值采用；小型大写不采用。中文「迅　启上」「弟 曼福 顿首」中，署名与「启上/顿首」是一个整体，整行标 `signature`，不做 sender/signature 的细分，以免过度标注。
- 落地：guide/04 T8：`p.closing` 加 `epub:type="z3998:valediction"`，`p.signature` 加 `epub:type="z3998:sender z3998:signature"`；T8 的识别信号保持。图片签名（registry 里的 `signature-img`）alt 写人名，不进 LoI（见 7.D.4）。

### SE 7.B.10　祝颂语与签名是同一个分句时，合为一个 `<p>`，用 `<br/>` 分行
- SE 原规则：「Very sincerely yours,」与签名合在一个 p 内，用 br 换行。
- 我们现状：T8 把「此致」「敬礼」「署名」各自成 `p`。
- 结论：不采用
- 理由：中文不适用。「此致/敬礼」是两行，对齐不同；署名在右下方，不与祝颂语构成一个分句。保持分段，也与 03 的「不用 br 做结构」一致。
- 落地：无。

### SE 7.B.11　附言（P.S.）用 `z3998:postscript`；多段附言包 `<div epub:type="z3998:postscript">`
- SE 原规则：附言上方留 1em，不缩进，不右齐。
- 我们现状：无。T8 只有 signature、date。
- 结论：采用
- 理由：中文有「又及」「再启」「附言」「追启」，是确定的信件组成部分，可检测。
- 落地：guide/04 T8：增加 `<p class="postscript" epub:type="z3998:postscript">又及：……</p>`；CSS `p.postscript{ margin-top:1em; text-align:left; }` 首行缩进保持默认 2em（与中文习惯一致，不照搬 SE 的不缩进）；类名注册表新增 `postscript`。识别信号：署名之后出现以「又及/再启/再及/追启/附：/P.S.」开头的段。

### SE 7.B.12　书信示例 CSS：`header` 右对齐、`header + p` 不缩进
- SE 原规则：信头右对齐，其后第一段不缩进。
- 我们现状：T8：日期（落款处）右对齐；称谓顶格。
- 结论：不采用
- 理由：中文不适用，与 7.B.6、7.B.8 同理；中文信的日期通常在文末右下，不在信头。信头有日期时（书信集小标题处），沿用 T8 的 `.letter-date`。
- 落地：无。

---

## C. 插图（Images）

### SE 7.C.1　每个 `<figure>` 有唯一 id，形如 `illustration-N`，N 为顺序号
- SE 原规则：figure 的 id 是 `illustration-` 加序号。
- 我们现状：无规定；rebuild 生成的 `figure` 不带 id。
- 结论：修改后采用
- 理由：LoI 需要直接链到图（见 7.D.6），所以需要稳定 id。命名我们用 `fig-N`（与书内「图1—1」编号无关，N 为全书顺序号）。原书已有 id 且被引用时不改，只补缺。
- 落地：
  1. guide/02 §7.3（id 命名约定）加 `fig-N`。
  2. rebuild.py：生成 `figure` 时补 `id="fig-N"`（顺序号），已有 id 保留（`_anchors` 机制保持）；原书 id 若被外部链接引用，由 `id_map` 维持。
  3. guide/07：figure 缺 id 且存在 LoI 时报错；id 重复报错。

### SE 7.C.2　`alt` 用完整句子详细描述图像本身，不等于图注，也不是描述图在书中的位置
- SE 原规则：alt 描述视觉内容，不写「第十章的插图」，也不写人物关系或标题式文字。
- 我们现状：guide/05 §1.5：简述图像要传达的信息，≤125 字符，不写「图片」前缀，不重复紧邻 figcaption；检测文件名、「图」「图片」等无效 alt。
- 结论：已一致
- 理由：要点相同（描述画面、不抄图注）。
- 落地：无。

### SE 7.C.3　`alt` 不含不换行空格、词连接符；alt 以标点结尾，行内小图例外
- SE 原规则：alt 内不含 NBSP/WJ；alt 是完整句，以句号等结尾；行内图（如乐谱符号）可以是无标点的短语，读起来要融入上下文。
- 我们现状：05 §1.5 没有标点要求；06 §0 对 alt 只启用「空白」和「全角英数转半角」；生僻字图 alt 就是该字本身（05 §2）。
- 结论：修改后采用
- 理由：NBSP/WJ/零宽字符对读屏无意义，应清除；以全角句号结尾的要求适用于块级插图的描述性 alt；行内图（`glyph`、`formula`、字符图）不加标点。
- 落地：
  1. guide/06 §0 第 3 条：alt 规范化加「删除 U+00A0、U+2060、U+200B 一类不可见字符」。
  2. guide/05 §1.5：补一行「块级内容性插图的 alt 以句号（。）或其他句末标点结束；行内图（class `glyph`/`formula`，或位于文字中间且 ≤2em）不加」；检测为 info 级。
  3. guide/07 图像类新增一条 info 检查，ID 待分配。

### SE 7.C.4　alt 不一定与 `figcaption` 相同
- SE 原规则：alt 描述画面，图注是语境化的说明，二者可以不同。
- 我们现状：05 §1.5 一致；但 `rebuild.py` 第 470–472 行在 alt 缺失时直接把图注文字写进 alt。
- 结论：已一致（规范层）；实现层与规范有出入
- 理由：规范没问题；实现把图注复制成 alt，读屏会把同一句话读两遍，与 05 §1.5「不重复图注」相悖。
- 落地：rebuild.py：alt 缺失且有 figcaption 时，保留这一兜底，但在报告里标记「alt 取自图注，待确认」，并建议交 LLM 生成画面描述草稿（05 §1.5 已要求 AI 草稿须用户确认）。**需决策**：见汇总冲突点 3。

### SE 7.C.5　`<img>` 标图像类型：`z3998:illustration`、`z3998:photograph`
- SE 原规则：img 上带类型语义值。
- 我们现状：无。
- 结论：修改后采用
- 理由：标准词汇，有助于 LoI 筛选；但类型判断（照片/插画/地图）要靠视觉模型或用户确认，所以只作可选项，不自动全量添加。
- 落地：guide/02 §8：img 可选 `epub:type="z3998:illustration|z3998:photograph"`，须声明前缀；guide/05 §1.5：LLM 生成 alt 草稿时可同时给类型建议。优先级低。

### SE 7.C.6　黑白线稿图转成透明背景 SVG，加 `se:image.color-depth.black-on-transparent`
- SE 原规则：纯黑线稿一律是 SVG、透明底，带 SE 专属语义。
- 我们现状：T12 `img.line-art` 加白底板解决夜间模式；05 对 SVG 另有规定。
- 结论：不采用
- 理由：SE 出版物专属 / 与厂商无关原则冲突（`se:` 词汇）。我们处理别人的书，不重绘、不转矢量；位图保持位图。
- 落地：无。

### SE 7.C.7　写实风格线稿加 `se:image.style.realistic`
- SE 原规则：为写实线稿加一个附加语义。
- 我们现状：无。
- 结论：不采用
- 理由：SE 出版物专属（`se:` 词汇）。
- 落地：无。

### SE 7.C.8　块级图放在 `<figure>` 里，`<figcaption>` 可选，是简短、依语境而定的图注
- SE 原规则：块对齐或整页图用 figure；figcaption 可选，不必等同于 alt。
- 我们现状：T12/T13、02 §4、SEM-017 已规定。
- 结论：已一致
- 理由：做法相同。
- 落地：无。

### SE 7.C.9　figure/figcaption 的核心 CSS
- SE 原规则：`figure{break-inside:avoid; margin:1em 2.5em}`；`figure img{display:block; margin:auto; max-height:100vh; max-width:100%}`；`figcaption{font-size:smaller; font-style:italic; margin:1em; text-align:center}`；`figcaption p+p{text-indent:0}`。
- 我们现状：03 §5 有 `figure{break-inside:avoid; text-align:center}`、`figure img{display:block; margin:0 auto}`、`figcaption{font-size:.9em; 楷体; text-align:center}`；无 `max-height`；图注多段缩进未处理。
- 结论：修改后采用
- 理由：`break-inside:avoid`、居中、小字号已有；斜体和 2.5em 左右外边距不采用（中文、窄屏）。`max-height:100vh` 是有价值的补丁，能防止竖长图超出一屏；`figcaption p+p{text-indent:0}` 对多段图注有用（我们的 `figcaption` 已设 `text-indent:0`，覆盖了这一点）。
- 落地：guide/03 §5：`figure img` 加 `max-height:100vh; width:auto`（注意：与 `.w-80` 等宽度类并用时，`max-height` 优先导致比例失真的问题要用 `object-fit:contain` 或不对有宽度类的图加高度上限，【需实测】）。

### SE 7.C.10　整页图加 `full-page` 类：`break-before:page; break-after:page`
- SE 原规则：整页插图的 figure 带 `full-page`。
- 我们现状：05 §1.4 提到整页插图不裁；T12 没有对应类。
- 结论：采用
- 理由：中文书的插页、整页图常见；类名是我们自己的，不涉及 SE 词汇。
- 落地：guide/04 T12：增加 `figure.full-page{ break-before:page; break-after:page; }`，类名注册表新增 `full-page`；识别信号沿用 05 §1.4（宽高均 ≥90% 版心）。已自成一个文件的整页图（分文件时）不再加 `break-before`，避免空白页。

### SE 7.C.11　行内图（异星文字）：img 直接放在段落里，alt 读起来要通顺
- SE 原规则：行内图不放 figure，alt 融入上下文。
- 我们现状：T12 的 `glyph`、`formula` 行内图。
- 结论：已一致
- 理由：做法相同，alt 规则见 7.C.3。
- 落地：无。

### 补充　中文图注「图1—1」的编号习惯
- SE 原规则：无（英文书的图注不含固定编号格式）。
- 我们现状：T13 示例是「图 1-3　地平坐标系」（带空格、半字线）；识别正则 `^图\s*\d+[-—.．]?\d*` 已覆盖多种写法；06 PUN-11 只处理范围号，未涉及图表编号。
- 结论：修改后采用（对 T13 的补充）
- 理由：图表编号「图1—1」「图1-1」「图1.1」「图 1-1」在中文书中并存，全书应统一，但具体用哪种取决于原书，不宜强制。
- 落地：
  1. guide/04 T13：规定图号与图题之间用一个全角空格或半角空格，保持原书；全书统一为**占多数的写法**。
  2. guide/06 PUN-12 增加「图表编号连接符统计」C 级：`图\s*\d+[-—－–.．]\d+` 多种连接符并存时，列出少数派，建议统一，不自动改。
  3. 图号文字必须是实际文本，不用 CSS counter 生成（否则 LoI 和搜索里没有）。
  4. 图号**不用于 id**（id 用 `fig-N`，见 7.C.1）；表题（表1—1）同理。

---

## D. 插图目录（List of Illustrations）

### SE 7.D.1　只要有读者想回头看的插图（哪怕只有一张），就有 LoI
- SE 原规则：有值得回看的插图就设 `loi.xhtml`。
- 我们现状：02 §8 速查表有 `loi` 词；01 §导航允许自定义 `nav epub:type="loi"`；没有生成规则。
- 结论：修改后采用
- 理由：我们不凭空给别人的书加页面（原则 4 的精神），所以：原书已有「插图目录/图目录/图表目录/插图索引」页时，转成标准 LoI；原书没有时，仅在条件满足时**提示**，经用户确认才生成。
- 落地：
  1. guide/04 新增模板 T12a 插图目录（或并入 T12），识别信号：标题含「插图目录/图目录/插图索引/图片目录」，正文是一串「图X—Y　题名……页码」的行。页码要丢弃（电子书无固定页）。
  2. 生成条件（建议）：非装饰的块级带图注插图 ≥5 张时提示；用户确认后生成。
  3. rebuild/semantic：见 7.D.2 至 7.D.6。

### SE 7.D.2　LoI 文件为 `loi.xhtml`，语义 `backmatter`
- SE 原规则：路径固定，body 标 `backmatter`。
- 我们现状：无。
- 结论：修改后采用
- 理由：文件名 `loi.xhtml` 采用；位置与 body 语义按原书：中文书的插图目录常在前面（目录之后），此时保持位置，body 标 `frontmatter`，不强搬到书末。
- 落地：guide/02 §3 文件命名表加 `loi.xhtml`；guide/01 landmarks 加 `loi`（01 已列此值）；spine 位置跟随原书。

### SE 7.D.3　LoI 只收读者想回看的插图
- SE 原规则：举例保留叙事相关插图、地图、纪实照片；排除签名图、行内伪文字、版面元素图、示例乐谱、章末装饰。
- 我们现状：无。
- 结论：采用
- 理由：规则可判定，且和我们的 `class` 体系一致。
- 落地：guide/04 T12a：纳入条件为块级 `figure>img`，非装饰（alt 非空）；排除 `glyph`、`formula`、`signature-img`、`line-art`（线稿图、公式）以及 `alt=""` 的装饰图、章末花饰（宽或高小于版心 1/4）。用户可手工增删，列在确认清单。

### SE 7.D.4　LoI 结构：单个 `<nav id="loi" epub:type="loi">`，内含标题和 `<ol>`
- SE 原规则：nav 里放 `h2` 标题 + `ol`。
- 我们现状：01 允许 `nav epub:type="loi"`，无结构规定。
- 结论：采用
- 理由：EPUB 3.3 允许内容文档中的 nav，`loi` 来自结构语义词表；标准结构。标题层级沿用 T16 的做法，用 `h1`（独立文件首标题），而不是 SE 的 `h2`。
- 落地：guide/04 T12a：`<nav id="loi" epub:type="loi"><h1>插图目录</h1><ol>…</ol></nav>`；CSS `nav#loi ol{ list-style:none; padding-left:0 }`（编号已在图注里，不重复）。同时列为 spine 项并在 nav 文档的 toc 里出现「插图目录」。

### SE 7.D.5　条目文字优先用图注，没有时用 alt；图注太长时改用 alt
- SE 原规则：anchor 文字取 figcaption，无则 alt，图注太长改用 alt。
- 我们现状：无。
- 结论：修改后采用
- 理由：基本采用；中文图注含「图1—1　」编号与「来源：…」附注行（T13 的 `<br/>` 多行）。条目取**编号+题名的第一行**，去掉来源行；超过 40 字再回退到 alt（与 T13 的 ≤40 字识别阈值一致）。
- 落地：guide/04 T12a 写明取值顺序：figcaption 首行（≤40 字）→ alt；生成结果列入确认清单，由 LLM 或用户校对。

### SE 7.D.6　链接指向图的 id，不是文件顶部
- SE 原规则：href 带 `#illustration-N`。
- 我们现状：无。
- 结论：采用
- 理由：可检测可修复，且是 LoI 的价值所在。
- 落地：guide/07 新增检查：LoI 的每个链接目标存在且是 `figure`（或 img）的 id；不指向文件顶部；失败时报错。依赖 7.C.1。

---

## E. 尾注（Endnotes）

### SE 7.E.1　电子书不要脚注，只要尾注；脚注转成尾注
- SE 原规则：只保留尾注，脚注改成尾注。
- 我们现状：T16「默认统一做成全书一个书末尾注文件……一书一种方案，不混用」；rebuild 已实现。02 §7 保留脚注写法用于识别输入书。
- 结论：已一致
- 理由：做法相同。
- 落地：无。

### SE 7.E.2　`Ibid.`：上一条尾注即所指来源时展开为完整引文，否则保留
- SE 原规则：弹注环境里「同上」失去上下文，因此能展开就展开。
- 我们现状：T16 无此规则；rebuild 不处理。
- 结论：修改后采用
- 理由：弹注下「同上」确实无意义，中文同类词包括「同上」「同前」「同上书」「同前书」「同书」「前引书」「ibid.」。展开需要读上一条注并改写页码（「同上，第23页」→「《书名》，第23页」），机器容易错，只给建议，不自动改。
- 落地：guide/04 T16 要点加一条；guide/07 新增检查（SEM 系列，P2，info）：注文以上述词开头 → 取紧邻前一条尾注，若其是单一引文则生成展开建议；若不是紧邻前一条或前一条有多个来源，则保留并报告。处理方式：LLM + 用户确认。注意注序按首次引用重排后，原书的「上一条」可能变化，须在重排之后判断。

### SE 7.E.3　noteref 是带语义 `noteref` 的 `<a>`，直接指向尾注文件中的 `<li>`
- SE 原规则：`<a epub:type="noteref">`，href 指向 `endnotes.xhtml#note-n`。
- 我们现状：T16、rebuild 一致（另加 `role="doc-noteref"`）。
- 结论：已一致
- 理由：做法相同；多出的 `role="doc-noteref"` 是标准 DPUB-ARIA，不冲突。
- 落地：无。

### SE 7.E.4　noteref 有 `id="noteref-n"`，n 与尾注号相同；文本是注号
- SE 原规则：每个 noteref 有唯一 id，文本为注号。
- 我们现状：T16 一致；rebuild 用 `noteref-{num}`。
- 结论：已一致（规范）；**实现有隐患**
- 理由：rebuild.py `number_notes` 里同一条注被多处引用时，每个引用都得到 `id="noteref-{num}"`，会产生重复 id（02 §7.2.1 允许「一个注释可有多个引用」）。T16「回链指向第一次引用」只说了回链，没说其他引用的 id。
- 落地：rebuild.py：首次引用用 `noteref-n`，之后的引用用 `noteref-n-2`、`noteref-n-3`；回链只指第一个。guide/07 SEM-007 补「id 全局唯一」检查（07 已有通用的重复 id 检查，此处仅需确认覆盖）。

### SE 7.E.5　句末的 noteref 放在句末标点之后
- SE 原规则：位于句末时，noteref 放在标点后。
- 我们现状：T16「注号写在标点之后」，一概而论。
- 结论：修改后采用
- 理由：句末注放标点后与 SE 一致；但中文词语注（注在句中某个术语之后，如「牛顿¹的理论」）习惯贴着被注词，不应一律移到标点之后。registry 里的 `noteref-term` 类正是为此而设，但 T16 没写规则。
- 落地：guide/04 T16 要点：句末注放句末标点（含句末引号，见 7.E.6）之后；句中词语注保持原位置，不移动，也不移到逗号之后。rebuild 不移动注号，只清除前后空白（SEM-012）。

### SE 7.E.6　注释针对整句引文或引文末词时，noteref 放在引号之外
- SE 原规则：noteref 位于引号之外。
- 我们现状：T16 无。
- 结论：采用
- 理由：与中文习惯一致（注号在 `」` 或 `”` 之后），也避免注号被当作引文的一部分。
- 落地：guide/04 T16 要点；guide/07 新增检查（B 级，可自动修复）：注号紧贴在 `。」`/`。”` 之内（注号后紧跟闭引号）→ 移到闭引号之后。引文中本来就有注号（原作者自带注）的情况无法区分，列入报告，不静默改。

### SE 7.E.7　尾注文件 `endnotes.xhtml`，语义 `backmatter`
- SE 原规则：文件名、body 语义固定。
- 我们现状：T16 示例与 rebuild（`endnotes.xhtml`、`<body epub:type="backmatter">`）一致。
- 结论：已一致
- 理由：做法相同。
- 落地：无。

### SE 7.E.8　尾注文件只含一个 `<section id="endnotes" epub:type="endnotes">`，内含标题和 `<ol>`
- SE 原规则：结构固定；标题 `h2`。
- 我们现状：T16 一致（标题 `h1` 注释）；02 §7.2.5 建议「全书大量长注释时给每章一个子标题」。
- 结论：已一致；与 02 §7.2.5 有冲突待决
- 理由：单 section 单 ol 与 T16 一致。「按章分小标题」会把一个连续编号的 ol 拆成多个，与「一个 ol」冲突。
- 落地：**需决策**，见汇总冲突点 2。

### SE 7.E.9　尾注 id 递增有序
- SE 原规则：注号按顺序递增。
- 我们现状：T16「全书连续（1、2、3……），按注号在正文中首次出现的顺序」；rebuild 的 `number_notes` 实现；SEM-007 检查「序号连续不重复」。
- 结论：已一致
- 理由：做法相同。
- 落地：无。

### SE 7.E.10　尾注是 `<li id="note-n">`，含一个或多个块级元素和一个回链
- SE 原规则：`li` 里可有多个块级元素（段落、引用、诗），最后一个回链。
- 我们现状：T16 示例只有一个 `p`；rebuild `render_endnotes` 把整条注内容并入**一个** `p`（`self.inline(body_src, p, …)`），多段注和含引文/诗的注会被压平。
- 结论：修改后采用
- 理由：注文含多段或引文（学术书常见）时压平会丢结构。
- 落地：rebuild.py：注文若由多个块组成，保持各块（`p`/`blockquote`/`ul`），回链放在最后一个 `p` 末尾（7.E.11）；T16 增加多段注示例。【此项为代码改动，需排期】

### SE 7.E.11　回链：`epub:type="backlink"`，文字 `↩`，指向 noteref；末块是 `p` 时放在其末尾，前面恰好一个空格；末块是诗、引文等时回链单独放一个 `<p>`
- SE 原规则：同左。
- 我们现状：T16 与 rebuild：回链在 `p` 末尾，前一个空格，带 `aria-label="返回正文"`；没有「末块非 p」的情形。02 §8 却写「`backlink`（role 专用）」，暗示 epub:type 没有 `backlink`，与 T16、rebuild 不一致。
- 结论：修改后采用
- 理由：补上「末块为引文/诗/列表/表格时回链独立成 `<p>`」；`aria-label` 是我们多出的无障碍增强，保留。`epub:type="backlink"` 是否在结构语义词表中**【需核对】**：若不在，epubcheck 只会给用法提示，不报错；规范里只需保留 `role="doc-backlink"`。
- 落地：
  1. guide/04 T16 加「末块非 `p`：回链单独 `<p>`」及示例。
  2. guide/02 §8 的 `backlink` 行：核对后统一（保留 `epub:type="backlink" role="doc-backlink"` 两者或只留 role，同时修 T16/rebuild）。
  3. guide/02 §7.1 的尾注示例与 T16 对齐：回链加 `epub:type="backlink"`、`aria-label`，id 用 `note-n`/`noteref-n`。

### SE 7.E.12　尾注末尾的引文出处用 `<cite>` 包住（含破折号），后跟空格再加回链
- SE 原规则：结尾出处包 `<cite>`，破折号含在内。
- 我们现状：T16 无；02 §5.2 把 `cite` 当作书名的可选标记。
- 结论：修改后采用
- 理由：中文注文常以「——《史记·高祖本纪》」或「（引自《……》）」收尾，书名号已标出书名，`cite` 增益有限，而「破折号含在 cite 内」这条在中文里没有对应传统。只在原书已有 `cite`、或注末是明确的「——作者/书名」署名形式时保持/添加；不主动给所有书名号加 `cite`。
- 落地：guide/04 T16 要点一句；优先级低。

### 补充　其他与 T16 的遗漏核对
- 02 §7.1 示例与 T16 不一致：示例的 `li` 带 `epub:type="endnote" role="doc-endnote"`，T16 写「DPUB-ARIA 的 `doc-endnote` 已被弃用，不再写」，且 `li` 只要 `id`。02 的示例与说明应改成 T16 的结构。
- SEM-007 的检测对象是 `aside[@epub:type~='footnote']`，对尾注文件（`li`）覆盖不到；SEM-012 把「注号用 `sup`」当作修复动作，与 T16「不用 `<sup>`」相反。两处需要按 T16 改。
- `li` 上是否加 `epub:type="endnote"`（标准词汇，不弃用）：SE 不加。理由是弹注依据 noteref 的目标，不依赖目标语义；我们保持 T16 现状（不加），但这是**待决**的小点，见汇总冲突点 4。

---

## F. 术语表（Glossaries）

### SE 7.F.1　术语多、而且普通词典查不到时才加术语表
- SE 原规则：词条数量多、领域特殊时才设。
- 我们现状：02 §8 有 `glossary`，无生成规则。
- 结论：修改后采用
- 理由：我们不为别人的书新增术语表（原则 4 的精神，且需要大量内容创作）。只对原书已有的「术语表/名词解释/词汇表/译名对照表/人名对照表」做结构规范化。
- 落地：guide/04 新增模板 T22 术语表，识别信号：标题含上述词，正文是「词条＋全角冒号/破折号/空格＋释义」的成行文本、或两列表格；置信度：标题命中且 ≥5 条为高。无术语表的书不生成。

### SE 7.F.2　按 EPUB Dictionaries and Glossaries 1.0 编写，并需要 `glossary-search-key-map.xml`（包含各词形变体）
- SE 原规则：术语表须有 search key map 文件；只列书中实际出现的变体；单值时用 `<match value>`。
- 我们现状：无。
- 结论：不采用
- 理由：与厂商无关原则冲突 / 中文不适用。EPUB Dictionaries and Glossaries 1.0 是 IDPF 的独立规范，不在 EPUB 3.3 之内，要求 OPF 里额外的 `dc:type`/`rel` 等声明，阅读系统支持有限；search key map 的核心是英文词干变体，对中文分词毫无意义。
- 落地：无。T22 明确「不生成 search key map，不要求 OPF 声明词典」。

### SE 7.F.3　术语表文件 `glossary.xhtml`，`backmatter`，单个 `<section id="glossary" epub:type="glossary">`，其中放 `<dl>`；epub:type 放在 section 而不是 dl
- SE 原规则：同左，并说明 SE 与词典规范建议的位置不同。
- 我们现状：02 §8 表第 12 行：`glossary` / `doc-glossary` 用在 `section`。
- 结论：已一致
- 理由：`glossary` 在 `section` 上，对应 `doc-glossary`，符合结构语义词表与 DPUB-ARIA。文件位置跟随原书（可能在书末，也可能在附录里）。
- 落地：无。T22 里沿用此写法。

### SE 7.F.4　术语表的核心 CSS（dl 外边距、dd 左缩进 40px、`dd + dt` 间隔）
- SE 原规则：`dl{margin:1em 0} dd{margin-left:40px} dd+dt{margin-top:1em}`。
- 我们现状：03 §5 限定 `dd` 要显式 margin，但没有 dl/dt/dd 模板。
- 结论：修改后采用
- 理由：思路采用，单位改 em：`40px` 在不同字号下不稳定。中文术语表的词条通常加粗或用黑体，释义不缩进首行。
- 落地：guide/04 T22 CSS：`dl.glossary{ margin:1em 0 } dl.glossary dt{ font-weight:bold; margin-top:1em; text-indent:0 } dl.glossary dd{ margin:.2em 0 0 2em; text-indent:0 } dl.glossary dd p{ text-indent:0 }`。类名注册表新增 `glossary`。

### SE 7.F.5　词条结构：`<dt epub:type="glossterm"><dfn>词</dfn></dt>`；`<dd epub:type="glossdef">` 含至少一个块级子元素；多个 dt 共用一个 dd
- SE 原规则：同左。
- 我们现状：02 §8 有 `glossterm`/`glossdef` 词条，无模板；02 §5 的 dl 示例没有语义值与 `dfn`。
- 结论：采用
- 理由：全部来自标准词汇（`glossterm`、`glossdef`、`dfn`），可检测可修复。
- 落地：guide/04 T22：`<dt epub:type="glossterm"><dfn>夔</dfn></dt><dd epub:type="glossdef"><p>……</p></dd>`；同一释义对应多个称呼（异名、译名）时多个 `dt` 接一个 `dd`。词条里带外文原名时用 `<dfn>词</dfn>（<span lang="en">Original</span>）`。guide/07：`dt` 必含 `dfn`，`dd` 必含块级子元素，`dt/dd` 不孤立；从两列表格或「词：释」行转换时走 suggest，不静默改。

---

## 汇总

### 条目统计（按本文件内的条目，含两个「补充」小节中的条目计入）
共 60 条：已一致 11、采用 9、修改后采用 26、不采用 14；以下为明细。

**已一致**：7.C.2、7.C.4（规范层）、7.C.8、7.C.11、7.E.1、7.E.3、7.E.4（规范层）、7.E.7、7.E.9、7.F.3；7.E.8 同类（已一致，但有冲突点 2）。

**采用**：7.A.5、7.B.7、7.B.11、7.C.10、7.D.3、7.D.4、7.D.6、7.E.6、7.F.5。

**修改后采用**：7.A.4、7.A.7、7.A.8、7.A.9、7.A.11、7.A.12、7.A.13、7.B.1、7.B.4、7.B.5、7.B.9、7.C.1、7.C.3、7.C.5、7.C.9、「图1—1」补充、7.D.1、7.D.2、7.D.5、7.E.2、7.E.5、7.E.10、7.E.11、7.E.12、7.F.1、7.F.4。

**不采用**：7.A.1、7.A.2、7.A.3、7.A.6、7.A.10、7.B.2、7.B.3、7.B.6、7.B.8、7.B.10、7.B.12、7.C.6、7.C.7、7.F.2。

### 建议采用或修改后采用的重点
1. T11 剧本：加 `z3998:persona` / `z3998:stage-direction` 语义、「人名：台词」连排变体、人物表、整部剧本 `z3998:drama`（需核对幕/场词表）。
2. T8 书信：加 `z3998:letter`、`salutation`、`valediction`、`sender signature`、`recipient`、`postscript`（又及）；`<time datetime>` 仅在年份可确定时加。
3. 插图：figure 补 `id="fig-N"`；`full-page` 类；`max-height:100vh`；alt 清理不可见字符并要求块级插图 alt 以句号结尾；图表编号连接符统计（C 级）。
4. 插图目录：转换原书已有的插图目录页为 `nav epub:type="loi"`，条目链到 figure id；新建仅在用户确认后。
5. T16 注释：补 Ibid./「同上」展开建议；注号放引号外；词语注不移动；多块注文及末块非 `p` 时回链独立成段；修 rebuild 的重复 `noteref` id 与「注文压成一个 `p`」问题。
6. T22 术语表（新增）：`glossterm`/`glossdef`/`dfn`，不要 search key map。

### 与现有规范冲突、需要决策的点
1. **书信容器**：T8 用 `div.letter`，SE 用 `blockquote`。建议：叙事中被引用的信用 `blockquote`，书信集整封信用 `div`/`section`，均带 `z3998:letter`。要不要这样分，请定。
2. **尾注是否按章分小标题**：02 §7.2.5 说大量长注可「给每章一个子标题」；T16 要求一个连续编号的 `ol`。建议：单个 `ol` 不拆，需要分组时用多个 `ol start="N"` 加 `h2` 章名，仍属于同一 `section`；或者干脆删去 02 的这一句。
3. **alt 缺失时是否用图注兜底**：rebuild 现在把图注写进 alt（读屏重复），与 05 §1.5 相悖。建议保留兜底但标「待确认」，并推荐由 LLM 出画面描述草稿；是否接受这种折中，请定。
4. **`li` 是否加 `epub:type="endnote"`**：SE 不加，T16 同；02 §7.1 示例带 `endnote`+`doc-endnote`。建议：不加（含弃用的 `doc-endnote` 肯定不加），改 02 示例。如果用户在目标阅读器上遇到弹注失败，再考虑加 `endnote`。
5. **`epub:type="backlink"` 是否在词表内**：02 §8 称「role 专用」，T16/rebuild 却同时写 epub:type 与 role。需对照词表与 epubcheck 实测后统一。
6. **整部剧本的幕/场词表**：SE 把幕标为 `z3998:scene`，未核对 Z39.98 词表前不要照搬。
7. **插图目录的位置与新建策略**：沿用原书位置（中文书常在前面）而不强搬书末；原书无 LoI 时是否提示新建、阈值取几张（建议 5 张），请定。
