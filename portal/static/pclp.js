/* PCLP — comportamentul paginilor (fără dependențe). */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("pclp." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("pclp." + k, JSON.stringify(v)); } catch (e) { /* stocare indisponibilă */ } },
  };
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const post = (url, data) => {
    const fd = new FormData();
    Object.entries(data || {}).forEach(([k, v]) => fd.append(k, v));
    return fetch(url, { method: "POST", body: fd, headers: { "X-CSRFToken": window.PCLP.csrf } });
  };

  // înălțimea antetului (se poate rupe pe două rânduri) pentru elementele lipicioase
  const top = $(".top");
  const setTopH = () => document.documentElement.style.setProperty("--top-h", top.offsetHeight + "px");
  setTopH();
  window.addEventListener("resize", setTopH);

  // ---- meniu mobil
  const menu = $("#menu");
  if (menu) menu.addEventListener("click", () => $("#nav").classList.toggle("open"));

  // ---- căutare cu sugestii
  const q = $("#q"), sugg = $("#sugg");
  let sel = -1, timer = null;
  function renderSugg(items) {
    if (!items.length) { sugg.hidden = true; return; }
    sugg.innerHTML = items.map((it, i) => `<a href="/termen/${it.id}/" class="${i === sel ? "sel" : ""}"><b class="tl l${it.level}">${esc(it.label)}</b> <span class="badge">${esc(it.kind)}</span><span class="d">${esc(it.def)}</span></a>`).join("")
      + `<a href="/cauta/?q=${encodeURIComponent(q.value)}&toate=1" class="muted small">Caută „${esc(q.value)}” în tot textul →</a>`;
    sugg.hidden = false;
  }
  if (q) {
    q.addEventListener("input", () => {
      clearTimeout(timer); sel = -1;
      const v = q.value.trim();
      if (v.length < 1) { sugg.hidden = true; return; }
      timer = setTimeout(() => fetch("/api/sugestii/?q=" + encodeURIComponent(v)).then((r) => r.json()).then((d) => { q._items = d.items; renderSugg(d.items); }), 120);
    });
    q.addEventListener("keydown", (e) => {
      const n = (q._items || []).length;
      if (e.key === "ArrowDown") { sel = Math.min(n - 1, sel + 1); renderSugg(q._items || []); e.preventDefault(); }
      else if (e.key === "ArrowUp") { sel = Math.max(-1, sel - 1); renderSugg(q._items || []); e.preventDefault(); }
      else if (e.key === "Enter" && sel >= 0) { e.preventDefault(); location.href = "/termen/" + q._items[sel].id + "/"; }
      else if (e.key === "Escape") { sugg.hidden = true; q.blur(); }
    });
    document.addEventListener("click", (e) => { if (!e.target.closest(".search")) sugg.hidden = true; });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !e.target.closest("input,textarea,select,[contenteditable]")) { e.preventDefault(); q.focus(); q.select(); }
    });
  }

  // ---- tooltip cu definiția scurtă
  const tip = $("#tip");
  const termCache = {};
  let tipTimer = null;
  function showTip(a) {
    const id = a.dataset.t;
    const place = (d) => {
      tip.innerHTML = `<b class="tl l${d.level}">${esc(d.label)}</b><span class="muted small">${esc(d.kind)}${d.origin === "claude" ? " · adăugat, neverificat" : ""}</span><div>${esc(d.definition || "—")}</div>`;
      tip.hidden = false;
      const r = a.getBoundingClientRect();
      const w = Math.min(340, window.innerWidth - 20);
      let left = Math.max(10, Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - w - 10));
      tip.style.left = left + "px";
      tip.style.top = (window.scrollY + r.bottom + 8) + "px";
    };
    if (termCache[id]) return place(termCache[id]);
    fetch(`/api/termen/${id}/`).then((r) => r.json()).then((d) => { termCache[id] = d; if (a.matches(":hover")) place(d); });
  }
  document.addEventListener("mouseover", (e) => {
    const a = e.target.closest("a.term, a[data-tip]");
    if (!a || !a.dataset.t) return;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => showTip(a), 250);
  });
  document.addEventListener("mouseout", (e) => { if (e.target.closest("a.term, a[data-tip]")) { clearTimeout(tipTimer); tip.hidden = true; } });

  // ---- panoul de concept (cititor, capitol)
  const panelBox = $("#panel");
  const sheet = $("#sheet");
  const panelCache = {};
  const narrow = () => window.matchMedia("(max-width: 1180px)").matches;
  function openPanel(id, opts = {}) {
    const target = narrow() || !panelBox ? $(".sheet-body", sheet) : panelBox;
    const show = (html) => {
      target.innerHTML = html;
      const wrap = $("#panelwrap");
      if (wrap && target === panelBox) { wrap.hidden = false; const st = $("#secterms"); if (st) st.hidden = true; }
      if (target !== panelBox) sheet.hidden = false;
      applyLevelFilter();
      if (opts.list) navInfo(target, opts.list, id);
      document.dispatchEvent(new CustomEvent("pclp:panel", { detail: { id } }));
    };
    if (panelCache[id]) show(panelCache[id]);
    else fetch(`/api/panou/${id}/`).then((r) => r.text()).then((h) => { panelCache[id] = h; show(h); });
    if (!opts.keepHash) history.replaceState(null, "", location.pathname + location.search + "#t=" + id);
    highlightTerm(id);
  }
  window.PCLP.openPanel = openPanel;
  if (sheet) sheet.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) sheet.hidden = true; });

  function highlightTerm(id) {
    $$("a.term.hl-on").forEach((a) => a.classList.remove("hl-on"));
    if (!id) return;
    $$(`a.term[data-t="${id}"]`).forEach((a) => a.classList.add("hl-on"));
  }

  // în cititor și în capitol, clic pe termen → panou
  const inPanelMode = document.body.classList.contains("panelmode");
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a.term, a[data-panel]");
    if (!a || !inPanelMode || e.metaKey || e.ctrlKey) return;
    const id = a.dataset.t || a.dataset.panel;
    if (!id) return;
    e.preventDefault();
    tip.hidden = true;
    openPanel(id, { list: currentList() });
  });

  // ---- capitol: listă filtrabilă + navigare ←/→
  function currentList() { return $$(".clist li:not([hidden])").map((li) => li.dataset.id); }
  function navInfo(target, list, id) {
    const i = list.indexOf(id);
    const nav = target.querySelector(".nav2 .pos");
    if (nav) nav.textContent = i >= 0 ? `${i + 1} / ${list.length}` : "";
    $$(".clist li").forEach((li) => li.classList.toggle("sel", li.dataset.id === id));
  }
  $$(".clist li").forEach((li) => li.addEventListener("click", () => openPanel(li.dataset.id, { list: currentList() })));
  const filt = $("#cfilter");
  function norm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function applyChapterFilter() {
    const v = norm(filt ? filt.value : "");
    const lv = $$("input[data-lvl]").filter((c) => c.checked).map((c) => c.dataset.lvl);
    $$(".clist li").forEach((li) => { li.hidden = !(norm(li.dataset.label).includes(v) && lv.includes(li.dataset.level)); });
    $$(".lvlgroup").forEach((g) => { g.hidden = !$$("li:not([hidden])", g).length; });
  }
  if (filt) { filt.addEventListener("input", applyChapterFilter); $$("input[data-lvl]").forEach((c) => c.addEventListener("change", applyChapterFilter)); }
  document.addEventListener("keydown", (e) => {
    if (!inPanelMode || e.target.closest("input,textarea,select")) return;
    const cur = (location.hash.match(/#t=([\w-]+)/) || [])[1];
    const list = $(".clist") ? currentList() : [];
    if (!cur || !list.length) return;
    const i = list.indexOf(cur);
    if (["ArrowRight", "j"].includes(e.key) && i < list.length - 1) openPanel(list[i + 1], { list });
    if (["ArrowLeft", "k"].includes(e.key) && i > 0) openPanel(list[i - 1], { list });
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-step]");
    if (!b) return;
    const list = currentList();
    const cur = (location.hash.match(/#t=([\w-]+)/) || [])[1];
    const i = list.indexOf(cur) + parseInt(b.dataset.step, 10);
    if (i >= 0 && i < list.length) openPanel(list[i], { list });
  });

  // ---- filtrul de niveluri pentru termenii legați (memorat local)
  function applyLevelFilter() {
    const lf = store.get("lf", 3);
    document.body.classList.remove("lf-1", "lf-2");
    if (lf < 3) document.body.classList.add("lf-" + lf);
    $$(".levelfilter button").forEach((b) => b.classList.toggle("on", parseInt(b.dataset.lf, 10) === lf));
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".levelfilter button");
    if (!b) return;
    store.set("lf", parseInt(b.dataset.lf, 10));
    applyLevelFilter();
  });
  applyLevelFilter();

  // ---- cititor: toți termenii, cuprins activ, progres
  const allT = $("#allterms");
  if (allT) {
    allT.checked = store.get("allterms", false);
    document.body.classList.toggle("allterms", allT.checked);
    allT.addEventListener("change", () => { store.set("allterms", allT.checked); document.body.classList.toggle("allterms", allT.checked); });
  }
  const heads = $$(".text .rh");
  const tocLinks = {};
  $$(".toc a[data-sec]").forEach((a) => { tocLinks[a.dataset.sec] = a; });
  const bar = $("#readprog");
  const secTermsBox = $("#secterms");
  let lastSec = null;
  function onScroll() {
    if (!heads.length) return;
    let cur = heads[0];
    for (const h of heads) { if (h.getBoundingClientRect().top < 140) cur = h; else break; }
    const sid = cur.dataset.sec;
    if (sid !== lastSec) {
      lastSec = sid;
      $$(".toc a.on").forEach((a) => a.classList.remove("on"));
      const a = tocLinks[sid];
      if (a) { a.classList.add("on"); const side = a.closest(".side"); if (side) { const r = a.getBoundingClientRect(), sr = side.getBoundingClientRect(); if (r.top < sr.top + 40 || r.bottom > sr.bottom - 40) side.scrollTop += r.top - sr.top - sr.height / 3; } }
      if (secTermsBox && !secTermsBox.dataset.locked) renderSecTerms(sid);
    }
    if (bar) {
      const h = document.documentElement;
      bar.style.width = Math.min(100, 100 * h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)) + "%";
    }
  }
  function renderSecTerms(sid) {
    const data = (window.SEC_TERMS || {})[sid] || [];
    const title = (tocLinks[sid] && tocLinks[sid].textContent) || "";
    secTermsBox.innerHTML = `<div class="kicker">Termeni în secțiune</div><h3 style="margin:.2em 0 .6em">${esc(title)}</h3>`
      + (data.length ? `<ul class="tlist">${data.map((t) => `<li><a class="tl l${t.level}" href="/termen/${t.id}/" data-panel="${t.id}" data-t="${t.id}">${esc(t.label)}</a></li>`).join("")}</ul>`
        : `<p class="muted small">Niciun termen legat în această secțiune.</p>`)
      + `<p class="muted small" style="margin-top:14px">Clic pe un termen subliniat din text îl deschide aici. Selectează orice cuvânt ca să-l explice AI-ul.</p>`;
    applyLevelFilter();
  }
  if (heads.length) { window.addEventListener("scroll", onScroll, { passive: true }); onScroll(); }
  const back = $("#backsec");
  if (back) back.addEventListener("click", () => {
    $("#panelwrap").hidden = true; secTermsBox.hidden = false; renderSecTerms(lastSec); highlightTerm(null);
    history.replaceState(null, "", location.pathname + location.search);
  });

  // ---- ancore: ?t=<id>#b13 → deschide termenul și face paragraful să clipească
  function flashTarget() {
    const m = location.hash.match(/^#(b\d+)$/);
    if (m) { const el = document.getElementById(m[1]); if (el) { el.classList.add("flash-target"); el.scrollIntoView({ block: "center" }); } }
    const t = new URLSearchParams(location.search).get("t") || (location.hash.match(/#t=([\w-]+)/) || [])[1];
    if (t && inPanelMode) openPanel(t, { keepHash: !!m, list: $(".clist") ? currentList() : undefined });
  }
  window.addEventListener("load", flashTarget);

  // ---- copiere cod, lightbox
  document.addEventListener("click", (e) => {
    const c = e.target.closest(".copy, [data-copy]");
    if (c) {
      const src = c.dataset.copy ? document.getElementById(c.dataset.copy) : c.parentElement.querySelector("pre");
      const text = src ? (src.value !== undefined ? src.value : src.innerText) : "";
      navigator.clipboard.writeText(text).then(() => { const o = c.textContent; c.textContent = "✓ copiat"; setTimeout(() => { c.textContent = o; }, 1300); });
      return;
    }
    const z = e.target.closest("a.zoom");
    if (z) { e.preventDefault(); const lb = $("#lightbox"); $("img", lb).src = z.href; lb.hidden = false; }
    if (e.target.closest("#lightbox")) $("#lightbox").hidden = true;
  });

  // ---- „Explică”: selecție de 2–80 de caractere în text
  const exBtn = $("#explain");
  let exSel = null;
  document.addEventListener("mouseup", (e) => {
    if (e.target === exBtn) return;
    setTimeout(() => {
      const s = window.getSelection();
      const text = s ? s.toString().trim() : "";
      const zone = s && s.anchorNode && s.anchorNode.parentElement && s.anchorNode.parentElement.closest(".text, .explainable");
      if (!zone || text.length < 2 || text.length > 80) { exBtn.hidden = true; exSel = null; return; }
      const blockEl = s.anchorNode.parentElement.closest("[id^=b]");
      exSel = { text, unit: zone.dataset.unit || "", block: blockEl ? blockEl.id.slice(1) : "-1", context: (blockEl || zone).innerText.slice(0, 1500) };
      const r = s.getRangeAt(0).getBoundingClientRect();
      exBtn.style.left = (window.scrollX + r.left + r.width / 2 - 45) + "px";
      exBtn.style.top = (window.scrollY + r.top - 40) + "px";
      exBtn.hidden = false;
    }, 10);
  });
  if (exBtn) exBtn.addEventListener("click", () => {
    if (!exSel) return;
    exBtn.textContent = "⏳ Se explică…";
    post("/api/explica/", { selection: exSel.text, unit: exSel.unit, block: exSel.block, context: exSel.context })
      .then((r) => r.json()).then((d) => {
        exBtn.textContent = "✨ Explică"; exBtn.hidden = true;
        if (d.error) { alert(d.error); return; }
        if (d.not_term) { alert("Nu pare un termen de sine stătător: " + (d.reason || "") + (d.explanation ? "\n\n" + d.explanation : "")); return; }
        if (inPanelMode) openPanel(d.id); else location.href = "/termen/" + d.id + "/";
      }).catch(() => { exBtn.textContent = "✨ Explică"; alert("Cererea a eșuat."); });
  });

  // ---- problemă: rularea testelor
  const runBtn = $("#runtests");
  if (runBtn) runBtn.addEventListener("click", () => {
    const out = $("#testres");
    runBtn.disabled = true; runBtn.textContent = "⏳ Compilez și rulez…";
    post(runBtn.dataset.url, {}).then((r) => r.json()).then((d) => {
      runBtn.disabled = false; runBtn.textContent = "▶ Rulează testele";
      if (d.error) { out.innerHTML = `<div class="msg error">${esc(d.error)}</div>`; return; }
      let h = "";
      if (!d.compiled) h += `<div class="msg error">Programul nu compilează.</div><pre>${esc(d.compile_output)}</pre>`;
      else {
        if (d.compile_output) h += `<details class="rdet"><summary>Warning-uri de compilare</summary><pre>${esc(d.compile_output)}</pre></details>`;
        const ok = d.passed === d.total;
        h += `<div class="msg ${ok ? "success" : "warning"}"><b>${d.passed} / ${d.total}</b> teste trecute${ok ? " — bravo! Acum încearcă un review al codului." : ""}</div>`;
        h += (d.tests || []).map((t) => `<div class="t ${t.ok ? "ok" : "bad"}"><div><span>Test ${esc(t.name)}</span><span>${t.ok ? "✔ corect" : (t.timeout ? "⏱ timp depășit" : "✘ diferit")}</span></div>`
          + (t.ok ? "" : `<div class="cols"><div><div class="kicker">Intrare</div><pre>${esc(t.stdin)}</pre></div><div><div class="kicker">Așteptat</div><pre>${esc(t.expected)}</pre></div><div><div class="kicker">Programul tău</div><pre>${esc(t.got)}</pre></div></div>`) + "</div>").join("");
      }
      out.innerHTML = h;
      const st = $("#pstatus"); if (st && d.total && d.passed === d.total) st.textContent = "rezolvat";
    }).catch(() => { runBtn.disabled = false; runBtn.textContent = "▶ Rulează testele"; out.innerHTML = '<div class="msg error">Cererea a eșuat.</div>'; });
  });

  // ---- întrebări: butoanele de variantă trimit formularul
  $$(".q form.opts button").forEach((b) => b.addEventListener("click", () => { b.form.querySelector("[name=choice]").value = b.value; }));
})();
