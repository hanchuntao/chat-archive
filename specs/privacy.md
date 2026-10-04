# 隐私与脱敏设计（specs）

## 1. 分层脱敏策略

| 层 | 默认行为 | 触发 |
|---|---|---|
| 数据层入库 | **必脱敏**：清洗→脱敏→入库，库中无明文 PII | `CLI import`（顺序固定，无法关闭） |
| 业务层知识库 | **默认脱敏**：knowledge/*.md、training.jsonl、onboarding.md、FAQ | `--no-mask` 关闭（谨慎，需用户明确要求） |
| 业务层内部管理报表 | 保留原文（统计/日报/跟进/考核，供内部管理） | — |
| 全链路脱敏 | PII 掩码 + 员工/客户匿名化，**所有产物**无明文身份 | `--mask-all`（交付第三方/严格隐私必开） |

## 2. 规则引擎（`chat_archive/pipeline/desensitize.py`，唯一来源）

- 策略：`mask`（打码）/ `generalize`（泛化为「已脱敏」）/ `redact`（整条丢弃）
- 默认规则：cn_mobile / cn_id_card(18) / cn_id_card15 / bank_card / email(保留域名) / wxid / ipv4 / qq(默认关闭防误伤)
- `Desensitizer.apply` → (content, hits, redacted)；redact 命中短路并整条剔除
- `import --audit` 输出命中明细；`masked` 列入库标记
- 业务层额外规则：订单号（`A1234567B` 样式）掩码

## 3. 不可变原则

1. **LLM 不参与脱敏主逻辑**——脱敏是确定性规则，可测试、可审计；LLM 输入已掩码，输出 prompt 禁止还原。
2. **匿名化确定性**：`mask_identity` 用 sha1(sender)[:6] → `员工/客户+3位数字`，同一发送人每次运行映射一致。
3. **训练集红线**：`clean_training` 对命中考核红线词（导流/返现/辱骂等）的样本优先过滤。
4. **知识库双通道只传脱敏产物**：`sync_kb.py` 只上传 knowledge/*.md + onboarding.md，训练 jsonl 不上传。

## 4. 合规红线

- 仅处理工作群消息，不采集私聊
- 企业使用需员工知情同意（考核/监控场景建议公示）
- 全链路脱敏产物可安全交付第三方（培训/AI 训练/外包）

## 5. 验证

- 脱敏规则与全链路行为有专项测试（tests/test_pipeline.py、tests/test_business_main.py 的 mask-all 路径）
- 端到端验证：`--mask-all` 产物 grep 不到明文手机号/身份证/真名（三重验证矩阵见 specs/testing.md）
