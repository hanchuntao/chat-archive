"""吸收能力测试（P0-1..P0-6）：
跨次运行记忆层 / 昵称歧义消解 / 四分类摘要规则版 / 证据化考核 / 群活跃度 / 丢单信号。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"


def _load_biz():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("ca_biz_absorbed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


biz = _load_biz()


def _msg(sender: str, content: str, staff: bool = True, t: str = "2026-09-01 10:00") -> dict:
    return {"msg_id": sender + content[:4], "group_id": "g", "group_name": "客户群",
            "sender": sender, "is_staff": staff, "content": content,
            "sent_at": biz._parse_dt(t) or datetime.now()}


# ---- P0-1 跨次运行记忆层 ----

def test_memory_history_anchor(tmp_path):
    msgs = [_msg("张三", "今天发货 5 单，都签收了", t="2026-09-01 10:00"),
            _msg("张三", "明天有一批要发", t="2026-09-02 09:30")]
    st = biz.update_memory_layer(tmp_path, msgs)
    hist = biz.load_history(tmp_path)
    g = hist["groups"]["g"]
    assert g["last_message_time"] == "2026-09-02T09:30:00"
    assert g["first_seen"] == "2026-09-01T10:00:00"
    assert g["batches"] >= 1
    assert "张三" in g["members"]
    assert st["groups"] >= 1


def test_memory_profiles_only_after_3(tmp_path):
    msgs = [_msg("李四", f"有效回复第{i}条，内容正常" , t=f"2026-09-01 10:0{i}") for i in range(3)]
    biz.update_memory_layer(tmp_path, msgs)
    profs = list((tmp_path / "profiles").glob("*.md"))
    assert len(profs) == 1
    txt = profs[0].read_text(encoding="utf-8")
    assert "total_messages: 3" in txt
    assert "name: 李四" in txt


def test_memory_profile_append_only(tmp_path):
    msgs1 = [_msg("王五", f"第一条实质消息 {i}", t=f"2026-09-01 10:0{i}") for i in range(3)]
    biz.update_memory_layer(tmp_path, msgs1)
    profs = list((tmp_path / "profiles").glob("*.md"))
    before = profs[0].read_text(encoding="utf-8")
    msgs2 = [_msg("王五", "第二条实质消息", t="2026-09-02 10:00"),
             _msg("王五", "第三条实质消息", t="2026-09-02 10:01")]
    biz.update_memory_layer(tmp_path, msgs2)
    after = profs[0].read_text(encoding="utf-8")
    assert "第二条实质消息" in after          # 新金句追加
    assert "第一条实质消息 0" in after        # 旧金句保留（append-only，不回写）
    assert "total_messages: 5" in after       # frontmatter 跨批累计
    assert "last_seen: 2026-09-02" in after   # last_seen 更新
    assert before.split("## 金句")[-1].strip() in after


def test_memory_facts_dedup(tmp_path):
    m1 = [_msg("张三", "价格是 100 元每件", t="2026-09-01 10:00")]
    m2 = [_msg("张三", "价格是 100 元每件", t="2026-09-02 10:00")]
    biz.update_memory_layer(tmp_path, m1)
    biz.update_memory_layer(tmp_path, m2)
    mem = (tmp_path / "memory.md").read_text(encoding="utf-8")
    assert mem.count("价格是 100 元每件") == 1


def test_memory_skips_instructions(tmp_path):
    msgs = [_msg("张三", "请帮我查一下昨天的单", t="2026-09-01 10:00"),
            _msg("张三", "好的", t="2026-09-01 10:01")]
    biz.update_memory_layer(tmp_path, msgs)
    mem = (tmp_path / "memory.md").read_text(encoding="utf-8") if (tmp_path / "memory.md").exists() else ""
    assert "请帮我" not in mem


# ---- P0-2 昵称歧义消解 ----

def test_lowinfo_names():
    assert biz.is_lowinfo_name("")
    assert biz.is_lowinfo_name("nil")
    assert biz.is_lowinfo_name("test")
    assert biz.is_lowinfo_name("user")
    assert biz.is_lowinfo_name("👍")
    assert biz.is_lowinfo_name("张")
    assert biz.is_lowinfo_name("...")
    assert not biz.is_lowinfo_name("张三丰")
    assert not biz.is_lowinfo_name("客户A")


def test_resolve_ambiguous_skips_staff(tmp_path):
    staff_file = tmp_path / "staff.txt"
    staff_file.write_text("张三\n", encoding="utf-8")
    staff = biz.load_staff(str(staff_file), "")
    alias = biz.load_staff_aliases(str(staff_file), "")
    msgs = [_msg("张三", "明天发", staff=True, t="2026-09-01 10:00"),
            _msg("nil", "多少钱一件", staff=False, t="2026-09-01 10:01"),
            _msg("客户A", "有货吗", staff=False, t="2026-09-01 10:02")]
    n = biz.resolve_ambiguous_names(msgs, staff, alias)
    assert n == 1
    assert msgs[0]["sender"] == "张三"          # 员工不动
    assert msgs[1]["sender"].startswith("nil（")  # 占位符标注 ID 后 4 位
    assert msgs[2]["sender"] == "客户A"          # 正常昵称不动


# ---- P0-3 四分类摘要（规则版） ----

def test_decisions_unresolved():
    msgs = [_msg("张三", "发货方案就按这个定了，明天执行", t="2026-09-01 10:00"),
            _msg("李四", "价格还没定，待确认", t="2026-09-01 10:01"),
            _msg("王五", "收到", t="2026-09-01 10:02")]
    dec, un = biz.build_decisions_unresolved(msgs)
    assert len(dec) == 1 and "定了" in dec[0]["content"]
    assert len(un) == 1 and "待" in un[0]["content"]


def test_append_four_class_section():
    msgs = [_msg("张三", "就这样定了，周五上线", t="2026-09-01 10:00")]
    md = "# 群讨论要点总结\n\n（无）\n"
    out = biz.append_four_class_section(md, msgs)
    assert "## 核心决策" in out
    assert "周五上线" in out


# ---- P0-4 证据化考核 ----

def test_assessment_notes_evidence_and_rating_blank():
    msgs = [_msg("张三", "您下单的话今天就给您发货", staff=True, t="2026-09-01 10:00"),
            _msg("李四", "在吗？我想买两件", staff=False, t="2026-09-01 10:01"),
            _msg("张三", "好的收到", staff=True, t="2026-09-01 10:02")]
    results = [{"userid": "张三", "final_score": 105, "base_score": 100,
                "timeout_count": 0, "unanswered_count": 1, "violation_count": 0, "filler_rate": 0}]
    unanswered = [_msg("李四", "在吗？我想买两件", staff=False, t="2026-09-01 10:01")]
    notes = biz.build_assessment_notes(msgs, results, unanswered, [])
    assert "证据引用" in notes
    assert "需人工判断" in notes
    assert "Rating（主管填写）" in notes
    assert "您下单的话今天就给您发货" in notes


# ---- P0-5 群活跃度 ----

def test_activity_stats():
    msgs = [_msg("张三", "消息1", t="2026-09-01 09:00"),
            _msg("张三", "收到", t="2026-09-01 09:10"),
            _msg("张三", "消息3", t="2026-09-01 23:30"),
            _msg("李四", "消息4", t="2026-09-01 15:00")]
    rows = {r["userid"]: r for r in biz.activity_stats(msgs)}
    assert rows["张三"]["sent"] == 3
    assert rows["张三"]["effective"] == 2
    assert rows["张三"]["night"] == 1
    assert rows["张三"]["active_days"] == 1
    assert rows["张三"]["peak_hour"] == "23:00" or rows["张三"]["peak_hour"] == "09:00"
    summ = biz.activity_summary(msgs)
    assert summ["senders"] == 2
    assert summ["total"] == 4
    assert summ["top"][0]["userid"] == "张三"


# ---- P0-6 丢单/商机信号 ----

def test_inquiry_unanswered():
    msgs = [_msg("客户", "这个多少钱？有货吗", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "收到", staff=True, t="2026-09-01 10:01")]  # 口水不算回复
    inq, prom = biz.tag_deal_signals(msgs)
    assert len(inq) == 1
    assert "多少钱" in inq[0]["content"]


def test_promise_pending():
    msgs = [_msg("张三", "明天发，放心", staff=True, t="2026-09-01 10:00")]
    inq, prom = biz.tag_deal_signals(msgs)
    assert len(prom) == 1
    assert "承诺" in prom[0]["content"] or "明天发" in prom[0]["content"]


def test_inquiry_answered_not_flagged():
    msgs = [_msg("客户", "多少钱一件", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "99 元，今天下单今天发", staff=True, t="2026-09-01 10:02")]
    inq, _ = biz.tag_deal_signals(msgs)
    assert len(inq) == 0
