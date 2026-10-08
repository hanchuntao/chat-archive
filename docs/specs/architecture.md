# Chat Archive 架构设计（specs）

> 本文档是项目架构的权威说明。代码与本文不一致时，以本文为准并优先修正代码。
> 版本：1.0（2026-10-04，商业级质量审查后定稿）

## 1. 定位与边界

**产品定位**：电商企业微信群/QQ 群消息的自动化管理与知识沉淀工具——面向 10 人级小团队，
"导出消息 → 本地处理"模式，零部署、零第三方依赖、单机可跑，产出可直接交付的管理报表与知识库。

**明确不做**（边界）：
- 不做微信数据解密（官方备份为私有加密格式，解密属第三方工具灰色地带；项目以 `--tool-cmd` 桥接本机已装的 wechat-cli 类工具，**只转格式不解密**）
- 不做常驻服务/Web 平台（交付形态为 CLI + Skill，用户可在任意电脑直接运行）
- 不做私聊采集（仅处理用户提供的工作群记录；企业使用需员工知情同意）

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  业务层  skill/scripts/chat_archive.py（2747 行，单一可执行脚本） │
│   员工统计 / 日报 / 讨论要点 / 跟进 / 考核 / 知识库 / 经营分析      │
│   每次运行 → out/<日期_时间>_<毫秒>/ 快照 + latest 固定入口        │
└───────────────┬─────────────────────────────────────────────┘
                │ 复用（脱敏规则引擎唯一来源）
┌───────────────▼─────────────────────────────────────────────┐
│  数据层  chat_archive/ 包（pip 可装，console_script: chat-archive）│
│   db.py          SQLite+FTS5 主库（幂等入库、WAL、索引）           │
│   pipeline/      clean(清洗) → desensitize(脱敏) → ingest(入库)  │
│   importers/     wechat_json.py(.json/.jsonl) + plain.py(TXT/MD/CSV) │
│   search.py      FTS5 全文 + LIKE 中文兜底                        │
│   stats.py / report.py / llm.py / vector.py                    │
└─────────────────────────────────────────────────────────────┘
```

**职责划分原则**：
- 数据层 = 确定性管道：格式解析 → 清洗 → 脱敏 → 幂等入库 → 检索/统计/周报/备份。可独立安装使用（`pip install .` 后 `chat-archive` 命令）。
- 业务层 = 面向业务语义的分析：员工识别/考核计分/知识库沉淀/经营分析，产出管理报表。每次运行独立快照、可重跑、不覆盖。
- 脱敏规则**唯一**定义在数据层 `pipeline/desensitize.py`，业务层 `mask_pii` 复用，杜绝双份规则漂移。

## 3. 数据流

```
输入(明文 TXT/MD/JSON/CSV 或加密备份+--tool-cmd 转换)
  → load_input → normalize_messages（业务层；QQ 两行式/GBK 回退/系统消息过滤）
  → 昵称歧义消解 → （可选 --mask-all 全链路脱敏）
  → [数据层可选] CLI import：清洗→脱敏→SQLite+FTS5（审计输出）
  → 业务全流程（统计/日报/讨论/跟进/知识库/考核/经营分析/审计…27 项产物）
  → out/<快照>/ + state/ 记忆层 + latest_report.html
```

**入库顺序固定**：清洗 → 脱敏 → 入库（库中不含明文 PII，`masked` 列记录命中）。

## 4. 模块职责表

| 模块 | 职责 | 关键不变量 |
|---|---|---|
| `cli.py` | 子命令路由（init/import/search/stats/report/weekly/vectorize/info/backup）+ 零参数全流程 | 全局 `--db`/`--json`/`--version`；backup 用 sqlite online backup |
| `db.py` | schema/连接/幂等写入/FTS rebuild + **版本化迁移** | msg_id=sha256[:16] 幂等；WAL + synchronous=NORMAL；FTS 显式探测降级报错；PRAGMA user_version + MIGRATIONS 逐级升级，旧库自动迁移、未来库拒绝打开 |
| `pipeline/clean.py` | 噪声判定（表情/灌水/占位符） | **不含**「在吗/在」（询单信号，与业务层口径一致） |
| `pipeline/desensitize.py` | PII 规则引擎（mask/generalize/redact + 审计） | 顺序敏感：redact 优先短路；规则唯一来源 |
| `pipeline/ingest.py` | 解析→清洗→脱敏→入库 编排 | 支持 .json/.jsonl/.txt/.md/.csv；幂等 |
| `importers/wechat_json.py` | 工具导出 JSON 字段探测 | time 解析失败 → None（不落脏串） |
| `importers/plain.py` | TXT/MD/CSV 行解析（QQ 两行式） | 与业务层正则同源 |
| `search.py` | FTS5 全文 + LIKE 中文兜底 | 用户输入转义防注入；命中 0 自动降级 |
| `stats.py` | 按发送者/日/类型/分类聚合 + 关键词频次 | 全表扫描（规模小，可接受） |
| `report.py` | 数据层周报（规则版 + LLM 版降级） | LLM 失败自动降级不阻塞 |
| `llm.py` | OpenAI 兼容 chat_completion | 环境变量优先于 config；无 Key 明确报错 |
| `vector.py` | 可选 Chroma 向量化 | 未装 chromadb → 友好 RuntimeError |
| 业务脚本 | 全部业务语义（见 §5）+ 快照完整性 manifest | 每步 try/except 收 errors，尾部统一报错 exit 1；运行末尾生成 manifest.json（产物 SHA256+运行参数），`verify` 子命令校验篡改/缺失/多余 |
| `sync_kb.py` | 知识库双通道同步（本地 + 腾讯 ima） | 仅上传脱敏产物；未配 Key 导出 ima_export |
| `render_html.py` | 业务快照 → 离线 HTML 看板 | 纯标准库，无网络
| `convert_wx.py` | wechat-cli/手工文本 → 标准 JSON | 编码自动检测（UTF-8/GBK/GB18030/latin-1）；直调测试覆盖 99% |

## 5. 业务层子流程（main 步骤）

1. 有效回复统计（防消极怠工）→ `effective_stats.csv/.md`
2. 员工日报（去口水）→ `daily_reports/<员工>_<日期>.md`
3. 讨论要点 + 待跟进（防事务架空；漏回复自动入跟进）→ `discussion_summary.md` / `followups.csv/.md`
4. 知识库（清洗脱敏）+ 训练清洗 + FAQ 草稿 → `knowledge/`（`kb-draft` 子命令仅跑此步）
5. 绩效考核（规则计分 + 证据化评语）→ `assessment.csv/.md` + `assessment_notes.md`
6-27. 活跃度/压缩文本/需求洞察/质检信号/行为指标/对话对/会话经营分析（SLA/满意度/健康分/SOP/漏斗/时间线）/审计（撤回/流水/媒体）/承诺复核/检索/@提及/消息表/HTML 看板/快照清理/latest 入口/记忆层/成长报告/环比报告

## 6. 关键设计决策（ADR 摘要）

| 决策 | 结论 | 理由 |
|---|---|---|
| DB 选型 | SQLite+FTS5（非 PostgreSQL） | 单机批量处理导出消息，无并发写；零部署 |
| 交付形态 | CLI + Skill（非 Web 项目） | 用户反复验证 Web 部署失败；Skill 零部署、更新=替换 1 文件 |
| LLM | 可选、失败降级规则版 | 不可让外部 API 阻塞本地交付 |
| 输入 | 明文优先，加密备份走 --tool-cmd 桥接 | 微信官方备份无法明文导出（已查证） |
| 隐私 | 默认知识库脱敏；--mask-all 全链路脱敏 | 内部管理看原文、交付第三方看脱敏，分层 |
| 快照 | 每次运行独立目录 + latest 固定入口 + 保留策略 + manifest.json SHA256 完整性 | 可追溯、可回滚、可环比、防篡改可审计 |
