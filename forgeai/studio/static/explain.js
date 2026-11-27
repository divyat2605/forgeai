/* "How it works" - a scene player that explains ForgeAI with the selected run's REAL artifacts.
   Keys: Space play/pause · ←/→ scene · R record mode (hides controls) · Esc close. */
(function () {
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = x => x == null ? "–" : Math.round(x * 100) + "%";
  const stag = (i, base = 0.25, step = 0.32) => `style="animation-delay:${(base + i * step).toFixed(2)}s"`;

  function countUp(el, to, ms, fmt) {
    const t0 = performance.now();
    (function f(t) {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(to * e);
      if (k < 1 && el.isConnected) requestAnimationFrame(f);
    })(t0);
  }
  function typewrite(el, text, cps) {
    let i = 0;
    el.classList.add("caret");
    const h = setInterval(() => {
      i += 2; el.textContent = text.slice(0, i);
      if (i >= text.length || !el.isConnected) { clearInterval(h); el.classList.remove("caret"); }
    }, 1000 / cps * 2);
  }

  function scenes(b) {
    const s = b.summary || {}, req = b.requirements || {}, g = b.groundability || {}, tools = b.tools || [];
    const ev = b.evalstats || {}, tour = b.tournament || [], it = b.iterations || [], ch = b.changes || [], can = b.canaries || {};
    const rep = b.report || {}, cases = b.cases || [], docs = ((b.corpus || {}).documents || []);
    const checks = ev.checks || {};
    const dropped = Object.entries(checks).filter(([k, v]) => k.startsWith("dropped") && v);
    const fails = cases.filter(c => c.verdict && !c.verdict.pass);
    const showcase = cases.find(c => c.kind === "multi_doc" && c.verdict && c.verdict.pass) || cases.find(c => c.kind === "answerable" && c.verdict && c.verdict.pass);
    const gapCase = cases.find(c => (c.kind === "gap" || c.kind === "must_refuse") && c.verdict && c.verdict.pass);
    const meth = {};
    cases.forEach(x => ((x.verdict || {}).facts || []).forEach(f => { const k = f.method.startsWith("deterministic") ? "code" : "model"; meth[k] = (meth[k] || 0) + 1; }));
    const claimsM = {};
    cases.forEach(x => ((x.verdict || {}).claims || []).forEach(f => { const k = f.method.startsWith("deterministic") ? "code" : "model"; claimsM[k] = (claimsM[k] || 0) + 1; }));

    return [
      { id: "intro", focus: null, wide: true, dur: 10000, eyebrow: "ForgeAI",
        title: "The machine that builds the chatbot.",
        body: `<p>One paragraph and a folder of documents go in. A working, tested agent and an honest report come out.</p>
               <p>Every stage runs on small open models on this laptop - so every stage is checked by code that cannot be persuaded.</p>`,
        fact: `run ${esc(s.id)} · ${esc(s.models.factory_model)} · ${esc(s.models.agent_model)} · judge ${esc(s.models.judge_model)}`,
        viz: el => { el.innerHTML = `<div class="vcard" style="padding:10px"></div>`; const m = FactoryMap.create(el.firstChild); FactoryMap.fromRun(m, b); return () => m.destroy(); } },

      { id: "brief", focus: ["in", "ingest"], dur: 11000, eyebrow: "01 · Read",
        title: "It starts from a single paragraph.",
        body: `<p>Then it reads every file in the folder - PDF, Word, Excel, CSV, Markdown, HTML - into structure-aware chunks, each labelled with its document and section.</p>
               <p>Search is hybrid: exact words for part numbers and clause ids, embeddings for paraphrase.</p>`,
        fact: `${docs.length} documents · ${(b.corpus || {}).chunks} chunks`,
        viz: el => {
          el.innerHTML = `<div class="vcard"><p class="eyebrow">brief.md</p><div class="typewriter" id="tw"></div></div>
            <div class="reveal" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:16px">${docs.map(d => `<span class="pill" style="padding:7px 12px;font-size:13px">${esc(d.path)} <span class="faint num">${d.table_rows ? d.table_rows + " rows" : (d.chars || 0).toLocaleString() + " chars"}</span></span>`).join("")}</div>`;
          typewrite(el.querySelector("#tw"), s.brief || "", 70);
        } },

      { id: "interview", focus: ["intake"], dur: 11000, eyebrow: "02 · Interview",
        title: "It asks before it builds.",
        body: `<p>At most five questions - only the ones that would change the agent. Each comes with a stated default, so an unattended run still proceeds, and every defaulted answer is written down as an assumption.</p>`,
        fact: `${(req.interview || []).length} questions · ${(req.must_answer || []).length} must-answer · ${(req.must_refuse || []).length} must-refuse topics`,
        viz: el => {
          el.innerHTML = `<div class="reveal">${(req.interview || []).slice(0, 5).map((q, i) => `<div class="vcard" style="margin-bottom:10px;padding:12px 16px">
            <div class="row"><span class="num faint">Q${i + 1}</span><b style="font-size:14px">${esc(q.question)}</b></div>
            <div class="row" style="margin-top:6px"><span class="pill ${q.source === "default" ? "gold" : "good"}">${esc(q.source)}</span><span class="muted" style="font-size:13px">${esc(q.answer).slice(0, 120)}</span></div></div>`).join("")}</div>`;
        } },

      { id: "guard", focus: ["guard"], dur: 13000, eyebrow: "03 · Groundability guard",
        title: "It refuses to build what the documents cannot support.",
        body: `<p>For every required topic it looks for evidence. A “supported” verdict only counts if its quote exists word-for-word in the documents.</p>
               <p>${(g.gaps || []).length ? `This brief asked for <b>${(g.gaps || []).map(x => esc(x.topic)).join("</b> and <b>")}</b>. The documents say nothing about ${(g.gaps || []).length > 1 ? "them" : "it"} - so the agent is told to decline, instead of inventing answers.` : "Every topic this brief asked for is supported."}</p>`,
        fact: `coverage ${pct(g.coverage)} · ${g.disagreements || 0} model verdicts overridden by code`,
        viz: el => {
          const cls = { supported: "good", tool: "model", partial: "gold", unsupported: "bad" };
          el.innerHTML = `<div class="vcard reveal">${(g.topics || []).map(t => `<div class="vrow"><span class="pill ${cls[t.verdict]}" style="width:104px;justify-content:center">${esc(t.verdict)}</span>
            <div style="flex:1"><b>${esc(t.topic)}</b>${t.evidence[0] ? `<div class="muted" style="font:13px/1.4 var(--serif);margin-top:3px">“${esc(t.evidence[0].quote.slice(0, 90))}” <span class="mono" style="color:var(--good)">✓ verbatim</span></div>` : `<div class="muted" style="font-size:12.5px;margin-top:3px">${esc((t.missing || "").slice(0, 110))}</div>`}</div></div>`).join("")}</div>`;
        } },

      { id: "gen", focus: ["gen"], dur: 12000, eyebrow: "04 · Generate the agent",
        title: "Tools have to earn their place.",
        body: `<p>The model proposes tools; code vetoes any tool whose need is not evidenced by a supported requirement, whose precondition fails, or that would only serve a gap.</p>
               <p>The system prompt is written in sections, so that later fixes can change one section and nothing else.</p>`,
        fact: `attached: ${tools.filter(t => t.attach).map(t => t.tool).join(", ") || "none"}`,
        viz: el => {
          el.innerHTML = `<div class="vcard reveal">${tools.map(t => `<div class="vrow"><span class="mono" style="width:120px">${esc(t.tool)}</span>
            <span class="pill ${t.model_said ? "model" : ""}">model: ${t.model_said ? "attach" : "no"}</span>
            <span class="pill ${t.attach ? "good" : t.model_said ? "bad" : ""}">${t.attach ? "attached" : t.model_said ? "vetoed" : "not needed"}</span>
            <span class="muted ${!t.attach && t.model_said ? "" : ""}" style="font-size:12.5px;flex:1">${esc((t.final_reason || t.model_reason || "").slice(0, 90))}</span></div>`).join("")}</div>
            <div class="reveal" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:14px">${(((b.agent || {}).system_prompt || {}).sections || []).map(x => `<span class="pill" style="padding:6px 11px">${esc(x.id)}</span>`).join("")}</div>`;
        } },

      { id: "tests", focus: ["evalgen"], dur: 13000, eyebrow: "05 · Write the tests",
        title: "It writes its own exam - and distrusts it.",
        body: `<p>Answerable, cross-document, rule-application (a real situation where a condition decides the value - with the tempting wrong value recorded as a trap), re-phrased, tool, out-of-scope and gap questions, all generated from the documents. Then code throws out the weak ones: facts not found verbatim, questions the model answers <i>without</i> the documents, refusal labels the corpus contradicts, duplicates.</p>
               <p>The rest are split into <b>dev</b> - which the optimizer may learn from - and <b>holdout</b>, which it never sees.</p>`,
        fact: `${ev.total} kept · ${dropped.reduce((a, [, v]) => a + v, 0)} dropped by self-checks`,
        viz: el => {
          el.innerHTML = `<div class="vcard"><div class="row" style="align-items:flex-end;gap:18px"><div><div class="big num" id="cnt">0</div><div class="muted">verified cases</div></div>
            <div class="reveal" style="flex:1">${dropped.map(([k, v]) => `<div class="vrow"><span class="pill bad">−${v}</span><span class="muted" style="font-size:13px">${esc(k.replace("dropped_", "").replace(/_/g, " "))}</span></div>`).join("")}</div></div>
            <div style="display:flex;height:34px;border-radius:9px;overflow:hidden;margin-top:18px">
              <div style="flex:${ev.dev};background:var(--model-soft);color:var(--model);display:grid;place-items:center;font:12px var(--mono)">dev ${ev.dev}</div>
              <div style="flex:${ev.holdout};background:var(--good-soft);color:var(--good);display:grid;place-items:center;font:12px var(--mono)">holdout ${ev.holdout} · never shown to the optimizer</div></div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:14px">${Object.entries(ev.by_kind || {}).map(([k, v]) => `<span class="pill">${esc(k.replace("_", " "))} <b class="num">${v}</b></span>`).join("")}</div></div>`;
          countUp(el.querySelector("#cnt"), ev.total || 0, 1600, v => Math.round(v));
        } },

      { id: "tour", focus: ["tour", "judge"], dur: 10000, eyebrow: "06 · Prompt tournament",
        title: "Three prompts compete. The tests pick the winner.",
        body: `<p>Each candidate is scored case-by-case on the dev set - never by asking a model “which is better, A or B?”, so there is no position bias to exploit.</p>`,
        fact: tour.length ? `winner: ${esc((tour.find(t => t.winner) || {}).style)}` : "skipped (time budget)",
        viz: el => {
          el.innerHTML = `<div class="vcard">${tour.map(t => `<div class="vrow"><span class="mono" style="width:100px">${esc(t.style)}</span>
            <div class="bar model" style="flex:1;height:14px;border-radius:7px"><i style="width:0" data-w="${(t.dev.rate || 0) * 100}"></i></div>
            <span class="num" style="width:56px;text-align:right">${t.dev.passed}/${t.dev.n}</span>${t.winner ? `<span class="pill good">winner</span>` : `<span class="pill" style="visibility:hidden">winner</span>`}</div>`).join("")}</div>`;
          setTimeout(() => el.querySelectorAll("[data-w]").forEach(i => i.style.width = i.dataset.w + "%"), 400);
        } },

      { id: "judge", focus: ["judge", "audit"], dur: 13000, eyebrow: "07 · Judge",
        title: "Code judges first. The model only gets the leftovers - and is audited.",
        body: `<p>Exact and numeric fact matching, refusal flags and citation checks are plain code. Only ambiguous facts reach the model judge - one fact at a time, and its quote must exist in the answer. A changed number is never forgiven.</p>
               <p>Every run, the judge is tested on canaries whose verdict is known.</p>`,
        fact: `judge ${esc(s.models.judge_model)} ≠ agent family · canaries ${pct(can.overall)} (${can.n_canaries || 0})`,
        viz: el => {
          const tot = (meth.code || 0) + (meth.model || 0) || 1;
          const row = (l, v) => `<div class="vrow"><span style="width:230px;font-size:13.5px">${l}</span><div class="bar" style="flex:1;height:10px"><i style="width:0" data-w="${(v || 0) * 100}"></i></div><span class="num" style="width:46px;text-align:right">${pct(v)}</span></div>`;
          el.innerHTML = `<div class="vcard"><p class="eyebrow">Fact verdicts in the final run</p>
            <div style="display:flex;height:30px;border-radius:8px;overflow:hidden"><div style="flex:${meth.code || 0};background:var(--good-soft);color:var(--good);display:grid;place-items:center;font:12px var(--mono)">code ${meth.code || 0}</div>
            <div style="flex:${meth.model || 0};background:var(--model-soft);color:var(--model);display:grid;place-items:center;font:12px var(--mono)">model ${meth.model || 0}</div></div></div>
            <div class="vcard" style="margin-top:14px"><p class="eyebrow">Canary audit</p>
            ${row("correct answer accepted", can.gold_pass)}${row("wrong numbers rejected", can.corrupted_fail)}${row("padded answer accepted", can.padded_pass)}${row("fabricated claim caught", can.fabrication_caught)}</div>`;
          setTimeout(() => el.querySelectorAll("[data-w]").forEach(i => i.style.width = i.dataset.w + "%"), 500);
        } },

      { id: "opt", focus: ["judge", "opt"], dur: 14000, eyebrow: "07·k · Critic–optimizer",
        title: "Diagnose. Patch one thing. Prove it helped - or undo it.",
        body: `<p>Each failure is classified by measurement: was the fact in what the agent saw (<i>retrieval miss</i>)? is every claim supported (<i>hallucination</i>)? did it refuse with the answer in hand (<i>wrong refusal</i>)? Otherwise it is a <i>prompt defect</i>.</p>
               <p>A patch must fix its target cases without breaking others. ${ch.some(p => p.accepted) ? "" : "Here no proposed patch survived its gate - so nothing was changed. An honest stop beats a forced change."}</p>`,
        fact: `${ch.length} patches proposed · ${ch.filter(p => p.accepted).length} kept · max 3 iterations`,
        viz: el => {
          el.innerHTML = `<div class="reveal">${(ch.length ? ch : [{ id: "-", target: "no failures", change_summary: "Nothing needed fixing.", gate: {}, accepted: true }]).slice(0, 4).map(p => `<div class="vcard" style="margin-bottom:10px;padding:13px 16px">
            <div class="row"><span class="num faint">${esc(p.id)}</span><span class="pill model">${esc(p.target)}</span><span class="pill ${p.accepted ? "good" : "bad"}">${p.accepted ? "kept" : "rejected by gate"}</span>
            <span class="faint num" style="font-size:12px">fixed ${(p.gate.fixed || []).length} · broke ${(p.gate.broke || []).length}</span></div>
            <div style="margin-top:6px;font:15px/1.4 var(--serif)">${esc((p.change_summary || "").slice(0, 150))}</div></div>`).join("")}</div>`;
        } },

      { id: "result", focus: ["ship"], dur: 14000, eyebrow: "09 · Honest report",
        title: "It leads with the number you should trust.",
        body: `<p>The headline is the <b>holdout</b> score - cases the optimizer never saw - with its 95% interval. Then exactly what still fails, and why.</p>
               ${fails.length ? `<p>${fails.slice(0, 2).map(f => `<b>${esc(f.id)}</b> - ${esc(f.verdict.failure.category.replace("_", " "))}: ${esc(f.verdict.failure.detail.slice(0, 90))}`).join("<br>")}</p>` : ""}`,
        fact: `baseline holdout ${pct(rep.baseline && rep.baseline.holdout.rate)} → final ${pct(rep.holdout && rep.holdout.rate)} · dev ${pct(rep.dev && rep.dev.rate)}`,
        viz: el => {
          const h = rep.holdout || { rate: 0, ci95: [0, 0], passed: 0, n: 0 };
          el.innerHTML = `<div class="vcard" style="padding:28px 30px"><p class="eyebrow">Holdout pass rate</p><div class="big num" id="hv">0%</div>
            <div class="muted num" style="margin-top:8px">${h.passed}/${h.n} cases · 95% CI ${Math.round(h.ci95[0] * 100)}–${Math.round(h.ci95[1] * 100)}%</div>
            <div class="ci" style="height:26px;margin-top:22px"><div class="track"></div><div class="band" style="left:${h.ci95[0] * 100}%;width:${(h.ci95[1] - h.ci95[0]) * 100}%"></div><div class="pt" style="left:${h.rate * 100}%"></div></div>
            <div class="reveal" style="margin-top:20px">${Object.entries(rep.failures_final || {}).map(([k, v]) => `<div class="vrow"><span class="pill bad">${v}</span><span>${esc(k.replace("_", " "))}</span></div>`).join("") || `<div class="vrow"><span class="pill good">0</span><span>failures</span></div>`}</div></div>`;
          countUp(el.querySelector("#hv"), (h.rate || 0) * 100, 1800, v => Math.round(v) + "%");
        } },

      { id: "chat", focus: ["ship"], dur: 13000, eyebrow: "The agent it shipped",
        title: "Grounded answers. Honest refusals.",
        body: `<p>The generated agent runs in a generic runner that loads any definition - the same runtime the tests used. It cites the passages it used, and declines what its documents do not cover.</p>`,
        fact: `agent/agent.json · forge chat ${esc(s.id)}`,
        viz: el => {
          const one = (c) => c ? `<div class="vcard" style="margin-bottom:12px"><div class="msg me" style="margin:0 0 10px auto">${esc(c.question)}</div>
            <div style="font:16px/1.5 var(--serif)">${esc((c.response.answer || "").slice(0, 280))}</div>
            <div class="row wrap" style="margin-top:8px;gap:6px">${c.response.refused ? `<span class="pill gold">declined</span>` : ""}${(c.response.citations || []).map(l => `<span class="pill model">${esc(l)}</span>`).join("")}<span class="pill good">judge: pass</span></div></div>` : "";
          el.innerHTML = `<div class="reveal">${one(showcase)}${one(gapCase)}</div>`;
        } },

      { id: "outro", focus: null, wide: true, dur: 12000, eyebrow: "Why trust it",
        title: "Distrust the pipeline. Verify everything.",
        body: `<p>Quotes verified verbatim. Facts verified verbatim. Leakage probed. Labels checked against the corpus. Judge audited. Patches gated. Holdout untouched. Every model call recorded - and the whole run replays without a model, every artifact identical apart from timings.</p>`,
        fact: `forge build --brief-file brief.md --docs ./docs`,
        viz: el => { el.innerHTML = `<div class="vcard" style="padding:10px"></div>`; const m = FactoryMap.create(el.firstChild); FactoryMap.fromRun(m, b); return () => m.destroy(); } },
    ];
  }

  function open(bundle, onClose) {
    if (!bundle) { alert("Pick a run first."); onClose && onClose(); return; }
    const sc = scenes(bundle);
    const root = document.createElement("div");
    root.className = "film";
    root.innerHTML = `<header><div class="brand"><b>ForgeAI</b><span>how it works</span></div><span class="faint mono" style="font-size:12px">${esc(bundle.summary.agent)}</span>
        <span style="flex:1"></span><span class="ctl faint mono" style="font-size:11.5px">space · ← → · R record · esc</span><button class="btn ctl" id="x-close">Close</button></header>
      <div class="stage"><div class="copy" id="x-copy"></div><div class="viz" id="x-viz"></div></div>
      <div class="strip" id="x-strip"></div>
      <footer><button class="btn ctl" id="x-prev">←</button><button class="btn ctl" id="x-play">Pause</button><button class="btn ctl" id="x-next">→</button>
        <div class="tl">${sc.map((_, i) => `<i data-i="${i}"><b></b></i>`).join("")}</div><span class="num faint" id="x-n"></span></footer>`;
    document.body.appendChild(root);
    const strip = FactoryMap.create(root.querySelector("#x-strip"));
    FactoryMap.fromRun(strip, bundle);
    let idx = 0, playing = true, t0 = 0, elapsed = 0, raf = 0, cleanup = null;
    const segs = root.querySelectorAll(".tl b");
    function show(i) {
      idx = Math.max(0, Math.min(sc.length - 1, i)); elapsed = 0; t0 = performance.now();
      const s = sc[idx];
      root.classList.toggle("wide", !!s.wide);
      strip.focus(s.focus);
      if (cleanup) { try { cleanup(); } catch (e) { } cleanup = null; }
      root.querySelector("#x-copy").innerHTML = `<div class="reveal"><p class="eyebrow">${s.eyebrow}</p><h2>${s.title}</h2>${s.body}<p class="fact">${s.fact || ""}</p></div>`;
      const viz = root.querySelector("#x-viz");
      viz.innerHTML = ""; viz.className = "viz fade";
      cleanup = s.viz(viz) || null;
      root.querySelector("#x-n").textContent = `${idx + 1} / ${sc.length}`;
      segs.forEach((b, j) => b.style.width = j < idx ? "100%" : "0");
    }
    function loop(t) {
      raf = requestAnimationFrame(loop);
      if (!playing) { t0 = t - elapsed; return; }
      elapsed = t - t0;
      const d = sc[idx].dur;
      segs[idx].style.width = Math.min(100, elapsed / d * 100) + "%";
      if (elapsed >= d) { if (idx < sc.length - 1) show(idx + 1); else { playing = false; root.querySelector("#x-play").textContent = "Replay"; } }
    }
    function close() { cancelAnimationFrame(raf); if (cleanup) cleanup(); strip.destroy(); root.remove(); document.removeEventListener("keydown", key); onClose && onClose(); }
    function toggle() {
      if (!playing && idx === sc.length - 1 && elapsed >= sc[idx].dur) show(0);
      playing = !playing; root.querySelector("#x-play").textContent = playing ? "Pause" : "Play";
    }
    function key(e) {
      if (e.key === " ") { e.preventDefault(); toggle(); }
      else if (e.key === "ArrowRight") show(idx + 1);
      else if (e.key === "ArrowLeft") show(idx - 1);
      else if (e.key === "r" || e.key === "R") root.classList.toggle("rec");
      else if (e.key === "Escape") close();
    }
    document.addEventListener("keydown", key);
    root.querySelector("#x-close").onclick = close;
    root.querySelector("#x-prev").onclick = () => show(idx - 1);
    root.querySelector("#x-next").onclick = () => show(idx + 1);
    root.querySelector("#x-play").onclick = toggle;
    root.querySelectorAll(".tl i").forEach(x => x.onclick = () => show(+x.dataset.i));
    const qs = new URLSearchParams(location.search);
    show(+(qs.get("scene") || 0));
    if (qs.get("still")) { playing = false; root.classList.add("rec"); }
    raf = requestAnimationFrame(loop);
  }

  window.Explain = { open };
})();
