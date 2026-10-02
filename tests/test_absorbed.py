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


# ---- P1-⑦ 按时段压缩聊天文本 ----

def test_compact_chat_buckets():
    msgs = [_msg("张三", "第一批已发", t="2026-09-01 10:35"),
            _msg("李四", "我这边跟进了", t="2026-09-01 10:37"),
            _msg("张三", "客户收到货了", t="2026-09-01 11:00")]
    out = biz.compact_chat(msgs)
    assert "10:35~10:37" in out and "11:00" in out
    assert "张三:第一批已发" in out and "李四:我这边跟进了" in out
    # 跨 10 分钟窗口不合并
    assert out.count("[") == 2


def test_llm_compact_staff_only_and_truncate():
    msgs = [_msg("客户A", "多少钱", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "今天价格是 100，明天有活动", t="2026-09-01 10:05")]
    out = biz._llm_compact(msgs, limit_chars=20)
    assert "客户A" not in out  # 只留员工
    assert len(out) <= 20


# ---- P1-⑧ 需求洞察 ----

def test_extract_insights_groups_pain_points():
    msgs = [_msg("客户A", "这个太贵了，能不能便宜点", staff=False, t="2026-09-01 10:00"),
            _msg("客户B", "发货太慢了，迟迟不到", staff=False, t="2026-09-01 10:05"),
            _msg("客户C", "收到货是破的，质量差", staff=False, t="2026-09-01 10:10"),
            _msg("张三", "正常报价，不议价", t="2026-09-01 10:20")]
    ins = biz.extract_insights(msgs, top_n=5)
    assert ins, "应聚类出痛点"
    by_topic = {r["topic"]: r for r in ins}
    assert set(by_topic) >= {"价格/议价", "发货/物流", "质量/破损"}, "三条痛点各归其类"
    assert any("客户A" in e for e in by_topic["价格/议价"]["evidence"])


def test_extract_insights_all_staff_question_fallback():
    # --staff all 全员员工：带问句的消息（转述客户问题）也算
    msgs = [_msg("张三", "客户说太贵了，要降价吗？", t="2026-09-01 10:00"),
            _msg("李四", "今天订单都发出去了", t="2026-09-01 10:05")]
    ins = biz.extract_insights(msgs, top_n=5)
    topics = [r["topic"] for r in ins]
    assert "价格/议价" in topics  # 问句命中痛点


# ---- P1-⑨ 关键对话气泡 ----

def test_extract_dialogues_pairs():
    msgs = [_msg("客户A", "在吗？想退款", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "亲，可以的，我马上处理", t="2026-09-01 10:03"),
            _msg("客户B", "物流到哪了", staff=False, t="2026-09-01 10:05"),
            _msg("李四", "已发出，单号私发您", t="2026-09-01 10:06")]
    pairs = biz.extract_dialogues(msgs)
    assert len(pairs) == 2
    assert pairs[0]["customer"]["sender"] == "客户A"
    assert pairs[0]["staff"]["sender"] == "张三"


def test_extract_dialogues_all_staff_question():
    msgs = [_msg("张三", "客户问还有货吗？", t="2026-09-01 10:00"),
            _msg("李四", "有，库存充足", t="2026-09-01 10:02")]
    pairs = biz.extract_dialogues(msgs)
    assert len(pairs) == 1
    assert pairs[0]["staff"]["sender"] == "李四"


# ---- P1-⑩ 客服质检信号 ----

def test_signal_stats_four_types_and_confidence():
    msgs = [_msg("张三", "客户已下单，谢谢支持", t="2026-09-01 10:00"),
            _msg("张三", "客户投诉发货太慢", t="2026-09-01 10:05"),
            _msg("李四", "我提交了工单走流程", t="2026-09-01 10:06"),
            _msg("李四", "麻烦您提供订单号", t="2026-09-01 10:07")]
    rows = biz.signal_stats(msgs)
    by = {r["userid"]: r for r in rows}
    assert by["张三"]["success"] == 1 and by["张三"]["frustration"] == 1
    assert by["李四"]["workflow"] == 1 and by["李四"]["request"] == 1
    assert by["张三"]["confidence"] in ("高", "中", "低")


# ---- P1-⑪ 知识库自动分类归档 ----

def test_classify_info_type():
    assert biz.classify_info_type("明天记得跟进这个订单") == "任务待办"
    assert biz.classify_info_type("截止到周五前交") == "截止日期"
    assert biz.classify_info_type("我电话 13800138000") == "电话"
    assert biz.classify_info_type("收货地址发我一下") == "地址"
    assert biz.classify_info_type("价格是 500 元") == "金额交易"
    assert biz.classify_info_type("文档我发群里了") == "重要文件"


def test_knowledge_frontmatter_and_info_types():
    msgs = [_msg("客户A", "这个多少钱？", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "500 元，包邮", t="2026-09-01 10:03")]
    entries, train, ob = biz.build_knowledge(msgs, mask=True)
    assert entries, "应生成知识条目"
    e = entries[0]
    assert e["content"].startswith("---")
    assert "source: group-chat" in e["content"]
    assert "info_types:" in e["content"]
    assert "金额交易" in e["info_types"]
    row = train.splitlines()[0]
    assert "info_types" in row


# ---- P1-⑫ wx-cli 探测 + 增量过滤 ----

def test_detect_wx_cli_returns_existing_or_empty():
    import shutil
    got = biz.detect_wx_cli()
    if shutil.which("wx-cli") or shutil.which("wechat-cli"):
        assert got
    else:
        assert got == ""


def test_filter_incremental_uses_anchor(tmp_path):
    msgs = [_msg("张三", "第一批已发", t="2026-09-01 10:00"),
            _msg("张三", "第二批准备中", t="2026-09-02 09:30")]
    biz.update_memory_layer(tmp_path, msgs)
    new_msgs = [_msg("张三", "第二批准备中（旧）", t="2026-09-01 09:00"),
                _msg("张三", "第二批已发出", t="2026-09-02 10:00")]
    new, skipped = biz.filter_incremental(new_msgs, tmp_path)
    assert skipped == 1 and len(new) == 1
    assert new[0]["content"] == "第二批已发出"


# ---- P2-⑭ 沟通行为量化指标 ----

def test_behavior_metrics():
    msgs = [_msg("客户A", "在吗", staff=False, t="2026-09-01 10:00"),
            _msg("张三", "在的，亲", t="2026-09-01 10:05"),
            _msg("张三", "有什么可以帮您？", t="2026-09-01 10:06")]
    bm = biz.behavior_metrics(msgs)
    assert bm["responses"] == 1
    assert abs(bm["avg_response_min"] - 5.0) < 0.1
    assert bm["question_rate"] >= 50


# ---- P2-⑮ 检索质量门 ----

def test_verify_summary_mark_source():
    msgs = [_msg("张三", "今天发货 5 单，都签收了", t="2026-09-01 10:00")]
    md = "- 今天发货 5 单，都签收了\n- 客户都满意\n"
    out = biz.verify_summary(md, msgs)
    assert "[可溯源]" in out
    assert "[待核对]" in out


# ---- P2-⑰ 员工成长分析报告 ----

def test_build_growth_report_from_profiles(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir(parents=True)
    (prof / "张三.md").write_text(
        "# 员工画像：张三\n\nname: 张三\nrole: 员工\nfirst_seen: 2026-08-01T09:00:00\n"
        "last_seen: 2026-09-02T18:00:00\ntotal_messages: 50\neffective: 40\n\n"
        "- 处理了批量订单\n- 客户好评率高\n", encoding="utf-8")
    out = biz.build_growth_report(tmp_path)
    assert "张三" in out and "观察周期" in out and "50" in out
    assert "评分" not in out or "不写评分结论" in out  # 不自动下结论
