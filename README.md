# epub-typesetter：EPUB 排版优化软件

一个带网页界面的独立软件：输入已有的 EPUB（主要是中文书），借助规则引擎 + 大模型辅助，输出结构规范、排版精良的 EPUB 3。目标是任意符合 EPUB 3 规范的阅读系统，不绑定具体阅读器，不做格式转换。

当前阶段：**M0 内核可用**：读写 EPUB、规则引擎、EPUB 2→3 升级与第一批自动修复规则；22 本样本 epubcheck 错误 1117 → 9（剩余均为厂商私有属性，按策略需用户确认清除），全部幂等、可见文字不变。

## 目录

| 路径 | 内容 |
|---|---|
| `guide/` | **《EPUB 制作规范》**：按主题整理的 EPUB 3 知识，从 `00_总纲.md` 读起 |
| `src/`、`tests/` | 代码与测试 |
| `scripts/` | 辅助脚本（测试数据准备等） |
| `docker/`、`compose.dev.yml` | 开发环境（Python + epubcheck） |
| `软件设计建议.md` | 软件定位、处理管线、大模型辅助设计、网页界面、技术选型、开发路线 |
| `_book_src/` | （仅本地，不进仓库）学习素材：《EPub指南——从入门到放弃》副本，版权属原作者 |
| `_archive/` | （仅本地，不进仓库）初版读书笔记等过程材料 |
| `testdata/` | （仅本地，不进仓库）测试用 EPUB |

## 开发环境

所有命令都在 Docker 开发容器里跑（含 Python 3.13、Java、EPUBCheck 5.4.0），宿主机无需安装任何依赖：

```sh
docker compose -f compose.dev.yml build            # 首次构建
docker compose -f compose.dev.yml run --rm dev pytest
docker compose -f compose.dev.yml run --rm dev epubcheck book.epub
```

命令行（M0，供测试与批量验收；正式界面是网页）：

```sh
docker compose -f compose.dev.yml run --rm dev python -m epub_typesetter audit book.epub
docker compose -f compose.dev.yml run --rm dev python -m epub_typesetter fix book.epub -o out.epub --epubcheck
```

`fix` 只应用确定性的 `auto` 级修复，输出修改记录、修复前后问题数、可见文字是否一致，以及（加 `--epubcheck` 时）epubcheck 错误数对比。

## 已确定的方向（2026-10-22）

1. 目标阅读器：任意支持 EPUB 3 的阅读系统，不做厂商私有适配。
2. 要网页界面。
3. 独立软件，不和本地书库耦合。
4. 引入大模型辅助（只做判断，不改写正文）。
5. 只做 EPUB → 更好的 EPUB，不做格式转换。

## 致谢与许可

- `guide/` 的知识来源之一是赤霓《EPub指南——从入门到放弃》（第2版），已按 EPUB 3.3 重新整理、更新和更正；原书版权归原作者，本仓库不包含原书内容副本。
- 本项目以 [MIT 许可证](LICENSE) 发布。
