# chat-archive

**面向电商 / 生意场景**：群消息自动管理 —— 员工回复监控、客服绩效考核、知识库沉淀（训练 AI 客服 / 新员工培训）。

把 wechat-cli / WeFlow 导出的群聊记录（JSON/TXT/MD/CSV），经 **清洗 → 脱敏 → 入库** 沉淀为 SQLite+FTS5 主库，
产出**六类结果**（有效回复统计 / 员工日报 / 讨论要点 / 待跟进 / 知识库 / 考核评分）+ 一个 HTML 网页看板。
全程本地处理，不上传任何第三方云端。

> 📖 **完整用户手册**（Windows / Mac / 手机备份，从"导出明文"到"一键整理"分步图解）：[docs/用户手册.md](docs/用户手册.md)
> 🔧 **高级用法**（CLI 全表 / 20 段配置 / 输入格式 / 平台安装 / 打包分发 / 通知 / 知识库同步）：[docs/高级用法.md](docs/高级用法.md)

## 快速开始

**第 1 步 · 用自带样例先跑通**（30 秒；输出目录请用独立文件夹，**不要用 `./` 或项目根**）：

```bash
python3 /Users/chhan/work/chat-archive/skill/scripts/chat_archive.py all \
  --input sample_data/ecom_chat.txt --staff all --out /tmp/ca_demo
```

跑完后浏览器打开 `/tmp/ca_demo/report.html`——六类产物齐全（含知识库）。
员工名单一个参数三种写法：**`--staff all`**（全部发送人视为员工，员工群最常用）；`--staff "张三,李四"`（只统计这几个员工）；`--staff 名单.txt`（名单文件）。

**第 2 步 · 换成你自己的群记录**（只需改 `config.json` 的 `defaults`）：

```json
"defaults": {
  "input": "sample_data/ecom_chat.txt",
  "staff": "all",
  "out": "chat_archive_output"
}
```

把 `input` 改成你的群记录文件（相对路径基于项目根解析）；`staff` 三种写法见「员工名单」。

**第 3 步 · 一键出全部结果**（零参数 = 全流程）：

```bash
python3 /Users/chhan/work/chat-archive/chat-archive.py
# 已装成命令的话，直接敲：chat-archive
```

**第 4 步 · 看结果**（在 `out` 目录最新一份 `<日期_时间>_<毫秒>/` 中，每次运行一份，重跑不覆盖）：

| 文件 | 是什么 |
|---|---|
| `latest_report.html` | **最新看板固定入口**（永远指向最近一次运行，可收藏） |
| `latest.txt` | 最新结果目录的**完整绝对路径**（脚本读取用） |
| `report.html` | 本次结果目录里的汇总看板 |
| `effective_stats.csv`（+.md/.yml） | 谁在认真回复、谁消极怠工 |
| `daily_reports/` | 每个员工的工作日报（每人一份 Markdown） |
| `followups.csv`（+.md/.yml） | 待跟进事项（含漏回复/丢单风险标记） |
| `knowledge/` | 沉淀的知识库（脱敏，话题分类 .md + 训练集 + FAQ 草稿 + 培训手册） |
| `assessment.csv`（+.md/.yml） | 绩效考核 + 证据化评语（每条扣分引原文证据） |
| `manifest.json` | 本次运行快照（产物 SHA256），`verify` 校验完整性 |

**分析增强**（销售漏斗 / 需求洞察 / 关键词趋势 / 情感 / 成员画像 / SLA / 合规审计 / ChatLab 导出等 30+ 产物）：见 [docs/高级用法.md](docs/高级用法.md) 或直接看结果目录。

**第 5 步（可选）· 让结果更聪明**：在 `config.json` 的 `llm.api_key` 填你的 Key（DeepSeek 或任意 OpenAI 兼容服务），日报/要点/知识库自动走 AI 提炼。

> 出问题先看文末「常见问题」；仍不行把报错原样发出来。

## 架构

```
wechat-cli / WeFlow JSON
        │
        ▼
清洗(去噪/去重) → 脱敏(PII 掩码/泛化/剔除) → SQLite+FTS5 主库
        │                                        │
        │                        ┌───────────────┼────────────────┐
        ▼                        ▼               ▼                ▼
   纯本地数据             FTS5 全文检索      统计聚合(成员/日/    Markdown 周报
                        (时间/发送者/类型过滤) 类型/关键词)         /FAQ(规则或 LLM)
                                                                │
                                                      (可选) Chroma 语义检索
```

详细模块设计见 [docs/specs/architecture.md](docs/specs/architecture.md)。

## 员工名单（--staff，一个参数三种写法）

统计、日报、考核**只针对员工**：

| 写法 | 含义 | 示例 |
|---|---|---|
| `--staff all` | **全部发送人视为员工**（员工群/工作群，最常用） | `--staff all` |
| `--staff "张三,李四"` | 只要名单里的几个员工（群里混着客户时用） | `--staff "张三,李四"` |
| `--staff 名单.txt` | 名单文件，每行一个（`#` 开头为注释） | `--staff /path/名单.txt` |

- **名单文件支持别名**（微信昵称常改，改了不丢）：每行 `规范名|别名1|别名2`
- `config.json` 的 `defaults.staff` 同样支持这三种写法
- **不传 `--staff` 时**：默认所有发送人视为客户，结果无意义——AI 用法下会从上下文推断名单
- **知识库与名单的关系**：`--staff all`（员工群）时知识库**按话题聚合员工消息**；`--staff "张三,李四"`（群内混有客户）时为标准**问答对**（客户提问→员工回答）

## 漏回复检测（防丢单核心）

**"客户提问没人理"是最伤生意的场景**：客户消息（或任何带问句的消息）之后直到群末没有员工**实质回复**（"收到/好的/👍"等口水不算），即判为漏回复。

- 自动列入 `followups.md/csv`，看板跟进区红标「漏回复」
- 考核表新增「漏回复」列；配置 `assessment.duty` 值班员工后，超时与漏回复都扣到该员工头上
- 超时（实质回复间隔超 `timeout_sec`，默认 300 秒）归属扣分同样走 `duty`；**不配 duty 时只展示不扣分**

```json
"duty": { "电商客户群": "李四", "*": "张三" }
```

## 脱敏（默认全开，入库前执行）

手机号/身份证/银行卡/邮箱/微信号/IP/QQ 号自动打码，命中消息库中标记 `masked=1`，`import --audit` 看审计明细。
**顺序固定：清洗 → 脱敏 → 入库**，库中只存干净数据。完整规则见 [docs/specs/privacy.md](docs/specs/privacy.md)。

## LLM 提炼（可选）

**零第三方依赖**（标准库 `urllib` 实现）。在 `config.json` 的 `llm` 段配置，与其他配置同源、改一处全生效：

```json
{ "llm": { "api_key": "sk-xxx", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat" } }
```

- 未配置密钥时自动走规则模式；LLM 调用失败自动降级，不阻塞交付
- 环境变量 `CHAT_ARCHIVE_LLM_API_KEY/_BASE_URL/_MODEL` 优先于 config.json（临时换服务/密钥不落盘）
- 业务层 `all` 同样消费此配置：要点/日报/知识库自动走 AI 提炼，可用 `--llm` 强制、`--no-llm` 禁用
- **LLM 输入统一先过脱敏（PII 掩码），输出禁止还原个人信息**

## 合规说明

- 仅处理你作为群主有权管理、且成员知情的群聊记录；不外传、不公开、不商业化
- 脱敏在入库前完成，所有产物不含明文 PII
- 微信官方备份为私有加密格式，需先用 wechat-cli 类工具转出明文 JSON 再导入
- 数据全程本地：SQLite 主库 + Markdown + Chroma 均在本地磁盘

## Skill 挂载（多工具）

本仓库同时是 AI Skill 的源仓库。`skill/` 目录为标准 SKILL.md 结构（Agent Skills 开放规范），
通过符号链接挂载到各工具（同一份源，改一处全生效）：

| 工具 | 挂载路径 | 命令行可用 |
|---|---|---|
| 豆包 | `.doubaowork/agent_mode/workspace/.user_skills/chat-archive` | 否（对话触发） |
| Claude Code | 项目 `./.claude/skills/chat-archive` | **是** |
| Codex | `~/.codex/skills/chat-archive` | **是** |
| WorkBuddy | `~/.workbuddy/skills/chat-archive` | 否（对话触发） |
| DeepSeek | `~/.agents/skills/chat-archive`（GUI）+ `./.deepcode/skills/chat-archive`（IDE） | 否（对话触发） |

**命令行可用性说明**：能直接用的是 Claude Code（项目内）和 Codex（全局）；豆包/WorkBuddy/DeepSeek 桌面版没有 CLI，skill 只在各自对话里生效——想让它们在命令行干活，把 `base_url`+`api_key` 填进 `config.json` 的 `llm` 段即可（AI 提炼全走该模型）。无论哪种入口，产物一致。

`skill/SKILL.md` 是唯一源，改它即改所有工具行为。业务脚本 `skill/scripts/chat_archive.py` 复用 CLI 脱敏规则引擎，PII 规则全局唯一。

## AI Skills 用法（在豆包 / Claude / Codex / WorkBuddy / DeepSeek 里）

**用的时候不敲命令**——在任一已挂载工具的对话中直接用自然语言提需求，AI 会读取 `skill/SKILL.md` 并按工作流执行。

**三步触发**：
1. 把群记录文件/目录路径发给 AI（JSON / TXT/MD/CSV 均可，格式自动探测）
2. 说明员工名单（如"员工是张三、李四、王五"；不说也行，AI 会从上下文推断）
3. 说出要什么（**不说 = 默认全部结果**）：

| 你说 | AI 产出 |
|---|---|
| "统计群成员有效回复条数，谁在消极怠工" | 有效回复统计表（`effective_stats`） |
| "生成员工工作日报，去掉口水话" | 每人日报（`daily_reports/`） |
| "总结讨论要点和待跟进事项" | 要点 + 跟进清单（`discussion_summary` + `followups`） |
| "沉淀成公司知识库，要脱敏" | 脱敏知识库（`knowledge/` + 训练集 + 培训手册） |
| "按规则考核群成员" | 绩效评分表（`assessment`） |
| "全部做一遍" | 六类产物 + `report.html`，一份独立结果目录 |

产物落在 `--out` 目录（默认 `chat_archive_output/`），每次运行一份独立结果目录 `<日期_时间>_<毫秒>/`（重跑不覆盖）。

## 配置（config.json）

核心段示例（完整 20 段总览见 [docs/高级用法.md](docs/高级用法.md)）：

```json
{
  "defaults": { "input": "D:/weixin_data/XXXX.json", "staff": "张三,李四,王五", "out": "chat_archive_output" },
  "snapshot": { "keep": 30 },
  "llm": { "api_key": "", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat" },
  "knowledge": {
    "local": { "enabled": true, "dir": "knowledge", "vector": { "enabled": false, "backend": "chroma" } },
    "ima": { "enabled": false, "api_key": "", "client_id": "", "knowledge_base_name": "", "folder": "" }
  }
}
```

- `defaults.input`：**零参数模式的默认输入**；`defaults.staff`/`defaults.out` 可选
- `llm`：AI 提炼配置（`report --llm` 用）；`base_url`/`model` 可换任意 OpenAI 兼容服务
- `snapshot.keep`：`out/` 下保留最近 N 份结果目录（每次运行一份），超出自动清理；`0` = 永久保留
- `topics`：**知识库话题规则**，换成你的行业关键词（如安全/IT：漏洞、CVE、内推、面试…），不配置用内置电商话题
- `assessment`：**考核方案与合规规则**（基准分/超时扣分/违规扣分/口水阈值 + `rules` 违规话术清单），改这里即改考核制度
- `knowledge.local.dir`：可填 Obsidian vault 路径等任意绝对路径
- `knowledge.ima`：腾讯 ima 凭证，在 https://ima.qq.com/agent-interface 生成（**只放 `config.local.json`**）

> **密钥隔离**：`config.json` 会被 git 跟踪——不要把真实 `llm.api_key` 写进去。真实密钥放 `config.local.json`（已被 .gitignore 忽略），程序自动深合并覆盖。

## 常见问题

| 问题 | 解决 |
|---|---|
| `chat-archive: command not found` | 没装成全局命令。用全路径 `/Users/chhan/work/chat-archive/bin/chat-archive`、或 `python3 /Users/chhan/work/chat-archive/chat-archive.py`、或 `pip install -e .` 装一次 |
| 控制台中文乱码 | 先执行 `chcp 65001`（Windows）或 `set PYTHONUTF8=1` |
| 知识库为空 | 样例话题不匹配你的行业——改 `config.json` 的 `topics`；电商样例用 `sample_data/ecom_chat.txt` |
| 重跑会覆盖吗 | 不会。每次运行生成独立结果目录 `<日期_时间>_<毫秒>/`；`latest_report.html` 永远指向最新一次 |
| ima 上传失败 | 密钥放 `config.local.json`（gitignore）；无效 Key 会明确报错并返回退出码 1；未配 Key 时自动导出 `out/ima_export/` 供手动导入 |
| `--staff` 不传会怎样 | 默认全当客户，统计/日报/考核无意义；AI 用法下会从上下文推断名单 |
| Windows 打不开 report.html | 用浏览器直接双击打开即可，无需服务器；`echarts.min.js` 已随产物复制到同一目录，离线可看 |

## 质量与测试

- **352 项测试全绿**、覆盖率 97%（`--fail-under=95` 门禁）、ruff 0 告警 + mypy 通过（CI 强制）
- **真实链路实测**：LLM 提炼 / webhook/email 发送 / 腾讯 ima 上传 5/5 / PyInstaller 打包——均非模拟
- 详细质量报告见 [docs/质量报告.md](docs/质量报告.md)；演进历史见 [CHANGELOG.md](CHANGELOG.md)

## License

MIT License（见 [LICENSE](LICENSE)）。
