"""LLM 提炼(可选): OpenAI 兼容 API, 默认 DeepSeek。

不配置密钥时, report 命令走规则聚合; 配置后生成 AI 提炼周报/FAQ。
配置来源（环境变量优先，其次 config.json 的 llm 段）:
  CHAT_ARCHIVE_LLM_BASE_URL / llm.base_url  (默认 https://api.deepseek.com/v1)
  CHAT_ARCHIVE_LLM_API_KEY  / llm.api_key
  CHAT_ARCHIVE_LLM_MODEL    / llm.model     (默认 deepseek-chat)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _llm_settings() -> dict:
    """合并 config.json 的 llm 段与环境变量（环境变量优先）。"""
    cfg: dict = {}
    p = Path(__file__).resolve().parents[1] / "config.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("llm"), dict):
                cfg = d["llm"]
        except Exception:
            pass
    key = os.environ.get("CHAT_ARCHIVE_LLM_API_KEY") or str(cfg.get("api_key") or "")
    base = (
        os.environ.get("CHAT_ARCHIVE_LLM_BASE_URL")
        or str(cfg.get("base_url") or "")
        or "https://api.deepseek.com/v1"
    ).rstrip("/")
    model = os.environ.get("CHAT_ARCHIVE_LLM_MODEL") or str(cfg.get("model") or "") or "deepseek-chat"
    return {"api_key": key, "base_url": base, "model": model}


def llm_configured() -> bool:
    return bool(_llm_settings()["api_key"])


def chat_completion(system: str, user: str, *, timeout: int = 120) -> str:
    """调用 OpenAI 兼容 chat completions, 返回 assistant 文本。"""
    s = _llm_settings()
    base = s["base_url"]
    key = s["api_key"]
    if not key:
        raise RuntimeError("未配置 LLM API Key（config.json 的 llm.api_key 或环境变量 CHAT_ARCHIVE_LLM_API_KEY）")
    model = s["model"]

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM HTTP {e.code}: {e.read()[:200].decode('utf-8', 'ignore')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 请求失败: {e.reason}") from e
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"LLM 返回结构异常: {data}") from e
