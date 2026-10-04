"""第三轮补测：render_html/sync_kb/report/ingest/search/clean 剩余分支到 ≥95%。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"


def _load(name: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rh = _load("skill/scripts/render_html.py", "ca_rh_topup")
sk = _load("skill/scripts/sync_kb.py", "ca_sk_topup")
biz = _load("skill/scripts/chat_archive.py", "ca_biz_topup")


def _write(out: Path, rel: str, text: str):
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _base_out(out: Path):
    (out / "daily_reports").mkdir(parents=True, exist_ok=True)
    _write(out, "daily_reports/张三_2026-09-01.md",
           "# 张三 工作日报（2026-09-01）\n\n## 一、实际工作内容\n\n- 10:00 发货 200 单\n")
    _write(out, "daily_reports/李四_2026-09-01.md",
           "# 李四 工作日报（2026-09-01）\n\n## 二、规范与时效\n\n- 09:30 超时 30 分钟回复\n")
    _write(out, "effective_stats.csv", "userid,sent,effective,filler,filler_rate\n张三,4,3,1,25\n")
    _write(out, "followups.csv",
           "group,content,assignee,due,source,time,unanswered,type\n"
           "群,承诺补发,张三,2000-01-01,客户A,2026-09-01 10:00,false,承诺待兑现\n"
           "群,漏回复事项,张三,,客户A,2026-09-01 10:00,true,漏回复\n")
    _write(out, "activity.csv",
           "userid,sent,effective,filler,active_days,peak_hour,night\n张三,4,3,1,2,20,6\n")
    _write(out, "behavior.csv", "avg_response_min,responses,question_rate,statement_rate\n98.0,12,23,77\n")
    _write(out, "assessment.csv",
           "userid,base_score,final_score,sent,effective,filler_rate,timeout_count,unanswered_count,violation_count,hits,deductions\n"
           "张三,100,95,4,3,25,0,0,1,\"[]\",\"{}\"\n")
    _write(out, "assessment_notes.md", "证据化评语" + "x" * 4200)
    _write(out, "signal.csv",
           "userid,total,success,frustration,workflow,request,signal_count,confidence\n张三,4,1,2,1,0,4,80\n")
    _write(out, "dialogues.json", "{bad json")
    _write(out, "timeline.json", "{bad json")
    _write(out, "knowledge/发货_物流.md",
           "# 发货/物流知识条目\n\n## 问答示例（已脱敏）\n\n问：多久到？\n答：1-3 天\n")
    _write(out, "insight.md", "## 物流慢（3 条）\n- 快递三天没到\n")
    _write(out, "pending.csv", "customer,content,time,group\n客户A,在吗,2026-09-01 10:00,群\n")
    _write(out, "satisfaction.csv", "customer,level,content,time\n客户A,positive,满意,2026-09-01 10:00\n")
    _write(out, "sla.csv", "customer,priority,first_reply,status,time\n客户A,P1,60,timeout,2026-09-01 10:00\n")
    _write(out, "health.csv", "customer,score,playbook,time\n客户A,55,优先回访,2026-09-01 10:00\n")
    _write(out, "sop_compliance.csv", "rule,target,time,detail,content\n首响,客户A,2026-09-01T10:00:00,超时,内容\n")
    _write(out, "payment_ledger.csv", "amount,who,time,type,note\n99,客户A,2026-09-01 10:00,转账,货款\n")
    _write(out, "revoke_audit.csv", "sender,content,time,file\n张三,撤回消息,2026-09-01 10:00,c.txt\n")
    _write(out, "funnel.csv", "stage,customer,trigger,time\n询价,客户A,多少钱,2026-09-01 10:00\n")
    _write(out, "insight_level.csv", "level,topic,count,reason\nP0,物流慢,3,投诉\n")
    _write(out, "mentions.csv", "userid,count,by_who,last_time\n张三,3,李四,2026-09-01 10:00\n")
    _write(out, "messages.csv", "msg_id,sender,content,time\na,张三,内容,2026-09-01 10:00\n")
    _write(out, "media_manifest.csv", "file,line,kind,note\na.txt,[图片],image,占位\n")
    _write(out, "discussion_summary.md", "## 发货/物流\n\n- 09-28 10:00 张三：快递单号已更新\n")
    _write(out, "sessions.csv", "start,end,customer,msgs,group\n2026-09-01T10:00:00,2026-09-01T10:02:00,客户A,2,群\n")
    _write(out, "trend.md", "## 环比\n- 消息 +10%\n")


# ============================================================ render_html

def test_render_html_remaining_branches(tmp_path):
    out = tmp_path / "o"
    _base_out(out)
    html = rh.render(out, title="看板T")
    # 规范与时效 hits
    assert "规范与时效" in html
    # 逾期 followup
    assert "已过期待复核" in html or "逾期" in html or "承诺待兑现" in html
    # 熬夜冠军 head
    assert "熬夜冠军" in html
    # 截断
    assert "…（截断" in html
    # 坏 JSON 不炸
    assert "<html" in html
    # 无 userid 的 signal 行跳过
    _write(out, "signal.csv",
           "userid,total,success,frustration,workflow,request,signal_count,confidence\n,4,1,2,1,0,4,80\n")
    assert "<html" in rh.render(out)


def test_render_html_parse_daily_missing():
    assert rh._parse_daily(Path("/nonexistent/x.md"))["name"] == "x"


def test_render_html_main_argv(tmp_path, monkeypatch):
    out = tmp_path / "o"
    _base_out(out)
    dest = tmp_path / "r.html"
    monkeypatch.setattr(sys, "argv", ["rh", "--out", str(out), "--title", "T2", "--output", str(dest)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rh.main()
    assert dest.exists() and "报告已生成" in buf.getvalue()
    monkeypatch.setattr(sys, "argv", ["rh", "--out", str(out), "--title", "T3"])
    with contextlib.redirect_stdout(io.StringIO()):
        rh.main()
    assert (out / "report.html").exists()


def test_render_html_trend_md_read_exception(tmp_path, monkeypatch):
    out = tmp_path / "o2"
    _base_out(out)
    import builtins
    real_open = builtins.open
    def _boom(*a, **k):
        if str(a[0]).endswith("trend.md"):
            raise OSError("boom")
        return real_open(*a, **k)
    monkeypatch.setattr(builtins, "open", _boom)
    html = rh.render(out)
    assert "<html" in html


# ============================================================ sync_kb

def test_sync_kb_remaining(monkeypatch, tmp_path):
    # load_config 坏文件
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    assert sk.load_config(str(bad)) == {}
    # _find_knowledge_base：name 空 + addable 列表 → 打印
    def _addable(path, body, c, k):
        assert body.get("cursor") is not None
        return {"code": 0, "data": {"addable_knowledge_base_list": [{"name": "A", "id": "1"}]}}
    monkeypatch.setattr(sk, "_ima_post", _addable)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        kb_id, err = sk._find_knowledge_base("c", "k", "")
    assert kb_id is None and err is None and "可添加的知识库" in buf.getvalue()
    # sync_ima：out/knowledge 不存在
    assert "不存在" in sk.sync_ima(tmp_path, {"ima": {"client_id": "c", "api_key": "k",
                                                    "knowledge_base_name": "KB"}})
    # sync_ima：上传失败计数
    out = tmp_path / "o"
    (out / "knowledge").mkdir(parents=True)
    (out / "knowledge" / "a.md").write_text("# A", encoding="utf-8")
    monkeypatch.setattr(sk, "_find_knowledge_base", lambda c, k, n: ("kb1", None))
    monkeypatch.setattr(sk, "_upload_file", lambda *a, **k: (False, "cos down"))
    summary = sk.sync_ima(out, {"ima": {"client_id": "c", "api_key": "k",
                                        "knowledge_base_name": "KB"}})
    assert "失败" in summary and "cos down" in summary
    # main() 入口
    monkeypatch.setattr(sys, "argv", ["sk", "--out", str(out), "--to", "local"])
    with contextlib.redirect_stdout(io.StringIO()):
        sk.main()


# ============================================================ 数据层小缺口

def test_report_query_window_filters(tmp_path):
    from chat_archive import report as rp
    db = tmp_path / "t.db"
    from chat_archive.db import Database
    dm = Database(str(db))
    dm.insert_message({"msg_id": "m1", "chat_id": "g1", "sender": "张三",
                        "time": "2026-09-01 10:00:00", "content": "内容一"})
    dm.insert_message({"msg_id": "m2", "chat_id": "g2", "sender": "李四",
                        "time": "2026-09-01 12:00:00", "content": "内容二"})
    # 全组合过滤
    rows = rp._query_window(dm, None, None, None)
    assert len(rows) == 2
    rows = rp._query_window(dm, "g1", None, None)
    assert len(rows) == 1
    rows = rp._query_window(dm, None, "2026-09-01 11:00:00", None)
    assert len(rows) == 1
    rows = rp._query_window(dm, None, None, "2026-09-01 09:00:00")
    assert rows == []


def test_report_empty_window_rule_report(tmp_path):
    from chat_archive import report as rp
    db = tmp_path / "t2.db"
    from chat_archive.db import Database
    dm = Database(str(db))
    md = rp.generate_report(dm, start_time="2026-09-01 00:00:00", end_time="2026-09-02 00:00:00")
    assert "无消息" in md or "无" in md


def test_report_render_llm_empty(tmp_path):
    from chat_archive import report as rp
    db = tmp_path / "t3.db"
    from chat_archive.db import Database
    dm = Database(str(db))
    md = rp._rule_report(dm, None, "2026-09-01 00:00:00", "2026-09-02 00:00:00", "标题")
    assert isinstance(md, str)


def test_ingest_redacted_and_hits(tmp_path, monkeypatch):
    from chat_archive.pipeline.desensitize import Desensitizer, Rule
    db = tmp_path / "t5.db"
    from chat_archive.db import Database
    dm = Database(str(db))
    bad = tmp_path / "bad.txt"
    bad.write_text("2026-09-01 10:00 张三: 正常内容\n",
                   encoding="utf-8")
    from chat_archive.pipeline.ingest import ingest_file

    # redact 策略命中（单元级）
    d2 = Desensitizer([Rule("r", "违禁", strategy="redact")])
    res = d2.apply("这是违禁词")
    assert res.redacted

    # ingest_file 的 redact 剔除分支（mock Desensitizer.apply 返回 redacted）
    class _FakeDR:
        def __init__(self, c):
            self.content, self.hits, self.redacted = c, {"r": 1}, True

    class _FakeD:
        def apply(self, content):
            return _FakeDR(content)

    monkeypatch.setattr("chat_archive.pipeline.ingest.Desensitizer", lambda: _FakeD())
    st = ingest_file(dm, bad, chat_id="g5")
    assert st.redacted == 1

    # desensitizer mask 命中
    d = Desensitizer()
    out = d.apply("手机 13812345678")
    assert out.hits and out.redacted is False


def test_search_chat_id_filter(tmp_path):
    from chat_archive import search as sr
    db = tmp_path / "t4.db"
    from chat_archive.db import Database
    dm = Database(str(db))
    dm.insert_message({"msg_id": "m1", "chat_id": "g1", "sender": "张三",
                        "time": "2026-09-01 10:00:00", "content": "内容一"})
    dm.insert_message({"msg_id": "m2", "chat_id": "g2", "sender": "李四",
                        "time": "2026-09-01 10:00:00", "content": "内容二"})
    hits = sr.search(dm, "内容", chat_id="g1")
    assert len(hits.rows) == 1 and hits.total == 1


def test_clean_emoji_and_filler_tokens():
    from chat_archive.pipeline import clean as cl
    assert cl.is_noise("😀😀😀") is True
    assert cl.is_noise("好的，收到") is True
    assert cl.is_noise("今天发货200单") is False
