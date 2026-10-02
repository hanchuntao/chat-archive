---
name: chat-archive
description: 电商企业微信群/QQ群消息自动化管理与知识沉淀。当用户提供群聊天记录（微信/QQ 导出的 TXT/Markdown/JSON/CSV 明文文件，或微信加密备份文件），并要求：① 统计员工有效信息回复条数（识别消极怠工）、② 生成员工工作日报（去口水凑字数）、③ 总结讨论要点与待跟进事项（防事务架空）、④ 把有用信息清洗脱敏后沉淀为公司知识库（用于训练 AI 客服、员工入职培训）、⑤ 制定绩效考核制度用 AI 监督考核（监控群成员是否违反规则并评分），或要求全文检索群消息、生成群周报时使用。也适用于用户说“整理群聊天记录”“监控员工回复”“沉淀知识库”“考核客服”“搜一下群里说过的XX”等意图。
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

## 输出清单（`--out` 目录）

| 产物 | 对应需求 |
|---|---|
| `effective_stats.csv/.md` | 有效回复条数统计（防消极怠工） |
| `daily_reports/<员工>_<日期>.md` | 员工工作日报（已去口水） |
| `discussion_summary.md` | 讨论要点总结 |
| `followups.csv/.md` | 待跟进事项（防事务架空） |
| `knowledge/*.md` + `training.jsonl` + `onboarding.md` | 清洗脱敏后的知识库（AI 训练/入职培训） |
| `assessment.csv/.md` | AI 监督绩效考核评分 |
| `report.html` | 汇总以上全部产物的离线 HTML 看板（`all` 流程自动生成） |
| `out/<日期_时间>_<毫秒>/` | 每次运行的完整结果目录（一份，重跑不覆盖，保留策略见下） |

数据层（CLI）产物：SQLite+FTS5 主库（`archive.db`）、`search` 检索结果（JSON）、`report` 周报（Markdown）。

## 常见问题

- **“识别不出消息”**：检查文件是否为支持的格式（见 references）；TXT 需要“时间 发送人: 内容”行；QQ 消息管理器导出支持“时间 发送人(QQ号)+下一行内容”两行式。
- **员工被当成客户**：发送人显示名必须与 `--staff` 名单一致（支持昵称/ID/姓名）。
- **加密备份无法读取**：微信官方备份为私有加密格式，必须配置 `--tool-cmd` 指向本机 wechat-cli 类工具；未配置时脚本明确提示并跳过。
- **CLI 找不到模块**：CLI 入口是仓库根 `chat-archive.py`（自动定位包路径），不要用 `python3 -m chat_archive.cli`（依赖工作目录）。
- **结果保留**：`out/` 下默认保留最近 30 份结果目录（`config.json` 的 `snapshot.keep`，0=永久保留），或运行时加 `--keep-snapshots N` 覆盖。
- **知识库双通道**：`config.json` 的 `knowledge` 段控制产物去向——本地（默认 `out/knowledge/`）+ 腾讯 ima（可选）。ima 在 https://ima.qq.com/agent-interface 生成 API Key/Client ID 填入配置后，运行 `chat_archive.py kb-sync --out 目录` 自动上传脱敏 .md；未配 Key 时导出到 `out/ima_export/` 供手动导入。
