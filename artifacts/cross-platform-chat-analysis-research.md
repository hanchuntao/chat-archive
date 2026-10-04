# 跨平台聊天/IM 数据分析与可视化开源项目调研 —— chat-archive 交互式分析能力吸收参考

> 调研日期：2026-10-04
> 视角：工程最佳实践 + 商业化 + **可交互**（重点不是导出，而是分析+可视化+交互）
> chat-archive 现状基线：纯 Python 标准库、双平台（Win/macOS）、report.html（19 模块）、SQLite+FTS5、301 测试通过。已吸收能力见任务书，本文不重复。
> star 数均取自 GitHub REST API（2026-10-04）或官方/ecosyste.ms 页面，已标注来源；未核验者明确标注。

---

## 一、项目卡片

### WhatsR
- 仓库: https://github.com/gesiscss/WhatsR | 语言: R | Star≈: 29（API 实测） | License: GPL-3.0
- 定位: GESIS（德国社科机构）出品的 WhatsApp 导出日志解析/匿名化/可视化 R 包，面向"量化人际关系"的学术研究。
- 核心能力:
  - **交互式参与者网络图** `plot_network()`：每条消息视为对上一条的回复，同一人连续消息合并为一个"session"，节点=人、边=回复关系，**输出可交互 HTML（非静态图）**。
  - **词汇离散度图（Lexical Dispersion Plot）** `plot_lexical_dispersion(keywords=c(...))`：横轴=时间线，纵轴=每个参与者，标出关键词在何时被谁说——这是"关键词时序"之外的另一种交互视角。
  - **回复时间分布** `plot_replytimes(type="replytime")`；**链接发送热图** `plot_links(plot="heatmap")`；emoji 拆分条形 `plot_emoji(plot="splitbar")`；人均词云 `plot_wordcloud(comparison=TRUE)`；tokens 按小时分布 `plot_tokens_over_time(plot="hours")`；位置可视化。
  - 匿名化参数 `anonymize=TRUE`（与 chat-archive 脱敏方向一致）；`create_chatlog()` 造模拟语料用于测试。
- 交互形态与实现: R 包函数返回 ggplot/networkD3 风格的**可交互 HTML 对象**；配套 ChatDashboard 是 **R Shiny Web 应用**（上传→审核→安全捐赠聊天记录），见 Kohne & Montag (2024) Behav Res Methods 论文。图表库：ggplot2 + patchwork + networkD3/plotly 类。
- 工程最佳实践: ①`create_chatlog()` 内置合成数据→可脱离真实敏感数据跑测试（chat-archive 已有 sample_data，可对标）；②多语言通过 `languages.csv` + 正则扩展，而非硬编码；③emoji 字典可爬虫更新。
- 商业化模式: 纯开源学术工具（机构维护），靠论文引用驱动；Shiny 版用于"数据捐赠"科研流程，非售卖。
- 关键事实来源URL: https://github.com/gesiscss/WhatsR ；https://gesiscss.github.io/WhatsR/ ；https://www.juliankohne.com/publication/ChatDashboard/ChatDashboard2023_Kohne_Montag.pdf

### whatstk
- 仓库: https://github.com/lucasrodes/whatstk | 语言: Python | Star≈: 151（API 实测） | License: GPL-3.0
- 定位: 把 WhatsApp 导出（Android/iOS，含 zip）解析成 pandas DataFrame 的 Python 工具包，主打"交互式可视化"。
- 核心能力:
  - **Plotly 交互式图表**（悬停数值、缩放、图例开关、导出 PNG）：如 `plot_user_message_count(df)` 直接 `fig.show()`。
  - `WhatsAppChat.from_source()` 单一入口加载单文件/多文件；`df_from_whatsapp()` 一步到 DataFrame。
  - CLI：`whatstk-to-csv input.txt output.csv`（与 chat-archive 的 bin/chat-archive 双入口哲学一致）。
  - 多语言日期格式自动探测；header 自动检测；12/24 小时制兼容。
- 交互形态与实现: **Python 库 + Plotly figure 对象**（.show() 开浏览器），另有 "Try Live Demo" 托管 demo；文档站 readthedocs。图表库 = Plotly（生成自包含 HTML `<div>`，可直接嵌进 report.html）。
- 工程最佳实践: ①库与 CLI 双入口（chat-archive 已是此模式，可继续强化）；②`Featured Projects` 列出基于本包的二次创作，形成生态；③pyproject + uv.lock + pyright 类型检查 + codecov，工程化完整。
- 商业化模式: 纯开源（作者个人维护，页内 Sponsor 按钮），无付费版。
- 关键事实来源URL: https://github.com/lucasrodes/whatstk ；https://pypi.org/project/whatstk/

### Chatistics
- 仓库: https://github.com/MasterScrat/Chatistics | 语言: Python | Star≈: 932（API 实测） | License: MIT
- 定位: 把 Messenger/Hangouts/WhatsApp/Telegram 四种导出统一解析成同一个 pandas DataFrame 的多平台归一化工具。
- 核心能力:
  - **统一数据模型**：每条消息固定列 `timestamp / conversationId / conversationWithName / senderName / outgoing(bool) / text / language(自动检测) / platform`——跨平台归一 schema 的范本。
  - **可组合的 CLI 筛选管线**（交互分析的关键）：`--filter-conversation`、`--filter-sender`、`--remove-conversation`、`--remove-sender`、`--contains-keyword`、`--outgoing-only`/`--incoming-only`、`-n 10` topN、`--as-density`。
  - 直方图 `visualize.py breakdown`；**带 mask 形状的词云** `visualize.py cloud -m outline.jpg`（白色镂空处留白、其余按图片配色填词）。
  - 导出 stdout/json/csv/pkl 多格式。
- 交互形态与实现: **CLI 报表 + matplotlib 静态直方图 + word_cloud 位图**；无 Web UI，交互全部通过命令行参数组合完成。图表库 matplotlib + amueller/word_cloud。
- 工程最佳实践: ①统一 schema 让"跨平台对比"成为可能（chat-archive 只做微信/QQ，但其扁平消息表导出已是同思路）；②筛选 flag 设计正交可组合，值得抄进 report 的筛选器；③Stopwords 用现成 stopwords-json。
- 商业化模式: 纯开源（MIT，曾上 HackerNews/Reddit），无商业化。
- 关键事实来源URL: https://github.com/MasterScrat/Chatistics

### DiscordChatExporter
- 仓库: https://github.com/Tyrrrz/DiscordChatExporter | 语言: C# | Star≈: 12130（API 实测，本组最高） | License: MIT
- 定位: Discord 频道/私聊历史归档事实标准工具（导出为主，分析弱）。
- 核心能力:
  - 导出四种格式：**HTML（Discord 主题网页，最受欢迎）** / JSON（程序化消费）/ CSV / 纯文本。
  - GUI 桌面版 + CLI + 官方 Docker 镜像；Win/macOS/Linux 自包含二进制。
  - 本仓库本身不做统计分析，但其 **HTML 消息渲染**（时间分隔、附件、表情、引用、频道主题样式）是"可浏览聊天回放"的标杆。
- 交互形态与实现: 离线静态 HTML（Discord 视觉主题、可折叠、带导航），非看板；数据层输出 JSON/CSV 供下游分析。
- 工程最佳实践: ①GUI+CLI+Docker 三形态覆盖不同用户（chat-archive 双入口可借鉴"是否再加 GUI/桌面打包"）；②导出格式分层：人看的 HTML / 机器吃的 JSON/CSV 分离；③自包含单二进制分发，零运行时依赖。
- 商业化模式: 开源免费（作者页接受捐赠），靠口碑与捐赠。
- 关键事实来源URL: https://github.com/Tyrrrz/DiscordChatExporter ；https://tyrrrz.me/projects ；https://discordchatexporter.org/

### imessage-exporter
- 仓库: https://github.com/ReagentX/imessage-exporter | 语言: Rust | Star≈: 5636（API 实测） | License: GPL-3.0
- 定位: 直接读 macOS `~/Library/Messages/chat.db` SQLite，导出 iMessage + 运行诊断。
- 核心能力:
  - **直接消费原生 SQLite 库**（与 chat-archive 的 SQLite+FTS5 路线同源），输出 HTML/CSV/JSON/TXT 等。
  - 自带 **Diagnostics**（诊断消息库健康/一致性）——对应 chat-archive 的 snapshot manifest/verify。
- 交互形态与实现: CLI 导出为主，HTML 为可浏览归档；无看板交互。
- 工程最佳实践: ①"导出 + 数据质量诊断"一体（chat-archive 已有 verify，方向正确）；②Rust 单二进制、零依赖分发；③逆向私有库 schema 的范式。
- 商业化模式: 开源免费（GPL-3.0）。
- 关键事实来源URL: https://github.com/ReagentX/imessage-exporter

### telegram-analysis
- 仓库: https://github.com/amiryousefi/telegram-analysis | 语言: Python | Star≈: 369（API 实测） | License: 未声明（API license=null）
- 定位: 基于 Telethon 抓取 Telegram 公开群/频道用户与消息后做分析的工具集。
- 核心能力: 拉取群成员与消息列表，做发言量、活跃度等基础统计；群与频道在 Telegram 等价，公开/私有群只要是成员即可取。
- 交互形态与实现: 脚本/Notebook 式，matplotlib 静态图为主，无 Web 交互。
- 工程最佳实践: 用 Telethon 高阶 API 做数据采集（chat-archive 走 convert_wx/wx-cli 桥接，思路类似：先解决"取数"再谈分析）。
- 商业化模式: 个人开源，无商业化。
- 关键事实来源URL: https://github.com/amiryousefi/telegram-analysis ；https://awesome.ecosyste.ms/projects/github.com/amiryousefi/telegram-analysis

### ChatLab（本组最值得对标）
- 仓库: https://github.com/ChatLab/ChatLab | 语言: TypeScript | Star≈: 7472（API 实测） | License: AGPL-3.0
- 定位: **Local-first 本地优先的 AI 聊天记录分析工具**，已支持 WhatsApp/**微信**/**QQ**/Discord/Instagram（即将支持 iMessage/LINE/Messenger），与 chat-archive 的赛道几乎完全重合。
- 核心能力:
  - **AI Agent + 灵活 SQL 引擎**："自由拆解、查询甚至重构社交数据"——即对归档库做自然语言/对话式问答。
  - 本地优先（隐私）、多平台归一、数据可视化。
- 交互形态与实现: **桌面/Web 应用（TypeScript/前端重度）**，chatlab.fun；交互形态 = 看板 + 对话式 AI 查询（chat-over-your-data）。
- 工程最佳实践: ①把"AI 对话查询"作为一等公民而非事后插件；②local-first 隐私定位（聊天数据敏感）；③明确的多平台适配矩阵与 roadmap。
- 商业化模式: 开源（AGPL-3.0，注意：AGPL 具传染性，chat-archive 若借鉴其思路须自行重写、勿直接抄码）；有官网/产品化外壳，疑似走"开源核心 + 托管/增值"路线。
- 关键事实来源URL: https://github.com/ChatLab/ChatLab ；https://www.gstars.dev/repo/ChatLab/ChatLab

### telegram-stats-bot
- 仓库: https://github.com/mkdryden/telegram-stats-bot | 语言: Python | Star≈: 33（repos.ecosyste.ms 实测） | License: GPL 系
- 定位: 常驻群内的统计 bot，把消息写入 PostgreSQL，再把统计表/图以 Telegram 消息形式发回群。
- 核心能力:
  - **双人消息时间相关性表**：`/stats corr` 返回与"我"消息时间相关性最高/最低的成员列表（如 0.335）——一种"互动配对"的量化新视角。
  - 中位消息时间差（与其他用户）；最活跃用户榜。
  - 图：**按小时活跃度、按星期几活跃度、周×小时活动热图矩阵、活动历史曲线**。
- 交互形态与实现: bot 命令驱动（`/stats`、`/stats corr`），后端 PostgreSQL + matplotlib 出图再发图。交互 = 在 IM 内对话式触发统计。
- 工程最佳实践: ①"谁和谁作息/发言时间最同步"这一度量新颖，可作为互动配对的补充指标；②周×小时二维热图是活跃度的最佳视觉形态。
- 商业化模式: 个人开源小工具，无商业化。
- 关键事实来源URL: https://repos.ecosyste.ms/hosts/GitHub/repositories/mkdryden/telegram-stats-bot ；https://www.zzun.app/repo/mkdryden-telegram-stats-bot-python-third-party-apis-wrappers

### ConvoKit（Cornell Conversational Analysis Toolkit）
- 仓库: https://github.com/Cornell-Conversational-Analysis-Toolkit/convokit （官网 convokit.cornell.edu） | 语言: Python | Star≈: 未单独核验（官网/学术项目） | License: 开源（BSD 系，未在本次核验，标注无来源不展开）
- 定位: Cornell 出品的"对话分析"统一框架，scikit-learn 风格接口，专门建模对话的社会交互。
- 核心能力:
  - **统一 Corpus 数据模型**：Utterance（话语）/ Speaker（说话人）/ Conversation（会话）三层对象，配套 Transformer 流水线。
  - 内置对话结构/元特征抽取器、话题与社交现象分析；**GenAI 模块**（4.x）：统一封装 GPT/Gemini/本地模型，把 LLM prompt 作为 Transformer 应用到整个语料。
- 交互形态与实现: Python 库/Notebook，非 Web；交互靠编程接口；学术配套数据集。
- 工程最佳实践: ①把"对话"抽象成 Speaker/Utterance/Conversation 三层，比扁平消息表更适合话题/网络分析（chat-archive 的扁平消息表是正确底座，可在上层补这层语义模型）；②LLM 调用抽象成可插拔 Transformer，便于换模型。
- 商业化模式: 学术开源，无商业化。
- 关键事实来源URL: https://convokit.cornell.edu/ ；https://convokit.cornell.edu/documentation/genai.html

---

## 二、可交互分析模式清单（本组重点交付）

| 交互模式 | 代表项目 | 交互形态 | 实现方式 | 纯标准库可否实现 | 若需依赖，推荐什么 |
|---|---|---|---|---|---|
| 回复关系社交网络图 | WhatsR `plot_network` | 可拖拽/悬停的节点-边图（HTML） | networkD3/plotly 渲染 R 对象 | 半可：节点坐标+边可纯 stdlib 算出并输出 SVG；**真交互（拖拽/缩放/悬停）需 JS** | 内嵌 vendored ECharts（graph）或 vis-network；单 JS 文件随 report.html 分发 |
| 关键词词汇离散度图 | WhatsR `plot_lexical_dispersion` | 横轴时间×纵轴成员的关键词命中刻度带 | 逐条消息命中即在对应行画刻度 | **可（纯 stdlib 生成内联 SVG）** | 无需；最多用 SVG `<line>` |
| 报告内多维筛选（人/会话/关键词/收发方向） | Chatistics CLI flags | 交互式筛选器（复选/搜索框）联动各图 | 数据内嵌 JSON + 原生 JS 过滤 | **可**：Python 只产出数据与一小段 vanilla JS | 无需依赖；如需顺滑可内嵌 Alpine.js（~15KB） |
| 7×24 活动热图矩阵 | telegram-stats-bot / WhatsR heatmap | 星期×小时彩色矩阵，悬停看数值 | 二维计数→色阶格子 | **可（纯 stdlib 表格/SVG 上色）** | 无需 |
| 词云（含形状 mask） | Chatistics `cloud -m` | 按词频缩放的文字云图 | 位图填充算法 | 半可：纯 stdlib 只能做"按字号散点"的简陋词云，无精美排版 | `wordcloud`（Python）或纯 CSS/SVG 简易版 |
| Plotly 式悬停交互图 | whatstk | 悬停数值/缩放/图例开关/导出 PNG | Plotly figure → 自包含 HTML div | 否（Plotly 本体重） | 内嵌 vendored Plotly.js 或 ECharts |
| 双人发言时间相关性 / 互动配对量化 | telegram-stats-bot `/stats corr` | 排名列表 + 可点开两人连线 | 皮尔逊/中位时间差计算 | **可（纯 stdlib 计算，结果渲染成表/条）** | 无需 |
| 回复时间分布 | WhatsR `plot_replytimes` | 分布直方图/密度 | 分箱计数 | **可（纯 stdlib SVG 直方图）** | 无需 |
| 对话式问答 / SQL-on-chat / AI 对话查询 | ChatLab / ConvoKit GenAI | 聊天框对归档库自然语言提问 | 本地 SQLite + 前端输入框；LLM 生成 SQL/摘要 | **计算与 UI 可纯 stdlib**；"智能"那步需外部 LLM API | Python 侧零新依赖（SQLite 已有）；LLM 走外部 API，不引入 Python 包 |
| 可浏览聊天回放 HTML（Discord 主题） | DiscordChatExporter | 时间分隔的会话流网页 | 纯模板字符串生成 HTML | **可（纯 stdlib 模板渲染）** | 无需 |
| 聊天式 bot 命令触发统计 | telegram-stats-bot | IM 内 `/stats` 命令 | bot 后端 | chat-archive 是离线归档，不适用 | —（排除，见下） |

---

## 三、可吸收能力建议（本组）

> 对齐 chat-archive 现状缺口，**不重复**已吸收能力（活跃度/话唠榜/@提及/关键词周趋势/年度情感/响应速度/消息日历/类型/互动配对等已存在）。

| 能力 | 来源项目 | chat-archive 现状缺口 | 实施成本 | 商业化价值 | 交互增益 | 是否需新依赖 |
|---|---|---|---|---|---|---|
| **回复关系交互式网络图**（节点=成员，边=谁回复谁，可拖拽悬停） | WhatsR | 现有"互动配对"只是静态配对统计，无可视化的关系网络 | 中 | 高 | ★★★★★ 一眼看出谁是群内信息枢纽/关键客服 | 渲染需内嵌 ECharts graph（vendored JS），计算纯 stdlib |
| **对话式问答 / AI 查库**（在 report.html 里对归档库自然语言提问"上周谁问了价格"） | ChatLab / ConvoKit | 现有洞察都是预生成固定模块，无法临时追问 | 中-高 | 高 | ★★★★★ 从"读报表"升级为"问数据"，最强交互卖点 | Python 侧无新依赖（SQLite 已有）；LLM 走外部 API |
| **report.html 内多维筛选器**（按人/按关键词/按收发方向联动所有图） | Chatistics | 现有 19 模块全是静态全量统计，无法聚焦到某客户/某关键词子集 | 低-中 | 中 | ★★★★ 电商场景刚需：只看某客户群、只看"询价"关键词子集 | 无需（内嵌 JSON + vanilla JS） |
| **关键词词汇离散度图**（某词在整个时间轴上"谁在何时说了"） | WhatsR | 现有"关键词趋势(按周)"只有汇总曲线，看不到逐条命中与发言者 | 低 | 中 | ★★★★ 比周趋势更锐利，可定位"某投诉词首次出现时间/是谁引爆" | 无需（纯 stdlib 内联 SVG） |
| **7×24 周×小时活动热图** | telegram-stats-bot | 现有"活跃时段"是单维小时分布，缺"星期×小时"二维矩阵 | 低 | 中 | ★★★ 排班/客服值守决策直接可用 | 无需（纯 stdlib 上色表格） |
| **词云（成员/全局，带形状 mask）** | Chatistics | 现有"高频词"只是表格，无可视化词云 | 低 | 中 | ★★★ 报告页视觉抓手，老板一眼爱看 | 推荐 `wordcloud`（需说明理由：排版算法复杂，纯 stdlib 难做到美观）；或纯 SVG 简易版兜底 |
| **双人发言时间相关性榜**（谁和谁作息/发言最同步） | telegram-stats-bot | 现有互动配对是"谁回复谁"，缺"时间节奏相似度"这一维 | 低 | 中 | ★★★ 可识别"高频同事/水军/托儿"成对出现 | 无需 |
| **可浏览聊天回放 HTML**（时间分隔、附件、@引用的会话流） | DiscordChatExporter | 现有扁平消息表 CSV + report 图表，缺"像聊天记录一样翻回去看上下文"的页面 | 中 | 中 | ★★★ 证据化考核需要"点击某结论→跳回原始上下文" | 无需（纯 stdlib 模板渲染） |
| 回复时间分布直方图（非中位数） | WhatsR | 现有"响应速度"疑似只给中位/均值，缺分布形态 | 低 | 低 | ★★ 看长尾（多久没回的客户） | 无需 |
| Emoji 使用拆分条形图 | WhatsR | 现有未单独做 emoji 维度 | 低 | 低 | ★★ 客户情绪的弱信号补充 | 无需 |

---

## 四、排除项（本组）

| 项目/能力 | 排除原因 |
|---|---|
| DiscordChatExporter / imessage-exporter 的**导出器本体** | chat-archive 已有 convert_wx/wx-cli 桥接 + 快照 verify，导出/归档链路已建成；这两个仓库价值在"HTML 回放样式"而非"再做一个导出器"。 |
| telegram-analysis / telegram-stats-bot 的**在线 bot 常驻采集与 IM 内发图** | chat-archive 是离线归档工具，不常驻群、不主动发消息；bot 模式与"稳定第一、纯标准库、离线"约束冲突。 |
| ConvoKit 的**完整 Corpus 框架与学术数据集** | 重依赖、面向研究语料；chat-archive 扁平消息表已是正确底座，只吸收其"三层语义模型 + LLM 可插拔 Transformer"思想，不引入整个框架。 |
| WhatsR / ConvoKit 的 **R 语言栈与 ggplot/networkD3 技术实现** | chat-archive 纯 Python；只借鉴图表"形态与指标"，不引入 R 运行时。 |
| ChatLab **直接抄代码** | License 为 AGPL-3.0，具网络传染性；chat-archive 若保持宽松/闭源商用不可直接 copy，只能借鉴交互形态自行用 Python 重写。 |
| Streamlit 系（chat-wrapped / ChatLens 等）**整套 Web 框架** | Streamlit 是重依赖且需起服务，与"单文件 report.html、纯标准库、双平台稳定"约束冲突；其"本地 100% 隐私、不入库、刷新即焚"的理念可吸收，但不用 Streamlit 实现。 |
| 词云的**位图 mask 精美排版**（第一版） | 纯 stdlib 做不出 amueller/word_cloud 的效果；首期建议先上"按字号 SVG 简易词云"，`wordcloud` 作为可选增强依赖，不阻塞主线。 |

---

## 五、一句话结论

跨平台分析工具圈对 chat-archive 最有价值的不是"再导一次数据"，而是三类交互升级：**①把静态统计变成可筛选、可拖拽的图（网络图/筛选器/词云/热图），②把预生成报表变成可临时追问的对话式查库，③把结论跳回原始上下文（聊天回放 HTML）**；其中网络图与对话式查库交互增益最大，且绝大部分可用纯标准库生成 SVG/内联 JS 落地，仅网络图与精美词云建议内嵌 vendored ECharts/`wordcloud`。
