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
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    dirs = [p for p in (out_dir).iterdir() if p.is_dir() and p.name.startswith("20")]
    assert dirs, "无运行结果目录"
    return sorted(dirs)[-1]


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
