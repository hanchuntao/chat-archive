# 测试与质量门（specs）

## 1. 测试金字塔

| 层 | 覆盖对象 | 位置 |
|---|---|---|
| 单元 | 数据层全部模块（db/clean/desensitize/ingest/importers/search/stats/report/llm/vector/cli） | tests/test_pipeline.py + tests/test_data_layer_full.py + tests/test_cli.py |
| 单元 | 业务层纯函数（员工语义/话题/知识库/考核/记忆/经营分析…） | tests/test_business_layer.py + tests/test_absorbed.py |
| 集成 | 业务层 main() 全子命令（subprocess 真实运行，断言产物存在与内容） | tests/test_business_main.py |
| 脚本 | sync_kb / convert_wx / render_html | tests/test_scripts.py |

## 2. 覆盖率门禁（CI 强制执行）

```bash
coverage run -m pytest tests/ -q
coverage report --omit='*/tests/*' --fail-under=95 -m
```

- 目标：**总覆盖率 ≥ 95%**（业务脚本 + 数据层 + 辅助脚本）
- CI（.github/workflows/ci.yml）：Python 3.10/3.11/3.12 矩阵，pytest 全绿 + coverage --fail-under=95 双重门禁

## 3. 三重路径交叉验证矩阵

每次发布前，对同一输入跑三条独立路径，结果必须一致：

| 路径 | 入口 | 验证点 |
|---|---|---|
| A. 数据层 CLI | `chat-archive --db X.db import/search/stats/report/info/backup` | 入库条数、检索命中、统计、周报、备份可打开 |
| B. 业务层 subprocess | `python3 skill/scripts/chat_archive.py all --input ... --staff all` | 27 项产物齐全、内容断言、快照/latest 正常 |
| C. 业务层纯函数 | pytest 直接调用模块函数 | 与 B 同输入同断言（内存态与文件态一致） |

补充验证：`--mask-all` 产物全链路无明文 PII/真名；`kb-draft` 只产知识库+FAQ；`--incremental` 锚点过滤。

## 4. 运行命令

```bash
python3 -m pytest tests/ -q                          # 全量测试
python3 -m coverage run -m pytest tests/ -q          # 覆盖率采集
python3 -m coverage report --omit='*/tests/*' -m     # 覆盖率报告
```

## 5. 已知限制

- 向量化（vector.py）依赖可选 chromadb：测试用 mock 覆盖逻辑，CI 不安装真实依赖
- LLM 提炼（llm.py/report.py/business AI 分支）：测试用 mock urlopen 覆盖成功与失败降级两条路径，CI 不联网
- 腾讯 ima 同步（sync_kb.py）：测试 mock HTTP；真实上传需用户 API Key（config 未配时导出 ima_export）
