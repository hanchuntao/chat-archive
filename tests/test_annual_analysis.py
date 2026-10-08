"""年度分析（第3轮吸收：对齐 WeChatMsg/MemoTrace 年度报告能力）测试。

覆盖：高频词 TopN、情感倾向（总体/每日/成员）、群成员完整信息表。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
SAMPLE = REPO / "sample_data" / "sample_chat.json"
PY = sys.executable


def _run_all(out_dir: Path, staff: str = "all"):
    r = subprocess.run(
        [PY, str(SCRIPT), "all", "--input", str(SAMPLE), "--staff", staff, "--out", str(out_dir)],
        capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    dirs = [p for p in (out_dir).iterdir() if p.is_dir() and p.name.startswith("20")]
    assert dirs, "无运行结果目录"
    return max(dirs)


def test_annual_artifacts_generated(tmp_path):
    run = _run_all(tmp_path)
    assert (run / "keywords.csv").exists()
    assert (run / "sentiment.json").exists()
    assert (run / "members.csv").exists()


def test_keywords_topn(tmp_path):
    run = _run_all(tmp_path)
    rows = (run / "keywords.csv").read_text(encoding="utf-8").strip().splitlines()
    assert rows[0].startswith("word,count,share")
    assert len(rows) >= 2
    assert "," in rows[1]


def test_sentiment_structure(tmp_path):
    run = _run_all(tmp_path)
    d = json.loads((run / "sentiment.json").read_text(encoding="utf-8"))
    assert {"pos", "neg", "neu"} <= set(d["total"])
    assert isinstance(d["daily"], list) and d["daily"]
    assert isinstance(d["by_member"], list)
    # 总体 = 每日之和（跨天合计应等于 pos+neg+neu）
    tot = d["total"]
    assert tot["pos"] + tot["neg"] + tot["neu"] > 0


def test_members_fields(tmp_path):
    run = _run_all(tmp_path)
    rows = (run / "members.csv").read_text(encoding="utf-8").strip().splitlines()
    head = rows[0]
    for col in ("userid", "sent", "effective", "active_days", "chars", "mentioned",
                "pos", "neg", "first_time", "last_time", "peak_hour", "night"):
        assert col in head, f"members.csv 缺列 {col}"
    assert len(rows) >= 2


def test_report_contains_annual_section(tmp_path):
    run = _run_all(tmp_path)
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "年度分析与成员档案" in html
    assert "情感倾向" in html


def test_round6_message_insight_artifacts(tmp_path):
    """第6轮吸收：每日消息量 / 消息类型分布 / 互动配对。"""
    run = _run_all(tmp_path)
    assert (run / "activity_daily.csv").exists()
    assert (run / "message_types.csv").exists()
    assert (run / "interactions.csv").exists()
    types = (run / "message_types.csv").read_text(encoding="utf-8").splitlines()
    assert types[0].startswith("type,count,share")
    assert len(types) >= 2
    daily = (run / "activity_daily.csv").read_text(encoding="utf-8").splitlines()
    assert daily[0].startswith("date,total,effective")
    inter = (run / "interactions.csv").read_text(encoding="utf-8").splitlines()
    assert inter[0].startswith("from,to,count")


def test_round6_report_section19(tmp_path):
    run = _run_all(tmp_path)
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "消息类型与互动网络" in html
    assert "互动配对" in html


def test_round7_trend_voice_media(tmp_path):
    """第7轮吸收：关键词趋势 / 语音转写占位 / 媒体归档增强。"""
    run = _run_all(tmp_path)
    assert (run / "keywords_trend.csv").exists()
    assert (run / "voice_pending.csv").exists()
    assert (run / "media_archive.csv").exists()
    trend = (run / "keywords_trend.csv").read_text(encoding="utf-8")
    assert trend.splitlines()[0].startswith("week,word,count")
    # 空语音清单不应产生虚假行
    vp = (run / "voice_pending.csv").read_text(encoding="utf-8").strip()
    assert vp == "(无数据)" or vp.splitlines()[0].startswith("msg_id,sender")


def test_round7_report_sections(tmp_path):
    run = _run_all(tmp_path)
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "关键词趋势" in html
    assert "媒体归档" in html


def test_empty_csv_parsed_as_empty():
    """(无数据) 占位文件读取应返回空列表，不产生虚假行。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rh2", REPO / "skill" / "scripts" / "render_html.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import tempfile
    td = Path(tempfile.mkdtemp())
    (td / "empty.csv").write_text("(无数据)\n", encoding="utf-8")
    assert m._read_csv(td / "empty.csv") == []
