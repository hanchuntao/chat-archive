---
name: chat-archive
description: 电商企业微信群/QQ群消息自动化管理与知识沉淀。当用户提供群聊天记录（微信/QQ 导出的 TXT/Markdown/JSON/CSV 明文文件，或微信加密备份文件），并要求：① 统计员工有效信息回复条数（识别消极怠工）、② 生成员工工作日报（去口水凑字数）、③ 总结讨论要点与待跟进事项（防事务架空）、④ 把有用信息清洗脱敏后沉淀为公司知识库（用于训练 AI 客服、员工入职培训）、⑤ 制定绩效考核制度用 AI 监督考核（监控群成员是否违反规则并评分）、⑥ 提取丢单/商机信号（询价未回复/承诺待兑现/商机线索）、⑦ 统计群活跃度（话唠榜/熬夜冠军/高峰时段）、⑧ 跨次运行记忆沉淀（员工画像/群事实记忆）、⑨ 需求洞察（客户痛点 TopN + 产品机会）、⑩ 客服质检信号（Success/Frustration/Workflow/Request）、⑪ 按时段压缩聊天文本、⑫ 知识库自动分类归档（7 类 + frontmatter）、⑬ 增量运行与员工成长报告时使用。也适用于用户说“整理群聊天记录”“监控员工回复”“沉淀知识库”“考核客服”“有没有丢单风险”“群里谁最活跃”“客户在抱怨什么”“客服服务得怎么样”等意图。
---

# Chat Archive — 群消息统计·监管·知识沉淀

两层架构：**数据层 = chat-archive CLI（清洗/脱敏/入库/检索/周报，本仓库 `chat_archive/` 包）**，
**业务层 = 本脚本（员工统计/日报/跟进/考核/知识库精修）**。通用 PII 脱敏规则已统一由
CLI 规则引擎提供（`skill/scripts/chat_archive.py` 的 `mask_pii` 复用 `chat_archive.pipeline.desensitize`）。

## 两种入口，同一结果

- **AI 一句话**：用户说"读取 <路径> 聊天记录，用 chat-archive 生成结果"→ 按下方工作流执行，默认产出**全部六类结果** + `report.html` + 快照（除非用户点名只要某一类）。
- **CLI 零参数**：`chat-archive`（不带子命令）或 `python3 <skill_dir>/scripts/chat_archive.py`（不带 task）→ 读取 `config.json` 的 `defaults`（input/staff/out）执行同一全流程，产物完全一致。

## 工作流

1. **确定输入**：用户提供的聊天记录文件/目录（明文 TXT/MD/JSON/CSV，或加密备份 `.db/.bak/.zip`）。格式细节见 [references/input-formats.md](references/input-formats.md)。
2. **确定员工名单**：`--staff` 一个参数三种写法——`--staff all`（全部发送人视为员工，员工群最常用）、`--staff "张三,李四"`（指定几个员工）、`--staff 名单.txt`（名单文件，每行一个）；也可用 `config.json` 的 `defaults.staff`。名单缺失时默认所有发送人视为客户——**优先从对话上下文/项目人员表推断**；推断不出就直接跑，产物照常生成，汇报时提示用户可补名单重跑。**不得因名单缺失而阻塞流程**。
3. **数据层（需要检索/周报/知识沉淀时执行）**：先调 CLI 入库（自动清洗+脱敏+幂等）：

```bash
# CLI 入口: 仓库根 chat-archive.py, 任意目录可调用
CLI=<仓库根>/chat-archive.py
python3 "$CLI" --db <输出目录>/archive.db import <输入文件或目录> --audit
python3 "$CLI" --db <输出目录>/archive.db search "关键词" --json
python3 "$CLI" --db <输出目录>/archive.db report --start YYYY-MM-DD --end YYYY-MM-DD -o 周报.md
```

4. **业务层（核心，必跑）**：

```bash
python3 <skill_dir>/scripts/chat_archive.py all \
  --input <文件或目录> --staff "张三,李四,王五" --out 输出目录
```

   加密备份（微信官方备份）需追加 `--tool-cmd 'wechat-cli export --input {input} --output {dir}'`（本机已安装的转换工具，`{input}`/`{dir}` 为占位符，平台自动填入）。
5. **汇报与精修**：
   - 统计/跟进/考核：读取 `effective_stats.md`、`followups.md`、`assessment.md`，向用户汇报要点；
   - 知识库：脚本产出**脱敏草稿**（`knowledge/*.md` + `training.jsonl` + `onboarding.md`），在此基础上按用户业务口径**精修为正式知识库文档**（推荐交付飞书文档），并说明已脱敏；
   - 检索/周报：CLI 的 `search`/`report` 产物直接汇报或落盘。
6. **隐私红线**：脱敏分两层——默认知识库输出时脱敏（PII 掩码 + 匿名化），本地统计/日报/跟进/考核保留原文供内部管理；若产物要交付第三方或用户明确要求严格隐私，加 `--mask-all` 做输入后全链路脱敏。仅处理工作群消息，不采集私聊；企业使用需员工知情同意。**CLI 入库时脱敏在写入前完成（顺序固定：清洗→脱敏→入库），库中不含明文 PII。**

## 可选参数（业务层）

| 参数 | 作用 |
|---|---|
| `--staff all` | **全部发送人视为员工**（员工群场景；`--all-staff` 为等价写法） |
| `--user 员工` | 只生成指定员工日报/考核 |
| `--date YYYY-MM-DD` | 日报日期（默认今天） |
| `--rules-file rules.json` | 合规规则文件（默认内置电商规则：私域导流/私下返现/绝对化话术/内部底价/夸大承诺/辱骂客户） |
| `--scheme base:100,timeout_penalty:5,violation_penalty:10,filler_threshold:50,filler_penalty:5,bonus:1,bonus_cap:20` | 考核方案 |
| `--duty 群ID:员工,群ID:员工` | 群值班人（超时扣分归属） |
| `--no-mask` | 关闭知识库脱敏（谨慎） |
| `--llm` / `--no-llm` | 强制/禁用 LLM 提炼（默认：配置了 `config.json` 的 `llm.api_key` 自动启用）。AI 提炼覆盖讨论要点/员工日报/知识库，失败自动降级规则版；LLM 输入先脱敏，输出禁止还原个人信息 |
| `--mask-all` | **输入后立即全链路脱敏**：PII 掩码 + 员工/客户匿名化，所有产物（统计/日报/跟进/考核/知识库）均不含明文身份与敏感信息。默认关闭（本地内部管理看原文）；交付第三方或严格隐私场景必开 |
| `--incremental` | 增量模式（P1-⑫）：以记忆层 `state/history.json` 各群锚点为界，只处理锚点之后的新消息（需先跑过一次非增量；`config.json` 的 `incremental.enabled` 可常开）。多群分别按各自锚点过滤 |

## 输出清单（`--out` 目录）

| 产物 | 对应需求 |
|---|---|
| `effective_stats.csv/.md` | 有效回复条数统计（防消极怠工） |
| `daily_reports/<员工>_<日期>.md` | 员工工作日报（已去口水） |
| `discussion_summary.md` | 讨论要点（LLM 版为四分类：核心决策/待办/未解决问题/重要信息；规则版自动追加决策/未决两节） |
| `followups.csv/.md` | 待跟进事项（防事务架空；含**类型**：待跟进/漏回复/询价未回复/承诺待兑现/商机线索） |
| `knowledge/*.md` + `training.jsonl` + `onboarding.md` | 清洗脱敏后的知识库（AI 训练/入职培训） |
| `assessment.csv/.md` | AI 监督绩效考核评分（规则计分，可配 duty） |
| `assessment_notes.md` | **证据化考核评语**（P0-4）：Summary + 证据引用（原话@时间）+ 需人工判断清单 + Rating 留空由主管填；LLM 版由 AI 生成，规则版兜底 |
| `activity.csv/.md` | **群活跃度**（P0-5）：话唠榜/活跃天数/高峰时段/熬夜冠军 |
| `report.html` | 汇总以上全部产物的离线 HTML 看板（含丢单风险面板、群活跃度模块） |
| `state/`（`--out` 下） | **跨次运行记忆层**（P0-1）：`history.json` 群历史锚点、`profiles/*.md` 员工/客户画像、`memory.md` 群事实记忆；供增量日报/成长分析/防重复犯错 |
| `chat_compact.txt` | **按时段压缩聊天文本**（P1-⑦）：同窗连续发言合并 `[10:35~10:39] 张三:… | 李四:…`，快速浏览 + LLM 预处理省 token |
| `insight.md`（+`insight_llm.md`） | **需求洞察**（P1-⑧）：客户痛点按话题聚类 TopN，每条挂带时间戳原话证据；配置 LLM 时另出 AI 提炼（痛点 Top5 + 产品/服务机会） |
| `signal.csv/.md` | **客服质检信号**（P1-⑩）：Success/Frustration/Workflow/Request 四类计数 + confidence（命中占比启发式） |
| `behavior.csv` | **沟通行为量化指标**（P2-⑭，规则版）：客户提问→员工首次实质回复平均分钟数、问句/陈述占比 |
| `dialogues.json` | **关键对话对**（P1-⑨）：客户问→员工实质回复配对，report.html 气泡展示（前 8 组） |
| `state/growth.md` | **员工成长分析报告**（P2-⑰）：由记忆层画像套模板（观察周期/发言概况/关键事件），**不写评分结论**、不可直接当考核依据 |
| `out/<日期_时间>_<毫秒>/` | 每次运行的完整结果目录（一份，重跑不覆盖，保留策略见下） |

数据层（CLI）产物：SQLite+FTS5 主库（`archive.db`）、`search` 检索结果（JSON）、`report` 周报（Markdown）。

## 新能力说明（吸收自开源同类 skill/项目）

- **昵称歧义消解**：占位符/低信息量昵称（nil/null/test/单 emoji/≤2 字等）且非员工 → 报表中显示为「昵称（ID 后 4 位）」，绝不原样占位；员工名单与别名优先匹配（参考 baoyu-wechat-summary 的 contacts 解析思路，规则版零依赖）。
- **四分类摘要**：LLM 提炼改为「核心决策 / 待办 / 未解决问题 / 重要信息」四分类，每条挂责任人+截止；未配置 LLM 时规则版自动追加决策/未决两节（参考 wechat-summarizer）。
- **证据化考核**：考核分仍由规则自动计算，另出 `assessment_notes.md` 定性评语——每条结论就地引证据、单列需人工判断清单、**不写评分结论**（Rating 留空由主管填写），防 AI 编造、考核更有说服力（参考 Claude 官方绩效评审方法论）。
- **丢单/商机信号**：`followups` 类型区分漏回复/询价未回复/承诺待兑现/商机线索；report.html 独立「丢单风险」面板（参考 WeChat Intelligence Hub）。
- **跨次运行记忆层**：每次 `all` 运行后把本批消息并入 `out/state/`，跨批积累员工画像与群事实，供增量日报、员工成长分析（参考 baoyu-wechat-summary 的 history/profiles/memory 架构）。
- **群活跃度**：话唠榜/活跃天数/高峰时段/熬夜冠军，纯标准库；词云是可选开关（`config.json` 的 `activity.wordcloud`，默认关，依赖 jieba）。（参考 shiyin-li/wx-daily-reports）
- **按时段压缩**（P1-⑦）：同窗连续发言合并为时间桶行，LLM 提炼输入自动走压缩（6000 字符截断），省 token 且保留“谁在说”语境。（参考 shiyin-li/wx-daily-reports）
- **需求洞察**（P1-⑧）：规则版把客户负面/痛点消息按话题聚类 TopN，每条挂带时间戳原话证据；`--staff all` 时带问句的员工消息（转述客户问题）自动计入。LLM 版提炼高频痛点 Top5 + 产品/服务机会（证据至上，失败降级规则版）。
- **关键对话气泡**（P1-⑨）：客户提问→员工首次实质回复配对，report.html 日报模块下气泡展示；`--staff all` 时员工问句→实质回复也配对（与考核语义一致）。（参考 WeChat Intelligence Hub 的对话对提取）
- **客服质检信号**（P1-⑩）：Success（成交/好评）/Frustration（投诉/不满/催促）/Workflow（流程）/Request（请求）四类按发送人计数 + confidence（命中/消息数启发式），report.html 独立面板，Frustration 行标红供质检优先跟进。
- **知识库自动分类归档**（P1-⑪）：每条目提取 7 类信息（任务待办/截止日期/会议约定/电话/地址/金额交易/重要文件）写入 frontmatter（type/source/created/tags/info_types），training.jsonl 同步加 info_types 元数据，供 AI 客服训练/检索。
- **wx-cli 桥接 + 增量运行**（P1-⑫）：自动探测本机 wx-cli/wechat-cli（仅提示用法，**不内置微信解密**——数据解密层整体灰色地带）；`--incremental` 以记忆层锚点只处理新消息，多群分别过滤。
- **沟通行为量化**（P2-⑭）：客户提问→员工首次实质回复平均分钟数 + 问句/陈述占比，写入 behavior.csv 并展示在看板活跃度模块。
- **检索质量门**（P2-⑮，`config.json` verify.enabled 默认关）：对讨论摘要每条要点做原文可溯源标注（[可溯源]/[待核对]），防 AI 提炼编造。
- **员工成长报告**（P2-⑰）：由记忆层画像跨批累计生成观察周期/发言概况/关键事件，**只观察不评分**，供主管做激励/培训参考。
- **report.html 长图开关**（P2-⑬，`config.json` report.screenshot.enabled 默认关）：依赖 playwright 截图，pip 可用时开启；纯标准库默认不启用。

以上能力全部并入本项目，CLI 与 AI skill 两种入口产物一致；无新增 pip 依赖（词云除外，默认关）。

## 常见问题

- **“识别不出消息”**：检查文件是否为支持的格式（见 references）；TXT 需要“时间 发送人: 内容”行；QQ 消息管理器导出支持“时间 发送人(QQ号)+下一行内容”两行式。
- **员工被当成客户**：发送人显示名必须与 `--staff` 名单一致（支持昵称/ID/姓名）。
- **加密备份无法读取**：微信官方备份为私有加密格式，必须配置 `--tool-cmd` 指向本机 wechat-cli 类工具；未配置时脚本明确提示并跳过。
- **CLI 找不到模块**：CLI 入口是仓库根 `chat-archive.py`（自动定位包路径），不要用 `python3 -m chat_archive.cli`（依赖工作目录）。
- **结果保留**：`out/` 下默认保留最近 30 份结果目录（`config.json` 的 `snapshot.keep`，0=永久保留），或运行时加 `--keep-snapshots N` 覆盖。
- **知识库双通道**：`config.json` 的 `knowledge` 段控制产物去向——本地（默认 `out/knowledge/`）+ 腾讯 ima（可选）。ima 在 https://ima.qq.com/agent-interface 生成 API Key/Client ID 填入配置后，运行 `chat_archive.py kb-sync --out 目录` 自动上传脱敏 .md；未配 Key 时导出到 `out/ima_export/` 供手动导入。
- **insight/dialogues 为空**：`--staff all` 全员员工时，洞察只看带问句的消息（转述客户问题）、对话按员工问句→实质回复配对；指定真实员工名单（`--staff "张三,李四"`）时客户消息直接计入，结果更完整。
- **增量跑一次**：`--incremental` 依赖记忆层锚点，第一次跑请用普通模式（不带该参数）建立 `state/history.json`；之后每次只处理锚点后的新消息，无新消息时直接跳过并提示。
