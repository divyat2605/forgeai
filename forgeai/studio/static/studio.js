/* ForgeAI Studio - single-page app over the factory's artifacts. Vanilla JS, no build step. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = x => x == null ? "–" : Math.round(x * 100) + "%";
  const frac = r => r && r.n ? `${r.passed}/${r.n}` : "–";
  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }

  const S = { runs: [], run: null, bundle: null, route: "overview", tab: "summary", map: null, chat: {}, env: null };
  window.Studio = S;

  // ------------------------------------------------------------- theme
  const QS = new URLSearchParams(location.search);
  if (QS.get("static")) document.documentElement.classList.add("noanim");
  const savedTheme = QS.get("theme") || (() => { try { return localStorage.getItem("forge-theme"); } catch (e) { return null; } })();
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  $("#theme").onclick = () => {
    const dark = getComputedStyle(document.documentElement).colorScheme === "dark";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("forge-theme", document.documentElement.dataset.theme); } catch (e) { }
  };

  // ------------------------------------------------------------- runs
  async function loadRuns(select) {
    S.runs = await api("/api/runs");
    const done = S.runs.filter(r => r.status === "complete");
    let saved = null; try { saved = localStorage.getItem("forge-run"); } catch (e) { }
    if (!select && !S.run && QS.get("run") && S.runs.find(r => r.id === QS.get("run"))) select = QS.get("run");
    if (!select && !S.run && saved && S.runs.find(r => r.id === saved)) select = saved;
    const pref = select || S.run || (done.find(r => r.id.startsWith("demos/")) || done[0] || S.runs[0] || {}).id;
    renderPicker();
    if (pref) await pickRun(pref, true);
  }
  function renderPicker() {
    $("#pickmenu").innerHTML = S.runs.length ? S.runs.map(r => `
      <div class="opt" data-id="${esc(r.id)}"><b class="clip">${esc(r.agent || r.name)}</b>
      <span class="num faint">${r.holdout ? "holdout " + frac(r.holdout) : esc(r.status || "")}</span>
      <small class="clip mono">${esc(r.id)}</small></div>`).join("") : `<div class="empty">No runs yet - build one.</div>`;
    $("#pickmenu").querySelectorAll(".opt").forEach(o => o.onclick = () => { $("#picker").classList.remove("open"); pickRun(o.dataset.id); });
  }
  $("#pickbtn").onclick = e => { e.stopPropagation(); $("#picker").classList.toggle("open"); };
  document.addEventListener("click", () => $("#picker").classList.remove("open"));
  async function pickRun(id, quiet) {
    S.run = id;
    try { localStorage.setItem("forge-run", id); } catch (e) { }
    S.bundle = await api("/api/run?id=" + encodeURIComponent(id));
    $("#pickname").textContent = S.bundle.summary.agent || S.bundle.summary.name;
    if (!quiet || S.route !== "build") render();
  }

  // ------------------------------------------------------------- routing
  const TITLES = { overview: "Overview", build: "Build an agent", report: "Report", cases: "Eval cases", chat: "Chat with the agent", explain: "How it works", brief: "The brief" };
  function go(route, tab) { location.hash = "#/" + route + (tab ? "/" + tab : ""); }
  function parse() {
    const [, route, tab] = (location.hash || "#/overview").split("/");
    S.route = TITLES[route] ? route : "overview";
    if (tab) S.tab = tab;
  }
  window.addEventListener("hashchange", () => { parse(); render(); });
  document.querySelectorAll(".nav").forEach(b => b.onclick = () => go(b.dataset.route));

  function render() {
    document.querySelectorAll(".nav").forEach(b => b.classList.toggle("on", b.dataset.route === S.route));
    $("#title").textContent = TITLES[S.route];
    if (S.map && S.route !== "overview" && S.route !== "build") { S.map.destroy(); S.map = null; }
    const page = $("#page");
    page.className = "page fade";
    void page.offsetWidth;
    ({ overview, build, report, cases, chat, explain, brief: p => window.Brief.mount(p) })[S.route](page);
  }

  // ------------------------------------------------------------- shared bits
  function ciBar(r, base) {
    if (!r || !r.n) return "";
    const lo = r.ci95[0] * 100, hi = r.ci95[1] * 100, p = r.rate * 100;
    return `<div class="ci" title="95% Wilson interval ${Math.round(lo)}-${Math.round(hi)}%">
      <div class="track"></div><div class="band" style="left:${lo}%;width:${hi - lo}%"></div>
      <div class="pt" style="left:${p}%"></div>${base && base.n ? `<div class="base" style="left:${base.rate * 100}%" title="baseline ${frac(base)}"></div>` : ""}</div>`;
  }
  function verdictPill(v) {
    const m = { supported: "good", tool: "model", partial: "gold", unsupported: "bad" };
    return `<span class="pill ${m[v] || ""}"><i></i>${esc(v)}</span>`;
  }
  function passPill(ok) { return ok ? `<span class="pill good"><i></i>pass</span>` : `<span class="pill bad"><i></i>fail</span>`; }
  const CAT = { retrieval_miss: "Retrieval miss", prompt_defect: "Prompt defect", hallucination: "Hallucination", wrong_refusal: "Wrong refusal" };
  const CATD = {
    retrieval_miss: "The passage with the answer was never retrieved, so the model could not see it.",
    prompt_defect: "The right passage was retrieved, but the behaviour was wrong: incomplete, uncited, answered what it should refuse, or skipped its tool.",
    hallucination: "The answer states things no source the agent saw contains.",
    wrong_refusal: "The agent refused although the answer was in the retrieved passages.",
  };
  function needRun(page, allowPartial) {
    if (S.bundle && !S.bundle.report && !allowPartial) {
      const st = S.bundle.summary.status || "unknown";
      const msg = st === "running" ? "This run is still in progress (or was interrupted before it finished)."
        : st.startsWith("stopped") ? "The factory stopped this run before building an agent - the brief was not groundable."
        : `This run has no report (status: ${st}).`;
      page.innerHTML = `<div class="card" style="max-width:760px"><p class="eyebrow">${esc(S.bundle.summary.id)}</p><h2 class="h2">${esc(S.bundle.summary.agent || S.bundle.summary.name)}</h2>
        <p class="muted">${msg}</p>${S.bundle.groundability ? `<p>Coverage ${pct(S.bundle.groundability.coverage)} · gaps: ${(S.bundle.groundability.gaps || []).map(g => esc(g.topic)).join("; ") || "none"}</p>` : ""}
        <div class="row" style="margin-top:14px"><button class="btn" onclick="location.hash='#/overview'">See its pipeline</button><button class="btn" id="nr-pick">Pick another run</button></div></div>`;
      $("#nr-pick").onclick = e => { e.stopPropagation(); $("#picker").classList.add("open"); };
      return true;
    }
    if (S.bundle) return false;
    page.innerHTML = `<div class="empty"><p class="h2">No run selected</p><p>Build an agent or pick a run from the menu.</p>
      <button class="btn primary" onclick="location.hash='#/build'">Build an agent</button></div>`;
    return true;
  }

  // ------------------------------------------------------------- overview
  function overview(page) {
    if (needRun(page, true)) return;
    const b = S.bundle, s = b.summary, rep = b.report || {}, ev = b.evalstats || {};
    const fails = Object.entries(rep.failures_final || {});
    page.innerHTML = `
      <div class="row wrap" style="align-items:flex-end;margin-bottom:22px">
        <div style="flex:1;min-width:320px"><p class="eyebrow">${esc(s.id)}</p><h2 class="display">${esc(s.agent || s.name)}</h2>
        <p class="muted" style="max-width:820px;font:17px/1.55 var(--serif);margin:14px 0 0">${esc(s.brief)}</p></div>
      </div>
      <div class="card" style="padding:18px 18px 10px" id="mapcard"></div>
      <p class="map-cap">The real pipeline of this run; every label is read from its artifacts. Moving dots show direction, not throughput.</p>
      <div class="grid g4" style="margin-top:22px">
        <div class="card stat"><p class="eyebrow">Holdout pass rate</p><div class="v">${pct(s.holdout && s.holdout.rate)}<small>${frac(s.holdout)}</small></div>
          ${ciBar(s.holdout, s.baseline && s.baseline.holdout)}<div class="l">Cases the optimizer never saw. Band = 95% interval; ring = baseline.</div></div>
        <div class="card stat"><p class="eyebrow">Dev pass rate</p><div class="v">${pct(s.dev && s.dev.rate)}<small>${frac(s.dev)}</small></div>
          ${ciBar(s.dev, s.baseline && s.baseline.dev)}<div class="l">Cases the critic was allowed to learn from.</div></div>
        <div class="card stat"><p class="eyebrow">Gaps flagged before building</p><div class="v">${(s.gaps || []).length}<small>of ${((b.requirements || {}).must_answer || []).length} topics</small></div>
          <div class="l">${(s.gaps || []).map(esc).join("; ") || "Every required topic is supported."}</div></div>
        <div class="card stat"><p class="eyebrow">Judge accuracy on canaries</p><div class="v">${pct(s.judge)}<small>${(b.canaries || {}).n_canaries || 0} checks</small></div>
          <div class="l">The judge is tested every run on answers whose verdict is known.</div></div>
      </div>
      <div class="grid g2" style="margin-top:16px">
        <div class="card"><p class="eyebrow">What still fails, and why</p>
          ${fails.length ? fails.map(([k, n]) => `<div class="vrow"><span class="pill bad">${n}</span><div><b>${CAT[k]}</b><div class="muted" style="font-size:13px">${CATD[k]}</div></div></div>`).join("")
            : `<p class="muted">Every generated case passes - which is a reason to suspect the test set, not to celebrate.</p>`}
          <button class="btn" style="margin-top:12px" onclick="location.hash='#/report/summary'">Open the full report →</button></div>
        <div class="card"><p class="eyebrow">The test set it wrote for itself</p>
          <div class="row wrap" style="gap:6px;margin-bottom:12px">${Object.entries(ev.by_kind || {}).map(([k, v]) => `<span class="pill">${esc(k.replace("_", " "))} <b class="num">${v}</b></span>`).join("")}</div>
          <dl class="kv"><dt>Total</dt><dd class="num">${ev.total} cases · ${ev.dev} dev / ${ev.holdout} holdout</dd>
          <dt>Dropped by self-checks</dt><dd class="num">${Object.entries(ev.checks || {}).filter(([k]) => k.startsWith("dropped")).reduce((a, [, v]) => a + v, 0)}</dd>
          <dt>Models</dt><dd class="mono">${esc(s.models.factory_model)} · ${esc(s.models.agent_model)} · judge ${esc(s.models.judge_model)}</dd>
          <dt>Wall time</dt><dd class="num">${s.minutes} min</dd></dl>
          <button class="btn" style="margin-top:12px" onclick="location.hash='#/cases'">Explore every case →</button></div>
      </div>`;
    if (S.map) S.map.destroy();
    S.map = FactoryMap.create($("#mapcard"));
    FactoryMap.fromRun(S.map, b);
  }

  // ------------------------------------------------------------- build
  let job = null, files = [];
  function build(page) {
    page.innerHTML = `
      <div class="grid" style="grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:20px;align-items:start">
        <div class="card stack">
          <div><p class="eyebrow">1 · The brief</p><textarea class="input" id="b-brief" rows="6" placeholder="One paragraph: who the assistant is for and what it must answer."></textarea></div>
          <div><p class="eyebrow">2 · The documents</p>
            <div class="drop" id="b-drop">Drop PDF, DOCX, XLSX, CSV, MD, TXT or HTML files here, or click to choose<input type="file" id="b-file" multiple hidden></div>
            <div class="files" id="b-files"></div>
            <label class="field" style="margin-top:10px"><span>…or a folder on this machine</span><input class="input mono" id="b-path" placeholder="demos/hr-shore-staff/docs"></label></div>
          <div><p class="eyebrow">3 · Requester notes <span class="faint">(optional)</span></p>
            <textarea class="input" id="b-notes" rows="3" placeholder="Answers to the interviewer's questions. Without notes, stated defaults are assumed and recorded."></textarea></div>
          <div class="grid g2">
            <label class="field"><span>Model profile</span><select class="input" id="b-prof">${Object.keys((S.env || {}).profiles || { standard: 1 }).map(p => `<option ${p === (S.env || {}).profile ? "selected" : ""}>${p}</option>`).join("")}</select></label>
            <label class="field"><span>Time budget (minutes, 0 = none)</span><input class="input num" id="b-min" type="number" value="0" min="0"></label>
          </div>
          <div class="row"><button class="btn primary" id="b-go">Build the agent</button><span class="faint" id="b-state"></span></div>
          <div class="row wrap" style="gap:6px"><span class="faint" style="font-size:12.5px">Examples:</span>
            <button class="btn" style="padding:5px 10px;font-size:12.5px" data-ex="hr-shore-staff">HR policies</button>
            <button class="btn" style="padding:5px 10px;font-size:12.5px" data-ex="ship-spares-procurement">Ship spares</button></div>
        </div>
        <div class="stack">
          <div class="card" style="padding:14px" id="b-map"></div>
          <div class="row"><p class="eyebrow" style="margin:0">Live log</p><div class="sp" style="flex:1"></div><span class="num faint" id="b-time"></span></div>
          <div class="console" id="b-log"><span class="faint">The factory's own output will stream here.</span></div>
          <div id="b-done"></div>
        </div>
      </div>`;
    if (S.map) S.map.destroy();
    S.map = FactoryMap.create($("#b-map"), { ambient: false });
    S.map.reset();
    const drop = $("#b-drop"), inp = $("#b-file");
    drop.onclick = () => inp.click();
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); };
    inp.onchange = () => addFiles(inp.files);
    page.querySelectorAll("[data-ex]").forEach(b => b.onclick = async () => {
      const ex = b.dataset.ex;
      const t = await api(`/api/text?id=${encodeURIComponent("demos/" + ex + "/run")}&path=brief.md`).catch(() => ({ text: "" }));
      $("#b-brief").value = (t.text || "").trim();
      $("#b-path").value = `demos/${ex}/docs`;
      files = []; showFiles();
    });
    $("#b-go").onclick = startBuild;
    if (job) pollJob(true);
  }
  function addFiles(list) {
    [...list].forEach(f => files.push(f)); showFiles();
  }
  function showFiles() { $("#b-files").innerHTML = files.map(f => `<span class="pill">${esc(f.name)} <span class="faint num">${Math.round(f.size / 1024)} KB</span></span>`).join(""); }
  async function startBuild() {
    const brief = $("#b-brief").value.trim();
    if (!brief) return toast("Write a brief first.");
    const payload = { brief, notes: $("#b-notes").value, profile: $("#b-prof").value, max_minutes: +$("#b-min").value || 0 };
    if (files.length) {
      payload.files = await Promise.all(files.map(f => new Promise(res => {
        const r = new FileReader(); r.onload = () => res({ name: f.name, b64: r.result.split(",")[1] }); r.readAsDataURL(f);
      })));
    } else payload.docs_path = $("#b-path").value.trim();
    try {
      const r = await api("/api/build", payload);
      job = { id: r.job, since: 0, lines: [] };
      $("#b-log").innerHTML = "";
      S.map.reset();
      $("#b-go").disabled = true;
      pollJob();
    } catch (e) { toast(e.message); }
  }
  function lineHtml(l) {
    const t = esc(l);
    if (/^\[\d/.test(l.trim())) return `<span class="st">${t}</span>`;
    if (/✔|✓|\+ /.test(l)) return `<span class="ok">${t}</span>`;
    if (/⚠|!|warn/i.test(l)) return `<span class="wa">${t}</span>`;
    if (/✘|error|failed|Traceback/i.test(l)) return `<span class="er">${t}</span>`;
    return t;
  }
  async function pollJob(redraw) {
    if (!job) return;
    if (redraw && $("#b-log")) { $("#b-log").innerHTML = job.lines.map(lineHtml).join("\n"); }
    let r;
    try { r = await api(`/api/job?id=${job.id}&since=${job.since}`); } catch (e) { return; }
    job.since = r.next;
    job.lines.push(...r.lines);
    const log = $("#b-log");
    if (log && r.lines.length) {
      log.insertAdjacentHTML("beforeend", (log.innerHTML ? "\n" : "") + r.lines.map(lineHtml).join("\n"));
      log.scrollTop = log.scrollHeight;
    }
    if (S.map && S.route === "build") {
      r.stages.forEach(st => S.map.stage(st.n));
      const gl = job.lines.filter(l => /required topic\(s\) are NOT supported/.test(l))[0];
      if (gl) S.map.gaps("▲ " + gl.replace(/.*?(\d+) required.*/, "$1") + " unsupported topics → declined");
      job.lines.forEach(l => {
        let m;
        if ((m = l.match(/(\d+) chunks indexed/))) S.map.metric("ingest", `${m[1]} chunks indexed`);
        if ((m = l.match(/(\d+) must-answer, (\d+) must-refuse topics; (\d+) question/))) S.map.metric("intake", `${m[3]} questions · ${m[1]} topics`);
        if ((m = l.match(/tools attached: (.*?)\s+\(/))) S.map.metric("gen", m[1] === "none" ? "no tools needed" : "tools: " + m[1]);
        if ((m = l.match(/(\d+) verified cases/))) S.map.metric("evalgen", `${m[1]} cases written`);
        if ((m = l.match(/winner: (\w+)/))) S.map.metric("tour", "winner: " + m[1]);
        if ((m = l.match(/dev (\d+)\/(\d+)\s+holdout (\d+)\/(\d+)\s+failures/))) S.map.metric("judge", `dev ${m[1]}/${m[2]} · holdout ${m[3]}/${m[4]}`);
        if ((m = l.match(/judge accuracy on (\d+) canaries: (\d+)%/))) S.map.metric("audit", `judge ${m[2]}% on ${m[1]}`);
        if ((m = l.match(/RESULT\s+holdout (\d+)\/(\d+) \((\d+)%/))) S.map.metric("ship", `holdout ${m[1]}/${m[2]} (${m[3]}%)`);
      });
    }
    const tm = $("#b-time"); if (tm) tm.textContent = `${Math.floor(r.elapsed / 60)}:${String(Math.floor(r.elapsed % 60)).padStart(2, "0")}`;
    if (r.status === "running") { setTimeout(pollJob, 700); return; }
    if ($("#b-go")) $("#b-go").disabled = false;
    if (S.map && r.status === "done") S.map.allDone();
    if (S.map && r.status.startsWith("stopped")) { S.map.set("ship", "stop", "stopped: not groundable"); }
    const done = $("#b-done");
    if (done) done.innerHTML = r.run_id ? `<div class="card row"><div style="flex:1"><b>${r.status === "done" ? "Agent built." : "Run stopped."}</b>
      <div class="muted">${esc(r.run_id)}</div></div><button class="btn primary" id="b-open">Open report</button>
      ${r.status === "done" ? `<button class="btn" id="b-chat">Chat with it</button>` : ""}</div>` : `<div class="card">${esc(r.status)}</div>`;
    if (r.run_id) {
      await loadRuns(r.run_id);
      $("#b-open") && ($("#b-open").onclick = () => go("report", "summary"));
      $("#b-chat") && ($("#b-chat").onclick = () => go("chat"));
    }
    job.finished = true;
  }

  // ------------------------------------------------------------- report
  const TABS = [["summary", "Summary"], ["requirements", "Requirements"], ["guard", "Groundability"], ["agent", "Agent"],
    ["optimizer", "Optimizer"], ["judge", "Judge"], ["cost", "Cost"], ["markdown", "REPORT.md"]];
  function report(page) {
    if (needRun(page)) return;
    if (!TABS.find(t => t[0] === S.tab)) S.tab = "summary";
    page.innerHTML = `<div class="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" class="${k === S.tab ? "on" : ""}">${l}</button>`).join("")}</div><div id="tab"></div>`;
    page.querySelectorAll(".tabs button").forEach(b => b.onclick = () => go("report", b.dataset.t));
    ({ summary: rSummary, requirements: rReq, guard: rGuard, agent: rAgent, optimizer: rOpt, judge: rJudge, cost: rCost, markdown: rMd })[S.tab]($("#tab"));
  }
  function iterChart(its) {
    const pts = its.filter(h => h.scorecard);
    if (!pts.length) return "";
    const W = 560, H = 190, P = 34, n = Math.max(2, pts.length);
    const x = i => P + (W - 2 * P) * (pts.length === 1 ? 0.5 : i / (n - 1)), y = v => H - P - (H - 2 * P) * v;
    const line = (k) => pts.map((h, i) => `${i ? "L" : "M"}${x(i)} ${y(h.scorecard[k].rate || 0)}`).join(" ");
    const band = pts.map((h, i) => `${x(i)},${y(h.scorecard.holdout.ci95[1])}`).join(" ") + " " +
      pts.slice().reverse().map((h, i) => `${x(pts.length - 1 - i)},${y(h.scorecard.holdout.ci95[0])}`).join(" ");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}">
      ${[0, .25, .5, .75, 1].map(v => `<line class="ax" x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}"/><text x="4" y="${y(v) + 4}">${v * 100}%</text>`).join("")}
      ${pts.length > 1 ? `<polygon class="band-hold" points="${band}"/>` : ""}
      <path class="l-dev" d="${line("dev")}"/><path class="l-hold" d="${line("holdout")}"/>
      ${pts.map((h, i) => `<circle cx="${x(i)}" cy="${y(h.scorecard.holdout.rate || 0)}" r="4" fill="var(--good)"/><circle cx="${x(i)}" cy="${y(h.scorecard.dev.rate || 0)}" r="3.4" fill="var(--model)"/>
        <text x="${x(i)}" y="${H - 10}" text-anchor="middle">${esc(String(h.iteration).replace("tool audit", "tools"))}</text>`).join("")}
    </svg><div class="row" style="gap:16px;font-size:12.5px"><span><b style="color:var(--good)">━</b> holdout (band = 95% CI)</span><span><b style="color:var(--model)">━</b> dev</span></div>`;
  }
  function rSummary(el) {
    const b = S.bundle, rep = b.report || {}, its = b.iterations || [];
    const fails = (b.cases || []).filter(c => c.verdict && !c.verdict.pass);
    el.innerHTML = `
      <div class="grid g2">
        <div class="card"><p class="eyebrow">Headline</p>
          <div class="row" style="gap:28px;align-items:flex-end">
            <div class="stat"><div class="v" style="font-size:58px">${pct(rep.holdout && rep.holdout.rate)}</div><div class="l">holdout · ${frac(rep.holdout)} · CI ${rep.holdout ? Math.round(rep.holdout.ci95[0] * 100) + "–" + Math.round(rep.holdout.ci95[1] * 100) + "%" : ""}</div></div>
            <div class="stat"><div class="v">${pct(rep.dev && rep.dev.rate)}</div><div class="l">dev · ${frac(rep.dev)}</div></div>
            <div class="stat"><div class="v faint">${pct(rep.baseline && rep.baseline.holdout.rate)}</div><div class="l">baseline holdout</div></div>
          </div>
          <p class="muted" style="margin-top:16px">The holdout score is the one to trust: the optimizer never saw those cases. With ${rep.holdout ? rep.holdout.n : 0} cases the interval is wide, so small differences are noise.</p></div>
        <div class="card">${its.filter(h => h.scorecard).length > 1 ? `<p class="eyebrow">Per-iteration scorecard</p>${iterChart(its)}` : kindBars()}</div>
      </div>
      <div class="card flush" style="margin-top:16px"><div style="padding:18px 22px 6px"><p class="eyebrow">What still fails, and why</p></div>
        ${fails.length ? `<table class="tbl"><thead><tr><th>Case</th><th>Split</th><th>Category</th><th>Question</th><th>What happened</th></tr></thead><tbody>
          ${fails.map(c => `<tr class="click" data-c="${c.id}"><td class="num">${c.id}</td><td>${c.split}</td><td><span class="pill bad">${CAT[c.verdict.failure.category]}</span></td>
          <td>${esc(c.question)}</td><td class="muted">${esc(c.verdict.failure.detail)}</td></tr>`).join("")}</tbody></table>`
          : `<p class="muted" style="padding:0 22px 18px">Nothing fails. Suspect the test set.</p>`}</div>
      <div class="card" style="margin-top:16px"><p class="eyebrow">Iteration log</p>
        <table class="tbl"><thead><tr><th>Iter</th><th>Dev</th><th>Holdout</th><th>Fact recall</th><th>Grounded</th><th>Retrieval</th><th>Refusals</th><th>Decision</th></tr></thead><tbody>
        ${its.map(h => { const sc = h.scorecard, m = sc && sc.metrics; return `<tr><td class="num">${esc(h.iteration)}</td>
          <td class="num">${sc ? frac(sc.dev) : "–"}</td><td class="num">${sc ? frac(sc.holdout) : "–"}</td><td class="num">${m ? pct(m.fact_recall_mean) : "–"}</td>
          <td class="num">${m ? pct(m.grounded_rate) : "–"}</td><td class="num">${m ? pct(m.retrieval_recall) : "–"}</td><td class="num">${m ? pct(m.correct_refusal_rate) : "–"}</td>
          <td class="muted">${esc(h.decision)}</td></tr>`; }).join("")}</tbody></table></div>`;
    el.querySelectorAll("[data-c]").forEach(r => r.onclick = () => openCase(r.dataset.c));
  }
  function kindBars() {
    const by = {};
    (S.bundle.cases || []).forEach(c => { if (!c.verdict) return; const k = by[c.kind] = by[c.kind] || [0, 0]; k[1]++; if (c.verdict.pass) k[0]++; });
    return `<p class="eyebrow">Final pass rate by kind of test</p>` + Object.entries(by).sort((a, b) => b[1][1] - a[1][1]).map(([k, [p, n]]) =>
      `<div class="vrow"><span style="width:120px">${esc(k.replace("_", " "))}</span><div class="bar ${p === n ? "" : "gold"}" style="flex:1"><i style="width:${p / n * 100}%"></i></div><span class="num" style="width:44px;text-align:right">${p}/${n}</span></div>`).join("") +
      `<p class="faint" style="font-size:12.5px;margin:10px 0 0">The optimizer made no accepted change, so there is one scored iteration.</p>`;
  }
  function rReq(el) {
    const r = S.bundle.requirements || {}, g = S.bundle.groundability || {};
    const gv = Object.fromEntries((g.topics || []).map(t => [t.topic, t.verdict]));
    el.innerHTML = `<div class="grid g2">
      <div class="card"><p class="eyebrow">Requirements</p><h3 class="h2">${esc(r.agent_name)}</h3><p class="muted">${esc(r.summary)}</p>
        <dl class="kv"><dt>Audience</dt><dd>${esc(r.audience)}</dd><dt>Tone</dt><dd>${esc(r.tone)}</dd><dt>Scope</dt><dd>${esc(r.scope)}</dd></dl>
        <hr class="hr"><p class="eyebrow">Must answer</p>${(r.must_answer || []).map(t => `<div class="vrow">${verdictPill(gv[t.topic] || "-")}<div><b>${esc(t.topic)}</b><div class="muted" style="font-size:13px">${esc(t.description)}</div></div></div>`).join("")}
        <hr class="hr"><p class="eyebrow">Must refuse</p>${(r.must_refuse || []).map(t => `<div class="vrow"><span class="pill">refuse</span><div><b>${esc(t.topic)}</b><div class="muted" style="font-size:13px">${esc(t.reason)}</div></div></div>`).join("")}</div>
      <div class="card"><p class="eyebrow">Interview · at most five questions</p>
        ${(r.interview || []).map((q, i) => `<div style="padding:12px 0;border-bottom:1px solid var(--hair)"><div class="row"><span class="num faint">Q${i + 1}</span><b>${esc(q.question)}</b></div>
          <div class="muted" style="font-size:13px;margin:4px 0 8px 26px">${esc(q.why)}</div>
          <div class="row" style="margin-left:26px;align-items:flex-start"><span class="pill ${q.source === "default" ? "gold" : "good"}">${esc(q.source)}</span><span style="font-family:var(--serif);font-size:15px">${esc(q.answer)}</span></div></div>`).join("") || `<p class="muted">No questions were needed.</p>`}
        ${(r.assumptions || []).length ? `<hr class="hr"><p class="eyebrow">Recorded assumptions</p><ul class="muted">${r.assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}</div></div>`;
  }
  function rGuard(el) {
    const g = S.bundle.groundability || {};
    el.innerHTML = `<div class="card" style="margin-bottom:16px"><div class="row" style="gap:30px">
        <div class="stat"><div class="v">${pct(g.coverage)}</div><div class="l">coverage (supported = 1, partial = ½)</div></div>
        <div class="muted" style="max-width:640px">Every verdict is cross-checked in code: a "supported" verdict needs a quote that exists verbatim in the retrieved passages, and topic vocabulary the corpus never uses downgrades it. <b>${g.disagreements || 0}</b> model verdict(s) were overridden.</div></div></div>
      ${(g.topics || []).map(t => `<div class="card" style="margin-bottom:10px"><div class="row">${verdictPill(t.verdict)}<b style="font-size:16px">${esc(t.topic)}</b>
        ${t.model_verdict !== t.verdict ? `<span class="pill gold">model said ${esc(t.model_verdict)}</span>` : ""}<span class="sp" style="flex:1"></span><span class="faint num">lexical ${pct(t.lexical_coverage)}</span></div>
        ${t.evidence.length ? t.evidence.map(e => `<div class="quote" style="margin-top:10px">“${esc(e.quote)}” <span class="mono faint">${esc(e.chunk_id)} ✓ verified</span></div>`).join("") : ""}
        ${t.missing ? `<div class="quote bad" style="margin-top:10px">${esc(t.missing)}</div>` : ""}
        ${(t.notes || []).map(n => `<div class="pill gold" style="margin-top:8px">${esc(n)}</div>`).join("")}</div>`).join("")}`;
  }
  function rAgent(el) {
    const a = S.bundle.agent || {}, tools = S.bundle.tools || [], tour = S.bundle.tournament || [], k = a.knowledge || {};
    el.innerHTML = `<div class="grid g2">
      <div class="card"><p class="eyebrow">Tools · each one has to earn its place</p>
        <table class="tbl"><thead><tr><th>Tool</th><th>Model proposed</th><th>Attached</th><th>Why</th></tr></thead><tbody>
        ${tools.map(t => `<tr><td class="mono">${esc(t.tool)}</td><td>${t.model_said ? "yes" : "no"}</td><td>${t.attach ? `<span class="pill good">attached</span>` : `<span class="pill">${t.model_said ? "vetoed" : "no"}</span>`}</td>
          <td class="muted" style="font-size:13px">${esc(t.final_reason || t.model_reason)}</td></tr>`).join("")}</tbody></table>
        <hr class="hr"><p class="eyebrow">Knowledge &amp; retrieval</p>
        <dl class="kv"><dt>Documents</dt><dd>${(k.documents || []).map(d => esc(d.path)).join("<br>")}</dd>
        <dt>Chunking</dt><dd class="num">${k.chunking ? k.chunking.max_chars + " chars / " + k.chunking.overlap + " overlap" : ""}</dd>
        <dt>Retrieval</dt><dd class="num">${k.retrieval ? `hybrid · top_k ${k.retrieval.top_k} · bm25 ${k.retrieval.bm25_weight} · neighbours ${k.retrieval.neighbours || 0}${k.retrieval.query_rewrite ? " · rewrite" : ""}` : ""}</dd>
        <dt>Abstention</dt><dd class="num">${(a.guards || {}).min_relevance || 0}</dd><dt>Model</dt><dd class="mono">${esc((a.model || {}).name)}</dd></dl>
        ${tour.length ? `<hr class="hr"><p class="eyebrow">Prompt tournament (dev, pointwise)</p>${tour.map(t => `<div class="vrow"><span class="mono" style="width:90px">${esc(t.style)}</span>
          <div class="bar model" style="flex:1"><i style="width:${(t.dev.rate || 0) * 100}%"></i></div><span class="num">${frac(t.dev)}</span>${t.winner ? `<span class="pill good">winner</span>` : `<span class="pill" style="visibility:hidden">winner</span>`}</div>`).join("")}` : ""}</div>
      <div class="card"><p class="eyebrow">System prompt · sectioned so fixes stay targeted</p>
        ${((a.system_prompt || {}).sections || []).map(s => `<div style="margin-bottom:14px"><div class="mono faint" style="text-transform:uppercase;letter-spacing:.1em;font-size:11px;margin-bottom:4px">${esc(s.id)}</div>
          <div style="white-space:pre-wrap;font-size:13.5px">${esc(s.text)}</div></div>`).join("")}
        <div class="box mono faint" style="font-size:11.5px">+ fixed runtime contract: JSON {answer, citations, refused}; never patchable by the optimizer</div></div></div>`;
  }
  function wordDiff(a, b) {
    a = String(a || ""); b = String(b || "");
    const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
    const n = A.length, m = B.length;
    if (n * m > 400000) return `<del>${esc(a)}</del>\n<ins>${esc(b)}</ins>`;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    let i = 0, j = 0, out = "";
    while (i < n && j < m) {
      if (A[i] === B[j]) { out += esc(A[i]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) out += `<del>${esc(A[i++])}</del>`;
      else out += `<ins>${esc(B[j++])}</ins>`;
    }
    while (i < n) out += `<del>${esc(A[i++])}</del>`;
    while (j < m) out += `<ins>${esc(B[j++])}</ins>`;
    return out;
  }
  function rOpt(el) {
    const ch = S.bundle.changes || [], its = S.bundle.iterations || [];
    el.innerHTML = `<div class="card" style="margin-bottom:16px"><p class="muted" style="margin:0">Each failure is <b>classified by measurement</b> (was the fact in what the agent saw? is every claim supported?), then the critic proposes a <b>targeted</b> patch to one prompt section or one parameter group. A patch must fix its targeted dev cases without breaking a regression sample; an iteration is kept only if dev strictly improves. Holdout never influences a decision.</p></div>
      ${ch.length ? ch.map(p => `<div class="card" style="margin-bottom:12px"><div class="row wrap"><span class="num faint">${esc(p.id)}</span><span class="pill model">${esc(p.target)}</span>
        <span class="pill">${CAT[p.category] || esc(p.category)}</span>${p.accepted ? `<span class="pill good">kept</span>` : `<span class="pill bad">rejected</span>`}
        <span class="faint" style="font-size:12.5px">iteration ${esc(p.iteration)} · addresses ${(p.addresses || []).join(", ") || "-"} · gate: fixed ${(p.gate.fixed || []).length}, broke ${(p.gate.broke || []).length}</span></div>
        <h3 class="h3" style="margin-top:12px">${esc(p.change_summary)}</h3><p class="muted" style="margin:4px 0 12px">Why: ${esc(p.diagnosis)}</p>
        <div class="diff">${typeof p.before === "string" ? wordDiff(p.before, p.after) : `<del>${esc(JSON.stringify(p.before))}</del>\n<ins>${esc(JSON.stringify(p.after))}</ins>`}</div>
        ${p.iteration_decision ? `<p class="faint" style="font-size:12.5px;margin:10px 0 0">Iteration ${esc(p.iteration)} outcome (all accepted patches merged and re-evaluated): ${esc(p.iteration_decision)}</p>` : ""}</div>`).join("")
        : `<div class="empty">No patches were needed or proposed.</div>`}
      <p class="faint" style="font-size:12.5px">${its.filter(h => String(h.decision || "").startsWith("stopped")).map(h => "Iteration " + h.iteration + ": " + h.decision).join(" · ")}</p>`;
  }
  function rJudge(el) {
    const c = S.bundle.canaries || {}, cases = S.bundle.cases || [];
    const meth = {};
    cases.forEach(x => ((x.verdict || {}).facts || []).forEach(f => meth[f.method] = (meth[f.method] || 0) + 1));
    const tot = Object.values(meth).reduce((a, b) => a + b, 0) || 1;
    const row = (l, v, d) => `<div class="vrow"><div style="width:300px"><b>${l}</b><div class="muted" style="font-size:12.5px">${d}</div></div><div class="bar" style="flex:1"><i style="width:${(v || 0) * 100}%"></i></div><span class="num" style="width:48px;text-align:right">${pct(v)}</span></div>`;
    el.innerHTML = `<div class="grid g2"><div class="card"><p class="eyebrow">Canary audit · ${c.n_canaries || 0} answers with known verdicts</p>
      ${row("Correct answer accepted", c.gold_pass, "the facts, stated plainly")}
      ${row("Wrong numbers rejected", c.corrupted_fail, "numbers changed or facts swapped")}
      ${row("Padded answer still accepted", c.padded_pass, "verbosity must not change the verdict")}
      ${row("Fabricated claim caught", c.fabrication_caught, "an invented sentence appended")}
      <p class="muted" style="margin-top:12px">Verbosity effect: <b class="num">${c.verbosity_effect != null ? (c.verbosity_effect >= 0 ? "+" : "") + Math.round(c.verbosity_effect * 100) + " pts" : "–"}</b></p></div>
      <div class="card"><p class="eyebrow">Who decided each fact verdict</p>
        ${Object.entries(meth).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div class="vrow"><span style="width:300px" class="mono">${esc(k)}</span><div class="bar model" style="flex:1"><i style="width:${v / tot * 100}%"></i></div><span class="num">${v}</span></div>`).join("")}
        <hr class="hr"><dl class="kv"><dt>Position bias</dt><dd>not applicable - every judgement is pointwise</dd><dt>Self-preference</dt><dd>judge ${esc(S.bundle.summary.models.judge_model)} vs agent ${esc(S.bundle.summary.models.agent_model)} (different families)</dd>
        <dt>Verbosity</dt><dd>binary per-fact checks with a quote that must exist in the answer</dd></dl></div></div>`;
  }
  function rCost(el) {
    const m = (S.bundle.manifest || {}).meter || {}, st = m.by_stage || {}, sec = (S.bundle.manifest || {}).stage_seconds || {};
    const rows = Object.entries(st).sort((a, b) => b[1].model_seconds - a[1].model_seconds);
    const max = Math.max(1, ...rows.map(([, v]) => v.model_seconds));
    el.innerHTML = `<div class="grid g4" style="margin-bottom:16px">
      <div class="card stat"><div class="v">${((m.wall_seconds || 0) / 60).toFixed(1)}<small>min</small></div><div class="l">wall time</div></div>
      <div class="card stat"><div class="v">${(m.calls || 0).toLocaleString()}</div><div class="l">model calls · ${m.cache_hits || 0} cached</div></div>
      <div class="card stat"><div class="v">${(((m.tokens_in || 0) + (m.tokens_out || 0)) / 1000).toFixed(0)}<small>k</small></div><div class="l">fresh tokens</div></div>
      <div class="card stat"><div class="v">${m.repairs || 0}</div><div class="l">schema repairs · ${m.failures || 0} failed calls</div></div></div>
      <div class="card"><p class="eyebrow">Model time by stage</p>${rows.map(([k, v]) => `<div class="vrow"><span class="mono" style="width:260px">${esc(k)}</span><div class="bar model" style="flex:1"><i style="width:${v.model_seconds / max * 100}%"></i></div><span class="num" style="width:150px;text-align:right">${v.calls} calls · ${Math.round(v.model_seconds)}s</span></div>`).join("")}</div>
      <p class="faint" style="font-size:12.5px">Stage wall seconds: ${Object.entries(sec).map(([k, v]) => `${esc(k)} ${v}s`).join(" · ")}</p>`;
  }
  async function rMd(el) {
    const t = await api(`/api/text?id=${encodeURIComponent(S.run)}&path=REPORT.md`);
    el.innerHTML = `<div class="card"><pre class="mono" style="white-space:pre-wrap;margin:0">${esc(t.text)}</pre></div>`;
  }

  // ------------------------------------------------------------- cases
  function cases(page) {
    if (needRun(page)) return;
    const cs = S.bundle.cases || [];
    const kinds = [...new Set(cs.map(c => c.kind))];
    let f = { kind: "all", split: "all", res: "all", q: "" };
    page.innerHTML = `<div class="row wrap" style="margin-bottom:16px;gap:12px">
      <div class="seg" id="f-split">${["all", "dev", "holdout"].map(x => `<button data-v="${x}" class="${x === "all" ? "on" : ""}">${x}</button>`).join("")}</div>
      <div class="seg" id="f-res">${["all", "pass", "fail"].map(x => `<button data-v="${x}" class="${x === "all" ? "on" : ""}">${x}</button>`).join("")}</div>
      <select class="input" id="f-kind" style="width:auto"><option value="all">all kinds</option>${kinds.map(k => `<option>${k}</option>`).join("")}</select>
      <input class="input" id="f-q" placeholder="Search questions" style="max-width:280px"><span class="faint num" id="f-n"></span></div>
      <div class="card flush"><table class="tbl"><thead><tr><th>Case</th><th>Kind</th><th>Split</th><th>Question</th><th>Expected</th><th>Baseline</th><th>Final</th></tr></thead><tbody id="f-body"></tbody></table></div>`;
    function draw() {
      const rows = cs.filter(c => (f.kind === "all" || c.kind === f.kind) && (f.split === "all" || c.split === f.split) &&
        (f.res === "all" || (c.verdict && c.verdict.pass) === (f.res === "pass")) && (!f.q || c.question.toLowerCase().includes(f.q.toLowerCase())));
      $("#f-n").textContent = `${rows.length} of ${cs.length}`;
      $("#f-body").innerHTML = rows.map(c => `<tr class="click" data-c="${c.id}"><td class="num">${c.id}</td><td><span class="pill">${esc(c.kind.replace("_", " "))}</span></td><td>${c.split}</td>
        <td>${esc(c.question)}</td><td class="muted" style="font-size:13px">${c.expected.should_refuse ? "<i>must decline</i>" : esc((c.expected.key_facts || []).map(k => k.text).join(" · ") || (c.expected.tool ? "uses " + c.expected.tool : ""))}</td>
        <td>${c.baseline_pass == null ? "–" : c.baseline_pass ? "✓" : "✗"}</td><td>${c.verdict ? passPill(c.verdict.pass) : "–"}</td></tr>`).join("");
      $("#f-body").querySelectorAll("[data-c]").forEach(r => r.onclick = () => openCase(r.dataset.c));
    }
    ["split", "res"].forEach(k => $("#f-" + k).querySelectorAll("button").forEach(b => b.onclick = () => {
      f[k] = b.dataset.v; $("#f-" + k).querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); draw();
    }));
    $("#f-kind").onchange = e => { f.kind = e.target.value; draw(); };
    $("#f-q").oninput = e => { f.q = e.target.value; draw(); };
    draw();
  }
  function openCase(id) {
    const c = (S.bundle.cases || []).find(x => x.id === id); if (!c) return;
    const v = c.verdict || {}, r = c.response || {};
    const d = $("#drawer");
    d.innerHTML = `<div class="row"><span class="num faint">${c.id}</span><span class="pill">${esc(c.kind)}</span><span class="pill">${c.split}</span>${v.pass != null ? passPill(v.pass) : ""}<span style="flex:1"></span><button class="btn" id="d-x">Close</button></div>
      <h2 class="h2" style="margin-top:16px;font-size:26px">${esc(c.question)}</h2>
      <p class="eyebrow" style="margin-top:20px">Expected</p>
      ${c.expected.should_refuse ? `<p>Must decline. <span class="muted">${esc(c.expected.refuse_reason || "")}</span></p>` :
        (c.expected.key_facts || []).map(k => `<div class="quote">“${esc(k.text)}” <span class="mono faint">${esc(k.chunk_id || "")} · verbatim in source</span></div>`).join("") + (c.expected.tool ? `<p>Must use <b class="mono">${esc(c.expected.tool)}</b>.</p>` : "") +
        (c.expected.trap ? `<div class="quote bad" style="margin-top:8px">Trap - must NOT be the answer: “${esc(c.expected.trap)}”<div class="mono faint" style="font-size:11.5px">${esc((c.provenance || {}).condition || "")}</div></div>` : "")}
      <p class="eyebrow" style="margin-top:20px">The agent said ${r.refused ? `<span class="pill gold">declined</span>` : ""}</p>
      <div class="box" style="font:16px/1.55 var(--serif)">${esc(r.answer || "")}</div>
      ${(r.tool_calls || []).map(t => `<div class="box mono" style="margin-top:8px">${esc(t.tool)}(${esc(JSON.stringify(t.arguments))}) → ${esc(t.result)}</div>`).join("")}
      <p class="eyebrow" style="margin-top:20px">Judge</p>
      ${v.failure ? `<div class="vrow"><span class="pill bad">${CAT[v.failure.category]}</span><span class="muted">${esc(v.failure.subtype)} · ${esc(v.failure.detail)}</span></div>` : ""}
      ${(v.facts || []).map(f => `<div class="vrow">${f.stated ? `<span class="pill good">stated</span>` : `<span class="pill bad">missing</span>`}<span style="flex:1">${esc(f.text)}</span><span class="mono faint">${esc(f.method)}</span></div>`).join("")}
      ${(v.claims || []).map(cl => `<div class="vrow">${cl.supported ? `<span class="pill good">supported</span>` : `<span class="pill bad">unsupported</span>`}<span style="flex:1;font-size:13.5px">${esc(cl.claim)}</span><span class="mono faint" style="max-width:200px">${esc(cl.method)}</span></div>`).join("")}
      <p class="eyebrow" style="margin-top:20px">What it retrieved</p>
      ${(r.retrieved || []).map(x => `<div class="passage ${(r.citations || []).includes(x.label) ? "on" : ""}"><div class="row"><b class="mono">${x.label}</b><span class="mono faint">${esc(x.chunk_id)}</span><span style="flex:1"></span>
        <span class="num faint">rel ${(+x.dense).toFixed(3)}</span>${(r.citations || []).includes(x.label) ? `<span class="pill model">cited</span>` : ""}</div>
        <div style="margin-top:6px;white-space:pre-wrap">${esc(((r.contexts || {})[x.label] || "").slice(0, 900))}</div></div>`).join("")}
      <p class="faint mono" style="font-size:11.5px">${esc((c.provenance || {}).prompt || "")} ${(c.provenance || {}).seed_chunk ? "· seed " + esc(c.provenance.seed_chunk) : ""} ${r.latency_s ? "· " + r.latency_s + "s" : ""}</p>`;
    d.classList.add("open"); $("#scrim").classList.add("open");
    $("#d-x").onclick = closeDrawer;
  }
  function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); }
  $("#scrim").onclick = closeDrawer;
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  // ------------------------------------------------------------- chat
  function chat(page) {
    if (needRun(page)) return;
    const b = S.bundle, key = S.run;
    const st = S.chat[key] = S.chat[key] || { msgs: [] };
    if (b.summary.status !== "complete") { page.innerHTML = `<div class="empty">This run did not produce an agent (${esc(b.summary.status)}).</div>`; return; }
    const examples = (b.cases || []).filter(c => ["answerable", "multi_doc", "gap", "must_refuse", "tool"].includes(c.kind)).slice(0, 40);
    const pick = k => (examples.find(c => c.kind === k) || {}).question;
    const sugg = [pick("answerable"), pick("multi_doc"), pick("tool"), pick("gap") || pick("must_refuse")].filter(Boolean);
    page.innerHTML = `<div class="chat"><div class="thread"><div class="msgs" id="c-msgs"></div>
      <div class="row wrap" id="c-sugg" style="gap:6px;margin:8px 0">${sugg.map(q => `<button class="btn" style="padding:6px 11px;font-size:12.5px">${esc(q)}</button>`).join("")}</div>
      <div class="composer"><textarea class="input" id="c-in" placeholder="Ask ${esc(b.summary.agent)} anything…"></textarea><button class="btn primary" id="c-go">Send</button></div></div>
      <div class="side"><p class="eyebrow">Sources for the last answer</p><div id="c-src" class="faint">Citations appear here, with the exact passage text.</div></div></div>`;
    const box = $("#c-msgs");
    function draw() {
      box.innerHTML = st.msgs.length ? st.msgs.map((m, i) => m.role === "user" ? `<div class="msg me">${esc(m.content)}</div>` :
        m.pending ? `<div class="msg ai"><div class="typing"><span></span><span></span><span></span></div></div>` :
        `<div class="msg ai"><div class="body">${esc(m.content)}</div><div class="meta">${m.res.refused ? `<span class="pill gold">declined</span>` : ""}
          ${(m.res.citations || []).map(c => `<span class="pill cite" data-i="${i}" data-l="${c}">${c} · ${esc(((m.res.passages[c] || {}).header || "tool").replace(/^\[|\]$/g, ""))}</span>`).join("")}
          ${(m.res.tool_calls || []).map(t => `<span class="pill model">⚙ ${esc(t.tool)}</span>`).join("")}<span class="faint num" style="font-size:11.5px">${m.res.latency_s}s</span></div></div>`).join("")
        : `<div class="empty"><p class="h2">${esc(b.summary.agent)}</p><p>${esc((b.requirements || {}).summary || "")}</p></div>`;
      box.querySelectorAll(".cite").forEach(c => c.onclick = () => showSrc(st.msgs[+c.dataset.i].res, c.dataset.l));
      box.scrollTop = box.scrollHeight;
    }
    function showSrc(res, focus) {
      const ps = res.passages || {};
      const tl = (res.tool_calls || []).map(t => `<div class="passage ${focus === t.label ? "on" : ""}"><b class="mono">${t.label} · ${esc(t.tool)}</b><div class="mono" style="margin-top:6px;white-space:pre-wrap">${esc(JSON.stringify(t.arguments))}\n→ ${esc(t.result)}</div></div>`).join("");
      $("#c-src").innerHTML = tl + Object.entries(ps).map(([l, p]) => `<div class="passage ${(res.citations || []).includes(l) ? "on" : ""}" id="src-${l}">
        <div class="row"><b class="mono">${l}</b><span class="mono faint clip">${esc(p.header)}</span></div>
        <div class="row" style="margin:6px 0"><div class="bar model" style="flex:1"><i style="width:${Math.max(0, p.dense) * 100}%"></i></div><span class="num faint">${(+p.dense).toFixed(2)}</span></div>
        <div style="white-space:pre-wrap;color:var(--ink2)">${esc(p.text.slice(0, 700))}</div></div>`).join("") || `<span class="faint">No passages were retrieved.</span>`;
      if (focus && $("#src-" + focus)) $("#src-" + focus).scrollIntoView({ behavior: "smooth", block: "center" });
    }
    async function send(q) {
      q = (q || $("#c-in").value).trim(); if (!q) return;
      $("#c-in").value = "";
      const history = st.msgs.filter(m => !m.pending).map(m => ({ role: m.role, content: m.content }));
      st.msgs.push({ role: "user", content: q }, { role: "assistant", pending: true }); draw();
      try {
        const res = await api("/api/chat", { run: key, message: q, history });
        st.msgs[st.msgs.length - 1] = { role: "assistant", content: res.answer, res };
        draw(); showSrc(res);
      } catch (e) { st.msgs.pop(); draw(); toast(e.message); }
    }
    $("#c-go").onclick = () => send();
    $("#c-in").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
    $("#c-sugg").querySelectorAll("button").forEach(bt => bt.onclick = () => send(bt.textContent));
    draw();
    const last = st.msgs.filter(m => m.res).pop(); if (last) showSrc(last.res);
  }

  // ------------------------------------------------------------- explain
  function explain(page) {
    page.innerHTML = "";
    window.Explain.open(S.bundle, () => go("overview"));
  }

  // ------------------------------------------------------------- boot
  (async function boot() {
    parse();
    try {
      S.env = await api("/api/env");
      $("#envline").textContent = `${S.env.backend} · ${S.env.profile}`;
      $("#verline").textContent = "forgeai " + S.env.version;
    } catch (e) { }
    await loadRuns().catch(e => toast(e.message));
    render();
  })();
})();
