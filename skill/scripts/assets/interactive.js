// chat-archive report 交互层（P0-1：Tab 导航 / 全局搜索 / 表格排序；P0-2：ECharts 三件套；P0-3：消息回放过滤）
(function () {
  var NAV = [
    ["经营", "01 有效回复统计", "02 员工工作日报", "03 讨论要点", "04 丢单商机风险", "05 待跟进事项"],
    ["团队", "06 群活跃度", "07 知识库沉淀", "08 AI监督绩效考核"],
    ["客户", "09 需求洞察", "10 客服质检信号", "11 待回复挂起队列", "12 SLA分诊", "13 丢单健康分", "14 SOP合规审计"],
    ["洞察", "15 销售漏斗", "16 会话时间线", "17 @提及与消息明细", "18 年度分析与成员档案", "19 消息类型与互动网络"],
    ["图表", "20 交互图表看板"],
    ["回放", "21 消息回放时间线"]
  ];
  var nav = document.createElement("nav");
  nav.className = "ca-nav";
  NAV.forEach(function (g) {
    var span = document.createElement("span");
    span.className = "ca-group";
    var lab = document.createElement("b");
    lab.textContent = g[0];
    span.appendChild(lab);
    g.slice(1).forEach(function (t) {
      var a = document.createElement("a");
      a.textContent = t;
      a.onclick = function (e) {
        e.preventDefault();
        var s = document.getElementById("sec-" + t.slice(0, 2));
        if (s) {
          s.scrollIntoView({ behavior: "smooth", block: "start" });
          s.classList.add("flash");
          setTimeout(function () { s.classList.remove("flash"); }, 1200);
        }
      };
      span.appendChild(a);
    });
    nav.appendChild(span);
  });
  document.body.insertBefore(nav, document.body.firstChild);

  var sh = document.createElement("div");
  sh.className = "ca-search";
  sh.innerHTML = '<input id="ca-q" type="text" placeholder="搜索全部模块（关键词 / 人名 / 群名）…"><span id="ca-qc" class="num"></span>';
  var head = document.querySelector(".masthead");
  if (head) { head.parentNode.insertBefore(sh, head.nextSibling); } else { document.body.appendChild(sh); }
  var q = document.getElementById("ca-q"), qc = document.getElementById("ca-qc");
  q.addEventListener("input", function () {
    var k = q.value.trim().toLowerCase(), n = 0;
    document.querySelectorAll("section.ca-sec").forEach(function (s) {
      var hit = s.textContent.toLowerCase().indexOf(k) > -1;
      s.style.borderColor = hit ? "#e8b339" : "transparent";
      if (hit) { n++; s.scrollIntoView({ block: "nearest" }); }
    });
    qc.textContent = k ? ("命中 " + n + " 个模块") : "";
  });

  document.querySelectorAll("table.sortable th").forEach(function (th) {
    th.style.cursor = "pointer";
    th.title = "点击排序";
    th.addEventListener("click", function () {
      var tb = th.closest("table").querySelector("tbody");
      if (!tb) { return; }
      var rows = Array.prototype.slice.call(tb.rows);
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var asc = th.dataset.asc !== "1";
      rows.sort(function (a, b) {
        var x = a.cells[idx] ? a.cells[idx].textContent.trim() : "";
        var y = b.cells[idx] ? b.cells[idx].textContent.trim() : "";
        var nx = parseFloat(x), ny = parseFloat(y);
        var r = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y, "zh") : nx - ny;
        return asc ? r : -r;
      });
      rows.forEach(function (r) { tb.appendChild(r); });
      th.dataset.asc = asc ? "1" : "0";
    });
  });

  var data = null;
  var cd = document.getElementById("ca-data");
  if (cd) {
    try { data = JSON.parse(cd.textContent); } catch (e) { data = null; }
  }
  if (window.echarts && data) {
    var cal = data.daily || [], st = data.sender_type || [], it = data.interactions || [];
    var calDom = document.getElementById("ch-cal");
    if (calDom && cal.length) {
      var calMax = 1;
      cal.forEach(function (x) { if ((+x.total || 0) > calMax) { calMax = +x.total; } });
      echarts.init(calDom).setOption({
        tooltip: {},
        visualMap: {
          min: 0, max: calMax, calculable: true, orient: "horizontal",
          left: "center", bottom: 0,
          inRange: { color: ["#f6f1ea", "#c8d6c8", "#b3c6b3", "#7da37d", "#3f6f4f"] }
        },
        calendar: {
          range: cal[0].date + "|" + cal[cal.length - 1].date,
          cellSize: ["auto", 14], dayLabel: { firstDay: 1 }, monthLabel: { nameMap: "cn" }
        },
        series: [{
          type: "heatmap", coordinateSystem: "calendar",
          data: cal.map(function (x) { return [x.date, +x.total || 0]; })
        }]
      });
    }
    var skDom = document.getElementById("ch-sankey");
    if (skDom && st.length) {
      var senders = [], seen = {}, types2 = [], seen2 = {};
      st.forEach(function (r) {
        if (!seen[r.sender]) { seen[r.sender] = 1; senders.push(r.sender); }
        if (!seen2[r.type]) { seen2[r.type] = 1; types2.push(r.type); }
      });
      echarts.init(skDom).setOption({
        series: [{
          type: "sankey", left: 20, right: 20, top: 10, bottom: 10,
          data: senders.map(function (s) { return { name: s }; })
                .concat(types2.map(function (t) { return { name: t }; })),
          links: st.map(function (r) { return { source: r.sender, target: r.type, value: +r.count || 0 }; }),
          label: { fontSize: 11 }
        }]
      });
    }
    var grDom = document.getElementById("ch-graph");
    if (grDom && it.length) {
      var nodes = {}, links = [];
      it.forEach(function (r) {
        ["from", "to"].forEach(function (k) {
          var nm = r[k];
          if (nm && !nodes[nm]) { nodes[nm] = { name: nm }; }
        });
        links.push({ source: r.from, target: r.to, value: +r.count || 1 });
      });
      echarts.init(grDom).setOption({
        tooltip: {},
        series: [{
          type: "graph", layout: "force", roam: true,
          data: Object.keys(nodes).map(function (k) { return nodes[k]; }),
          links: links, force: { repulsion: 180 },
          label: { show: true, fontSize: 10 }, lineStyle: { opacity: 0.4 }
        }]
      });
    }
  } else if (document.getElementById("ca-charts")) {
    document.getElementById("ca-charts").insertAdjacentHTML(
      "afterbegin",
      '<p class="tag">ECharts 组件缺失（未找到 echarts.min.js），以下图表不可用；其他功能不受影响。</p>'
    );
  }

  var tlq = document.getElementById("tl-q");
  if (tlq) {
    function apply() {
      var k = tlq.value.trim().toLowerCase();
      document.querySelectorAll(".tl-msg").forEach(function (m) {
        var s = m.dataset.sender;
        var showMem = null;
        document.querySelectorAll(".tl-mem input").forEach(function (cb) {
          if (cb.value === s) { showMem = cb; }
        });
        var okMem = !showMem || showMem.checked;
        var okTxt = !k || (m.dataset.text || "").toLowerCase().indexOf(k) > -1;
        m.style.display = (okMem && okTxt) ? "" : "none";
      });
      document.querySelectorAll(".tl-day").forEach(function (d) {
        var vis = false;
        d.querySelectorAll(".tl-msg").forEach(function (m) {
          if (m.style.display !== "none") { vis = true; }
        });
        d.style.display = vis ? "" : "none";
      });
    }
    tlq.addEventListener("input", apply);
    document.querySelectorAll(".tl-mem input").forEach(function (cb) {
      cb.addEventListener("change", apply);
    });
    apply();
  }
})();
