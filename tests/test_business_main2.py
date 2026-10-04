"""业务层第二轮补测：LLM 成功路径、main 全错误分支、辅助脚本内部函数、边角分支。

目标：把业务脚本从 89% 提到 95%+，同时覆盖 sync_kb/render_html/convert_wx 剩余分支。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
ECOM = REPO / "sample_data" / "ecom_chat.txt"


def _load_biz():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("ca_biz_main2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


biz = _load_biz()


def _msg(sender: str, content: str, staff: bool = True, t: str = "2026-09-01 10:00") -> dict:
    return {"msg_id": sender + content[:4], "group_id": "g", "group_name": "群",
            "sender": sender, "is_staff": staff, "content": content,
            "sent_at": biz._parse_dt(t) or datetime.now()}


def _run_main(argv: list[str], monkeypatch) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        monkeypatch.setattr(sys, "argv", argv)
        biz.main()
    return buf.getvalue()


def _stamp_dirs(out: Path) -> list[str]:
    return [d.name for d in out.iterdir()
            if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)]


def _load_script(name: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "skill" / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================ LLM 成功路径

def test_ai_extract_leads_success(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: json.dumps(
        [{"content": "我们要 500 件", "who": "客户A", "hint": "大单"}]))
    leads = biz.ai_extract_leads([_msg("客户A", "我们要 500 件", staff=False)])
    assert leads and leads[0]["content"] == "我们要 500 件" and leads[0]["hint"] == "大单"


def test_ai_extract_leads_bad_json_and_exception(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: "not json")
    assert biz.ai_extract_leads([_msg("客户A", "x", staff=False)]) == []
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert biz.ai_extract_leads([_msg("客户A", "x", staff=False)]) == []
    # 无客户消息 → 直接空
    assert biz.ai_extract_leads([]) == []


def test_ai_assessment_review_success(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: "**评语**：响应及时")
    md = biz.ai_assessment_review([_msg("张三", "好的，马上处理", staff=True)],
                                  [{"userid": "张三", "sent": 1}])
    assert "张三" in md and "评语" in md
    # 无有效回复 → 空
    assert biz.ai_assessment_review([_msg("张三", "收到", staff=True)], [{"userid": "张三", "sent": 1}]) == ""
    # LLM 失败 → 空
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert biz.ai_assessment_review([_msg("张三", "好的，马上处理", staff=True)],
                                    [{"userid": "张三", "sent": 1}]) == ""


def test_ai_summarize_discussion_and_daily(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: "AI 要点内容")
    assert biz.ai_summarize_discussion([_msg("张三", "讨论", staff=True)]) == "AI 要点内容"
    assert biz.ai_build_daily([_msg("张三", "工作", staff=True)], "张三", "2026-09-01") == "AI 要点内容"
    # LLM 抛错向上冒（main 捕获）
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        biz.ai_summarize_discussion([_msg("张三", "x", staff=True)])


def test_ai_build_knowledge_success_and_empty(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion",
                        lambda *a, **k: "## 回答\n这是 AI 生成的知识条目内容")
    d = biz.ai_build_knowledge([{"qa": [{"q": "问", "a": "答"}], "category": "发货/物流",
                                 "title": "发货/物流知识条目", "filename": "发货_物流.md"}])
    assert d and any("AI 生成的知识条目" in v for v in d.values())
    assert biz.ai_build_knowledge([]) == {}


def test_ai_extract_insights_success(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: "AI 洞察")
    assert biz.ai_extract_insights([_msg("客户A", "物流太慢", staff=False)]) == "AI 洞察"
    assert biz.ai_extract_insights([_msg("张三", "工作", staff=True)]) == ""  # 无客户消息


def test_verify_summary_traceability():
    md = "## 要点\n- 客户问发货时间，员工答复明日发出"
    msgs = [_msg("张三", "客户问发货时间，员工答复明日发出", staff=True)]
    out = biz.verify_summary(md, msgs)
    assert "[可溯源]" in out
    out2 = biz.verify_summary(md, [_msg("张三", "完全无关内容", staff=True)])
    assert "[待核对]" in out2
    assert biz.verify_summary("", msgs) == ""


# ============================================================ 纯函数边角

def test_mask_identity_anon_bucket():
    anon: dict = {}
    a1 = biz.mask_identity("张三", True, {"张三"}, anon)
    a2 = biz.mask_identity("张三", True, {"张三"}, anon)
    assert a1 == a2 and "员工" in a1
    c1 = biz.mask_identity("客户A", False, set(), anon)
    assert "客户" in c1


def test_classify_branches():
    assert biz.classify("") == "filler"
    assert biz.classify("收到收到") == "filler"
    assert biz.classify("👍👍👍") == "filler"
    assert biz.classify("今天发 200 单") == "substantive"
    assert biz.classify("好的呢") == "filler"


def test_is_noise_branches():
    assert biz.is_noise("[图片]") is True
    assert biz.is_noise("[红包]") is True
    assert biz.is_noise("正常消息") is False
    assert biz.is_noise("") is True


def test_read_text_any_all_fail(tmp_path):
    f = tmp_path / "bin.txt"
    f.write_bytes(b"\xff\xff\xff\xff\xff")
    txt = biz._read_text_any(f)
    assert isinstance(txt, str)  # 全编码失败回退 errors=ignore


def test_load_history_corrupt(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    (d / "history.json").write_text("{broken", encoding="utf-8")
    assert biz.load_history(d) == {"groups": {}, "updated_at": ""}


def test_load_input_encrypted_with_tool(tmp_path):
    src = tmp_path / "bak.db"
    src.write_bytes(b"x")
    items, fmts = biz.load_input(str(src), f"cp {ECOM} {{dir}}/out.txt")
    assert items and fmts == ["tool+db"]


def test_build_knowledge_noise_pair_skipped():
    msgs = [
        _msg("客户A", "[图片]", staff=False),
        _msg("张三", "已收到您的图片", staff=True),
    ]
    entries, _, _ = biz.build_knowledge(msgs, mask=True)
    # 噪声客户消息不构成问答对 → 无话题命中（"图片"非话题词）→ 空
    assert entries == [] or all(e["category"] != "发货/物流" for e in entries)


def test_run_assessment_filler_penalty():
    msgs = [_msg("张三", "收到", staff=True), _msg("张三", "好的", staff=True),
            _msg("张三", "嗯", staff=True), _msg("张三", "哦", staff=True),
            _msg("张三", "行", staff=True), _msg("张三", "今天发", staff=True)]
    scheme = {"base_score": 100, "timeout_penalty": 5, "violation_penalty": 10,
              "filler_threshold": 50, "filler_penalty": 5, "bonus": 1, "bonus_cap": 20,
              "timeout_sec": 300, "unanswered_penalty": 5, "duty": {}}
    results, _ = biz.run_assessment(msgs, biz.DEFAULT_RULES, scheme)
    r = results[0]
    assert r["filler_rate"] == 83 and "口水率超标" in r["deductions"]


def test_split_sessions_gap_and_enders():
    msgs = [
        _msg("客户A", "你好", staff=False, t="2026-09-01 10:00"),
        _msg("张三", "您好", staff=True, t="2026-09-01 10:05"),
        _msg("客户A", "再见", staff=False, t="2026-09-01 10:06"),
        _msg("客户B", "在吗", staff=False, t="2026-09-02 09:00"),  # 跨日 → 切分会话
    ]
    sessions = biz.split_sessions(msgs, gap_min=30)
    assert len(sessions) >= 2


def test_pending_queue_ender_exemption():
    msgs = [
        _msg("客户A", "在吗", staff=False, t="2026-09-01 10:00"),
        _msg("客户A", "算了不要了", staff=False, t="2026-09-01 10:05"),  # 客户自己结束
    ]
    assert biz.pending_queue(msgs, grace_min=15) == []


def test_commitment_review_due_today(tmp_path):
    today = datetime.now().strftime("%Y-%m-%d")
    fups = [{"group": "g", "content": "跟进 X", "assignee": "张三", "due": today,
             "source": "李四", "time": today + " 10:00"}]
    rows = biz.commitment_review(fups, tmp_path)
    assert rows and rows[0]["status"] == "今日到期"


def test_search_messages_date_range():
    msgs = [
        _msg("客户A", "发货了吗", staff=False, t="2026-09-01 10:00"),
        _msg("客户B", "发货了吗", staff=False, t="2026-09-05 10:00"),
    ]
    hits = biz.search_messages(msgs, query="发货", date_from="2026-09-02", date_to="2026-09-10")
    assert len(hits) == 1 and hits[0]["sender"] == "客户B"


def test_faq_draft_min_freq_filter():
    entries = [{"category": "发货/物流", "qa": [{"q": "多久到", "a": "1-3 天"}]},
               {"category": "发货/物流", "qa": [{"q": "多久到", "a": "1-3 天"}]},
               {"category": "退款/售后", "qa": [{"q": "多久退", "a": "1-3 天"}]}]
    md, rows = biz.faq_draft(entries, min_freq=2)
    assert len(rows) == 1  # 仅频次≥2 的问答


def test_bm25_search_no_bigrams():
    assert biz.bm25_search([], "a") == []  # 无 bigram → 空


def test_media_manifest_supported_types(tmp_path):
    f = tmp_path / "chat.txt"
    f.write_text("2026-09-01 10:00 张三: [图片] 和 [语音]\n", encoding="utf-8")
    rows = biz.media_manifest(str(f))
    assert len(rows) == 1 and rows[0]["kind"] == "image"  # 同行多个占位只记首个
    # 不支持的后缀跳过
    g = tmp_path / "chat.pdf"
    g.write_text("x", encoding="utf-8")
    assert biz.media_manifest(str(g)) == []


def test_clean_training_bad_json_lines():
    train = ('{"input":"请问多久发货","output":"1-3个工作日"}\n'
             '{"input":"请问多久发货","output":"1-3个工作日"}\n'
             'not-json\n{"input":"","output":""}\n')
    kept, dropped = biz.clean_training(train, [{"name": "R", "pattern": "违禁词", "level": "high"}])
    assert len(kept) == 1 and len(dropped) == 1  # 重复行计 1 条


def test_read_csv_rows_missing_and_bad(tmp_path):
    assert biz._read_csv_rows(tmp_path / "nope.csv") == []
    f = tmp_path / "bad.csv"
    f.write_bytes(b"\x00\x01\x02")
    assert biz._read_csv_rows(f) == []


def test_trend_compare_no_new_topics(tmp_path):
    out = tmp_path / "out"
    (out / "2026-09-01_000000_000000").mkdir(parents=True)
    (out / "2026-09-01_000000_000000" / "insight.md").write_text(
        "## 发货/物流（3 条）\n- 快递太慢", encoding="utf-8")
    (out / "2026-09-02_000000_000000").mkdir()
    (out / "2026-09-02_000000_000000" / "insight.md").write_text(
        "## 发货/物流（2 条）\n- 快递慢", encoding="utf-8")
    md = biz.trend_compare(out, out / "2026-09-02_000000_000000")
    assert "无新冒头问题" in md


def test_effective_stats_mixed():
    msgs = [_msg("张三", "收到", staff=True), _msg("张三", "今天发 200 单", staff=True)]
    rows = biz.effective_stats(msgs)
    assert rows[0]["filler_rate"] == 50


def test_extract_dialogues_empty():
    assert biz.extract_dialogues([_msg("张三", "只有员工", staff=True)]) == []


def test_satisfaction_neutral():
    msgs = [_msg("客户A", "嗯", staff=False)]
    rows = biz.satisfaction(msgs)
    assert rows and rows[0]["level"] == "未判定"


def test_sla_triage_default():
    msgs = [_msg("客户A", "请问发货时间", staff=False)]
    rows = biz.sla_triage(msgs)
    assert isinstance(rows, list)


def test_payment_ledger_no_amounts():
    assert biz.payment_ledger([_msg("张三", "今天发了 200 单", staff=True)]) == []


def test_level_problems_empty():
    assert biz.level_problems([], {}) == []


def test_funnel_analysis_empty_sessions():
    assert biz.funnel_analysis([]) == []


def test_session_timeline_empty():
    assert biz.session_timeline([]) == []


def test_mentions_stats_empty():
    assert biz.mentions_stats([]) == []


def test_export_messages_mask_flag():
    msgs = [_msg("张三", "电话 13812345678", staff=True)]
    rows = biz.export_messages(msgs, mask=True)
    assert "13812345678" not in rows[0]["content"]
    rows2 = biz.export_messages(msgs, mask=False)
    assert "13812345678" in rows2[0]["content"]


def test_clean_training_keeps_rules():
    train = '{"input":"请问多久发货","output":"1-3个工作日"}\n'
    kept, dropped = biz.clean_training(train, [{"name": "R", "pattern": "违禁词", "level": "medium"}])
    assert kept and dropped == []


def test_build_assessment_notes_with_results():
    results = [{"userid": "张三", "final_score": 95, "base_score": 100, "effective": 3, "sent": 4,
                "filler_rate": 25, "timeout_count": 0, "unanswered_count": 0,
                "violation_count": 0, "hits": [], "deductions": {}}]
    md = biz.build_assessment_notes([_msg("张三", "实质内容", staff=True)], results, [], [])
    assert isinstance(md, str) and "张三" in md and "机器分" in md


# ============================================================ main() 全错误分支

def test_main_all_errors_collect_and_exit(tmp_path, monkeypatch):
    """所有可选步骤失败 → errors 收集、错误打印、exit 1，主产物仍生成。"""
    monkeypatch.setattr(biz, "_build_kb_section", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kb boom")))
    monkeypatch.setattr(biz, "activity_stats", lambda msgs: (_ for _ in ()).throw(RuntimeError("act boom")))
    monkeypatch.setattr(biz, "compact_chat", lambda msgs: (_ for _ in ()).throw(RuntimeError("compact boom")))
    monkeypatch.setattr(biz, "extract_insights", lambda msgs: (_ for _ in ()).throw(RuntimeError("insight boom")))
    monkeypatch.setattr(biz, "signal_stats", lambda msgs: (_ for _ in ()).throw(RuntimeError("signal boom")))
    monkeypatch.setattr(biz, "behavior_metrics", lambda msgs: (_ for _ in ()).throw(RuntimeError("bm boom")))
    monkeypatch.setattr(biz, "extract_dialogues", lambda msgs: (_ for _ in ()).throw(RuntimeError("dlg boom")))
    monkeypatch.setattr(biz, "split_sessions", lambda msgs, gap_min=30: (_ for _ in ()).throw(RuntimeError("sess boom")))
    monkeypatch.setattr(biz, "revoke_audit", lambda p: (_ for _ in ()).throw(RuntimeError("revoke boom")))
    monkeypatch.setattr(biz, "commitment_review", lambda f, d: (_ for _ in ()).throw(RuntimeError("cmt boom")))
    monkeypatch.setattr(biz, "search_messages", lambda msgs, query="": (_ for _ in ()).throw(RuntimeError("search boom")))
    monkeypatch.setattr(biz, "mentions_stats", lambda msgs: (_ for _ in ()).throw(RuntimeError("ment boom")))
    monkeypatch.setattr(biz, "export_messages", lambda msgs, mask=False: (_ for _ in ()).throw(RuntimeError("exp boom")))
    monkeypatch.setattr(biz, "update_memory_layer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mem boom")))
    monkeypatch.setattr(biz, "build_growth_report", lambda d: (_ for _ in ()).throw(RuntimeError("grow boom")))
    monkeypatch.setattr(biz, "trend_compare", lambda o, r: (_ for _ in ()).throw(RuntimeError("trend boom")))
    import types
    monkeypatch.setitem(sys.modules, "render_html",
                        types.SimpleNamespace(render=lambda d, t="": (_ for _ in ()).throw(RuntimeError("html boom"))))

    out = tmp_path / "out"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit) as e:
        monkeypatch.setattr(sys, "argv", ["ca", "all", "--input", str(ECOM), "--staff", "all",
                                          "--out", str(out), "--search", "快递"])
        biz.main()
    assert e.value.code == 1
    assert "存在失败项" in buf.getvalue()
    # 主产物（统计/日报/跟进/考核）仍生成
    dirs = _stamp_dirs(out)
    d = out / dirs[0]
    for name in ("effective_stats.csv", "assessment.csv", "followups.csv",
                 "assessment_notes.md"):
        assert (d / name).exists(), name
    assert not (d / "latest_report.html").exists()


def test_main_kb_draft_failure_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(biz, "_build_kb_section", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kb boom")))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        _run_main(["ca", "kb-draft", "--input", str(ECOM), "--staff", "all",
                   "--out", str(out)], monkeypatch)
    assert e.value.code == 1


def test_main_mask_all_and_ambiguous(tmp_path, monkeypatch):
    src = tmp_path / "c.txt"
    src.write_text("2026-09-28 09:00:00 wxid_abc123: 电话 13812345678\n"
                   "2026-09-28 09:01:00 客户B: 好的\n", encoding="utf-8")
    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(src), "--staff", "all",
                      "--out", str(out), "--mask-all"], monkeypatch)
    assert "昵称歧义消解" in text or "视为员工" in text
    dirs = _stamp_dirs(out)
    d = out / dirs[0]
    assert "wxid_abc123" not in (d / "messages.csv").read_text(encoding="utf-8")


def test_main_llm_ok_with_toolcmd_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(biz, "llm_configured", lambda: True)
    monkeypatch.setattr(biz, "ai_build_daily", lambda *a, **k: "AI 日报")
    monkeypatch.setattr(biz, "ai_summarize_discussion", lambda *a, **k: "AI 要点")
    monkeypatch.setattr(biz, "ai_extract_leads", lambda *a, **k: [])
    monkeypatch.setattr(biz, "ai_assessment_review", lambda *a, **k: "AI 评语")
    monkeypatch.setattr(biz, "ai_extract_insights", lambda *a, **k: "AI 洞察")
    monkeypatch.setattr(biz, "ai_build_knowledge", lambda entries: {"x.md": "# AI 知识"})
    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out), "--tool-cmd", "echo {input} {dir}"], monkeypatch)
    assert "LLM 已就绪" in text
    assert "商机线索" not in text  # leads 空 → 无商机提示


# ============================================================ sync_kb 内部 API

def test_sync_kb_internal_api(monkeypatch, tmp_path):
    sk = _load_script("sync_kb.py", "ca_sync_kb2")
    import urllib.request as ur
    import urllib.error as ue

    # _ima_post 成功
    def _ok(req, timeout=30):
        return io.BytesIO(b'{"code":0,"data":{"info_list":[{"id":"kb1","name":"KB"}]}}')

    monkeypatch.setattr(ur, "urlopen", _ok)
    resp = sk._ima_post("/x", {}, "cid", "key")
    assert resp["code"] == 0

    # HTTPError
    def _http_err(req, timeout=30):
        raise ue.HTTPError("u", 403, "forbidden", {}, None)
    monkeypatch.setattr(ur, "urlopen", _http_err)
    assert sk._ima_post("/x", {}, "c", "k")["code"] == 403

    # 其他异常
    def _boom(req, timeout=30):
        raise OSError("net down")
    monkeypatch.setattr(ur, "urlopen", _boom)
    assert sk._ima_post("/x", {}, "c", "k")["code"] == -1

    # _find_knowledge_base：按名称命中
    def _found(path, body, c, k):
        return {"code": 0, "data": {"info_list": [{"id": "kb9", "name": "KB"}]}}
    monkeypatch.setattr(sk, "_ima_post", _found)
    assert sk._find_knowledge_base("c", "k", "KB") == ("kb9", None)

    # 按名称未命中 → 走 addable 列表
    def _no_name(path, body, c, k):
        if "search_knowledge_base" in path:
            return {"code": 0, "data": {"info_list": [{"id": "x", "name": "Other"}]}}
        return {"code": 0, "data": {"addable_knowledge_base_list": [{"name": "A", "id": "1"}]}}
    monkeypatch.setattr(sk, "_ima_post", _no_name)
    kb_id, err = sk._find_knowledge_base("c", "k", "KB")
    assert kb_id is None and err is None

    # 搜索 API 错误
    def _err(path, body, c, k):
        return {"code": -1, "msg": "bad key"}
    monkeypatch.setattr(sk, "_ima_post", _err)
    assert sk._find_knowledge_base("c", "k", "KB")[1]

    # _cos_sign 确定性
    sig = sk._cos_sign("sk", "cos/key.md", "b.cos.region.myqcloud.com", "100;200")
    assert len(sig) == 40  # sha1 hex

    # _cos_upload 成功/失败
    def _put(req, timeout=120):
        class _R:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _R()
    monkeypatch.setattr(ur, "urlopen", _put)
    cred = {"custom_domain": "cdn.example.com", "secret_key": "sk", "secret_id": "id",
            "expired_time": 9999999999, "token": "t"}
    f = tmp_path / "a.md"
    f.write_text("# A", encoding="utf-8")
    assert sk._cos_upload(cred, "k.md", f) is True
    monkeypatch.setattr(ur, "urlopen", lambda req: (_ for _ in ()).throw(OSError()))
    assert sk._cos_upload(cred, "k.md", f) is False

    # _upload_file：create_media 失败
    monkeypatch.setattr(sk, "_ima_post", lambda *a, **k: {"code": -1, "msg": "no media"})
    ok, msg = sk._upload_file("c", "k", "kb", f)
    assert not ok and "create_media" in msg

    # _upload_file：无 COS 凭证
    monkeypatch.setattr(sk, "_ima_post",
                        lambda *a, **k: {"code": 0, "data": {"media_id": "m1", "cos_credential": {}}})
    ok, msg = sk._upload_file("c", "k", "kb", f)
    assert not ok and "COS 凭证" in msg

    # _upload_file：COS 上传失败
    def _ok_media(path, body, c, k):
        if path.endswith("create_media"):
            return {"code": 0, "data": {"media_id": "m1",
                                        "cos_credential": {"cos_key": "k.md", "secret_key": "sk",
                                                           "secret_id": "id", "expired_time": 9999999999}}}
        return {"code": 0, "data": {}}
    monkeypatch.setattr(sk, "_ima_post", _ok_media)
    monkeypatch.setattr(sk, "_cos_upload", lambda *a, **k: False)
    ok, msg = sk._upload_file("c", "k", "kb", f)
    assert not ok and "COS 上传失败" in msg

    # _upload_file：add_knowledge 失败
    monkeypatch.setattr(sk, "_cos_upload", lambda *a, **k: True)
    def _add_fail(path, body, c, k):
        if path.endswith("add_knowledge"):
            return {"code": -1, "msg": "add failed"}
        return {"code": 0, "data": {"media_id": "m1", "cos_credential": {"cos_key": "k"}}}
    monkeypatch.setattr(sk, "_ima_post", _add_fail)
    ok, msg = sk._upload_file("c", "k", "kb", f, folder_id="f1")
    assert not ok and "add_knowledge" in msg

    # _upload_file：全成功
    def _all_ok(path, body, c, k):
        if path.endswith("create_media"):
            return {"code": 0, "data": {"media_id": "m1", "cos_credential": {"cos_key": "k"}}}
        return {"code": 0, "data": {}}
    monkeypatch.setattr(sk, "_ima_post", _all_ok)
    ok, msg = sk._upload_file("c", "k", "kb", f)
    assert ok and msg == "ok"


def test_sync_kb_run_and_main(tmp_path, monkeypatch):
    sk = _load_script("sync_kb.py", "ca_sync_kb3")
    out = tmp_path / "out"
    (out / "knowledge").mkdir(parents=True)
    (out / "knowledge" / "a.md").write_text("# A", encoding="utf-8")
    # run()：local + ima 未配 Key
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sk.run(str(out), "", "all")
    txt = buf.getvalue()
    assert "本地" in txt and "未配置 API Key" in txt
    # run()：ima 已配 Key 但定位失败 → exit 1
    monkeypatch.setattr(sk, "load_config", lambda c: {"knowledge": {"ima": {"client_id": "c", "api_key": "k"}}})
    monkeypatch.setattr(sk, "_find_knowledge_base", lambda c, k, n: (None, "auth err"))
    with pytest.raises(SystemExit) as e:
        with contextlib.redirect_stdout(io.StringIO()):
            sk.run(str(out), "", "ima")
    assert e.value.code == 1
    # main()：sys.argv 注入（load_config 仍返回 ima 配置 → run all 会 auth err → exit 1）
    monkeypatch.setattr(sys, "argv", ["sk", "--out", str(out), "--to", "local"])
    with contextlib.redirect_stdout(io.StringIO()):
        sk.main()


# ============================================================ convert_wx main

def test_convert_wx_main(tmp_path, monkeypatch):
    cw = _load_script("convert_wx.py", "ca_convert_wx2")
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"messages": ["[2026-09-01 20:11] 张三: 内容"]}), encoding="utf-8")
    dst = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["cw", "--input", str(src), "--output", str(dst)])
    with contextlib.redirect_stdout(io.StringIO()):
        cw.main()
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data[0]["senderDisplayName"] == "张三"
    # 坏结构 → sys.exit
    src2 = tmp_path / "bad.json"
    src2.write_text(json.dumps({"x": 1}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["cw", "--input", str(src2), "--output", str(tmp_path / "o2.json")])
    with pytest.raises(SystemExit):
        with contextlib.redirect_stdout(io.StringIO()):
            cw.main()


# ============================================================ render_html 分支

def test_render_html_branches(tmp_path):
    rh = _load_script("render_html.py", "ca_render_html2")

    # _json_field 三态
    assert rh._json_field('{"a": 1}', "a") == 1
    assert rh._json_field("[1,2]", "a") == [1, 2]
    assert rh._json_field("{bad", "a") == ""
    assert rh._json_field("", "a") == ""

    # _stat_card hot
    assert "hot" in rh._stat_card(3, "风险", hot=True)
    assert rh._stat_card(0, "正常")  # 非 hot

    # 空目录渲染不再崩溃（修复回归）
    empty = tmp_path / "e"
    empty.mkdir()
    html = rh.render(empty, title="T")
    assert "<html" in html

    # 有内容的分支组合渲染
    out = tmp_path / "o"
    (out / "daily_reports").mkdir(parents=True, exist_ok=True)
    (out / "daily_reports" / "张三_2026-09-01.md").write_text(
        "# 张三 工作日报（2026-09-01）\n\n- 消息总数：2\n\n## 一、实际工作内容\n\n- 10:00 发货 200 单\n",
        encoding="utf-8")
    (out / "discussion_summary.md").write_text("## 发货/物流\n\n- 09-28 10:00 张三：快递单号已更新\n",
                                               encoding="utf-8")
    (out / "knowledge").mkdir()
    (out / "knowledge" / "发货_物流.md").write_text(
        "# 发货/物流知识条目\n\n## 问答示例（已脱敏）\n\n问：多久到？\n答：1-3 天\n", encoding="utf-8")
    (out / "assessment_notes.md").write_text("证据化评语" + "x" * 4200, encoding="utf-8")
    (out / "insight.md").write_text("## 物流太慢（3 条）\n- 快递三天没到\n", encoding="utf-8")
    (out / "behavior.csv").write_text("avg_response_min,responses,question_rate,statement_rate\n98.0,12,23,77\n",
                                      encoding="utf-8")
    (out / "effective_stats.csv").write_text("userid,sent,effective,filler,filler_rate\n张三,4,3,1,25\n",
                                             encoding="utf-8")
    (out / "followups.csv").write_text(
        "group,content,assignee,due,source,time,unanswered,type\n群,询价未回复,,,客户A,2026-09-01 10:00,true,询价未回复\n",
        encoding="utf-8")
    (out / "assessment.csv").write_text(
        "userid,base_score,final_score,sent,effective,filler_rate,timeout_count,unanswered_count,violation_count,hits,deductions\n"
        "张三,100,95,4,3,25,0,0,1,\"[]\",\"{'合规违规': -5}\"\n", encoding="utf-8")
    (out / "activity.csv").write_text("userid,sent,effective,filler,active_days,peak_hour,night\n张三,4,3,1,2,20,0\n",
                                      encoding="utf-8")
    (out / "signal.csv").write_text("userid,total,success,frustration,workflow,request,signal_count,confidence\n张三,4,1,1,1,1,4,80\n",
                                    encoding="utf-8")
    (out / "dialogues.json").write_text(json.dumps([{
        "customer": {"sender": "客户A", "content": "多少钱", "sent_at": "2026-09-01T10:00:00"},
        "staff": {"sender": "张三", "content": "99 元", "sent_at": "2026-09-01T10:02:00"}}]), encoding="utf-8")
    (out / "sessions.csv").write_text("start,end,customer,msgs,group\n2026-09-01T10:00:00,2026-09-01T10:02:00,客户A,2,群\n",
                                      encoding="utf-8")
    (out / "pending.csv").write_text("customer,content,time,group\n客户A,在吗,2026-09-01 10:00,群\n", encoding="utf-8")
    (out / "satisfaction.csv").write_text("customer,level,content,time\n客户A,positive,满意,2026-09-01 10:00\n",
                                          encoding="utf-8")
    (out / "sla.csv").write_text("customer,priority,first_reply,status,time\n客户A,P1,60,timeout,2026-09-01 10:00\n",
                                 encoding="utf-8")
    (out / "health.csv").write_text("customer,score,playbook,time\n客户A,55,优先回访,2026-09-01 10:00\n",
                                    encoding="utf-8")
    (out / "sop_compliance.csv").write_text("rule,target,time,detail,content\n首响,客户A,2026-09-01T10:00:00,超时,内容\n",
                                            encoding="utf-8")
    (out / "payment_ledger.csv").write_text("amount,who,time,type,note\n99,客户A,2026-09-01 10:00,转账,货款\n",
                                            encoding="utf-8")
    (out / "revoke_audit.csv").write_text("sender,content,time,file\n张三,撤回消息,2026-09-01 10:00,c.txt\n",
                                          encoding="utf-8")
    (out / "funnel.csv").write_text("stage,customer,trigger,time\n询价,客户A,多少钱,2026-09-01 10:00\n",
                                    encoding="utf-8")
    (out / "insight_level.csv").write_text("level,topic,count,reason\nP0,物流慢,3,投诉\n", encoding="utf-8")
    (out / "timeline.json").write_text(json.dumps([{
        "session": "2026-09-01T10:00:00", "customer": "客户A",
        "nodes": [{"time": "10:00", "sender": "客户A", "content": "多少钱", "stage": "询价",
                   "is_staff": False, "latency_min": 130}]}]), encoding="utf-8")
    (out / "media_manifest.csv").write_text("file,line,kind,note\na.txt,[图片],image,占位\n", encoding="utf-8")
    (out / "mentions.csv").write_text("userid,count,by_who,last_time\n张三,3,李四,2026-09-01 10:00\n",
                                      encoding="utf-8")
    (out / "messages.csv").write_text("msg_id,sender,content,time\na,张三,内容,2026-09-01 10:00\n",
                                      encoding="utf-8")
    (out / "trend.md").write_text("## 环比\n- 消息 +10%\n", encoding="utf-8")

    html = rh.render(out, title="组合看板")
    for token in ("组合看板", "有效回复统计", "张三 · 2026-09-01", "发货/物流", "待跟进",
                  "询价未回复", "知识库沉淀", "绩效考核", "需求洞察", "质检信号",
                  "沟通行为指标", "挂起队列", "SLA", "满意度", "健康分", "SOP",
                  "销售漏斗", "P0", "@提及", "会话时间线", "周期环比", "多模态占位"):
        assert token in html, f"{token} 未渲染"
    # assessment_notes 超长截断
    assert "…（截断" in html
