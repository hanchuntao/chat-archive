# 数据模型（specs）

## 0. Schema 版本管理

- 数据库以 `PRAGMA user_version` 记录 schema 版本（当前 **SCHEMA_VERSION=1**），`chat_archive/db.py` 的 `migrate()` 在打开连接时按 `MIGRATIONS` 逐级升级（事务内，失败回滚）。
- 旧版本代码创建的库（user_version=0）自动补齐建表并置为最新；版本高于程序支持时拒绝打开（提示升级程序）。
- 未来加列/建表：在 `MIGRATIONS` 追加新版本号与 SQL，老库自动迁移，**无需手工删库**。

## 1. SQLite 主库（数据层 `archive.db`）

```sql
chats (
  chat_id    TEXT PRIMARY KEY,   -- 群标识（文件推断或 --chat 指定）
  name       TEXT,               -- 群名（upsert 更新）
  first_time TEXT, last_time TEXT, msg_count INTEGER
)

messages (
  msg_id     TEXT PRIMARY KEY,   -- sha256(chat_id|sender|time|content)[:16]，幂等去重
  chat_id    TEXT NOT NULL,
  sender     TEXT,
  time       TEXT,               -- '%Y-%m-%d %H:%M:%S'（解析失败为 NULL）
  content    TEXT,               -- 脱敏后内容
  type       TEXT DEFAULT 'text',-- text/image/link/system/voice/video/file/emoji...
  category   TEXT,               -- 话题分类（业务层标注）
  tags       TEXT,
  raw_hash   TEXT,               -- 完整 sha256（审计用）
  masked     INTEGER DEFAULT 0,  -- 1 = 至少命中一次掩码/泛化
  created_at TEXT DEFAULT (datetime('now'))
)
索引: idx_messages_time / sender / type

messages_fts (FTS5 外部内容表, content='messages', content_rowid='rowid')
  -- 需手动 rebuild 同步；中文命中 0 时 search 自动降级 LIKE
```

写入顺序固定：**清洗 → 脱敏 → 入库**（`pipeline/ingest.py`），库中不含明文 PII。

## 2. 业务层产物清单（每次运行 → `out/<快照>/`）

| 产物 | 内容 | 对应需求 |
|---|---|---|
| effective_stats.csv/.md | 员工消息/有效/口水/口水率 | 防消极怠工 |
| daily_reports/<员工>_<日期>.md | 去口水日报 | 员工日报 |
| discussion_summary.md | 四分类讨论要点 | 讨论总结 |
| followups.csv/.md | 待跟进（类型：待跟进/漏回复/询价未回复/承诺待兑现/商机线索） | 防事务架空 |
| knowledge/*.md | 话题知识条目（脱敏 + frontmatter 7 类信息） | 知识沉淀 |
| knowledge/training.jsonl | AI 客服训练集（脱敏） | AI 训练 |
| knowledge/training_clean.jsonl | 训练集清洗（去重/红线/低质） | 训练质量 |
| knowledge/faq_drafts.md | 高频已解决问答 FAQ 草稿（人工复核后入库） | 客服速查 |
| knowledge/onboarding.md | 入职培训手册草稿 | 入职培训 |
| assessment.csv/.md | 考核评分（base100，超时/漏回/违规/口水扣分，有效回复加分） | AI 监督考核 |
| assessment_notes.md | 证据化评语（引原话+时间，Rating 留空主管填） | 考核可追溯 |
| activity.csv/.md | 话唠榜/活跃天数/高峰/熬夜冠军 | 群活跃度 |
| chat_compact.txt | 按时段压缩文本 | 快速浏览/LLM 预处理 |
| insight.md (+_llm.md) | 客户痛点 TopN + 证据 | 需求洞察 |
| insight_level.csv | 问题分级 P0-P3 | 优先级 |
| signal.csv/.md | 质检四信号 + confidence | 客服质检 |
| behavior.csv | 响应速度/问句占比 | 沟通量化 |
| dialogues.json | 客户问→员工答配对 | 对话分析 |
| sessions/pending/satisfaction/sla/health/sop_compliance/funnel/.csv(.md) | 会话经营分析 | 经营看板 |
| revoke_audit.csv / payment_ledger.csv / media_manifest.csv | 撤回/流水/媒体占位审计 | 审计 |
| commitment_review.csv | 承诺到期复核 | 闭环 |
| search.csv | 检索命中（--search/--search-bm25） | 检索 |
| mentions.csv/.md | @提及统计 | 关键对接人 |
| messages.csv | 扁平消息表（Excel 透视） | 导出 |
| report.html | 离线 HTML 看板 | 汇总 |
| trend.md | 周期环比 | 趋势 |
| state/（out 下） | history.json / profiles/*.md / memory.md / checklist.json / growth.md | 跨次记忆 |

## 3. 配置（config.json）与覆盖优先级

命令行参数 > config.json；LLM 配置：环境变量 > config.json。
员工名单三种写法：`all`（全员员工）/ `张三,李四`（名单）/ 文件路径（每行一个，支持 `规范名|别名`）。
