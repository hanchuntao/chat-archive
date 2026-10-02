#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb-sync — 知识库同步：本地 + 腾讯 ima 双通道（按 config.json 的 knowledge 段）。

用法：
  python3 sync_kb.py --out <业务产物目录> [--config <config.json>] [--to local|ima|all]

行为：
  - local：把脱敏产物（knowledge/）同步到配置的本地目录（默认就地，无需动作）
  - ima   ：已配 API Key/Client ID → 自动上传 .md 到指定 ima 知识库
            未配 Key → 把脱敏产物导出到 <out>/ima_export/，附导入说明，供手动导入
仅上传已脱敏产物（knowledge/*.md、onboarding.md），训练 jsonl 不上传（供本地训练用）。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import shutil
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

IMA_BASE = "https://ima.qq.com"
IMA_WIKI = IMA_BASE + "/openapi/wiki/v1"


# ---------------------------------------------------------------- 配置

def load_config(cfg_path: str | None) -> dict:
    path = Path(cfg_path) if cfg_path else Path(__file__).resolve().parents[2] / "config.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def knowledge_cfg(config: dict) -> dict:
    return config.get("knowledge", {}) if isinstance(config, dict) else {}


# ---------------------------------------------------------------- 本地同步

def sync_local(out: Path, cfg: dict) -> str:
    local = cfg.get("local", {})
    src = out / "knowledge"
    if not src.exists():
        return "本地：out/knowledge/ 不存在，跳过"
    dest = Path(local.get("dir", "knowledge"))
    if not dest.is_absolute():
        dest = out / dest
    if dest.resolve() == src.resolve():
        return f"本地：产物即位于 {src}/（就地，无需复制）"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dest / f.name)
            n += 1
    return f"本地：已同步 {n} 个文件 → {dest}/"


# ---------------------------------------------------------------- ima 导出（无 Key 时）

def export_for_ima(out: Path) -> str:
    src = out / "knowledge"
    dest = out / "ima_export"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    if src.exists():
        for f in sorted(src.glob("*.md")):
            shutil.copy2(f, dest / f.name)
            n += 1
    readme = dest / "导入说明.md"
    readme.write_text(
        "# ima 知识库导入说明\n\n"
        "- 这些文件是 chat-archive 产出的**已脱敏**知识条目（Markdown）。\n"
        "- 手动导入：打开 ima（ima.qq.com 或客户端）→ 知识库 → 添加文件 → 选择本目录的 .md 文件。\n"
        "- 自动导入：在 https://ima.qq.com/agent-interface 生成 API Key 与 Client ID，填入仓库根 "
        "`config.json` 的 `knowledge.ima`，然后运行 `python3 skill/scripts/sync_kb.py --out <out目录>`。\n",
        encoding="utf-8")
    return f"ima：未配置 API Key，已导出 {n} 份脱敏产物 → {dest}/（手动导入或配置 Key 后自动上传）"


# ---------------------------------------------------------------- ima API

def _ima_post(path: str, body: dict, client_id: str, api_key: str) -> dict:
    req = urllib.request.Request(
        IMA_WIKI + path,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
        },
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": f"HTTP {e.code}"}
    except Exception as e:
        return {"code": -1, "msg": str(e)}
    return data


def _find_knowledge_base(client_id: str, api_key: str, name: str) -> tuple[str | None, str | None]:
    """按名称定位知识库 ID；返回 (kb_id 或 None, 错误信息或 None)。认证/API 错误明确报出。"""
    if name:
        resp = _ima_post("/search_knowledge_base",
                         {"query": name, "cursor": "", "limit": 20}, client_id, api_key)
        if resp.get("code") != 0:
            return None, (f"ima API 错误（code={resp.get('code')}）：{resp.get('msg')}"
                          "（检查 API Key / Client ID 是否有效，生成页 https://ima.qq.com/agent-interface）")
        for kb in resp.get("data", {}).get("info_list", []):
            if kb.get("name") == name:
                return kb["id"], None
    resp = _ima_post("/get_addable_knowledge_base_list",
                     {"cursor": "", "limit": 50}, client_id, api_key)
    if resp.get("code") != 0:
        return None, (f"ima API 错误（code={resp.get('code')}）：{resp.get('msg')}"
                      "（检查 API Key / Client ID 是否有效，生成页 https://ima.qq.com/agent-interface）")
    lst = resp.get("data", {}).get("addable_knowledge_base_list", [])
    if lst and not name:
        print("可添加的知识库：")
        for kb in lst:
            print(f"  - {kb.get('name')} (id={kb.get('id')})")
        print('请在 config.json 的 knowledge.ima.knowledge_base_name 中指定其一。')
    return None, None


def _cos_sign(secret_key: str, cos_key: str, host: str, key_time: str) -> str:
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    http_string = f"put\n/{cos_key}\n\nhost={host}\n"
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    return hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()


def _cos_upload(cred: dict, cos_key: str, file_path: Path) -> bool:
    host = cred.get("custom_domain") or f"{cred.get('bucket_name')}.cos.{cred.get('region')}.myqcloud.com"
    now = int(time.time())
    key_time = f"{now};{cred.get('expired_time', now + 600)}"
    signature = _cos_sign(cred.get("secret_key", ""), cos_key, host, key_time)
    auth = (f"q-sign-algorithm=sha1&q-ak={cred.get('secret_id')}&q-sign-time={key_time}"
            f"&q-key-time={key_time}&q-header-list=host&q-url-param-list=&q-signature={signature}")
    data = file_path.read_bytes()
    req = urllib.request.Request(
        f"https://{host}/{cos_key}",
        data=data,
        headers={
            "Host": host,
            "Authorization": auth,
            "x-cos-security-token": cred.get("token", ""),
            "Content-Type": "text/markdown",
            "Content-Length": str(len(data)),
        },
        method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


def _upload_file(client_id: str, api_key: str, kb_id: str, path: Path) -> tuple[bool, str]:
    size = path.stat().st_size
    resp = _ima_post("/create_media", {
        "file_name": path.name, "file_size": size,
        "content_type": "text/markdown", "knowledge_base_id": kb_id,
        "file_ext": path.suffix.lstrip(".") or "md",
    }, client_id, api_key)
    if resp.get("code") != 0:
        return False, f"create_media 失败: {resp.get('msg')}"
    data = resp.get("data", {})
    media_id = data.get("media_id")
    cred = data.get("cos_credential", {})
    if not cred:
        return False, "未返回 COS 凭证"
    if not _cos_upload(cred, cred.get("cos_key", ""), path):
        return False, "COS 上传失败"
    finfo = {"cos_key": cred.get("cos_key", ""), "file_size": size,
             "last_modify_time": int(time.time()), "file_name": path.name}
    resp = _ima_post("/add_knowledge", {
        "media_type": 7, "media_id": media_id, "title": path.stem,
        "knowledge_base_id": kb_id, "file_info": finfo,
    }, client_id, api_key)
    if resp.get("code") != 0:
        return False, f"add_knowledge 失败: {resp.get('msg')}"
    return True, "ok"


def sync_ima(out: Path, cfg: dict) -> str:
    ima = cfg.get("ima", {})
    client_id = (ima.get("client_id") or "").strip()
    api_key = (ima.get("api_key") or "").strip()
    if not client_id or not api_key:
        return export_for_ima(out)
    src = out / "knowledge"
    if not src.exists():
        return "ima：out/knowledge/ 不存在，跳过"
    kb_name = (ima.get("knowledge_base_name") or "").strip()
    kb_id, err = _find_knowledge_base(client_id, api_key, kb_name)
    if err:
        raise RuntimeError(err)
    if not kb_id:
        raise RuntimeError("ima：未能定位知识库（检查 knowledge_base_name，或按上方列表填写）")
    files = sorted(src.glob("*.md"))
    ok, fail = 0, []
    for f in files:
        succ, msg = _upload_file(client_id, api_key, kb_id, f)
        if succ:
            ok += 1
        else:
            fail.append(f"{f.name}: {msg}")
    report = f"ima：上传完成 {ok}/{len(files)} 个文件 → 知识库「{kb_name or kb_id}」"
    if fail:
        report += "\n失败：" + "\n".join(fail)
    return report


# ---------------------------------------------------------------- 主入口

def main():
    ap = argparse.ArgumentParser(description="知识库同步：本地 + 腾讯 ima")
    ap.add_argument("--out", required=True, help="业务产物目录（含 knowledge/）")
    ap.add_argument("--config", default="", help="config.json 路径（默认仓库根）")
    ap.add_argument("--to", choices=["local", "ima", "all"], default="all",
                    help="同步目标（默认 all）")
    args = ap.parse_args()
    out = Path(args.out)
    cfg = knowledge_cfg(load_config(args.config))
    msgs = []
    if args.to in ("local", "all"):
        msgs.append(sync_local(out, cfg))
    if args.to in ("ima", "all"):
        try:
            msgs.append(sync_ima(out, cfg))
        except RuntimeError as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
    for m in msgs:
        print(m)


if __name__ == "__main__":
    main()
