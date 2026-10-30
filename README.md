# epub-typesetter：EPUB 排版优化软件

一个带网页界面的独立软件：输入已有的 EPUB（主要是中文书），借助规则引擎 + 大模型辅助，输出结构规范、排版精良的 EPUB 3。目标是任意符合 EPUB 3 规范的阅读系统，不绑定具体阅读器，不做格式转换。

当前阶段：**M2 排版重建可用**（命令行与网页）：语义分析（标题层级、插图/图注/出处、注释、列表、目录页、广告）→ 按章拆分、EPUB 3 弹注、统一主题样式、重建导航；23 本样本 epubcheck 错误 1308 → 4（剩余为厂商私有属性），内容块全部保留、全部幂等。网页上的「分组确认」尚未做。

## 目录

| 路径 | 内容 |
|---|---|
| `guide/` | **《EPUB 制作规范》**：按主题整理的 EPUB 3 知识，从 `00_总纲.md` 读起 |
| `src/`、`tests/` | 后端代码（内核 + `web/` 网页后端）与测试 |
| `frontend/` | 网页前端（Vue 3 + Vite） |
| `Dockerfile`、`compose.yml` | 交付镜像与运行配置 |
| `scripts/` | 辅助脚本（测试数据准备等） |
| `docker/`、`compose.dev.yml` | 开发环境（Python + epubcheck） |
| `软件设计建议.md` | 软件定位、处理管线、大模型辅助设计、网页界面、技术选型、开发路线 |
| `_book_src/` | （仅本地，不进仓库）学习素材：《EPub指南——从入门到放弃》副本，版权属原作者 |
| `_archive/` | （仅本地，不进仓库）初版读书笔记等过程材料 |
| `testdata/` | （仅本地，不进仓库）测试用 EPUB |

## 运行

```sh
docker compose up -d --build      # 然后打开 http://127.0.0.1:8780
```

上传的书和处理结果保存在 `./data/`（每本书一个目录，原件不会被修改）。

## 开发环境

所有命令都在 Docker 开发容器里跑（含 Python 3.13、Java、EPUBCheck 5.4.0），宿主机无需安装任何依赖：

```sh
docker compose -f compose.dev.yml build            # 首次构建
docker compose -f compose.dev.yml run --rm dev pytest
docker compose -f compose.dev.yml run --rm dev epubcheck book.epub
```

命令行（供测试与批量验收；正式界面是网页）：

```sh
docker compose -f compose.dev.yml run --rm dev python -m epub_typesetter check book.epub [--format json] [--hits all]
docker compose -f compose.dev.yml run --rm dev python -m epub_typesetter fix book.epub -o out.epub --epubcheck
```

`check` 的报告格式见 `guide/07` §6：每条问题 = 规则编号 + 问题 + 修改提示 + 规范条目 + 命中位置；退出码 0 = 无未豁免的 error，1 = 有，2 = 用法或豁免文件错误。`fix` 只应用确定性的 `auto` 级修复。

**按书豁免**（`guide/07` §7）：在书旁放 `<书名>.epub.typeset-ignore.json`，按「规则 × 文件（可通配）× 选择器/文字锚点 × 必填理由」声明有意的例外；被豁免的问题显示为「已豁免」，修复时跳过。网页上点「忽略此问题…」即可生成。

规则的说明、修改提示、规范条目只写在 `guide/07`，改完运行 `python3 scripts/build_rules_meta.py` 重新生成 `src/epub_typesetter/rules_meta.json`。

## 大模型辅助（M3，可选）

用 Claude 原生接口（Anthropic 官方 Python SDK）。大模型只看书的片段、只给判断，结果显示在确认板上，由你点「采纳」后才生效；不配置也能用，只是没有这些建议。

地址和令牌不写进代码，按优先级从三处读：

1. 网页右上角「大模型设置」（保存在 `data/settings.json`，不进仓库）；
2. 环境变量 `EPUBTS_LLM_*`：复制 `.env.example` 为 `.env` 填写，`docker compose up -d` 会读取（`.env` 不进仓库）；
3. Anthropic SDK 的标准环境变量 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`。

官方接口填 API key；兼容 Claude 原生协议的中转填中转地址和 Bearer 令牌。分两档模型：轻量（默认 `claude-haiku-5-5`）做大批量判断，重型（默认 `claude-opus-5-5`）做标题层级、注释配对。SDK 暂时固定在 1.x：2.x 默认发送的 API 版本 2026-10-21 有些中转还不接受。

## 已确定的方向（2026-10-22）

1. 目标阅读器：任意支持 EPUB 3 的阅读系统，不做厂商私有适配。
2. 要网页界面。
3. 独立软件，不和本地书库耦合。
4. 引入大模型辅助（只做判断，不改写正文）。
5. 只做 EPUB → 更好的 EPUB，不做格式转换。

## 致谢与许可

- `guide/` 的知识来源之一是赤霓《EPub指南——从入门到放弃》（第2版），已按 EPUB 3.3 重新整理、更新和更正；原书版权归原作者，本仓库不包含原书内容副本。
- 本项目以 [MIT 许可证](LICENSE) 发布。
