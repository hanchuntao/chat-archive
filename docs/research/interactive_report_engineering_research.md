# chat-archive 调研报告：可交互升级模式库 + 工程最佳实践

> 调研日期：2026-10-04
> 调研范围：交互式数据报告/分析工具、聊天查看器交互模式、工程最佳实践
> 项目约束回顾：纯 Python 标准库优先（新增依赖必须说明理由）、Windows+macOS 双平台、稳定第一、CLI+Skill 形态、**明确不做常驻 Web 服务**（架构文档 §1）
> 已吸收能力（本报告不重复）：SQLite+FTS5、跨次运行记忆层、昵称消歧、四分类摘要、证据化考核、群活跃度、丢单/商机信号、按时段压缩、需求洞察、日报、质检信号分类、知识库自动归档、增量处理、@提及统计、扁平导出、年度分析、消息洞察、关键词趋势、语音转写占位、媒体归档、convert_wx 桥接、快照 manifest、db 迁移、report.html 长图截图（playwright 默认关）

---

## 一、现状诊断（写在前面）

通过阅读 `.claude/skills/chat-archive/scripts/render_html.py`（1062 行）确认：
- **当前 report.html 是纯静态 HTML+CSS，全文仅 1 处 `<style>`，0 处 `<script>`**——没有任何 JS 交互。
- 数据来自快照目录下已生成的 CSV/MD 文件（`effective_stats.csv`、`daily_reports/`、`followups.csv`、`knowledge/`、`assessment.csv`），在 Python 端一次性读入并渲染为表格/列表。
- 已有能力：`chat-archive search`（FTS5 CLI）、`chat-archive stats --group sender/day/type/category`、`--json` 输出、可选 Chroma 向量、LLM 降级规则版。
- **架构红线**：§1 明确"不做常驻服务/Web 平台"；§6 决策记录"交付形态 = CLI + Skill，用户反复验证 Web 部署失败；Skill 零部署、更新=替换 1 文件"。

**这意味着所有"起 Python Web 服务"的模式（Streamlit/Dash/Metabase/Superset/Datasette 服务端模式）都与产品形态有张力；真正的升级方向是"构建时数据物化 + 浏览器端 vanilla JS 交互"，即 Observable Framework / Evidence 的静态编译范式。**

---

## 二、可交互升级模式清单（重点交付 1）

| 交互模式 | 代表项目/工具 | 交互形态 | 实现方式 | 纯标准库可否实现 | 若需依赖，推荐什么+理由 | 建议优先级 |
|---|---|---|---|---|---|---|
| **静态数据物化 + 浏览器端 vanilla JS 筛选/下钻**（Observable Framework 范式） | Observable Framework（`observablehq.com/framework/getting-started`）、Evidence（`evidence.dev`） | 构建时把 SQL/Python 聚合结果导出为 JSON/Parquet，浏览器端 reactive inputs（slider/checkbox/搜索框）联动图表 | render_html.py 在生成 HTML 时把所有聚合结果序列化为 `<script type="application/json" id="data">...</script>` 内嵌；前端 ~200 行 vanilla JS 做过滤、排序、Tab 切换、图表联动 | **完全可以**——stdlib `json.dumps` + 手写 JS 模板字符串；零运行时依赖 | 无需依赖。ECharts 可选内联（见下一行） | **P0（最优先）** |
| **ECharts 内嵌图表（日历热图/桑基/网络图/时间轴）** | Apache ECharts（`echarts.apache.org`）；AntV G6（关系图） | 日历热图看每日消息密度、桑基图看"发送者→分类→响应"流向、力导向图看 @提及关系、时间轴看小时活跃度 | 构建时下载 `echarts.min.js`（~1MB，Apache-2.0）内嵌进 HTML（`<script>...</script>`），数据通过内嵌 JSON 喂给 `echarts.init()` | **HTML 本身可纯标准库生成**，但 echarts.min.js 是第三方 JS 文件，需要在 build 时下载一次并内嵌（或随包发布到 `chat_archive/assets/`） | 推荐 ECharts 单文件内嵌。理由：Apache-2.0 商用友好、中文文档全、calendar/sankey/graph 原生支持，无 npm 依赖 | **P0** |
| **Datasette Lite（WASM 浏览器内跑 SQLite）** | Datasette Lite（`docs.datasette.io/en/0.62/getting_started.html`） | 把 .db 文件 + Python WASM 打包进浏览器，用户双击 HTML 即可在浏览器里跑任意 SQL、排序、过滤、FTS 搜索、facet | `chat-archive serve-static` 子命令：复制 `chat_archive.db` 到快照目录，生成一个 index.html 通过 CDN 加载 datasette-lite.wasm，传入本地 .db 路径；用户双击后所有查询在浏览器内完成，**无需 Python 服务端** | 生成 HTML 可纯标准库；但运行时依赖 ~10MB 的 WASM 包（首次加载需 CDN，离线需内联） | **可选 P1**。理由：这是最接近"Datasette 升级路径"但又不违反"不起常驻服务"红线的形态。代价：WASM 包大（~10MB）、离线分发需内联、首次加载慢。适合"高级探索"场景，不适合默认 report.html | P1（高级模式） |
| **Datasette 服务端模式（`datasette db.db`）** | Datasette（`docs.datasette.io/en/latest/changelog.html`） | 起一个本地 Web 服务，自动生成表页/SQL 编辑器/FTS/facet/JSON API，插件生态（datasette-vega、datasette-cluster-map） | `chat-archive serve` 子命令调用 `datasette chat_archive.db --read-only` | 否（datasette 是重依赖，含 Starlette/uvicorn/click 等） | **不推荐默认引入**。理由：违反"不做常驻服务"红线；依赖树 ~50MB；用户要 `pip install datasette`。但可作为"可选 extras"：`pip install chat-archive[serve]`，高级用户主动启用 | P2（可选 extras） |
| **聊天记录时间线浏览（MemoTrace/WeChatMsg 范式）** | WeChatMsg/MemoTrace（`memotrace.lc044.love`；`davidblackcn.cc` 博客评测）；WeChat PC 端搜索交互（`cs.help.wechat.com`） | 按日分组的吸顶时间线、关键词搜索高亮+上下跳转、左侧成员列表点击过滤、媒体/链接/文件 Tab 分类、词云年报 | 把消息表（脱敏后）导出为 JSON 数组内嵌；vanilla JS 渲染虚拟滚动列表（10 万条以内可全量渲染，超过则分页）；搜索用前端 `String.includes` 或预构建的倒排索引 | **完全可以**——消息数据本来就在 SQLite，导出为 JSON 即可 | 无需依赖。虚拟滚动可手写 ~100 行；如消息量 >10 万条再考虑引入 | **P0** |
| **前端即时搜索（FTS5 子集 + 客户端高亮）** | Datasette table page（`docs.datasette.io/_/downloads/en/0.47.2/pdf/`）；Slack 双层搜索范式（`jsguide.dev`） | 报告页顶部搜索框，输入即过滤（client-side 即时），无服务端往返 | 构建时把 messages 表的 `content + sender + time` 导出为 JSON；前端 JS 做 `includes` 过滤 + 关键词 `<mark>` 高亮；支持"按发送者/按日期"二级过滤 | **完全可以** | 无需依赖。10 万条以内 `includes` 性能足够；超过则构建时预生成倒排索引（token→message_ids 的 JSON map） | **P0** |
| **静态 HTML 内"问答框"（假聊天真搜索）** | FastGPT/Dify 的聊天 UI 模式（`doc.fastgpt.cn`；`github.com/langgenius/dify`）借鉴 UI，不引入后端 | 页面右下角悬浮输入框，输入问题→展示候选证据片段（来自 FTS 搜索结果）→可选调用用户配置的 OpenAI 兼容 API 生成答案 | 两阶段：(1) **默认模式（零配置）**：前端 JS 把问题切词 → 对内嵌消息 JSON 做 FTS-like 匹配 → 展示 top-K 证据卡片（不调 LLM，纯检索）；(2) **可选模式**：用户在设置里填自己的 OpenAI 兼容 endpoint+key，前端 `fetch` 流式调 API（需用户接受 CORS 风险，或通过 `chat-archive ask --serve-proxy` 起一个 stdlib http.server 转发） | 阶段 1 完全可以；阶段 2 前端直调有 CORS 问题 | 阶段 1 零依赖。阶段 2 如需 proxy，用 stdlib `http.server` 写一个 ~100 行转发器（可选 extras） | **P1** |
| **Streamlit / Dash / Gradio 交互应用** | Streamlit、Plotly Dash、Gradio（`modern-datatools.com/compare/streamlit-vs-gradio-vs-dash`） | Python 脚本即 Web 应用，widget 自动联动，回调驱动 | `streamlit run app.py` 起本地服务 | 否（Streamlit 依赖树 ~300MB，含 Tornado/pyarrow） | **不推荐**。理由：违反"不做常驻服务"红线；依赖过重；与 CLI+Skill 形态冲突。仅可作为内部探索工具参考 | **排除** |
| **Metabase / Superset BI 嵌入** | Metabase、Apache Superset（`meetrix.io/blogs/metabase-vs-redash-vs-superset/`） | 企业级 BI：问题→图表→仪表板→下钻→行级权限→SAML SSO | Docker/JVM 部署，连接 SQLite 作为外部数据源 | 否（Superset 需要 Python 服务 + 元数据库；Metabase 需要 JAR/JVM） | **排除**。理由：10 人小团队零部署定位下，JVM/Docker 运维成本过高；与"Skill 替换 1 文件"形态完全不符。但其"问题→图表→下钻"交互模式可借鉴到 P0 静态看板 | **排除** |
| **sqlite-vec 本地向量检索（替代 Chroma）** | sqlite-vec（`alexgarcia.xyz/sqlite-vec`；`dreaming.press/posts/sqlite-vec-vs-lancedb-vs-chroma`） | 在同一个 .db 文件里存向量表，SQL `SELECT ... ORDER BY vec_distance_cosine(embedding, ?) LIMIT 10` | 把 chromadb 的独立 persist_dir 替换为 SQLite 扩展，向量与 messages 同库事务一致 | 部分（sqlite-vec 是 C 扩展，需 pip install；但比 Chroma 轻一个数量级，无 Rust/Java 依赖） | **推荐作为 Chroma 的轻量替代 P1**。理由：Chroma 依赖树重（含 onnxruntime/hnswlib）；sqlite-vec 是 SQLite 作者 Mattn 维护的扩展，与现有 FTS5 同库、可联合 SQL 过滤、零新存储引擎。10 万级向量够用（性能天花板 ~几十万） | P1 |

---

## 三、工程最佳实践清单（重点交付 2）

| 实践 | 代表项目/来源 | chat-archive 现状差距 | 实施成本 | 收益 |
|---|---|---|---|---|
| **SQLite PRAGMA 黄金组合：WAL + synchronous=NORMAL + busy_timeout=5000 + cache_size=-64000 + wal_autocheckpoint 调优** | devshelfhub SQLite cheatsheet（`devshelfhub.com/cheatsheets/sqlite/`）；DB Pro（`dbpro.app/blog/how-to-fix-slow-sqlite-queries`） | 架构文档 §4 已记 WAL + synchronous=NORMAL；**缺 busy_timeout（多进程并发时可能 database is locked）和 cache_size/wal_autocheckpoint 调优** | 低（db.py 加 3 行 PRAGMA） | 高：避免 Windows 下 playwright 截图进程与入库进程争锁失败 |
| **FTS5 查询优化：`ORDER BY rank`（BM25）+ ANALYZE 后再测查询计划** | elsolitario.org SQLite 生产实践（`elsolitario.org/2026/07/18/sqlite-en-produccion-analyze-wal-backups/`）；Coddy.Tech FTS5 指南（`coddy.tech/docs/es/sqlite/full-text-search`） | search.py 当前是 FTS5 命中后"0 命中降级 LIKE"，**未用 BM25 rank 排序，结果相关性靠 SQLite 默认** | 低（search.py 加 `ORDER BY rank LIMIT ?`） | 中：搜索结果质量提升，对"找客户投诉/找商机"场景直接体感 |
| **FTS5 维护：`optimize` 命令 + `fts5_automerge` 调优 + 删除触发器同步** | c13n.club FTS5 性能笔记（`c13n.club/blog/2026-04-30/index.pdf`）；nostrify.dev SQLite（`nostrify.dev/store/sqlite`） | db.py 有 FTS rebuild，但**无定期 optimize、无 automerge 调优**；长期增量运行后 FTS 段会膨胀 | 低（加 `chat-archive fts-optimize` 子命令 + 入库后调用） | 中：长期库搜索性能稳定 |
| **CLI 分层：命令组（init/import/search/stats/report/weekly/vectorize/info/backup/serve/ask）按域分组** | Python Brasil CLI 2026（`python.dev.br/blog/criando-cli-com-python/`）；Click/Typer 对比（`inventivehq.com/blog/how-to-create-cli-utilities-with-python`） | cli.py 已用 argparse 平铺 9 个子命令；**子命令语义重叠（report vs weekly）、缺分组、缺 --help 命令树** | 低（重构 argparse subparser 加 `--group` 或 `category` 元数据，--help 时按组打印） | 中：用户发现性提升；纯标准库可做 |
| **CLI 参数校验：type hints + 自动类型转换** | Typer（`typer.tiangolo.com`）；Dokodu.it 对比表（`dokodu.it/blog/python/praktyka/tworzenie-cli-w-pythonie`） | argparse 需手动 `int()` 转换；`--limit` 已有 type=int，但 `--start/--end` 日期格式未校验 | 低（写一个 `_valid_date` 类型函数） | 低：提前报错而非 SQL 错误 |
| **保持 argparse 不迁 Typer/Click 的决策** | 多源一致结论：argparse 零依赖、stdlib、适合脚本；Click/Typer 适合复杂交互式 CLI（`pythonhowtoprogram.com/how-to-build-cli-apps-with-python-click`） | 现状已正确。**需要在 ADR 里写明"为何不迁"**，防止未来被"现代化"呼声带偏 | 低（在 specs/architecture.md §6 加一行 ADR） | 中：守住"纯标准库"红线 |
| **PyInstaller 双平台打包（GitHub Actions matrix）** | PyInstaller 官方（`pyinstaller.org`）；pydevtools handbook（`pydevtools.com/handbook/reference/pyinstaller/`）；uv+PyInstaller 跨平台限制（`pyobfuscate.com/blog/build-python-exe-with-uv-pyinstaller`） | **现状：无打包发布流程**。用户需 `git clone + pip install .`，对非技术用户（电商运营/主管）门槛高 | 中（加 `.github/workflows/release.yml`，windows-latest + macos-latest 双 runner，产物附到 GitHub Release；约 200 行 YAML） | **高**：直接面向最终用户分发，商业化关键 |
| **PyInstaller onedir 模式而非 onefile** | cjgdev 分发调研（`cjgdev.github.io/midi-markdown/developer-guide/distribution-research/`） | 无（未打包） | 低（在 spec 里选 onedir） | 中：启动快 3x，杀软误报率低 |
| **Nuitka 作为杀软误报缓解路径（备选）** | DEV Community PyInstaller→Nuitka（`dev.to/weisshufer/from-pyinstaller-to-nuitka-convert-python-to-exe-without-false-positives-19jf`）；yuksblog 对比（`yuksblog.github.io/nuiitivet/latest/guide/packaging/`） | 无 | 高（Nuitka 需 C 编译器，构建慢 10-30 分钟） | 中：仅当 Windows Defender 大量误报时启用 |
| **pipx / uv 作为开发者安装路径** | pydevtools handbook（`pydevtools.com/handbook/explanation/how-do-i-ship-a-python-application-to-end-users/`） | 现有 `pip install .` 可用，但**未在 README 推荐 `uv tool install chat-archive`** | 低（README 加一行） | 低：开发者体验 |
| **测试覆盖率门禁 + ruff + mypy 静态检查** | 通用 CI 最佳实践（无单一来源） | **现状：301 测试通过，但无覆盖率统计、无 lint、无类型检查门禁** | 中（加 `pytest --cov=chat_archive --cov-fail-under=80` + `ruff check` + `mypy --strict`，CI 跑） | **高**：稳定第一的项目必须有门禁，防止后续重构回归 |
| **Smoke test：打包后跑 `chat-archive info` 验证产物可执行** | DEV Community Streamlit CI（`dev.to/jhonyvargas/...`） | 无 | 低（CI 里 PyInstaller 后加一行 `./dist/chat-archive info`） | 高：防止"打包成功但运行即崩" |
| **结构化日志（logging 模块 + 运行日志落盘到快照目录）** | 通用最佳实践 | 现状：`print()` 到 stdout，错误靠 try/except 收进 errors 列表；**无时间戳、无日志级别、无持久化** | 中（接入 stdlib `logging`，写入 `out/<snapshot>/run.log`） | 中：用户反馈问题时可定位 |
| **错误分类与退出码约定** | 通用 CLI 设计 | 现状：`ValueError/RuntimeError → exit 1`，但**错误码未细分**（配置错误/输入错误/DB 错误/LLM 错误应不同） | 低（定义 `ExitCode` 枚举） | 低：脚本化调用方可用 |
| **分析模块注册表（importers/pipeline 模式扩展）** | Datasette 插件系统（`docs.datasette.io/en/latest/internals.html#datasette-add-background-task`）；Dargslan Click 插件架构（`dargslanpublishing.com/python-cli-tools-building-your-own-command-line-apps/`） | 现状：pipeline/ 分层已好；业务层 27 项产物在 `chat_archive.py`（2747 行）里硬编码顺序 | 高（把每个分析步骤注册为函数，CLI 可选跑子集） | 中：为未来插件化铺路，但当前优先级不高 |
| **快照 manifest 完整性校验已有（保持）** | 架构文档 §5 已记 manifest.json SHA256 + verify 子命令 | **已达标，无需改动** | — | — |
| **DB 迁移版本化已有（保持）** | 架构文档 §4 已记 PRAGMA user_version + MIGRATIONS | **已达标** | — | — |

---

## 四、可吸收能力建议（本组）

| 能力 | 来源 | chat-archive 现状缺口 | 实施成本 | 商业化价值 | 交互增益 | 是否需新依赖 |
|---|---|---|---|---|---|---|
| **report.html 内嵌 JSON + vanilla JS 筛选/Tab/搜索高亮** | Observable Framework、Evidence 静态编译范式 | render_html.py 0 行 JS，19 个模块全是静态表格，用户无法在浏览器里"按人筛/按日期筛/关键词搜" | 中（重写 render_html.py 输出层，~500 行新增） | 高：从"PDF 静态报表"升级为"可交付的交互看板"，是电商主管最直观的付费点 | **极高** | 否（纯 stdlib + 内嵌 JS） |
| **ECharts 日历热图（每日消息密度）** | ECharts calendar heatmap（`vpascode.com` ECharts playbook；阿里云 DataV 文档 `help.aliyun.com`） | 现有"每日消息量"是表格，无日历视图；主管一眼看不出"哪天爆量/哪天无人值守" | 低（构建时内嵌 echarts.min.js，写 ~50 行 option） | 高 | 高 | 否（echarts.min.js 随包分发到 `chat_archive/assets/`，Apache-2.0） |
| **ECharts 桑基图（消息流：发送者→分类→响应类型）** | SankeyMaster 指南（`sankeymaster.com`）；systergon 588 charts 对比（`systergon.com/blog/figma-charts-choosing-the-right-chart-library`） | 现有分类统计是孤立柱状图，看不出"谁在什么场景下产生了多少可交付信号" | 低 | 中 | 高 | 否（同上） |
| **ECharts 力导向图（@提及关系网）** | AntV G6 / ECharts graph series | 已有 @提及统计，但是 CSV 表格，看不出"谁跟谁高频联动" | 低 | 中 | 高 | 否 |
| **报告页顶部即时搜索框（client-side 过滤 + 高亮）** | Datasette table page（`docs.datasette.io/_/downloads/en/0.47.2/pdf/`）；WeChat PC 搜索交互（`cs.help.wechat.com`） | 现有 CLI `search` 要开终端；HTML 报告里不能搜 | 低（~150 行 JS） | 高：主管拿到 HTML 就能"搜'退款'" | 极高 | 否 |
| **消息时间线浏览（按日分组、吸顶日期、按人过滤侧栏）** | MemoTrace/WeChatMsg 导出 HTML（`blog.csdn.net/weixin_46686976/article/details/136123125`）；Cloudscape timeline 模式（`cloudscape.design/gen-ai/patterns/timeline-overview/`） | 现有"消息样本"只在周报里给最后 20 条，**不能在浏览器里翻完整消息流** | 中（导出脱敏消息 JSON + 虚拟滚动 ~300 行） | 高：审计/质检场景刚需 | 极高 | 否 |
| **"假聊天真搜索"问答框（默认零配置，证据卡片）** | FastGPT/Dify UI（`doc.fastgpt.cn`；`git-hub.com/labring/FastGPT`）；RAGFlow 引用卡片模式 | 现有 `chat-archive report --llm` 是离线一次性调用；HTML 里不能提问 | 中（前端输入框 + 切词 + 对内嵌 JSON 做 BM25-ish 排序 + 渲染 top-K 证据卡片） | 高：对标企业微信智能问答，但完全本地 | 高 | 否（默认模式）；可选 stdlib http.server 做 LLM 转发 proxy（P2） |
| **sqlite-vec 替代 Chroma 作为向量后端** | sqlite-vec vs LanceDB vs Chroma（`dreaming.press/posts/sqlite-vec-vs-lancedb-vs-chroma-embedded-vector-store-solo-builder.html`；`menuagentic.com/blogs/lancedb-vs-chroma-vs-sqlite-vec-vs-faiss`） | vector.py 当前依赖 chromadb（重依赖，未装时友好报错）；电商群消息量级（<100 万条）远不需要 Chroma | 中（vector.py 重写为 sqlite-vec 后端，~100 行） | 中：降低安装门槛是商业化关键 | 中（问答框的语义检索底座） | 是：`sqlite-vec`（~5MB，比 Chroma 轻 10 倍，同库事务） |
| **Datasette Lite 高级探索模式（可选）** | Datasette Lite（`docs.datasette.io/en/0.62/getting_started.html`） | 无"高级用户自由 SQL 探索"入口 | 高（需引入 wasm 加载流程，离线分发需内联 ~10MB） | 低（面向极客用户） | 中 | 是：datasette-lite（CDN 或内嵌 wasm） |
| **SQLite PRAGMA 加固（busy_timeout/cache_size/wal_autocheckpoint）** | devshelfhub cheatsheet（`devshelfhub.com/cheatsheets/sqlite/`） | db.py 缺 3 个 PRAGMA | 低 | 中（稳定性） | 无（后台） | 否 |
| **FTS5 BM25 排序 + 定期 optimize 子命令** | Coddy.Tech FTS5（`coddy.tech/docs/es/sqlite/full-text-search`）；c13n.club（`c13n.club/blog/2026-04-30/index.pdf`） | search.py 未按 rank 排序；无 optimize | 低 | 中 | 中（搜索结果相关性） | 否 |
| **PyInstaller 双平台 Release 打包** | PyInstaller（`pyinstaller.org`）；pyobfuscate uv 跨平台限制（`pyobfuscate.com/blog/build-python-exe-with-uv-pyinstaller`） | 无 .exe/.app 分发，用户需懂 Python | 中（GitHub Actions matrix） | **极高**：电商主管/运营不会 `pip install` | 无（分发层） | 是：PyInstaller（dev 依赖，不进 runtime） |
| **CI：pytest-cov 80% 门禁 + ruff + smoke test** | 通用 CI 最佳实践 | 301 测试无门禁；无 lint | 中 | 高（稳定第一） | 无 | 是：pytest-cov/ruff/mypy（dev 依赖） |
| **stdlib logging 落盘到快照 run.log** | 通用 | print 无时间戳无落盘 | 低 | 中（排障） | 无 | 否 |

---

## 五、排除项（本组）

| 项目/模式 | 排除原因 |
|---|---|
| **Streamlit / Plotly Dash / Gradio 作为 report.html 升级路径** | 违反架构文档 §1"不做常驻 Web 服务"红线；依赖树重（Streamlit ~300MB）；与 CLI+Skill"替换 1 文件更新"形态冲突。仅可作为内部探索工具参考，不进入交付物 |
| **Metabase / Apache Superset 嵌入** | 需要 JVM/Docker + 元数据库，运维成本对 10 人小团队不可接受；与"零部署、单机可跑"定位完全不符。但其"问题→图表→下钻→行级权限"交互模式可借鉴 |
| **FastGPT / Dify / RAGFlow 全栈私有化部署** | 技术栈 Next.js+Mongo+PG Vector+Redis，运维过重；chat-archive 的 RAG 需求（几万~几十万条群消息）远不需要完整 RAG 平台。仅借鉴其 UI 模式（聊天框+引用卡片+流式） |
| **LanceDB 替代 SQLite 作为主存储** | LanceDB 列式存储+版本化确实先进，但需引入 Rust 扩展，打包到 Windows .exe 复杂；chat-archive 的事务一致性需求（脱敏→入库→FTS）在 SQLite 内已闭环。向量场景下 sqlite-vec 已够用 |
| **Milvus / Qdrant / pgvector 向量服务** | 单机、零部署、10 人小团队场景下，独立向量服务是过度工程 |
| **Nuitka 默认打包路径** | 构建慢（10-30 分钟）、需 C 编译器；PyInstaller onedir 已够。仅在 Windows Defender 大量误报时作为备选 |
| **迁 CLI 到 Typer/Click** | argparse 纯标准库、当前 9 个子命令未到"必须迁"的复杂度；引入依赖违背"纯标准库优先"。在 ADR 里固化此决策即可 |
| **Observable Framework / Evidence / Quarto 作为构建工具** | 它们是 Node.js 生态（npm run build），会把项目拖入"Python 管道 + Node 构建"双工具链。**只借鉴其"构建时物化数据 + 浏览器端 reactive"范式，不引入工具本身**——render_html.py 自己就是这个编译器 |
| **服务端 LLM proxy（默认开启）** | 与"不做常驻服务"红线冲突；改为"可选 extras + 用户主动 `chat-archive ask --serve-proxy`"模式 |
| **MemoTrace/WeChatMsg 的微信数据解密功能** | 架构文档 §1 明确不做微信解密（灰色地带）；chat-archive 只做"已导出明文"的归档分析。借鉴其 HTML 查看器交互即可 |

---

## 六、关键事实来源 URL 汇总

- Datasette 官方文档：https://docs.datasette.io/en/0.62/getting_started.html （Datasette Lite / WASM 浏览器内运行）
- Datasette changelog：https://docs.datasette.io/en/latest/changelog.html
- Datasette table page 交互：https://docs.datasette.io/_/downloads/en/0.47.2/pdf/
- Streamlit vs Gradio vs Dash：https://www.modern-datatools.com/compare/streamlit-vs-gradio-vs-dash
- Observable Framework 静态编译：https://observablehq.com/framework/getting-started ；https://observablehq.com/framework/project-structure ；https://www.minot.bio/
- Evidence 静态站点：https://docs.evidence.dev/changelog ；https://www.mintlify.com/evidence-dev/evidence/quickstart
- Metabase vs Superset：https://meetrix.io/blogs/metabase-vs-redash-vs-superset/ ；https://preset.io/blog/open-source-embedded-analytics-platforms/
- ECharts 日历热图：https://www.vpascode.com/docs/vpascode-docs/echarts-playbook/calendar-chart-time-series-heatmaps-and-daily-activity-tracking-guide/ ；https://help.aliyun.com/en/datav/datav-6-0/user-guide/the-echarts-calendar-heatmap
- 桑基图最佳实践：https://sankeymaster.com/unleashing-the-power-of-sankey-charts-a-visual-guide-to-enhancing-data-storytelling/
- FastGPT：https://doc.fastgpt.cn/zh-CN/guide/getting-started ；https://git-hub.com/labring/FastGPT
- Dify：https://git-hub.com/langgenius/dify
- WeChatMsg/MemoTrace：https://blog.csdn.net/weixin_46686976/article/details/136123125 ；https://www.davidblackcn.cc/blog/ji-wen/yi-xie-wei-xin-liao-tian-ji-lu-bei-fen-fen-xi-gong-ju/
- 微信 PC 端搜索交互：https://cs.help.wechat.com/hc/zh-cn/articles/11917907846799
- SQLite WAL/FTS5 最佳实践：https://www.devshelfhub.com/cheatsheets/sqlite/ ；https://elsolitario.org/2026/07/18/sqlite-en-produccion-analyze-wal-backups/ ；https://www.dbpro.app/blog/how-to-fix-slow-sqlite-queries ；https://coddy.tech/docs/es/sqlite/full-text-search
- CLI 框架对比：https://python.dev.br/blog/criando-cli-com-python/ ；https://inventivehq.com/blog/how-to-create-cli-utilities-with-python ；https://dokodu.it/blog/python/praktyka/tworzenie-cli-w-pythonie
- PyInstaller 打包：https://www.pyinstaller.org/en/v6.8.0/operating-mode.html ；https://pydevtools.com/handbook/reference/pyinstaller/ ；https://pyobfuscate.com/blog/build-python-exe-with-uv-pyinstaller ；https://cjgdev.github.io/midi-markdown/developer-guide/distribution-research/
- Nuitka 替代：https://dev.to/weisshufer/from-pyinstaller-to-nuitka-convert-python-to-exe-without-false-positives-19jf
- sqlite-vec vs LanceDB vs Chroma：https://dreaming.press/posts/sqlite-vec-vs-lancedb-vs-chroma-embedded-vector-store-solo-builder.html ；https://menuagentic.com/blogs/lancedb-vs-chroma-vs-sqlite-vec-vs-faiss
- 聊天时间线 UX：https://cloudscape.design/gen-ai/patterns/timeline-overview/ ；https://www.dgp.toronto.edu/papers/dfono_CSCW2006.pdf ；https://www.jsguide.dev/question/design-realtime-chat-application-slack-messenger

---

## 七、一句话行动建议（按优先级）

1. **P0-1**：重写 `render_html.py` 输出层，把 19 个模块的数据全部内嵌为 JSON，加 ~200 行 vanilla JS 做 Tab/筛选/搜索高亮——这是性价比最高的一步，零新依赖。
2. **P0-2**：构建时下载 `echarts.min.js` 内嵌，新增日历热图 + 桑基图 + @提及力导向图——主管视角的" wow moment"。
3. **P0-3**：新增"消息时间线浏览"模块（脱敏消息 JSON + 按日分组 + 按人侧栏过滤）——审计/质检刚需。
4. **P1-1**：`sqlite-vec` 替代 Chroma，降低向量功能安装门槛。
5. **P1-2**："假聊天真搜索"问答框（默认零配置，证据卡片），可选 LLM 转发 proxy。
6. **工程 P0**：GitHub Actions matrix 跑 PyInstaller 出 Windows .exe + macOS .app；CI 加 pytest-cov 80% 门禁 + ruff。
7. **工程 P1**：SQLite PRAGMA 补全 busy_timeout/cache_size；FTS5 加 BM25 rank 排序 + optimize 子命令。
