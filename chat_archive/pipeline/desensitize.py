"""脱敏: 规则引擎, PII 掩码 / 泛化 / 整条丢弃, 带审计。

设计原则:
  1. 规则为主(确定性, 可测试可审计), LLM 不做脱敏主逻辑
  2. 每个规则返回替换次数, 调用方累计审计
  3. 支持策略: mask(打码) / generalize(泛化) / redact(丢弃整条)
  4. 命中 redact 的消息由上层从入库链路剔除
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# ---- 规则定义 ----

def _mask_default(m: re.Match) -> str:
    s = m.group(0)
    if len(s) <= 7:  # 短值整体打码
        return s[0] + "*" * max(1, len(s) - 2) + (s[-1] if len(s) > 1 else "")
    return s[:3] + "*" * max(3, len(s) - 7) + s[-4:]


def _mask_email(m: re.Match) -> str:
    """邮箱: 本地部分打码, 保留 @ 与域名。"""
    s = m.group(0)
    if "@" in s:
        local, domain = s.split("@", 1)
        if len(local) <= 1:
            return f"{local}@{domain}"
        return f"{local[0]}{'*' * max(1, len(local) - 1)}@{domain}"
    return _mask_default(m)


@dataclass
class Rule:
    name: str
    pattern: str
    strategy: str = "mask"  # mask | generalize | redact
    enabled: bool = True
    replacer: Callable[[re.Match], str] | None = None
    _re: re.Pattern = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._re = re.compile(self.pattern)

    def apply(self, text: str) -> tuple[str, int]:
        """返回 (处理后文本, 命中次数)。"""
        if not self.enabled:
            return text, 0

        if self.strategy == "mask":
            replacer = self.replacer or _mask_default
            new_text, n = self._re.subn(replacer, text)
            return new_text, n
        if self.strategy == "generalize":
            new_text, n = self._re.subn("[已脱敏]", text)
            return new_text, n
        if self.strategy == "redact":
            return "[敏感内容已删除]", len(self._re.findall(text))
        return text, 0


# 中国大陆 PII 规则(默认全开)
DEFAULT_RULES: list[Rule] = [
    Rule("cn_mobile", r"(?<!\d)(1[3-9]\d{9})(?!\d)"),                 # 手机号
    Rule("cn_id_card", r"(?<!\d)(\d{17}[\dXx])(?!\d)"),               # 身份证
    Rule("bank_card", r"(?<!\d)(\d{16,19})(?!\d)"),                   # 银行卡
    Rule("email", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
         replacer=_mask_email),                                       # 邮箱: 保留域名
    Rule("wxid", r"(?<![\w])(wxid_[A-Za-z0-9_\-]{6,})(?![\w])"),      # 微信号
    Rule("ipv4", r"(?<!\d)((?:\d{1,3}\.){3}\d{1,3})(?!\d)"),          # IP
    Rule("qq", r"(?<!\d)([1-9]\d{5,10})(?!\d)", enabled=False),       # QQ(易误伤, 默认关)
]


@dataclass
class DesensitizeResult:
    content: str
    hits: dict[str, int] = field(default_factory=dict)  # rule -> 命中次数
    redacted: bool = False


class Desensitizer:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules if rules is not None else DEFAULT_RULES

    def apply(self, text: str) -> DesensitizeResult:
        out = text
        hits: dict[str, int] = {}
        redacted = False
        for r in self.rules:
            if r.strategy == "redact" and r._re.search(out):
                redacted = True
                hits[r.name] = len(r._re.findall(out))
                out = "[敏感内容已删除]"
                break
            out, n = r.apply(out)
            if n:
                hits[r.name] = n
        return DesensitizeResult(content=out, hits=hits, redacted=redacted)

    def audit_summary(self, result: DesensitizeResult) -> str:
        if not result.hits:
            return "无命中"
        parts = ", ".join(f"{k}×{v}" for k, v in sorted(result.hits.items()))
        return f"命中 {parts}"


def load_rules_from_dict(cfg: dict | None) -> list[Rule]:
    """从配置加载规则(格式: [{name, pattern, strategy, enabled}]), 未命中则用默认。"""
    if not cfg:
        return DEFAULT_RULES
    rules: list[Rule] = []
    for item in cfg:
        rules.append(
            Rule(
                name=item.get("name", "custom"),
                pattern=item["pattern"],
                strategy=item.get("strategy", "mask"),
                enabled=item.get("enabled", True),
            )
        )
    return rules
