/* The brief: renders docs/*.brief decks (the EVIDENT deck format) inside the Studio.
   Format: "# Title", "> subtitle", "accent: clay", "## Slide", paragraphs, "- bullets", "> callout",
   "note: speaker note", ```visual blocks (metrics / flow+active / timeline+at / image+caption / quote),
   ```math blocks. Keys in present mode: ← → step · P autoplay · N notes · Esc stop. */
(function () {
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  const ACCENTS = { clay: ["#B5603A", "#E89A72"], teal: ["#0B7F73", "#42D9C4"], violet: ["#5350C4", "#A4A2FF"], gold: ["#A66B10", "#F3BC52"] };

  function parse(text) {
    const deck = { title: "", subtitle: "", accent: "clay", author: "", slides: [] };
    let cur = null, block = null;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/\s+$/, "");
      if (block) {
        if (line.startsWith("```")) { cur.parts.push(block); block = null; continue; }
        block.lines.push(line); continue;
      }
      if (line.startsWith("//")) continue;
      if (line.startsWith("```")) { block = { type: line.slice(3).trim() || "code", lines: [] }; if (!cur) cur = { title: "", parts: [], notes: [] }; continue; }
      if (line.startsWith("## ")) { cur = { title: line.slice(3).trim(), parts: [], notes: [] }; deck.slides.push(cur); continue; }
      if (!cur) {
        if (line.startsWith("# ")) deck.title = line.slice(2).trim();
        else if (line.startsWith("> ")) deck.subtitle = line.slice(2).trim();
        else if (/^accent:/.test(line)) deck.accent = line.split(":")[1].trim();
        else if (/^author:/.test(line)) deck.author = line.split(":").slice(1).join(":").trim();
        continue;
      }
      if (!line.trim()) continue;
      if (line.startsWith("note:")) cur.notes.push(line.slice(5).trim());
      else if (line.startsWith("- ")) { const last = cur.parts[cur.parts.length - 1]; if (last && last.type === "ul") last.items.push(line.slice(2)); else cur.parts.push({ type: "ul", items: [line.slice(2)] }); }
      else if (line.startsWith("> ")) cur.parts.push({ type: "callout", text: line.slice(2) });
      else cur.parts.push({ type: "p", text: line });
    }
    return deck;
  }

  function kv(lines) {
    const o = {};
    lines.forEach(l => { const i = l.indexOf(":"); if (i > 0) o[l.slice(0, i).trim()] = l.slice(i + 1).trim(); });
    return o;
  }

  function visual(v) {
    const o = kv(v.lines);
    if (o.metrics) {
      const ms = o.metrics.split("|").map(x => x.split("=").map(y => y.trim()));
      return `<div class="bv-metrics" style="grid-template-columns:repeat(${Math.min(4, ms.length)},1fr)">${ms.map(([l, val], i) =>
        `<div class="bv-m" style="animation-delay:${0.15 + i * 0.15}s"><div class="bv-mv">${esc(val)}</div><div class="bv-ml">${esc(l)}</div></div>`).join("")}</div>`;
    }
    if (o.flow) {
      const steps = o.flow.split("->").map(x => x.trim()), act = (o.active || "").trim();
      return `<div class="bv-flow">${steps.map((st, i) => `${i ? `<span class="bv-arrow"><i></i></span>` : ""}<span class="bv-step ${st === act ? "on" : ""}" style="animation-delay:${0.1 + i * 0.12}s">${esc(st)}</span>`).join("")}</div>`;
    }
    if (o.timeline) {
      const pts = o.timeline.split("|").map(x => x.trim()), at = +(o.at || pts.length);
      return `<div class="bv-tl"><div class="bv-tl-line"><i style="width:${Math.max(0, (at - 1) / Math.max(1, pts.length - 1) * 100)}%"></i></div>${pts.map((p, i) =>
        `<div class="bv-tl-p ${i < at ? "on" : ""}" style="left:${i / Math.max(1, pts.length - 1) * 100}%"><b></b><span>${esc(p)}</span></div>`).join("")}</div>`;
    }
    if (o.image) {
      return `<figure class="bv-img"><img src="/api/asset?path=${encodeURIComponent(o.image)}" alt="${esc(o.caption || "")}">${o.caption ? `<figcaption>${esc(o.caption)}</figcaption>` : ""}</figure>`;
    }
    if (o.quote) return `<blockquote class="bv-quote">${inline(o.quote)}</blockquote>`;
    return `<pre class="bv-code">${esc(v.lines.join("\n"))}</pre>`;
  }

  function slideHtml(deck, s, i) {
    const body = s.parts.map(p => {
      if (p.type === "p") return `<p>${inline(p.text)}</p>`;
      if (p.type === "ul") return `<ul>${p.items.map(x => `<li>${inline(x)}</li>`).join("")}</ul>`;
      if (p.type === "callout") return `<div class="bv-callout">${inline(p.text)}</div>`;
      if (p.type === "visual") return visual(p);
      if (p.type === "math") return `<pre class="bv-code">${esc(p.lines.join("\n"))}</pre>`;
      return `<pre class="bv-code">${esc((p.lines || []).join("\n"))}</pre>`;
    }).join("");
    return `<div class="bslide"><div class="bs-head"><span>${esc(deck.title)}</span><span class="num">${String(i + 1).padStart(2, "0")} / ${String(deck.slides.length).padStart(2, "0")}</span></div>
      <h2>${inline(s.title)}</h2><div class="bs-body">${body}</div></div>`;
  }

  function titleHtml(deck) {
    return `<div class="bslide btitle"><div class="bs-head"><span>${esc(deck.author)}</span><span class="num">ForgeAI</span></div>
      <h1>${esc(deck.title)}</h1><p class="bt-sub">${inline(deck.subtitle)}</p><div class="bt-rule"></div></div>`;
  }

  const CSS = `
  .bwrap{display:grid;grid-template-columns:250px minmax(0,1fr);gap:22px;align-items:start}
  .boutline{position:sticky;top:90px;max-height:calc(100vh - 120px);overflow:auto;font-size:13px}
  .boutline button{display:flex;gap:10px;width:100%;text-align:left;background:none;border:0;padding:7px 10px;border-radius:8px;color:var(--ink2);cursor:pointer}
  .boutline button.on{background:var(--surface);color:var(--ink);box-shadow:var(--shadow)} .boutline .num{color:var(--ink3);width:20px}
  .bframe{aspect-ratio:16/9;width:100%;background:var(--surface);border:1px solid var(--hair);border-radius:16px;overflow:hidden;position:relative;container-type:inline-size}
  .bslide{position:absolute;inset:0;padding:4.2cqw 5cqw;display:flex;flex-direction:column;animation:fade .45s ease both}
  .bs-head{display:flex;justify-content:space-between;font:1.05cqw var(--mono);color:var(--ink3);text-transform:uppercase;letter-spacing:.14em;margin-bottom:2.4cqw}
  .bslide h2{font:400 3.6cqw/1.08 var(--serif);letter-spacing:-.02em;margin:0 0 1.8cqw;max-width:80%}
  .bs-body{font:1.75cqw/1.5 var(--serif);color:var(--ink2);flex:1;display:flex;flex-direction:column;gap:1.3cqw;min-height:0}
  .bs-body p{margin:0;max-width:78%} .bs-body ul{margin:0;padding-left:2cqw;max-width:80%} .bs-body li{margin:.4cqw 0}
  .bs-body b{color:var(--ink);font-weight:600} .bs-body code{font:1.4cqw var(--mono);background:var(--raised);padding:.1cqw .5cqw;border-radius:.4cqw}
  .bv-callout{border-left:.3cqw solid var(--acc);padding:.4cqw 0 .4cqw 1.4cqw;color:var(--ink);font-style:italic;max-width:80%}
  .bv-metrics{display:grid;gap:1.6cqw;margin-top:auto}
  .bv-m{border-top:1px solid var(--hair);padding-top:1.2cqw;opacity:0;animation:fade .6s ease forwards}
  .bv-mv{font:400 5.2cqw/1 var(--serif);color:var(--ink);letter-spacing:-.03em} .bv-m:first-child .bv-mv{color:var(--acc)}
  .bv-ml{font:1.2cqw/1.35 var(--sans);color:var(--ink3);margin-top:.8cqw;max-width:90%}
  .bv-flow{display:flex;align-items:center;flex-wrap:wrap;gap:.6cqw;margin:auto 0 0}
  .bv-step{padding:1.1cqw 1.5cqw;border:1px solid var(--hair);border-radius:1cqw;font:1.45cqw var(--sans);color:var(--ink2);background:var(--bg);opacity:0;animation:fade .5s ease forwards}
  .bv-step.on{border-color:var(--acc);color:var(--ink);box-shadow:0 0 0 .35cqw color-mix(in srgb,var(--acc) 18%,transparent)}
  .bv-arrow{width:2.4cqw;height:2px;background:var(--hair);position:relative;overflow:hidden} .bv-arrow i{position:absolute;top:-1px;width:.8cqw;height:4px;border-radius:2px;background:var(--acc);animation:flow 1.6s linear infinite}
  @keyframes flow{from{left:-1cqw}to{left:2.6cqw}}
  .bv-tl{position:relative;height:7cqw;margin:auto 3cqw 0}
  .bv-tl-line{position:absolute;left:0;right:0;top:1.4cqw;height:2px;background:var(--hair)} .bv-tl-line i{display:block;height:100%;background:var(--acc);animation:grow 1.4s ease both}
  @keyframes grow{from{width:0}}
  .bv-tl-p{position:absolute;top:0;transform:translateX(-50%);text-align:center;width:12cqw} .bv-tl-p b{display:block;margin:.8cqw auto 1cqw;width:1.3cqw;height:1.3cqw;border-radius:50%;background:var(--surface);border:2px solid var(--hair)}
  .bv-tl-p.on b{background:var(--acc);border-color:var(--acc)} .bv-tl-p span{font:1.2cqw var(--sans);color:var(--ink2)}
  .bv-img{margin:0;flex:1;min-height:0;display:flex;flex-direction:column} .bv-img img{flex:1;min-height:0;object-fit:contain;object-position:left top;border-radius:1cqw;border:1px solid var(--hair);width:100%}
  .bv-img figcaption{font:1.15cqw var(--mono);color:var(--ink3);margin-top:.8cqw}
  .bv-quote{font:400 3.4cqw/1.25 var(--serif);color:var(--ink);margin:auto 0;max-width:85%;border-left:.4cqw solid var(--acc);padding-left:2.4cqw}
  .bv-code{font:1.3cqw/1.5 var(--mono);background:var(--bg);border:1px solid var(--hair);border-radius:1cqw;padding:1.2cqw 1.6cqw;margin:0;white-space:pre-wrap}
  .btitle{justify-content:center} .btitle h1{font:400 7cqw/1 var(--serif);letter-spacing:-.035em;margin:0} .bt-sub{font:2cqw/1.45 var(--serif);color:var(--ink2);max-width:70%;margin:2cqw 0 0}
  .bt-rule{width:9cqw;height:.35cqw;background:var(--acc);margin-top:3cqw;border-radius:1cqw}
  .bnotes{margin-top:14px} .bnotes p{margin:4px 0;color:var(--ink2);font-size:13.5px}
  .bpresent{position:fixed;inset:0;z-index:70;background:var(--bg);display:grid;place-items:center}
  .bpresent .bframe{width:min(100vw,177.78vh);border:0;border-radius:0}
  .bpresent .bnote-ov{position:fixed;left:24px;right:24px;bottom:18px;background:rgba(0,0,0,.72);color:#eee;padding:12px 16px;border-radius:10px;font-size:14px;display:none}
  .bpresent.notes .bnote-ov{display:block}
  .bprog{position:fixed;left:0;bottom:0;height:3px;background:var(--acc);transition:width .4s}`;

  async function mount(page) {
    if (!document.getElementById("brief-css")) { const st = document.createElement("style"); st.id = "brief-css"; st.textContent = CSS; document.head.appendChild(st); }
    let data;
    try { data = await (await fetch("/api/brief")).json(); } catch (e) { data = { error: String(e) }; }
    if (data.error) { page.innerHTML = `<div class="empty">${esc(data.error)}</div>`; return; }
    const deck = parse(data.text);
    const dark = getComputedStyle(document.documentElement).colorScheme === "dark";
    const acc = (ACCENTS[deck.accent] || ACCENTS.clay)[dark ? 1 : 0];
    page.style.setProperty("--acc", acc);
    const all = [{ title: deck.title, title_slide: true, notes: [] }, ...deck.slides];
    let i = 0;
    page.innerHTML = `<div class="row" style="margin-bottom:16px"><span class="faint mono" style="font-size:12px">${esc(data.path)} · every number on these slides is read from a file in this repository</span><span style="flex:1"></span>
      <button class="btn" id="bp-prev">←</button><button class="btn" id="bp-next">→</button><button class="btn primary" id="bp-present">Present</button></div>
      <div class="bwrap"><div class="boutline" id="bp-out">${all.map((s, k) => `<button data-k="${k}"><span class="num">${k}</span><span>${esc(s.title)}</span></button>`).join("")}</div>
      <div><div class="bframe" id="bp-frame"></div><div class="bnotes" id="bp-notes"></div></div></div>`;
    const frame = page.querySelector("#bp-frame");
    function draw(target) {
      const s = all[i];
      (target || frame).innerHTML = s.title_slide ? titleHtml(deck) : slideHtml(deck, s, i - 1);
      page.querySelector("#bp-notes").innerHTML = (s.notes || []).map(n => `<p>📝 ${inline(n)}</p>`).join("");
      page.querySelectorAll("#bp-out button").forEach(b => b.classList.toggle("on", +b.dataset.k === i));
    }
    const go = k => { i = Math.max(0, Math.min(all.length - 1, k)); draw(); };
    page.querySelector("#bp-prev").onclick = () => go(i - 1);
    page.querySelector("#bp-next").onclick = () => go(i + 1);
    page.querySelectorAll("#bp-out button").forEach(b => b.onclick = () => go(+b.dataset.k));
    page.querySelector("#bp-present").onclick = () => present();
    const navKey = e => {
      if (!page.isConnected || !page.querySelector("#bp-frame")) { document.removeEventListener("keydown", navKey); return; }
      if (document.querySelector(".bpresent") || /input|textarea/i.test((e.target || {}).tagName || "")) return;
      if (e.key === "ArrowRight") go(i + 1); else if (e.key === "ArrowLeft") go(i - 1);
    };
    document.addEventListener("keydown", navKey);
    draw();

    function present() {
      const ov = document.createElement("div");
      ov.className = "bpresent"; ov.style.setProperty("--acc", acc);
      ov.innerHTML = `<div class="bframe"></div><div class="bnote-ov"></div><div class="bprog"></div>`;
      document.body.appendChild(ov);
      const f = ov.querySelector(".bframe");
      let auto = null;
      const paint = () => {
        const s = all[i];
        f.innerHTML = s.title_slide ? titleHtml(deck) : slideHtml(deck, s, i - 1);
        ov.querySelector(".bnote-ov").innerHTML = (s.notes || []).map(inline).join("<br>") || "(no notes)";
        ov.querySelector(".bprog").style.width = (i / (all.length - 1) * 100) + "%";
      };
      const key = e => {
        if (["ArrowRight", " ", "PageDown"].includes(e.key)) { e.preventDefault(); i = Math.min(all.length - 1, i + 1); paint(); }
        else if (["ArrowLeft", "PageUp"].includes(e.key)) { i = Math.max(0, i - 1); paint(); }
        else if (e.key === "n" || e.key === "N") ov.classList.toggle("notes");
        else if (e.key === "p" || e.key === "P") { if (auto) { clearInterval(auto); auto = null; } else auto = setInterval(() => { if (i < all.length - 1) { i++; paint(); } else { clearInterval(auto); auto = null; } }, 9000); }
        else if (e.key === "Escape") { if (auto) clearInterval(auto); document.removeEventListener("keydown", key); ov.remove(); if (document.fullscreenElement) document.exitFullscreen(); draw(); }
      };
      document.addEventListener("keydown", key);
      ov.onclick = () => { i = Math.min(all.length - 1, i + 1); paint(); };
      if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => { });
      paint();
    }
  }
  window.Brief = { mount, parse };
})();
