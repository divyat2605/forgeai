/* Factory map: the real pipeline as a U-shaped line, drawn in SVG.
   Node states come from run artifacts (or a live build's stage markers).
   Moving dots show direction of work, not measured throughput. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const W = 210, H = 82;
  const NODES = [
    { id: "in", n: "00", t: "Brief + documents", x: 20, y: 60 },
    { id: "ingest", n: "01", t: "Read & index", x: 262, y: 60 },
    { id: "intake", n: "02", t: "Interview", x: 504, y: 60 },
    { id: "guard", n: "03", t: "Groundability guard", x: 746, y: 60 },
    { id: "gen", n: "04", t: "Generate the agent", x: 988, y: 60 },
    { id: "evalgen", n: "05", t: "Write the tests", x: 988, y: 222 },
    { id: "tour", n: "06", t: "Prompt tournament", x: 746, y: 222 },
    { id: "judge", n: "07", t: "Run + judge", x: 504, y: 222 },
    { id: "opt", n: "07·k", t: "Critic–optimizer", x: 504, y: 372 },
    { id: "audit", n: "08", t: "Audit the judge", x: 262, y: 222 },
    { id: "ship", n: "09", t: "Ship + report", x: 20, y: 222 },
  ];
  const EDGES = [
    ["in", "ingest"], ["ingest", "intake"], ["intake", "guard"], ["guard", "gen"], ["gen", "evalgen"],
    ["evalgen", "tour"], ["tour", "judge"], ["judge", "opt"], ["opt", "judge", "loop"], ["judge", "audit"], ["audit", "ship"],
  ];
  const STAGE_OF = { "1": "ingest", "2": "intake", "3": "guard", "4": "gen", "5": "evalgen", "6": "tour", "7": "judge",
    "8": "audit", "9": "ship" };

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const byId = Object.fromEntries(NODES.map(n => [n.id, n]));

  function edgePath(a, b, kind) {
    const A = byId[a], B = byId[b];
    if (A.y === B.y) {                       // same row
      const l2r = B.x > A.x;
      const x1 = l2r ? A.x + W : A.x, x2 = l2r ? B.x : B.x + W, y = A.y + H / 2;
      return `M${x1} ${y} L${x2} ${y}`;
    }
    if (kind === "loop") {                   // opt -> judge, curving out to the right
      return `M${A.x + W} ${A.y + H / 2} C${A.x + W + 70} ${A.y + H / 2}, ${B.x + W + 70} ${B.y + H / 2}, ${B.x + W} ${B.y + H / 2 + 14}`;
    }
    if (a === "judge" && b === "opt") {
      return `M${A.x} ${A.y + H / 2 + 14} C${A.x - 70} ${A.y + H / 2 + 14}, ${B.x - 70} ${B.y + H / 2}, ${B.x} ${B.y + H / 2}`;
    }
    // vertical drop (gen -> evalgen)
    return `M${A.x + W / 2} ${A.y + H} L${B.x + W / 2} ${B.y}`;
  }

  function create(container, opts) {
    opts = opts || {};
    const svg = el("svg", { viewBox: "0 0 1220 470", class: "map", role: "img",
      "aria-label": "ForgeAI pipeline: brief and documents, read and index, interview, groundability guard, generate agent, write tests, prompt tournament, run and judge with critic-optimizer loop, audit the judge, ship and report" });
    container.appendChild(svg);
    const gEdges = el("g", {}, svg), gPk = el("g", {}, svg), gNodes = el("g", {}, svg), gStub = el("g", {}, svg);
    const edges = EDGES.map(([a, b, kind]) => {
      const p = el("path", { d: edgePath(a, b, kind), class: "edge" + (kind === "loop" ? " loop" : "") }, gEdges);
      return { a, b, kind, p, len: p.getTotalLength() };
    });
    // arrow heads
    edges.forEach(e => {
      const pt = e.p.getPointAtLength(e.len), pr = e.p.getPointAtLength(Math.max(0, e.len - 6));
      const ang = Math.atan2(pt.y - pr.y, pt.x - pr.x);
      const s = 5;
      el("path", { d: `M${pt.x} ${pt.y} L${pt.x - s * Math.cos(ang - .5)} ${pt.y - s * Math.sin(ang - .5)} M${pt.x} ${pt.y} L${pt.x - s * Math.cos(ang + .5)} ${pt.y - s * Math.sin(ang + .5)}`,
        class: "edge", style: "stroke-width:1.4" }, gEdges);
    });
    const nodes = {};
    NODES.forEach(n => {
      const g = el("g", { class: "node", transform: `translate(${n.x} ${n.y})` }, gNodes);
      el("rect", { x: -4, y: -4, width: W + 8, height: H + 8, rx: 16, class: "ring" }, g);
      el("rect", { width: W, height: H, rx: 13 }, g);
      el("text", { x: 16, y: 22, class: "n" }, g).textContent = n.n;
      el("text", { x: 16, y: 46, class: "t" }, g).textContent = n.t;
      const m = el("text", { x: 16, y: 67, class: "m" }, g);
      const badge = el("circle", { cx: W - 18, cy: 18, r: 5, class: "badge" }, g);
      nodes[n.id] = { g, m, badge, state: "idle" };
    });
    const stub = el("text", { x: 746 + 16, y: 44, class: "stub", fill: "var(--bad)" }, gStub);

    let pkts = [], raf = 0, last = 0, running = true;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function tick(t) {
      raf = requestAnimationFrame(tick);
      if (!running || document.hidden) return;
      const dt = Math.min(50, t - (last || t)); last = t;
      // spawn
      edges.forEach(e => {
        const tgt = nodes[e.b].state, src = nodes[e.a].state;
        let rate = 0;
        if (tgt === "active" || (e.kind === "loop" && nodes.opt.state === "active")) rate = 1 / 650;
        else if (src === "done" && (tgt === "done" || tgt === "active")) rate = opts.ambient === false ? 0 : 1 / 4200;
        if (e.hot) rate = 1 / 420;
        if (rate && Math.random() < rate * dt && pkts.filter(k => k.e === e).length < 6) {
          const c = el("circle", { r: e.hot || tgt === "active" ? 3.4 : 2.6, class: "pkt" + (tgt === "done" && !e.hot ? " good" : "") }, gPk);
          pkts.push({ e, c, s: 0, v: (e.hot ? 0.00042 : 0.00028) * (600 / Math.max(120, e.len)) * 1.6 });
        }
      });
      pkts = pkts.filter(k => {
        k.s += k.v * dt;
        if (k.s >= 1) { k.c.remove(); return false; }
        const pt = k.e.p.getPointAtLength(k.s * k.e.len);
        k.c.setAttribute("cx", pt.x); k.c.setAttribute("cy", pt.y);
        k.c.setAttribute("opacity", Math.min(1, Math.min(k.s, 1 - k.s) * 8));
        return true;
      });
    }
    if (!reduce) raf = requestAnimationFrame(tick);

    const api = {
      svg,
      set(id, state, metric) {
        const n = nodes[id]; if (!n) return;
        if (state) { n.state = state; n.g.classList.remove("idle", "active", "done", "stop"); n.g.classList.add(state); }
        if (metric !== undefined) n.m.textContent = metric;
      },
      metric(id, text) { if (nodes[id]) nodes[id].m.textContent = text; },
      stage(num) {           // live build: "[n] Title" marker
        const key = String(num).split(".")[0];
        const id = String(num).includes(".") ? "opt" : STAGE_OF[key];      // "7.1", "7.t" = optimizer
        if (!id) return;
        const order = NODES.map(n => n.id);
        const idx = order.indexOf(id === "opt" ? "judge" : id);
        order.forEach((nid, i) => { if (i < idx && nodes[nid].state !== "stop") api.set(nid, "done"); });
        if (id === "opt") { api.set("judge", "done"); api.set("opt", "active"); }
        else { api.set(id, "active"); if (id === "audit") api.set("opt", nodes.opt.state === "active" ? "done" : nodes.opt.state); }
      },
      allDone() { NODES.forEach(n => api.set(n.id, "done")); },
      reset() { NODES.forEach(n => { api.set(n.id, "idle", ""); }); stub.textContent = ""; },
      gaps(text) { stub.textContent = text || ""; },
      focus(ids) {
        const set = ids ? new Set(ids) : null;
        NODES.forEach(n => {
          nodes[n.id].g.classList.toggle("dim", !!set && !set.has(n.id));
          nodes[n.id].g.classList.toggle("focus", !!set && set.has(n.id) && ids.length <= 2);
        });
        edges.forEach(e => {
          const on = set && set.has(e.a) && set.has(e.b);
          e.hot = !!on; e.p.classList.toggle("live", !!on);
          e.p.style.opacity = set && !on ? .35 : 1;
        });
      },
      pause(v) { running = !v; },
      destroy() { cancelAnimationFrame(raf); svg.remove(); },
    };
    return api;
  }

  // Fill a map from a finished run's artifacts.
  function fromRun(map, b) {
    if (!b) { map.reset(); return; }
    const s = b.summary || {}, c = b.corpus || {}, req = b.requirements || {}, g = b.groundability || {};
    const ev = b.evalstats || {}, tour = b.tournament || [], it = b.iterations || [], can = b.canaries || {};
    const docs = (c.documents || []).length;
    map.set("in", "done", `${docs} document${docs === 1 ? "" : "s"}`);
    map.set("ingest", "done", `${c.chunks || "?"} chunks indexed`);
    map.set("intake", "done", `${(req.interview || []).length} questions · ${(req.must_answer || []).length} topics`);
    map.set("guard", "done", `${(g.supported || []).length + (g.tool_backed || []).length} ok · ${(g.gaps || []).length} gaps`);
    const tools = b.agent && b.agent.tools ? b.agent.tools.map(t => t.name) : (b.tools || []).filter(t => t.attach).map(t => t.tool);
    map.set("gen", "done", tools.length ? `tools: ${tools.join(", ")}` : "no tools needed");
    map.set("evalgen", "done", `${ev.total || 0} cases · ${ev.dev || 0}/${ev.holdout || 0} split`);
    const win = tour.find(t => t.winner);
    map.set("tour", tour.length ? "done" : "idle", win ? `winner: ${win.style}` : "skipped");
    const base = it[0] && it[0].scorecard;
    map.set("judge", "done", base ? `baseline dev ${base.dev.passed}/${base.dev.n}` : "");
    const patches = it.slice(1).reduce((a, h) => a + (h.patches || []).length, 0);
    const acc = it.slice(1).reduce((a, h) => a + (h.patches || []).filter(p => p.accepted).length, 0);
    map.set("opt", it.length > 1 ? "done" : "idle", `${patches} patches · ${acc} kept`);
    map.set("audit", "done", can.overall != null ? `judge ${Math.round(can.overall * 100)}% on canaries` : "");
    const h = s.holdout;
    map.set("ship", s.status === "complete" ? "done" : (s.status || "").startsWith("stopped") ? "stop" : "idle",
      h ? `holdout ${h.passed}/${h.n} (${Math.round(h.rate * 100)}%)` : (s.status || ""));
    map.gaps((g.gaps || []).length ? `▲ ${(g.gaps || []).length} unsupported topic${(g.gaps || []).length > 1 ? "s" : ""} → declined` : "");
  }

  window.FactoryMap = { create, fromRun, NODES };
})();
