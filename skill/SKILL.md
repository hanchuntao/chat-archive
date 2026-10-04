---
name: chat-archive
description: 电商企业微信群/QQ群消息自动化管理与知识沉淀。当用户提供群聊天记录（微信/QQ 导出的 TXT/Markdown/JSON/CSV 明文文件，或微信加密备份文件），并要求：① 统计员工有效信息回复条数（识别消极怠工）、② 生成员工工作日报（去口水凑字数）、③ 总结讨论要点与待跟进事项（防事务架空）、④ 把有用信息清洗脱敏后沉淀为公司知识库（用于训练 AI 客服、员工入职培训）、⑤ 制定绩效考核制度用 AI 监督考核（监控群成员是否违反规则并评分）、⑥ 提取丢单/商机信号（询价未回复/承诺待兑现/商机线索）、⑦ 统计群活跃度（话唠榜/熬夜冠军/高峰时段）、⑧ 跨次运行记忆沉淀（员工画像/群事实记忆）、⑨ 需求洞察（客户痛点 TopN + 产品机会）、⑩ 客服质检信号（Success/Frustration/Workflow/Request）、⑪ 按时段压缩聊天文本、⑫ 知识库自动分类归档（7 类 + frontmatter）、⑬ 增量运行与员工成长报告、⑭ 会话级经营分析（挂起队列/满意度/SLA分诊/丢单健康分/销售SOP动作窗）、⑮ 资金流水对账与撤回审计、⑯ 会话阶段漏斗/问题分级P0-P3/FAQ草稿/混合检索/训练样本清洗/周期环比、⑰ @提及统计（找关键对接人）与扁平消息表导出（供 Excel 透视）、⑱ 年度分析（高频词 TopN / 情感倾向 / 群成员完整档案）时使用。也适用于用户说“整理群聊天记录”“监控员工回复”“沉淀知识库”“考核客服”“有没有丢单风险”“群里谁最活跃”“客户在抱怨什么”“客服服务得怎么样”“谁还没回消息”“这笔钱收到没有”等意图。
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
python3 "$CLI" --db <输出目录>/archive.db backup <备份文件.db>   # SQLite 热备
python3 "$CLI" --version                                          # 版本号
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
| `--search 关键词` | 正则批量检索（第2轮吸收⑩）：业务层多面过滤，输出 `search.csv`（可按发送人/日期过滤，见函数 search_messages） |
| `--search-bm25` | **混合检索排序**（第3轮吸收 21）：bigram-BM25 + 时间衰减打分，`search.csv` 带 `bm25` 分值列，旧消息自动降权 |
| `kb-draft` 子命令 | 只跑 FAQ 草稿（第3轮吸收 20）：`chat-archive kb-draft --input <文件> --staff all`，从高频已解决问答起草 `knowledge/faq_drafts.md` + `faq_search_terms.csv`，**人工复核后再入库** |

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
| `sessions.csv` | **按客户会话切分**（第2轮①）：30 分钟互动窗归并会话，会话级经营分析地基 |
| `pending.csv` | **待回复挂起队列**（第2轮②）：群末仍无实质回复的提问，按等待时长降序；客户结束语豁免 |
| `satisfaction.csv` | **会话级满意度三档**（第2轮⑤）：满意/一般/不满意/未判定（规则版关键词） |
| `sla.csv` | **SLA 分级分诊**（第2轮⑥）：咨询 P1-P4 分级（1h/4h/1工作日/2工作日） |
| `health.csv` | **丢单健康分+干预 playbook**（第2轮⑦）：按客户聚合 0-100 分，<60 输出挽留话术 |
| `sop_compliance.csv/.md` | **销售 SOP 动作窗合规**（第2轮④）：首响≤20s / 问价15min跟进 / 犹豫2min挽留 / 意向10min催拍（config `assessment.sop` 可调） |
| `revoke_audit.csv` | **撤回消息审计**（第2轮⑧）：从原始文本扫描撤回记录，按人统计 |
| `payment_ledger.csv` | **红包/转账流水对账**（第2轮⑨）：金额提取 + 已确认/待确认/未到账标记 |
| `search.csv` | 检索命中（`--search` 触发，第2轮⑩；`--search-bm25` 时带 bm25 分值列） |
| `funnel.csv/.md` | **销售漏斗与卡点**（第3轮吸收 18）：咨询→询价→催拍→下单未付款→成交，未成交会话标注卡点环节 |
| `insight_level.csv` | **问题分级 P0-P3**（第3轮吸收 19）：客户痛点按可解释阈值分级（config `problem_level` 可调），P0 最优先解决 |
| `timeline.json` | **客户会话时间线**（第3轮吸收 11）：客户提问/员工回复交替 + 阶段触发词 + 回复耗时，report 第 16 模块展示 |
| `media_manifest.csv` | **多模态占位归档**（第3轮吸收 12）：从原始输入扫描 `[图片]/[语音]` 等占位，待上游导出媒体/语音转写后补全 |
| `knowledge/training_clean.jsonl` + `training_clean_report.csv` | **训练样本级清洗**（第3轮吸收 15）：去重/红线词过滤/低质过短过滤，供 AI 客服训练 |
| `knowledge/faq_drafts.md` + `faq_search_terms.csv` | **FAQ 草稿**（第3轮吸收 20）：高频已解决问答 → Direct Answer/Details/Related + 搜索词表，人工复核后入库 |
| `trend.md` | **周期环比报告**（第3轮吸收 16）：最近两期关键指标对比 + 新冒头问题检测（需历史结果目录 ≥2 期） |
| `mentions.csv/.md` | **@提及统计**（第4轮吸收）：被 @ 最多的关键对接人识别（@所有人 单列；邮箱/URL 中的 @ 不误报） |
| `messages.csv` | **扁平消息表**（第4轮吸收）：每行一条有效消息（时间/群/发送人/角色/话题/内容），Excel 透视/筛选；`--mask-all` 时全表脱敏 |
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
- **待回复挂起队列**（第2轮②）：群末未回复提问按等待时长降序，「谁被晾最久」开机即看；客户自己说谢谢/再见等结束语豁免。（参考 WeFlow awaiting / 排班漏接）
- **承诺到期复核闭环**（第2轮③）：把已吸收的「承诺待兑现」推进到「到期复核」——due 已过自动标「已过期待复核」，主管处理完勾选后写入 `state/checklist.json` 不再重复出现。（参考 ComposioHQ meeting-notes-and-actions）
- **销售 SOP 动作窗合规**（第2轮④）：晓多科技规则表 → config `assessment.sop`（首响≤20s/问价15min跟进/犹豫2min挽留/意向10min催拍），命中即记录，report 第 14 模块展示。（参考 xiaoduoai.com 质检规则）
- **会话级满意度三档**（第2轮⑤）：通义晓蜜 7 条判定规则 → 规则版关键词（满意/一般/不满意），补上质检信号缺的「会话结局」。（参考通义晓蜜对话分析）
- **SLA 分级分诊**（第2轮⑥）：P1 紧急1h / P2 重要4h / P3 常规1工作日 / P4 一般2工作日，report 第 12 模块展示分级分布。（参考 augmentclaude customer-support-notque）
- **丢单多信号健康分**（第2轮⑦）：未回复 -30 / 不满意 -20 等信号聚合 0-100 分，<60 输出优先回访+挽留话术 playbook。（参考 claudecodehq customer-success）
- **撤回消息审计**（第2轮⑧）：扫描原始文本中「XX 撤回了一条消息」按人统计（撤回消息正常解析会被过滤，单独补审计视角）。
- **资金流水对账**（第2轮⑨）：提取红包/转账金额 → 流水，未收到/没收到 → 未到账红标，report 第 14 模块展示。
- **正则批量检索**（第2轮⑩）：`--search 关键词` 输出 search.csv，函数支持发送人/日期多面过滤。

## 第3轮吸收（P1×4 + P2×4，全部纯标准库）

- **会话阶段漏斗**（P2-18）：按客户会话判定咨询→询价→催拍→下单未付款→成交阶段（关键词状态机），`funnel.csv` 卡点统计 + report 第 15 模块漏斗条，一眼看清客户卡在哪个环节。（参考晓多科技「顾客咨询未下单…主动引导付款」+ 有机云过程指标方法论）
- **问题分级量化 P0-P3**（P2-19）：需求洞察的痛点按可解释阈值打标签（P0≥10条或投诉/差评词；P1≥5条或退款/赔偿词；P2≥3条；其余 P3），老板不用读原始聊天先看最该解决的。（参考 skillsmp support-data-analyzer 的 P0-P3 阈值表）
- **FAQ 草稿**（P2-20）：知识库 qa 配对中高频话题（≥2 条）自动起草 FAQ（Direct Answer→Details→Related + 搜索词表），**默认人工复核后再入库**；`kb-draft` 子命令可单独跑。（参考 augmentclaude customer-support-notque 的 KB 模式）
- **混合检索增强**（P2-21）：`--search-bm25` 用中文 bigram-BM25 打分 + 时间衰减（旧消息降权），替代纯正则命中排序，减少「夏天召回冬天话术」。（参考腾讯云 BM25+向量+时间戳元数据检索方案；向量 rerank 属第三方，仅 config 开关默认关）
- **客户会话时间线**（P1-11）：`timeline.json` 记录每个会话的客户提问/员工回复交替节点 + 阶段触发词 + 回复耗时（>120min 红标），report 第 16 模块可视化客户交互轨迹。
- **多模态占位归档**（P1-12）：`media_manifest.csv` 从原始输入文件扫描 `[图片]/[语音]/[文件]` 等占位（解析层已过滤不污染统计），提示「需上游导出媒体文件/语音转写后补全」；外部 whisper 转写属可选前置（config 开关，默认关）。
- **训练样本级清洗**（P1-15）：`training_clean.jsonl` 对知识库训练集做去重/红线词过滤（敏感样本优先）/低质过短过滤/长度截断，供 AI 客服训练更干净的数据。
- **周期环比报告**（P1-16）：`trend.md` 对比最近两期（员工消息/有效回复/平均得分/违规次数/待跟进）+ 本期新冒头话题检测；需历史结果目录 ≥2 期自动生效，不足时给出提示。

## 第4轮吸收（@提及统计 + 扁平消息表，零依赖快赢）

- **@提及统计**：按群消息中被 `@名称` 的次数聚合（`@所有人` 单列），输出被 @ 者榜——「被 @ 最多的关键对接人」一眼可见；邮箱（`team@example.com`）与 URL 里的 `@` 已排除不误报。（参考 WeChatMsg 年报活跃度扩展维度）
- **扁平消息表导出**：`messages.csv` 每行一条有效消息（sent_at/group/sender/role/topic/content），配合话题自动标注，Excel 透视表即可按员工/话题/日期任意切片；`--mask-all` 时全表脱敏（PII 掩码 + 匿名化）。
- **服务红线词表**（第2轮⑪）：威胁客户/敷衍回复并入考核规则（config `assessment.rules` 现有 8 条）。
- **防幻觉兜底**（第2轮⑫）：全部 LLM 提炼 prompt 强制「不得编造、信息不足标注原材料不足、消息中没有的不写」；讨论摘要另有可溯源标注（verify.enabled）。

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
