// Benchmarks section: draws bench/results.json (tools/bench/report.py) with Apache ECharts.
(function () {
  "use strict";
  // Words for people in the page's language (main.js has the same; sitei18n.py fills MDM_I18N).
  function t(s) { return (window.MDM_I18N || {})[s] || s; }
  var root = document.getElementById("bench");
  if (!root || !window.fetch) return;
  var data = null;
  var metric = "transfer_ms";
  var charts = [];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function palette() {
    return {
      ink: css("--ink"),
      ink2: css("--ink-2"),
      ink3: css("--ink-3"),
      surface: css("--surface"),
      line: css("--line"),
      idm: css("--bench-idm"),
      mdm: css("--bench-mdm"),
      startup: css("--bench-startup"),
      transfer: css("--bench-transfer"),
      finish: css("--bench-finish"),
    };
  }
  function fmtMs(v) {
    if (v == null) return "—";
    if (v >= 10000) return (v / 1000).toFixed(1) + " s";
    if (v >= 1000) return (v / 1000).toFixed(2) + " s";
    return (v >= 100 ? v.toFixed(0) : v.toFixed(1)) + " ms";
  }
  var FONT = "Inter, ui-sans-serif, system-ui, sans-serif";
  var SHORT = { "fast-1g": "1 GiB", "capped-100m": "2 MB/s per connection", "latency-100m": "150 ms latency",
                "slowconn-32m": "A crawling connection", "maxconns-50m": "2 connections allowed",
                "drops-50m": "Cut connections", "small-256k": "A small file" };
  function onView(node, fn, threshold) {
    if (!("IntersectionObserver" in window)) return fn();
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) { io.disconnect(); fn(); }
    }, { threshold: threshold || 0.25 });
    io.observe(node);
  }
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Bars grow, dots fall in one after another.
  function motion(extra) {
    var o = { textStyle: { fontFamily: FONT }, animation: !still, animationDuration: 1100, animationEasing: "cubicOut",
              animationDurationUpdate: 600, animationEasingUpdate: "cubicInOut" };
    for (var k in extra) o[k] = extra[k];
    return o;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function values(sc, client, m) {
    return data.runs
      .filter(function (r) { return r.scenario === sc.id && r.client === client && !r.warmup && r.ok && r[m] != null; })
      .map(function (r) { return r[m]; });
  }
  function dispose() {
    charts.forEach(function (c) { c.dispose(); });
    charts = [];
  }

  // One small chart per scenario: every run as a dot, the box from Q1 to Q3, the median labelled.
  function drawScenarios() {
    var grid = root.querySelector("[data-bench-grid]");
    grid.innerHTML = "";
    var p = palette();
    data.scenarios.forEach(function (sc) {
      var card = el("article", "bench-card");
      var head = el("header");
      head.appendChild(el("h3", null, sc.title));
      var cmp = el("p", "bench-ratio");
      var a = sc.clients.IDM.stats[metric], b = sc.clients.MDM.stats[metric];
      if (sc.provisional) {
        // Numbers shown, no verdict: the scenario is being measured again.
        card.classList.add("is-provisional");
        cmp.appendChild(el("span", "bench-badge", t("Being re-measured")));
      } else if (a && b) {
        var r = a.median / b.median;
        cmp.innerHTML = r >= 1
          ? t("{ratio} faster").replace("{ratio}", "<b>" + r.toFixed(2) + "×</b>")
          : t("{ratio} slower").replace("{ratio}", "<b>" + (1 / r).toFixed(2) + "×</b>");
        if (metric === "e2e_ms" && sc.compare) {
          cmp.innerHTML += ' <span title="95% bootstrap interval of the ratio of medians; two-sided Mann–Whitney U">(' +
            sc.compare.ratio_ci95[0].toFixed(2) + "–" + sc.compare.ratio_ci95[1].toFixed(2) +
            ", p=" + sc.compare.mann_whitney_p + ")</span>";
        }
      }
      head.appendChild(cmp);
      card.appendChild(head);
      var box = el("div", "bench-chart");
      card.appendChild(box);
      if (sc.provisional) card.appendChild(el("p", "bench-why", sc.provisional));
      // Requests per run: the median, and the most when it is far above it (refused retries).
      var rq = function (c) {
        var st = sc.clients[c].stats.requests;
        if (!st) return "—";
        var med = Math.round(st.median), most = Math.round(st.max);
        return most > 2 * med ? med + " (up to " + most.toLocaleString("en-US") + ")" : String(med);
      };
      var foot = el("p", "bench-meta", "faults: " + sc.faults + " · n=" + (a ? a.n : 0) +
        " each · requests per run: IDM " + rq("IDM") + ", MDM " + rq("MDM"));
      card.appendChild(foot);
      grid.appendChild(card);

      var clients = ["IDM", "MDM"];
      var stats = clients.map(function (c) { return sc.clients[c].stats[metric]; });
      var far = clients.map(function (c) { return Math.max.apply(null, values(sc, c, metric).concat([0])); });
      onView(box, function () {
      var chart = echarts.init(box, null, { renderer: "svg" });
      charts.push(chart);
      chart.setOption(motion({
        grid: { left: 44, right: 70, top: 8, bottom: 26 },
        xAxis: {
          type: "value",
          min: 0,
          axisLabel: { color: p.ink3, fontSize: 11, formatter: function (v) { return fmtMs(v); } },
          splitLine: { lineStyle: { color: p.line } },
        },
        yAxis: {
          type: "category",
          data: clients,
          inverse: true,
          axisLabel: { color: p.ink, fontWeight: 600 },
          axisLine: { lineStyle: { color: p.line } },
          axisTick: { show: false },
        },
        tooltip: {
          trigger: "item",
          formatter: function (it) {
            if (it.seriesType === "scatter") return it.name + " run: " + fmtMs(it.value[0]);
            var s = stats[it.dataIndex];
            return s ? clients[it.dataIndex] + "<br>median " + fmtMs(s.median) + "<br>IQR " + fmtMs(s.q1) + "–" +
              fmtMs(s.q3) + "<br>mean " + fmtMs(s.mean) + " ± " + fmtMs(s.sd) + "<br>95% CI of median " +
              fmtMs(s.ci95_median[0]) + "–" + fmtMs(s.ci95_median[1]) : "";
          },
        },
        series: [
          {
            type: "custom",
            renderItem: function (params, api) {
              var i = api.value(0);
              var s = stats[i];
              if (!s) return null;
              var y = api.coord([0, i])[1];
              var x1 = api.coord([s.q1, i])[0], x3 = api.coord([s.q3, i])[0], xm = api.coord([s.median, i])[0];
              var h = 18;
              var color = i === 0 ? p.idm : p.mdm;
              return {
                type: "group",
                children: [
                  { type: "rect", shape: { x: x1, y: y - h / 2, width: Math.max(2, x3 - x1), height: h },
                    style: { fill: color, opacity: 0.22 } },
                  { type: "rect", shape: { x: xm - 1.5, y: y - h / 2 - 3, width: 3, height: h + 6 },
                    style: { fill: color } },
                  { type: "text", x: Math.max(xm, x3, api.coord([far[i], i])[0]) + 10, y: y,
                    style: { text: fmtMs(s.median), fill: p.ink, font: "600 12px " + FONT,
                             verticalAlign: "middle", backgroundColor: p.surface, padding: [1, 3], borderRadius: 3 },
                    z2: 10 },
                ],
              };
            },
            data: [[0], [1]],
            z: 1,
            animationDelay: 500,
          },
          {
            type: "scatter",
            symbolSize: 6,
            z: 2,
            data: [].concat(
              values(sc, "IDM", metric).map(function (v) { return { name: "IDM", value: [v, 0], itemStyle: { color: p.idm } }; }),
              values(sc, "MDM", metric).map(function (v) { return { name: "MDM", value: [v, 1], itemStyle: { color: p.mdm } }; })
            ),
            itemStyle: { opacity: 0.85 },
            animationDelay: function (i) { return i * 45; },
          },
        ],
      }));
      });
    });
  }

  // Where the time goes: startup, transfer and finish, median of each, per scenario and client.
  function drawPhases() {
    var box = root.querySelector("[data-bench-phases]");
    var p = palette();
    var cats = [];
    var parts = { startup_ms: [], transfer_ms: [], finish_ms: [] };
    data.scenarios.forEach(function (sc) {
      ["IDM", "MDM"].forEach(function (c) {
        cats.push((SHORT[sc.id] || sc.id) + " · " + c);
        Object.keys(parts).forEach(function (m) {
          var s = sc.clients[c].stats[m];
          parts[m].push(s ? Math.max(0, s.median) : 0);
        });
      });
    });
    onView(box, function () {
    var chart = echarts.init(box, null, { renderer: "svg" });
    charts.push(chart);
    var names = { startup_ms: "Startup (command → first request)", transfer_ms: "Transfer (first request → last byte)",
                  finish_ms: "Finish (last byte → file ready)" };
    var colors = { startup_ms: p.startup, transfer_ms: p.transfer, finish_ms: p.finish };
    chart.setOption(motion({
      legend: { top: 0, textStyle: { color: p.ink2 }, itemWidth: 12, itemHeight: 12 },
      grid: { left: 190, right: 40, top: 44, bottom: 30 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
                 valueFormatter: function (v) { return fmtMs(v); } },
      xAxis: { type: "log", logBase: 10, min: 1, axisLabel: { color: p.ink3, formatter: function (v) { return fmtMs(v); } },
               splitLine: { lineStyle: { color: p.line } } },
      yAxis: { type: "category", data: cats, inverse: true,
               axisLabel: { color: p.ink2, fontSize: 11 }, axisLine: { lineStyle: { color: p.line } }, axisTick: { show: false } },
      series: Object.keys(parts).map(function (m) {
        return { name: names[m], type: "bar", stack: "t", data: parts[m], barWidth: 12,
                 itemStyle: { color: colors[m], borderRadius: m === "finish_ms" ? [0, 3, 3, 0] : 0 },
                 animationDelay: function (i) { return i * 60 + (m === "transfer_ms" ? 250 : m === "finish_ms" ? 500 : 0); } };
      }),
    }));
    });
  }

  // CPU time and peak memory of each client during a run (medians).
  function drawResources() {
    var box = root.querySelector("[data-bench-res]");
    var p = palette();
    var ids = data.scenarios.map(function (s) { return SHORT[s.id] || s.id; });
    var med = function (c, m) {
      return data.scenarios.map(function (s) { var st = s.clients[c].stats[m]; return st ? st.median : null; });
    };
    onView(box, function () {
    var chart = echarts.init(box, null, { renderer: "svg" });
    charts.push(chart);
    var first = function (i) { return i * 80; }, second = function (i) { return 600 + i * 80; };
    chart.setOption(motion({
      legend: { top: 0, textStyle: { color: p.ink2 } },
      tooltip: { trigger: "axis" },
      grid: [{ left: 60, right: 20, top: 40, height: "32%" }, { left: 60, right: 20, top: "60%", height: "30%" }],
      xAxis: [
        { type: "category", data: ids, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: p.line } } },
        { type: "category", data: ids, gridIndex: 1, axisLabel: { color: p.ink2, fontSize: 11, interval: 0, width: 120, overflow: "break" },
          axisLine: { lineStyle: { color: p.line } } },
      ],
      yAxis: [
        { type: "value", gridIndex: 0, name: "CPU ms", nameTextStyle: { color: p.ink3 },
          axisLabel: { color: p.ink3 }, splitLine: { lineStyle: { color: p.line } } },
        { type: "value", gridIndex: 1, name: "peak MB", nameTextStyle: { color: p.ink3 },
          axisLabel: { color: p.ink3 }, splitLine: { lineStyle: { color: p.line } } },
      ],
      series: [
        { name: "IDM", type: "bar", data: med("IDM", "cpu_ms"), itemStyle: { color: p.idm, borderRadius: [3, 3, 0, 0] }, xAxisIndex: 0, yAxisIndex: 0, animationDelay: first },
        { name: "MDM", type: "bar", data: med("MDM", "cpu_ms"), itemStyle: { color: p.mdm, borderRadius: [3, 3, 0, 0] }, xAxisIndex: 0, yAxisIndex: 0, animationDelay: first },
        { name: "IDM", type: "bar", data: med("IDM", "peak_ws_mb"), itemStyle: { color: p.idm, borderRadius: [3, 3, 0, 0] }, xAxisIndex: 1, yAxisIndex: 1, animationDelay: second },
        { name: "MDM", type: "bar", data: med("MDM", "peak_ws_mb"), itemStyle: { color: p.mdm, borderRadius: [3, 3, 0, 0] }, xAxisIndex: 1, yAxisIndex: 1, animationDelay: second },
      ],
    }));
    });
  }

  function drawTable() {
    var tb = root.querySelector("[data-bench-table] tbody");
    tb.innerHTML = "";
    data.scenarios.forEach(function (sc) {
      ["IDM", "MDM"].forEach(function (c, k) {
        var st = sc.clients[c].stats;
        var tr = document.createElement("tr");
        var cells = [
          k === 0 ? sc.title : "",
          c,
          st.e2e_ms ? st.e2e_ms.n : 0,
          st.e2e_ms ? fmtMs(st.e2e_ms.median) + " (" + fmtMs(st.e2e_ms.q1) + "–" + fmtMs(st.e2e_ms.q3) + ")" : "—",
          st.e2e_ms ? fmtMs(st.e2e_ms.ci95_median[0]) + "–" + fmtMs(st.e2e_ms.ci95_median[1]) : "—",
          st.transfer_ms ? fmtMs(st.transfer_ms.median) : "—",
          st.startup_ms ? fmtMs(st.startup_ms.median) : "—",
          st.connections ? st.connections.median : "—",
          st.requests ? st.requests.median : "—",
          st.cpu_ms ? fmtMs(st.cpu_ms.median) : "—",
          st.peak_ws_mb ? st.peak_ws_mb.median + " MB" : "—",
          k === 0 ? (sc.provisional ? "re-measuring" : sc.compare ? sc.compare.mann_whitney_p : "") : "",
        ];
        cells.forEach(function (v, i) {
          var td = document.createElement(i === 0 ? "th" : "td");
          if (i === 0) td.scope = "row";
          td.textContent = v;
          tr.appendChild(td);
        });
        if (sc.provisional) tr.className = "is-provisional";
        if (sc.clients[c].failed) tr.title = sc.clients[c].failed + " run(s) failed and are excluded";
        tb.appendChild(tr);
      });
    });
    var env = data.environment;
    root.querySelector("[data-bench-env]").textContent =
      env.cpu + " · " + env.ram_gb + " GB RAM · " + env.os + " · IDM " + env.idm_version +
      " · MDM " + env.mdm_commit + " · " + env.date.replace("T", " ");
  }

  function drawStatus() {
    var box = root.querySelector("[data-bench-status]");
    if (!box) return;
    box.hidden = data.status !== "preliminary";
    if (!box.hidden) {
      box.textContent = t("Preliminary results from {date}. A full re-run is under way; these numbers will be replaced when it finishes.")
        .replace("{date}", data.environment.date.slice(0, 10));
    }
  }

  function final(sc) { return sc.compare && !sc.provisional; }
  // "1G", "100M", "256K": the scenario's file size in bytes (binary units, as the lab server serves them).
  function bytes(size) {
    var m = /^(\d+(?:\.\d+)?)([KMG])?$/i.exec(size || "");
    return m ? +m[1] * Math.pow(1024, " KMG".indexOf((m[2] || " ").toUpperCase())) : 0;
  }
  var raceDone = false;
  function drawRace() {
    var box = document.querySelector("[data-race-src]");
    if (!box || raceDone || !window.mdmRace) return;
    raceDone = true;
    var races = data.scenarios.filter(final).map(function (sc) {
      var ph = function (c) {
        var st = sc.clients[c].stats;
        return ["startup_ms", "transfer_ms", "finish_ms"].map(function (m) { return Math.max(1, st[m] ? st[m].median : 0); });
      };
      var two = sc.id === "maxconns-50m";
      return { tab: SHORT[sc.id] || sc.title, note: sc.title + ".", mdm: ph("MDM"), idm: ph("IDM"),
               e2e: [sc.clients.MDM.stats.e2e_ms.median, sc.clients.IDM.stats.e2e_ms.median],
               ratio: sc.compare.ratio_idm_over_mdm, conns: two ? [2, 2] : [8, 8], bytes: bytes(sc.size) };
    });
    window.mdmRace(box, races);
  }

  // Speed-up per scenario: a bar from 1x on a log scale, its 95% interval, a counter.
  function fmtRatio(v) { return (v >= 10 ? Math.round(v) : v.toFixed(v < 2 ? 2 : 1)) + "\u00d7"; }
  function drawSpeedup() {
    var box = document.querySelector("[data-speedup]");
    if (!box || box.childNodes.length) return;
    var top = 200, lg = function (v) { return Math.log(Math.max(1, v)) / Math.log(top); };
    var rows = data.scenarios.filter(final)
      .sort(function (a, b) { return b.compare.ratio_idm_over_mdm - a.compare.ratio_idm_over_mdm; });
    var axis = el("div", "su-axis");
    [1, 2, 5, 10, 20, 50, 100, 200].forEach(function (v) {
      var t = el("span", null, v + "\u00d7"); t.style.left = (lg(v) * 100) + "%"; axis.appendChild(t);
    });
    box.appendChild(axis);
    rows.forEach(function (sc, i) {
      var c = sc.compare, row = el("div", "su-row");
      row.style.setProperty("--d", (i * 110) + "ms");
      var name = el("div", "su-name");
      name.appendChild(el("b", null, SHORT[sc.id] || sc.title));
      name.appendChild(el("small", null, sc.title));
      var track = el("div", "su-track");
      var bar = el("i", "su-bar"); bar.style.setProperty("--w", (lg(c.ratio_idm_over_mdm) * 100) + "%");
      var ci = el("i", "su-ci");
      ci.style.left = (lg(c.ratio_ci95[0]) * 100) + "%";
      ci.style.width = Math.max(0.4, (lg(c.ratio_ci95[1]) - lg(c.ratio_ci95[0])) * 100) + "%";
      [2, 5, 10, 20, 50, 100].forEach(function (v) {
        var t = el("i", "su-tick"); t.style.left = (lg(v) * 100) + "%"; track.appendChild(t);
      });
      track.appendChild(bar); track.appendChild(ci);
      var val = el("div", "su-val"), num = el("b", null, fmtRatio(c.ratio_idm_over_mdm));
      val.appendChild(num);
      val.appendChild(el("small", null, "p " + (c.mann_whitney_p < 0.001 ? "< 0.001" : c.mann_whitney_p)));
      row.appendChild(name); row.appendChild(track); row.appendChild(val);
      box.appendChild(row);
    });
    onView(box, function () {
      // The numbers are final from the start (a counter caught half-way read as a false
      // claim); only the bars grow.
      box.classList.add("in");
    }, 0.2);
  }

  // The server that allows two connections: one square per connection it saw (median run).
  function drawConns() {
    var box = document.querySelector("[data-conns]");
    if (!box || box.getAttribute("data-done")) return;
    var sc = data.scenarios.filter(function (s) { return s.id === "maxconns-50m"; })[0];
    if (!sc) return;
    box.setAttribute("data-done", "1");
    var n = { mdm: Math.round(sc.clients.MDM.stats.connections.median), idm: Math.round(sc.clients.IDM.stats.connections.median) };
    Object.keys(n).forEach(function (k) {
      var grid = box.querySelector('[data-conn-grid="' + k + '"]');
      for (var i = 0; i < n[k]; i++) { var q = el("i"); q.style.setProperty("--i", i); grid.appendChild(q); }
    });
    onView(box, function () {
      box.classList.add("in");
      Object.keys(n).forEach(function (k) {
        var out = box.querySelector('[data-conn-count="' + k + '"]');
        if (still) { out.textContent = n[k]; return; }
        // Squares appear 6 ms apart (the CSS delay); the counter keeps pace with them.
        var t0 = performance.now(), ms = Math.max(300, n[k] * 6);
        (function step(now) {
          var v = Math.min(n[k], Math.ceil((now - t0) / ms * n[k]));
          out.textContent = v;
          if (v < n[k]) requestAnimationFrame(step);
        })(t0);
      });
    }, 0.3);
  }

  function drawAll() {
    if (!data || !window.echarts) return;
    dispose();
    drawRace();
    drawSpeedup();
    drawConns();
    drawStatus();
    drawScenarios();
    drawPhases();
    drawResources();
    drawTable();
  }

  // Metric switch.
  root.querySelectorAll("[data-metric]").forEach(function (b) {
    b.addEventListener("click", function () {
      metric = b.getAttribute("data-metric");
      root.querySelectorAll("[data-metric]").forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
      drawAll();
    });
  });

  // Redraw on theme or size changes.
  new MutationObserver(drawAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);
  var resizeT;
  window.addEventListener("resize", function () {
    clearTimeout(resizeT);
    resizeT = setTimeout(function () { charts.forEach(function (c) { c.resize(); }); }, 120);
  });

  fetch("/bench/results.json")
    .then(function (r) { return r.json(); })
    .then(function (j) { data = j; drawAll(); })
    .catch(function () {
      root.querySelector("[data-bench-grid]").textContent = t("The benchmark data could not be loaded.");
    });

  // ---- Against the other download managers: bench/compare.json (tools/bench/compare_report.py).
  var others = document.querySelector("[data-others]");
  var cmp = null;
  var ORDER = ["MDM", "IDM", "ABDM", "FDM", "Gopeed", "Prism", "XDM", "aria2", "curl"];
  var LABEL = { MDM: "Mister Download Manager", IDM: "Internet Download Manager", ABDM: "AB Download Manager",
                FDM: "Free Download Manager", Gopeed: "Gopeed", Prism: "Prism", XDM: "Xtreme Download Manager",
                aria2: "aria2", curl: "curl" };
  var OTHER_SHORT = { "fast-1g": t("1 GiB"), "capped-100m": t("2 MB/s per connection"), "drops-50m": t("Cut connections"),
                      "maxconns-50m": t("2 connections allowed"), "norange-100m": t("No range support"),
                      "batch-32x256k": t("32 small files") };
  var OTHER_WHAT = {
    "fast-1g": t("1 GiB from a server with no limits: as fast as the loopback and the disk allow."),
    "capped-100m": t("100 MiB from a server that sends at most 2 MB/s on each connection."),
    "drops-50m": t("50 MiB at 4 MB/s per connection; the server cuts every second connection after 2 MiB."),
    "maxconns-50m": t("50 MiB from a server that allows 2 connections at a time, 2 MB/s each, and refuses more."),
    "norange-100m": t("100 MiB from a server that ignores ranges and always sends the whole file."),
    "batch-32x256k": t("32 different files of 256 KiB, handed over one after another.")
  };
  function secs(v) {
    if (v == null) return "—";
    return (v >= 10000 ? (v / 1000).toFixed(1) : v >= 1000 ? (v / 1000).toFixed(2) : (v / 1000).toFixed(3)) + " s";
  }
  function med(s, m) { var x = s.stats && s.stats[m]; return x == null ? null : (typeof x === "number" ? x : x.median); }
  function niceStep(max) {
    var raw = max / 4, p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function tabName(sc) {
    var n = OTHER_SHORT[sc.id] || sc.title;
    return sc.profile === "defaults" ? t("{name}, at defaults").replace("{name}", n) : n;
  }
  function failNote(s) {
    var bad = [];
    if (s.failed) bad.push(t("{n} of {m} failed").replace("{n}", s.failed).replace("{m}", s.runs));
    if (s.sha_failed) bad.push(t("{n} of {m} with a wrong file").replace("{n}", s.sha_failed).replace("{m}", s.runs));
    return bad.join(", ");
  }
  function drawOthersScenario(k) {
    var sc = cmp.scenarios[k];
    var tabs = others.querySelectorAll('[role="tab"]');
    for (var i = 0; i < tabs.length; i++) tabs[i].setAttribute("aria-selected", i === k ? "true" : "false");
    var box = others.querySelector("[data-others-rows]");
    box.innerHTML = "";
    others.classList.remove("in");
    var names = ORDER.filter(function (c) { return sc.clients[c]; });
    var rows = names.map(function (c) { return { c: c, s: sc.clients[c], m: med(sc.clients[c], "e2e_ms") }; });
    rows.sort(function (a, b) { return (a.m == null) - (b.m == null) || a.m - b.m; });
    var max = 0;
    rows.forEach(function (r) {
      var st = r.s.stats.e2e_ms;
      if (st) max = Math.max(max, st.q3 != null ? st.q3 : st.median);
    });
    var step = niceStep(max || 1), top = Math.ceil(max / step) * step || step;
    var axis = el("div", "ot-axis");
    for (var v = 0; v <= top + 1e-9; v += step) {
      var a = el("span", null, secs(v).replace(".000 s", " s").replace(".00 s", " s").replace(".0 s", " s"));
      a.style.left = (v / top * 100) + "%";
      axis.appendChild(a);
    }
    box.appendChild(axis);
    rows.forEach(function (r, i) {
      var s = r.s, st = s.stats.e2e_ms, env = (cmp.environment.clients || {})[r.c];
      var row = el("div", "ot-row" + (r.c === "MDM" ? " is-ours" : ""));
      row.style.setProperty("--d", (i * 70) + "ms");
      var name = el("div", "ot-name");
      name.appendChild(el("b", null, LABEL[r.c] || r.c));
      var small = r.c === "IDM"
        ? cmp.idm.version.replace(/, /g, ".") + " · " + t("from the run above, {date}").replace("{date}", cmp.idm.date.slice(0, 10))
        : (env ? env.version.replace(/\s*\(.*\)$/, "") : "") + " · " +
          (s.connections_setting === 1 ? t("1 connection") : t("{n} connections").replace("{n}", s.connections_setting));
      name.appendChild(el("small", null, small));
      var track = el("div", "ot-track");
      for (var v2 = step; v2 < top - 1e-9; v2 += step) {
        var tk = el("i", "ot-tick"); tk.style.left = (v2 / top * 100) + "%"; track.appendChild(tk);
      }
      var val = el("div", "ot-val");
      if (st) {
        var bar = el("i", "ot-bar"); bar.style.setProperty("--w", (st.median / top * 100) + "%");
        track.appendChild(bar);
        if (st.q1 != null && st.q3 != null && st.n > 1) {
          var iqr = el("i", "ot-iqr");
          iqr.style.left = (st.q1 / top * 100) + "%";
          iqr.style.width = Math.max(0.3, (st.q3 - st.q1) / top * 100) + "%";
          track.appendChild(iqr);
        }
        val.appendChild(el("b", null, secs(st.median)));
      } else {
        track.appendChild(el("span", "ot-none", t("No run finished with the right file.")));
        val.appendChild(el("b", null, "—"));
      }
      var note = failNote(s);
      if (note) val.appendChild(el("small", "is-bad", note));
      else if (st) val.appendChild(el("small", null, secs(st.q1) + "–" + secs(st.q3)));
      row.appendChild(name); row.appendChild(track); row.appendChild(val);
      box.appendChild(row);
    });
    var foot = (OTHER_WHAT[sc.id] || sc.title) + " " +
      (sc.profile === "defaults" ? t("Each app at its own default number of connections.")
                                 : t("Every app at 8 connections where that can be set.")) + " " +
      t("The whisker spans the middle half of the runs.");
    others.querySelector("[data-others-foot]").textContent = foot;
    var sub = others.querySelector("[data-others-sub]");
    var n = Math.max.apply(null, names.map(function (c) { return sc.clients[c].runs || 0; }));
    sub.textContent = t("{n} runs each. Shorter is faster.").replace("{n}", n);
    if (still) others.classList.add("in");
    else requestAnimationFrame(function () { requestAnimationFrame(function () { others.classList.add("in"); }); });
  }
  function drawOthersTable() {
    var body = others.querySelector("[data-others-table] tbody");
    body.innerHTML = "";
    cmp.scenarios.forEach(function (sc) {
      var first = true;
      ORDER.forEach(function (c) {
        var s = sc.clients[c];
        if (!s) return;
        var tr = el("tr"), st = s.stats;
        var cells = [
          tabName(sc), LABEL[c] || c,
          s.source === "run5" ? t("{n} (run5)").replace("{n}", s.runs - s.failed) : (s.runs - s.failed - (s.sha_failed || 0)) + " / " + s.runs,
          st.e2e_ms ? secs(st.e2e_ms.median) + " (" + secs(st.e2e_ms.q1) + "–" + secs(st.e2e_ms.q3) + ")" : "—",
          secs(med(s, "transfer_ms")),
          (med(s, "cpu_avg_cores") == null ? "—" : med(s, "cpu_avg_cores").toFixed(2)) + " / " +
            (med(s, "cpu_peak_cores") == null ? "—" : med(s, "cpu_peak_cores").toFixed(2)),
          med(s, "peak_mem_mb") == null ? "—" : Math.round(med(s, "peak_mem_mb")) + " MB",
          med(s, "idle_after_mb") == null ? "—" : Math.round(med(s, "idle_after_mb")) + " MB",
          med(s, "connections") == null ? "—" : String(Math.round(med(s, "connections")))
        ];
        cells.forEach(function (v, j) { tr.appendChild(el(j < 2 ? "th" : "td", null, v)); });
        if (!first) tr.firstChild.textContent = "";
        first = false;
        tr.firstChild.setAttribute("scope", "row");
        body.appendChild(tr);
      });
    });
    var e = cmp.environment;
    others.querySelector("[data-others-env]").textContent =
      e.cpu + ", " + e.ram_gb + " GB, " + e.os + ". " + e.date.slice(0, 10) + ". " +
      ORDER.filter(function (c) { return e.clients[c]; }).map(function (c) {
        return (LABEL[c] || c) + " " + e.clients[c].version;
      }).join("; ") + "; Internet Download Manager " + cmp.idm.version.replace(/, /g, ".") + " (" + t("run5") + ").";
  }
  function drawOthers() {
    if (!cmp.scenarios || !cmp.scenarios.length) throw new Error("compare.json: no scenarios");
    var list = others.querySelector("[data-others-tabs]");
    list.innerHTML = "";
    cmp.scenarios.forEach(function (sc, k) {
      var b = el("button", null, tabName(sc));
      b.type = "button"; b.setAttribute("role", "tab"); b.tabIndex = k ? -1 : 0;
      b.addEventListener("click", function () { drawOthersScenario(k); });
      list.appendChild(b);
    });
    list.addEventListener("keydown", function (e) {
      var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
      var i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      var d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      var j = (i + d + tabs.length) % tabs.length;
      tabs.forEach(function (b, x) { b.tabIndex = x === j ? 0 : -1; });
      tabs[j].focus();
      drawOthersScenario(j);
    });
    var status = others.querySelector("[data-others-status]");
    if (cmp.status === "provisional") {
      status.hidden = false;
      status.textContent = t("Provisional: these runs were taken while other programs were busy on the same PC. A run on a quiet machine will replace them.");
    }
    drawOthersScenario(0);
    drawOthersTable();
  }
  if (others && window.fetch) {
    fetch("/bench/compare.json")
      .then(function (r) { return r.json(); })
      .then(function (j) { cmp = j; drawOthers(); })
      .catch(function (e) {
        if (window.console) console.error(e && e.stack || e);
        others.querySelector("[data-others-rows]").textContent = t("The benchmark data could not be loaded.");
      });
  }
})();
