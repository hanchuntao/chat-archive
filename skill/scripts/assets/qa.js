// P1-2 群聊问答框：本地关键词检索（假聊天真搜索，数据不出本机）
// 由 render_html.py 在渲染时拼入 _INTERACTIVE_JS 的 /*__QA__*/ 占位处
(function () {
  var qaq = document.getElementById("qa-q");
  var cd = document.getElementById("ca-data");
  if (!qaq || !cd) { return; }
  var data = null;
  try { data = JSON.parse(cd.textContent); } catch (e) { data = null; }
  if (!data) { return; }
  var qout = document.getElementById("qa-out");
  var qbtn = document.getElementById("qa-run");

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function runQa() {
    var q = qaq.value.trim();
    if (!q) { qout.innerHTML = ""; return; }
    var terms = q.split(/[\s,，。？！、;；]+/).filter(function (t) { return t.length > 0; });
    var msgs = data.msgs || [];
    var andHits = [], orHits = [];
    for (var i = 0; i < msgs.length; i++) {
      var m = msgs[i], cc = m.c || "", hit = 0;
      for (var j = 0; j < terms.length; j++) { if (cc.indexOf(terms[j]) > -1) { hit++; } }
      if (hit === terms.length) { andHits.push(m); }
      else if (hit > 0) { orHits.push(m); }
      if (andHits.length >= 15) { break; }
    }
    var picks = andHits.length >= 3 ? andHits : orHits.slice(0, 8);
    if (!picks.length) {
      qout.innerHTML = '<p class="tag">未找到相关消息，换个关键词试试（如 发货 / 报价 / 价格）</p>';
      return;
    }
    picks.sort(function (a, b) { return (a.t || "") < (b.t || "") ? 1 : -1; });
    var html = '<p class="tag">命中 ' + (andHits.length >= 3 ? andHits.length : orHits.length) + ' 条相关消息（按时间倒序）</p>';
    var shown = 0;
    for (var k = 0; k < picks.length && shown < 12; k++) {
      var mm = picks[k];
      var t = esc(mm.c || "");
      terms.forEach(function (term) {
        t = t.split(term).join('<mark>' + term + '</mark>');
      });
      html += '<div class="qa-item"><b>' + esc(mm.s || "?") + '</b> <span>' + esc(mm.t || "") +
              '</span><div>' + t + '</div></div>';
      shown++;
    }
    qout.innerHTML = html;
  }

  qbtn.addEventListener("click", runQa);
  qaq.addEventListener("keydown", function (e) { if (e.key === "Enter") { runQa(); } });
})();
