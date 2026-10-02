# chat-archive

微信群聊消息过滤归档工具（纯本地）。把 wechat-cli / WeFlow 导出的群聊 JSON，
经 **清洗 → 脱敏 → 入库** 沉淀为 SQLite+FTS5 主库，支持全文检索、统计聚合、
Markdown 周报/FAQ 生成，可选用 LLM 提炼与本地 Chroma 语义检索。

数据全程本地处理，不上传任何第三方云端。

## 5 分钟上手（先看这个）

把群聊记录变成「有效回复统计 / 员工日报 / 讨论要点 / 待跟进 / 知识库 / 考核评分」六类结果，外加一个网页看板。

**第 1 步 · 用自带样例先跑通**（30 秒，不用改任何文件；输出目录请用独立文件夹，**不要用 `./` 或项目根**，避免产物混进仓库）：

```bash
python3 /Users/chhan/work/chat-archive/skill/scripts/chat_archive.py all \
  --input sample_data/ecom_chat.txt --staff all --out /tmp/ca_demo
```

跑完后浏览器打开 `/tmp/ca_demo/report.html` 看效果——六类产物齐全（含知识库）。
员工名单一个参数三种写法：**`--staff all`**（全部发送人视为员工，员工群最常用）；`--staff "张三,李四"`（只统计/日报/考核这几个员工）；`--staff 名单.txt`（名单放文件，每行一个）。
（`sample_data/sample_chat.json` 是安全内推群样例，不含电商话题，跑出来知识库为空属正常；`ecom_chat.txt` 是电商客服群样例，知识库有内容。）

**第 2 步 · 换成你自己的群记录**（只需改 1 个文件；**默认已填好样例配置，拿到即可直接跑第 3 步**）：

打开 `config.json`，看 `defaults`（**当前已填好样例配置，可直接跑第 3 步**）：

```json
"defaults": {
  "input": "sample_data/ecom_chat.txt",
  "staff": "all",
  "out": "chat_archive_output"
}
```

跑通后换成你自己的群记录，只需改 `input`（相对路径基于项目根解析，从任意目录运行都能找到）；`staff` 三种写法见下文「员工名单」专节。

**第 3 步 · 一键出全部结果**（零参数 = 全流程）：

```bash
python3 /Users/chhan/work/chat-archive/chat-archive.py
```

（如果已把项目装成命令，直接敲 `chat-archive` 即可）

**第 4 步 · 看结果**（在 `out` 目录里最新一份 `<日期_时间>_<毫秒>/` 中；每次运行一份，重跑不覆盖）：

| 文件 | 是什么 |
|---|---|
| `latest_report.html` | **最新看板固定入口**（永远指向最近一次运行，浏览器可收藏，路径不变） |
| `report.html` | 本次结果目录里的汇总看板 |
| `effective_stats.md` | 谁在认真回复、谁消极怠工 |
| `daily_reports/` | 每个员工的工作日报 |
| `followups.md` | 待跟进事项 |
| `knowledge/` | 沉淀的知识库（脱敏） |
| `assessment.md` | 绩效考核评分 |

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

## 快速开始

```bash
# 0. 环境: Python 3.10+（macOS 官方包 / Homebrew 自带 FTS5）
#    本 README 命令中的 /Users/chhan/work/chat-archive 是你的项目路径，
#    换机器/目录时整体替换成你的路径即可。

# 方式 0（一键全流程，推荐）：零参数 = 全部结果
#    config.json 的 defaults 已填好样例配置（sample_data/ecom_chat.txt / staff all），直接跑：
python3 /Users/chhan/work/chat-archive/chat-archive.py
#    结果在 chat_archive_output/<日期_时间>_<毫秒>/，浏览器打开 report.html 查看。

# 方式 A（任意目录可用，无需安装，数据层命令）：
python3 /Users/chhan/work/chat-archive/chat-archive.py import sample_data/sample_chat.json

# 方式 B（无需安装、无需 PATH，直接运行 bin 包装即可）：
/Users/chhan/work/chat-archive/bin/chat-archive import sample_data/sample_chat.json
# 想敲更短的 chat-archive？把 bin 目录加进 PATH 一次即可（可选）：
#   export PATH="/Users/chhan/work/chat-archive/bin:$PATH"                      # 当前终端生效
#   echo 'export PATH="/Users/chhan/work/chat-archive/bin:$PATH"' >> ~/.zshrc   # 永久生效

# 方式 C（macOS/Linux 直接用 bin 包装，无需安装）：
/Users/chhan/work/chat-archive/bin/chat-archive
```

```bash
# 全文检索（需先 import 过数据；未装短命令时把 chat-archive 换成 python3 /Users/chhan/work/chat-archive/chat-archive.py）
chat-archive search "内推" --sender 王五 --limit 10

# 统计
chat-archive stats --group sender
chat-archive stats --group day
chat-archive stats --keywords 内推 岗位

# 生成周报（规则模式，无需任何密钥）
chat-archive report --start 2026-09-01 --end 2026-09-30 -o report.md

# 数据库概览
chat-archive info

# 测试
python3 -m pytest tests/ -q
```

## 项目结构（使用者视角）

| 类型 | 目录/文件 | 说明 |
|---|---|---|
| **你要用的** | `chat-archive.py` + `bin/` | 命令行入口。`bin/chat-archive` 是 3 行 bash 包装（转发到 `chat-archive.py`），加 PATH 即可当命令用；也可直接 `python3 <仓库根>/chat-archive.py` |
| | `config.json` | 唯一需要改的配置文件（defaults / llm / knowledge / snapshot） |
| | `skill/` | AI Skill（SKILL.md + scripts 业务层），已符号链接挂到各工具，日常不用动 |
| **参考用** | `README.md`、`sample_data/`、`tests/` | 文档、样例数据、测试 |
| **不用管** | `chat_archive/`（核心代码包）、`pyproject.toml`、`requirements.txt` | 内部实现与打包声明，不接触也能正常用 |
| | `chat_archive.egg-info/` | `pip install -e .` 自动生成的安装元数据，只给 pip 看，删了会再生成 |
| | `.claude/`、`.deepcode/`、`.idea/`、`.pytest_cache/` | 工具配置与缓存，无关紧要 |

**最快上手**：改 `config.json` 的 `defaults.input` → 终端跑 `chat-archive`（零参数全流程）→ 产物在 `defaults.out`。

### bin/chat-archive 是怎么做的

它不是安装工具生成的，是一个**手写的 4 行脚本**，把调用转发给 `chat-archive.py`：

```bash
#!/usr/bin/env bash
# chat-archive 命令包装（macOS/Linux）。Windows 用 bin/chat-archive.cmd。
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$DIR/chat-archive.py" "$@"
```

原理：`$0` 是脚本自身路径 → `dirname` 取 `bin/` 目录 → 上一级就是项目根 → 用 `python3` 执行项目根的
`chat-archive.py`，命令行参数 `"$@"` 原样透传。所以它**不需要安装、不依赖 PATH、从任何目录都能跑**；
`/Users/chhan/work/chat-archive/bin/chat-archive` 和短命令 `chat-archive` 效果完全一样。

**自己做一个**：把这 4 行存成任意文件（如 `~/bin/ca`），`chmod +x ~/bin/ca`，以后就能用 `~/bin/ca` 当命令。
Windows 对应文件是 `bin/chat-archive.cmd`（批处理，开头 `chcp 65001 >nul` 防中文乱码），原理相同。

## Windows 使用

核心代码是纯标准库（SQLite/FTS5 均为 Python 自带），Windows 可直接用：

```bat
:: 方式 1（推荐）：安装为全局命令（生成 chat-archive.exe，任意目录可用）
py -m pip install -e C:\Users\HP\work\chat-archive
chat-archive info

:: 方式 2：不安装，直接跑入口脚本（任意目录）
python C:\Users\HP\work\chat-archive\chat-archive.py

:: 方式 3：用批处理包装（把 bin 目录加进 PATH）
set PATH=C:\Users\HP\work\chat-archive\bin;%PATH%
chat-archive
```

**Windows 注意事项**：
- `bin/chat-archive`（bash 脚本）仅 macOS/Linux 可用；Windows 用同目录的 `bin/chat-archive.cmd`。
- 控制台中文乱码时，先执行 `chcp 65001` 或 `set PYTHONUTF8=1` 再运行。
- `config.json` 里的路径用正斜杠：`"input": "D:/weixin_data/xxxx.json"`。
- 可选依赖：LLM 提炼 `pip install requests`；本地向量检索 `pip install chromadb`。
- 加密备份转换（`--tool-cmd`）在 Windows 上需指向 `wechat-cli.exe` 类工具，命令用双引号包裹参数。

## 输入格式

兼容 wechat-cli / WeFlow / wx-cli 导出的 JSON（字段自动探测）：

- 顶层：`{"messages": [...]}` / `{"messageList": [...]}` / 裸数组
- 消息字段：`content/text/msg` + `senderDisplayName/sender/nickname` + `formattedTime/time/timestamp`
- 支持时间字符串与 unix 秒/毫秒；消息类型自动归一化

## CLI 一览

| 命令 | 作用 |
|---|---|
| *（零参数）* | **全流程**：读 `config.json` 的 `defaults`（input/staff/out）→ 业务层全部结果 |
| `init` | 初始化数据库 |
| `import <file...>` | 导入（清洗+脱敏+入库，幂等可重跑），`--audit` 看脱敏审计 |
| `search <关键词>` | FTS5 全文检索；`--from/--to/--sender/--type/--limit` |
| `stats` | 聚合统计：`--group sender/day/type/category`，`--keywords` 频次 |
| `report` | 生成 Markdown 周报/FAQ；`--llm` 强制 AI 提炼 |
| `vectorize` | （可选）灌入本地 Chroma 语义检索 |
| `info` | 数据库概览（会话/消息数/时间范围） |

所有命令支持 `--json` 输出，便于 skill / 脚本调用。

## 员工名单（--staff，一个参数三种写法）

统计、日报、考核**只针对员工**，用 `--staff` 指定，自动识别三种写法：

| 写法 | 含义 | 示例 |
|---|---|---|
| `--staff all` | **全部发送人视为员工**（员工群/工作群，最常用） | `--staff all` |
| `--staff "张三,李四"` | 只要名单里的几个员工（群里混着客户时用） | `--staff "张三,李四"` |
| `--staff 名单.txt` | 名单文件，每行一个（`#` 开头为注释） | `--staff /path/名单.txt` |

- 识别规则：值为 `all` → 全员；值为**存在的文件路径** → 读文件当名单；否则按逗号/顿号/空格拆分
- `config.json` 的 `defaults.staff` 同样支持这三种写法（如 `"staff": "all"`）
- **不传 `--staff` 时**：默认所有发送人视为客户，统计/日报/考核结果无意义——AI 用法下会优先从上下文推断名单，推断不出直接跑并提示你补名单重跑
- 旧参数 `--all-staff`（等同 `--staff all`）、`--staff-file`（等同 `--staff 文件路径`）仍可用
- **知识库与名单的关系**：`--staff all`（员工群）时没有"客户问→员工答"配对，知识库自动退化为**按话题聚合员工消息**；`--staff "张三,李四"`（群内混有客户）时知识库为标准的**问答对**（客户提问→员工回答）

## 脱敏（默认全开，入库前执行）

| 规则 | 覆盖 | 策略 |
|---|---|---|
| `cn_mobile` | 中国大陆手机号 | 打码 `138****5678` |
| `cn_id_card` | 18 位身份证 | 打码 |
| `bank_card` | 16-19 位银行卡 | 打码 |
| `email` | 邮箱 | 本地部分打码，保留域名 |
| `wxid` | 微信号 | 打码 |
| `ipv4` | IP 地址 | 打码 |
| `qq` | QQ 号（默认关闭，易误伤） | 打码 |

- 命中掩码的消息在库中标记 `masked=1`，`import --audit` 可输出审计明细
- 规则可编程扩展（`pipeline/desensitize.py` 的 `DEFAULT_RULES`）
- **顺序固定：清洗 → 脱敏 → 入库**，库中只存干净数据

## LLM 提炼（可选）

**零第三方依赖**（标准库 `urllib` 实现，不需要 pip 装任何包）。在 `config.json` 的 `llm` 段配置（与其他配置同源，改一处全生效）：

```json
{ "llm": { "api_key": "sk-xxx", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat" } }
```

```bash
chat-archive report --llm -o weekly.md
```

未配置密钥时自动走规则模式；LLM 调用失败自动降级，不阻塞交付。
兼容：环境变量 `CHAT_ARCHIVE_LLM_API_KEY/_BASE_URL/_MODEL` 仍可用且**优先于** config.json（适合临时换服务/密钥不落盘场景）。

**业务层（`all` 全流程）同样消费此配置**：配置了 `llm.api_key` 后，讨论要点/员工日报/知识库自动走 AI 提炼（规则版作为降级兜底）；未配置则全部为规则版。可用 `--llm` 强制、`--no-llm` 禁用。LLM 输入统一先过脱敏（PII 掩码），输出禁止还原个人信息。

## Chroma 语义检索（可选）

```bash
pip install chromadb
chat-archive vectorize --persist-dir ./chroma_data
```

## 与业务 Skill 的对接

本工具是**数据层**（通用管道）；业务分析（员工考核、日报、跟进事项等）
放在你的业务 Skill 里调用本 CLI：

```bash
# skill 中典型调用, --json 输出便于解析
chat-archive search "待跟进" --json
chat-archive stats --group sender --json
chat-archive report --start 2026-09-01 --end 2026-09-07 -o weekly.md
```

## 合规说明

- 仅处理你作为群主有权管理、且成员知情的群聊记录；不外传、不公开、不商业化
- 脱敏在入库前完成，所有产物不含明文 PII
- 微信官方备份为私有加密格式，需先用 wechat-cli 类工具转出明文 JSON 再导入
- 数据全程本地：SQLite 主库 + Markdown + Chroma 均在本地磁盘


## Skill 挂载（多工具）

本仓库同时是 AI Skill 的源仓库。`skill/` 目录为标准 SKILL.md 结构（Agent Skills 开放规范），
通过符号链接挂载到各工具（同一份源，改一处全生效）：

| 工具 | 挂载路径 | 命令行可用 | 说明 |
|---|---|---|---|
| 豆包 | 豆包应用数据目录 `.doubaowork/agent_mode/workspace/.user_skills/chat-archive` | 否（无 CLI） | 仅在豆包对话里触发 |
| Claude Code | 项目 `./.claude/skills/chat-archive` | **是**（`claude` 命令） | 在项目目录打开终端即可用 |
| Codex | `~/.codex/skills/chat-archive` | **是**（`codex` 命令） | 全局，任意目录终端可用 |
| WorkBuddy | `~/.workbuddy/skills/chat-archive` | 否（无 CLI） | 仅在 WorkBuddy 对话里触发 |
| DeepSeek | `~/.agents/skills/chat-archive`（GUI） + 项目 `./.deepcode/skills/chat-archive`（IDE） | 否（无 CLI） | GUI/IDE 里触发；**命令行用 DeepSeek 模型 → 配 `config.json` 的 `llm` 段（OpenAI 兼容 API）**，无需 DeepSeek 命令 |

**命令行可用性说明**：
- **能直接用**（终端）：Claude Code（项目内 `.claude/skills`）、Codex（全局 `~/.codex/skills`）——打开终端说"读取 <路径>，用 chat-archive 生成结果"即触发。
- **不能直接用**（无 CLI）：豆包 / WorkBuddy / DeepSeek 桌面版——skill 只在各自应用对话里生效；它们在命令行没有入口，这是工具本身没有 CLI，不是挂载问题。DeepSeek 想在命令行获得其模型能力，把它的 `base_url`+`api_key` 填进 `config.json` 的 `llm` 段即可（`chat-archive` 的 AI 提炼全部走该模型）。
- 无论哪种入口，产物一致（见"AI Skills 用法"）。

`skill/SKILL.md` 是唯一源，改它即改所有工具行为。业务脚本
`skill/scripts/chat_archive.py`（员工统计/日报/跟进/考核/知识库）复用 CLI 脱敏规则引擎
（`chat_archive.pipeline.desensitize`），PII 规则全局唯一。

`skill/scripts/chat_archive.py all` 还会自动生成 `report.html`——把 6 类产物合并成一个离线可打开的 HTML 看板。

## AI Skills 用法（在豆包 / Claude / Codex / WorkBuddy / DeepSeek 里）

这套能力以标准 Agent Skills 形式挂载到各工具（见上表）。**用的时候不敲命令**——
在任一已挂载工具的对话中直接用自然语言提需求，AI 会读取 `skill/SKILL.md` 并按工作流执行。

**三步触发**：
1. 把群记录文件/目录路径发给 AI（wechat-cli / WeFlow JSON、TXT/MD/CSV、加密备份均可，格式自动探测）
2. 说明员工名单（如"员工是张三、李四、王五"；不说也行，AI 会从上下文推断，产物照常出）
3. 说出要什么（**不说 = 默认全部结果**）：

| 你说 | AI 产出 |
|---|---|
| "统计群成员有效回复条数，谁在消极怠工" | 有效回复统计表（`effective_stats`） |
| "生成员工工作日报，去掉口水话" | 每人日报（`daily_reports/`） |
| "总结讨论要点和待跟进事项" | 要点 + 跟进清单（`discussion_summary` + `followups`） |
| "沉淀成公司知识库，要脱敏" | 脱敏知识库（`knowledge/` + 训练集 + 培训手册） |
| "按规则考核群成员" | 绩效评分表（`assessment`） |
| "搜一下群里说过的『内推』" | 数据层全文检索结果 |
| "全部做一遍" | 六类产物 + `report.html`，一份独立结果目录 |

**AI 执行的工作流**（SKILL.md）：解析输入 → 与你确认员工名单 →（可选）数据层 CLI 入库/检索 → 业务层脚本出六类产物 → 汇报要点 + 把知识库草稿精修为正式文档。产物落在 `--out` 目录（默认 `chat_archive_output/`），每次运行生成一份独立结果目录 `<日期_时间>_<毫秒>/`（重跑不覆盖）。

> 脚本细节（子命令/参数）供 AI 与高级用户参考，见 `skill/SKILL.md`，无需手工记忆。

## 配置（config.json）

仓库根 `config.json` 跟随仓库走、改一处全生效：

```json
{
  "defaults": {
    "input": "D:/weixin_data/XXXX.json",
    "staff": "张三,李四,王五",
    "out": "chat_archive_output"
  },
  "snapshot": { "keep": 30 },
  "llm": { "api_key": "", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat" },
  "knowledge": {
    "local": {
      "enabled": true,
      "dir": "knowledge",
      "vector": { "enabled": false, "backend": "chroma" }
    },
    "ima": {
      "enabled": false,
      "api_key": "",
      "client_id": "",
      "knowledge_base_name": "",
      "folder": ""
    }
  }
}
```

- `defaults.input`：**零参数模式的默认输入**（CLI 直接运行 `chat-archive` 或 AI 一句话触发时使用）；`defaults.staff`/`defaults.out` 可选，不填则显式传参或使用默认输出目录。
- `llm`：AI 提炼配置（`report --llm` 用）；`base_url`/`model` 可换任意 OpenAI 兼容服务。
- `snapshot.keep`：`out/` 下保留最近 N 份结果目录（每次运行一份），超出自动清理；`0` = 永久保留。运行时可用 `--keep-snapshots N` 临时覆盖。
- `topics`：**知识库话题规则**，换成你的行业关键词（如安全/IT：漏洞、CVE、内推、面试…），改这里不用改代码；不配置时用内置电商话题
- `latest`：每次运行后自动更新 `out/latest_report.html`（最新看板固定入口）+ `out/latest.txt`（最新结果目录名），路径固定可收藏
- `knowledge.local.dir`：本地知识库目录，**可填 Obsidian vault 路径等任意绝对路径**（见下节）。
- `knowledge.ima`：腾讯 ima 凭证，在 https://ima.qq.com/agent-interface 生成。

## 知识库同步（kb-sync）

产物（脱敏后的 `knowledge/`）支持双通道消费，由 `config.json` 的 `knowledge` 段控制：

`knowledge` 段分两条并列通道：**local（本地）** 与 **ima（云端）**；本地内部的向量检索是 local 的子选项。

| 通道 | 配置 | 行为 |
|---|---|---|
| 本地 | `knowledge.local.enabled`（默认 true，`dir: knowledge`） | 产物就在 `out/knowledge/`，`dir` 可改绝对路径 |
| 本地·向量（子选项） | `knowledge.local.vector.enabled`（需 `pip install chromadb`） | 开启后由 CLI `vectorize` 建本地语义检索库 |
| 腾讯 ima | `knowledge.ima.enabled` + `api_key` + `client_id` | 自动上传脱敏 .md 到指定知识库；未配 Key 时导出 `out/ima_export/` 供手动导入 |

```bash
# 一键同步（按配置）
python3 skill/scripts/chat_archive.py kb-sync --out 输出目录
# 只同步本地 / 只同步 ima
python3 skill/scripts/chat_archive.py kb-sync --out 输出目录 --to local
```

ima 凭证在 https://ima.qq.com/agent-interface 生成（API Key 只显示一次）。上传只发**已脱敏**的 Markdown 知识条目，原始消息与训练集不上云。

## 本地知识库怎么消费（选型）

产物是**标准 Markdown**，谁都能吃。推荐分工：**产（本管道）→ 看（Obsidian）→ 问（RAG / ima）**。

| 用途 | 推荐 | 用法 |
|---|---|---|
| 人读、管理知识库 | **Obsidian** | 把 `knowledge.local.dir` 指到 vault 路径（如 `~/Documents/知识库/群聊沉淀`），`kb-sync` 后产物自动出现在库里，双链/图谱/插件照用 |
| AI 问答（轻量） | **内置 RAG** | `knowledge.local.vector.enabled: true` + `pip install chromadb`，CLI `vectorize` 建本地语义库 |
| AI 问答（重型） | Dify / AnythingLLM / RAGFlow | 直接导入 `knowledge/` 的 Markdown 建库，无需改造 |
| 云端问答 | 腾讯 ima | 配好 `knowledge.ima` 后自动上传脱敏条目 |
| 加密多端同步笔记（备选） | Joplin | 自带数据库与导入流程，适合私人笔记场景；不直接吃外部目录，仅备选 |

```bash
# 例：产物同步进 Obsidian vault
python3 skill/scripts/chat_archive.py kb-sync --out 输出目录 --to local
# 之后在 Obsidian 打开 vault 即可看到当天沉淀的知识条目
```
