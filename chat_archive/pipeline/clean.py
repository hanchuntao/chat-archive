"""清洗: 去噪、过滤无意义消息、类型归一。

判定为"无意义"的消息在导入时被剔除(不入库), 规则可配置:
  - 纯表情 / 纯符号 / 纯灌水词
  - 系统占位([图片]、[表情]、[动画表情] 等)
  - 超短且无实义(默认阈值 1 个字符)
"""

from __future__ import annotations

import re

# 常见灌水/无意义词(全角半角兼容), 命中即过滤
# 注意: 不包含 "在吗"/"在" —— 电商询单高频开场词, 属有效业务信息(丢单信号),
# 与业务层 classify/丢单检测口径保持一致; 单纯 "在" 由下方 token 规则按灌水处理。
_NOISE_WORDS = {
    "+1", "＋1", "1", "收到", "好的", "好", "ok", "okay", "嗯", "哦",
    "哈哈哈", "哈哈", "呵呵", "哈哈哈哈", "顶", "支持", "👍", "赞",
    "谢谢", "感谢", "辛苦", "晚安", "早安",
}

# 系统占位消息(微信导出常见)
_PLACEHOLDERS = {
    "[图片]", "[表情]", "[动画表情]", "[视频]", "[语音]", "[链接]",
    "[文件]", "[聊天记录]", "[小程序]", "[音乐]", "[转账]", "[红包]",
    "[位置]", "[名片]", "[系统消息]", "[提醒]",
}

_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2B00-\u2BFF]"
)
_SYMBOL_ONLY_RE = re.compile(r"^[\s~`!@#$%^&*()_+\-={}\[\]|\\:;\"'<>,.?/。，、；：？！…—·￥（）【】《》]+$")
_TOKEN_SPLIT_RE = re.compile(r"[\s,，。.;；:：!！?？、~～]+")


def is_noise(content: str, min_len: int = 1) -> bool:
    """判定消息是否无意义, 应被过滤。"""
    if content is None:
        return True
    s = content.strip()
    if not s:
        return True
    if s in _PLACEHOLDERS:
        return True
    if s.lower() in _NOISE_WORDS:
        return True
    if len(s) <= min_len and _SYMBOL_ONLY_RE.match(s):
        return True
    # 纯 emoji(去掉 emoji 后无文字)
    without_emoji = _EMOJI_RE.sub("", s)
    if without_emoji.strip() == "":
        return True
    # 全部 token 均为灌水词(如 "好的，收到"): 按标点/空白切分后逐 token 判定
    tokens = [t for t in _TOKEN_SPLIT_RE.split(s) if t]
    return bool(tokens and all(t.lower() in _NOISE_WORDS for t in tokens))


def clean_message(m: dict, drop_noise: bool = True) -> tuple[dict | None, str]:
    """返回 (清洗后消息 或 None(判定为噪声), 剔除原因)。"""
    content = (m.get("content") or "").strip()
    if drop_noise and is_noise(content):
        return None, "noise"
    m = dict(m)
    m["content"] = content
    return m, "ok"
