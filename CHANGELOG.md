# Changelog

本文件记录 chat-archive 的功能演进历史（能力维度，不含日常 bug 修复明细；完整提交历史见 `git log`）。

## 2026-10-08 · v2.0.x — ima 真实链路打通

- 腾讯 ima 知识库真实 API 上传 5/5 成功，知识库侧 content_count 实时增加
- 修复：search/addable 字段不一致兼容（kb_id/kb_name vs id/name）；COS 标准域名签名 + token 签入（custom_domain 实测 403）；签名窗口用凭证 start_time;expired_time；错误透传 HTTP 响应体
- 幂等：同批次重跑内容未变文件自动跳过（SHA256 state，ima 无去重 API）
- 安全：真实密钥只放 `config.local.json`（gitignore）；测试/CI 用 `CHAT_ARCHIVE_IGNORE_LOCAL_CONFIG=1` 隔离

## 2026-10-04 · v2.0 — 生产就绪

- 静态门禁：ruff 1576→0 + mypy 通过（CI 强制）
- 真实链路：LLM 提炼（本地 mock OpenAI 17 次请求验证鉴权/脱敏提示词）；webhook/email 发送（本地双接收端实测，Webhook 200/40 事件）
- watch 4 分钟压测内存 1.00x 无泄漏 + 优雅退出（SIGINT/SIGTERM）
- mcp --db 增量库幂等（591 插入→0 插入 606 跳过）；JSON-RPC + REST API
- PyInstaller 真打包 23MB onedir 全套冒烟
- kb-sync/ima 链路闭环（local 就地/复制、ima 未配 Key 降级导出）
- Windows 静态兼容审计（显式 UTF-8 / 控制台重配置 / 子进程编码）

## 第 8 轮 — 能力吸收（P0+P1）

- report 交互化：ca-data + 全局搜索高亮 + 表格排序 + ECharts 日历热图/桑基图/关系图 + 消息回放时间线
- Webhook/邮件主动触达；多群月报 + 员工排名
- DISCLAIMER/THANKS 合规文档；SQLite PRAGMA 加固（WAL/busy_timeout）
- PyInstaller 打包 + CI 门禁；MCP Server（JSON-RPC + 本地问答检索）
- 双人对话报告 `pair`；防撤回位（recalled 列）；知识库第 8 类（公众号文章）
- 周×小时活跃热图 + 词汇离散度 TTR/HHI；客户画像聚合（漏回复 SOP 提醒）；FTS5 BM25 排序优化

## 第 8 轮 — 能力吸收（P2）

- CSV 产物 YAML 伴生版；ChatLab 标准 JSONL 导出；`--active-days` 活跃窗口
- 行业规则包（config.industry）；知识库质量评分（quality_scores.csv）；report 高频词云模块
- `watch` 守护（mtime 变化自动重跑）；pair 双向平均回复延迟
- MCP Server REST API（/api/health、/api/search、/api/stats、/api/keywords）；version.json 格式适配表

## 第 5 轮 — 质量工程

- db schema 版本化迁移（PRAGMA user_version，旧库自动升级、未来库拒绝）
- 每次运行生成 `manifest.json`（产物 SHA256 + 运行参数），`verify` 子命令校验快照完整性
- 知识库条目级去重（相同问答不重复入库）

## 更早（第 1–4 轮）

记忆层、昵称消歧、四分类摘要、证据化考核、群活跃度、丢单/商机信号、需求洞察、日报升级、客服质检信号、知识库 8 类、增量导入、@提及统计、扁平消息表导出、消息类型/互动/关键词趋势/媒体归档等分析产物——详见 `git log`。
