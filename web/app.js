/* 旁批 · 讲义伴读 — front-end */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const params = new URLSearchParams(location.search);
  let TOKEN = params.get("t") || sessionStorage.getItem("pangpi-token") || "";
  if (params.get("t")) {
    sessionStorage.setItem("pangpi-token", params.get("t"));
    history.replaceState(null, "", location.pathname);
  }

  const S = {
    settings: {},
    corpus: { ready: false, docs: [], current: { doc: 0, page: 1 } },
    handout: { ready: false },
    page: 1,
    section: null,
    cards: [],
    els: new Map(),        // card id -> element
    streaming: new Map(),  // temp id -> {buf, el, timer}
    lastCapture: { text: "", at: 0 },
    uploadTimer: null
  };

  const md = window.MDRender || { render: (t) => escapeHtml(t || "").replace(/\n/g, "<br>") };

  // Model answers often split one numbered list into several blocks (a blank
  // line or a display formula in between). md.js restarts the numbering with
  // <ol start="N">; glue the pieces back so the spacing stays even.
  function renderAnswer(text) {
    let html = md.render(text || "");
    html = html.replace(/<\/ol>\s*<ol start="\d+">/g, "").replace(/<\/ul>\s*<ul>/g, "");
    // Give the bold "定位/讲解/依据/易错点" labels a class so CSS can colour them
    // by meaning instead of painting every bold run the same.
    html = html.replace(/<p><strong>([^<]{1,16})<\/strong>([：:])/g, (m, label, colon) => {
      const key = label.replace(/[（(].*$/, "").trim();
      return '<p class="sec" data-label="' + key + '"><strong>' + label + "</strong>" + colon;
    });
    return html;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ---------------------------------------------------------------- api

  async function api(path, opts = {}) {
    const headers = { "X-Pangpi-Token": TOKEN };
    let body = opts.body;
    if (body !== undefined && !(body instanceof Blob) && !(body instanceof Uint8Array)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || ("HTTP " + res.status);
      throw new Error(msg);
    }
    return data;
  }

  async function streamPost(path, payload, handlers) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Pangpi-Token": TOKEN },
      body: JSON.stringify(payload)
    });
    if (!res.ok || !res.body) {
      let msg = "HTTP " + res.status;
      try { const j = await res.json(); msg = j.error || msg; } catch (e) {}
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        let data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        let parsed = null;
        try { parsed = JSON.parse(data); } catch (e) { continue; }
        handlers(event, parsed);
      }
    }
  }

  // ---------------------------------------------------------------- ui bits

  let toastTimer = null;
  function toast(msg, kind = "") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast show " + kind;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = "toast " + kind; }, 2600);
  }

  function applyTheme() {
    const theme = S.settings.theme || "dark";
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.setProperty("--fs", (S.settings.font_size || 15) + "px");
  }

  function fmtTime(ts) {
    const d = new Date(ts || Date.now());
    return d.getHours().toString().padStart(2, "0") + ":" + d.getMinutes().toString().padStart(2, "0");
  }

  function pageLabel(card) {
    const bits = [];
    if (card.page) bits.push("P." + card.page);
    if (card.section) bits.push(card.section);
    return bits.join(" · ");
  }

  // ---------------------------------------------------------------- render

  function renderAll() {
    renderChip();
    renderFeed();
    renderOutline();
    renderPageInput();
  }

  function renderChip() {
    const chip = $("#chipText");
    if (S.corpus && S.corpus.ready) {
      const cur = S.corpus.current;
      chip.textContent = `${shortName(cur.name)} · P.${cur.page}`;
      $("#handoutChip").classList.add("on");
      $("#sectionName").textContent = cur.section || "";
      const total = $("#pageTotal");
      if (total) total.textContent = "/ " + cur.pages;
      return;
    }
    const h = S.handout;
    if (h && h.ready) {
      chip.textContent = `${shortName(h.name)} · P.${S.page}`;
      $("#handoutChip").classList.add("on");
    } else {
      chip.textContent = "未导入讲义";
      $("#handoutChip").classList.remove("on");
    }
    $("#sectionName").textContent = (S.section && S.section.title) || "";
    const total = $("#pageTotal");
    if (total) total.textContent = S.handout && S.handout.ready ? "/ " + S.handout.page_count : "";
  }

  function shortName(name) {
    if (!name) return "讲义";
    const base = name.replace(/\.pdf$/i, "");
    return base.length > 14 ? base.slice(0, 13) + "…" : base;
  }

  function renderPageInput() {
    const input = $("#pageInput");
    if (input && document.activeElement !== input) input.value = S.page || 1;
  }

  function renderFeed() {
    const feed = $("#feed");
    const empty = $("#empty");
    const hasCards = S.cards.length > 0 || S.streaming.size > 0;
    empty.style.display = hasCards ? "none" : "";
    for (const el of $$(".card", feed)) el.remove();
    S.els.clear();
    // 按时间平铺：后续的提示/解答永远排在点它的那一刻之后，
    // 不会因为 parent 关系被重排到前面去。
    const ordered = S.cards.slice().sort((a, b) => (a.ts || 0) - (b.ts || 0));
    for (const card of ordered) feed.appendChild(buildCard(card));
  }

  function renderAsk(el, data, card) {
    // 临时卡片用 text 存原文，服务端返回的卡片用 selection，两边都认
    const info = Object.assign({}, card || {}, (data && data.card) || {});
    const text = (info.selection || info.text || "").trim();
    const box = $(".answer", el);
    if (box) box.innerHTML = "";
    const bar = $(".card-actions", el);
    if (bar) bar.remove();
    const row = document.createElement("div");
    row.className = "ask-modes";
    const hint = document.createElement("p");
    hint.className = "ask-lead";
    hint.textContent = "这是习题。要先怎么做？";
    row.appendChild(hint);

    const choose = (mode) => {
      if (!text) {
        toast("没拿到选中的文字，麻烦重新选一次", "error");
        return;
      }
      el.remove();
      S.els.delete(card.id);
      S.cards = S.cards.filter((c) => c.id !== info.id && c.id !== card.id);
      startExplain({ text, mode, page: info.page, doc: info.doc });
    };

    const mk = (label, mode, kind, note) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ask-mode " + (kind || "");
      b.textContent = label;
      if (note) {
        const s = document.createElement("span");
        s.textContent = note;
        b.appendChild(s);
      }
      b.addEventListener("click", () => choose(mode));
      return b;
    };

    if (data.has_latin) row.appendChild(mk("只翻译", "translate", "", "译成中文，不讲解"));
    row.appendChild(mk("给提示", "hint", "primary", "先自己想，只给方向"));
    row.appendChild(mk("讲解", "explain", "", "完整讲一遍"));
    el.appendChild(row);
  }

  function requestMode(card, mode) {
    startExplain({
      text: card.selection || "",
      image_id: card.image_id || "",
      mode: mode,
      parent_id: card.parent_id || card.id,
      page: card.page || S.page,
      doc: card.doc,
    });
  }

  // 把讲解里的“第 3 页”“第2讲……第 4 页”变成可点的跳转
  function annotatePageRefs(root, card) {
    const hasCtx = (S.corpus && S.corpus.ready) || (S.handout && S.handout.ready);
    if (!hasCtx || !root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        let p = node.parentNode;
        while (p && p !== root) {
          const tag = p.tagName;
          if (p.classList && p.classList.contains("math")) return NodeFilter.FILTER_REJECT;
          if (tag === "CODE" || tag === "PRE" || tag === "A" || tag === "BUTTON") return NodeFilter.FILTER_REJECT;
          p = p.parentNode;
        }
        return /第\s*\d{1,3}\s*页/.test(node.nodeValue)
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    });

    const targets = [];
    while (walker.nextNode()) targets.push(walker.currentNode);

    for (const node of targets) {
      const text = node.nodeValue;
      const frag = document.createDocumentFragment();
      let last = 0;
      const re = /第\s*(\d{1,3})\s*页/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const before = text.slice(last, m.index);
        if (before) frag.appendChild(document.createTextNode(before));

        const page = parseInt(m[1], 10);
        // 同一行里如果前面写过“第N讲”，就用那一讲
        const head = text.slice(Math.max(0, m.index - 40), m.index);
        const docMatch = /第\s*(\d{1,2})\s*讲/g;
        let dm = null;
        let tmp;
        while ((tmp = docMatch.exec(head)) !== null) dm = tmp;
        const docIndex = dm ? parseInt(dm[1], 10) - 1 : (card.doc || 0);

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "jump";
        btn.textContent = m[0];
        btn.title = "跳到第" + (docIndex + 1) + "讲第" + page + "页";
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          jumpTo(docIndex, page);
        });
        frag.appendChild(btn);
        last = m.index + m[0].length;
      }
      if (last === 0) continue;
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
  }

  async function jumpTo(doc, page) {
    try {
      if (S.corpus && S.corpus.ready) {
        const res = await api("/api/corpus/position", { method: "POST", body: { doc, page } });
        applyCorpus(res.corpus);
      } else {
        await api("/api/page", { method: "POST", body: { page } });
        S.page = page;
      }
      renderAll();
      const cur = S.corpus && S.corpus.ready ? S.corpus.current : null;
      toast(cur ? "已切到 " + cur.name.replace(/\.(pptx|pdf)$/i, "") + " 第 " + page + " 页"
                : "已切到第 " + page + " 页");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function buildCard(card, opts = {}) {
    const el = document.createElement("article");
    el.className = "card" + (card.mode === "hint" ? " is-hint" : "") +
      (card.mode === "solution" ? " is-solution" : "") + (card.parent_id ? " is-child" : "");
    el.dataset.id = card.id || "";
    if (opts.streaming) el.classList.add("streaming");

    const head = document.createElement("div");
    head.className = "card-head";
    const loc = document.createElement("span");
    loc.className = "card-loc";
    const label = pageLabel(card);
    if (label) {
      const b = document.createElement("b");
      b.textContent = label;
      loc.appendChild(b);
    } else {
      loc.textContent = "新讲解";
    }
    head.appendChild(loc);

    if (card.mode === "hint") {
      const badge = document.createElement("span");
      badge.className = "badge hint";
      badge.textContent = "提示 " + (card.hint_level || 1);
      head.appendChild(badge);
    } else if (card.mode === "solution") {
      const badge = document.createElement("span");
      badge.className = "badge solution";
      badge.textContent = "解答";
      head.appendChild(badge);
    }
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    head.appendChild(spacer);

    if (card.status === "error") {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.style.color = "var(--danger)";
      badge.textContent = "失败";
      head.appendChild(badge);
    }
    el.appendChild(head);

    if (card.selection || card.image_id) {
      const quote = document.createElement("blockquote");
      quote.className = "quote";
      if (card.selection) quote.textContent = card.selection;
      if (card.image_id) {
        const img = document.createElement("img");
        img.className = "thumb";
        img.alt = "截图";
        img.src = `/api/image/${card.image_id}?t=${encodeURIComponent(TOKEN)}`;
        quote.appendChild(img);
      }
      quote.addEventListener("click", () => quote.classList.toggle("open"));
      requestAnimationFrame(() => {
        if (quote.scrollHeight > quote.clientHeight + 4) quote.classList.add("clamped");
      });
      el.appendChild(quote);
    }

    if (card.formula && !card.image_id) {
      const hint = document.createElement("div");
      hint.className = "formula-hint";
      const tip = document.createElement("span");
      tip.textContent = "这段像是公式：从 PDF 复制时上下标、根号常被吃掉。";
      const how = document.createElement("button");
      how.className = "link";
      how.type = "button";
      how.textContent = "怎么更准？";
      how.addEventListener("click", () => {
        toast("按 Win+Shift+S 框选这段公式，框完松手 —— 截图会直接送来用图重讲。");
      });
      hint.appendChild(tip);
      hint.appendChild(how);
      el.appendChild(hint);
    }

    const answer = document.createElement("div");
    answer.className = "answer";
    const text = card.answer || opts.partial || "";
    answer.innerHTML = text ? renderAnswer(text) : "";
    if (text) annotatePageRefs(answer, card);
    el.appendChild(answer);

    if (card.status === "streaming" && !text) {
      answer.innerHTML = '<div class="skeleton" style="width:62%"></div><div class="skeleton" style="width:84%"></div>';
      const hint = document.createElement("div");
      hint.className = "thinking";
      hint.innerHTML = '<span class="dots"><span></span><span></span><span></span></span><span>正在读你的讲义…</span>';
      answer.appendChild(hint);
    }

    if (card.thread && card.thread.length) {
      const thread = document.createElement("div");
      thread.className = "thread";
      for (const msg of card.thread) {
        const m = document.createElement("div");
        m.className = "msg " + (msg.role === "user" ? "user" : "assistant");
        if (msg.role === "user") m.textContent = msg.text;
        else m.innerHTML = renderAnswer(msg.text || "");
        thread.appendChild(m);
      }
      el.appendChild(thread);
    }

    if (card.error) {
      const err = document.createElement("p");
      err.className = "help";
      err.style.color = "var(--danger)";
      err.textContent = card.error;
      el.appendChild(err);
    }

    el.appendChild(buildActions(card, opts));
    S.els.set(card.id, el);
    return el;
  }

  function buildActions(card, opts = {}) {
    const bar = document.createElement("div");
    bar.className = "card-actions";
    if (opts.streaming || card.status === "streaming") return bar;

    if (card.mode === "explain" && !card.parent_id) {
      bar.appendChild(button(card.exercise ? "给提示" : "提示", card.exercise ? "primary" : "", () => requestHint(card, 1)));
    }
    if (card.mode === "hint") {
      const level = card.hint_level || 1;
      if (level < 3) {
        bar.appendChild(button("再提示一层", "primary", () => requestHint(card.parent_id || card.id, level + 1)));
      }
      bar.appendChild(button("讲解", "", () => requestMode(card, "explain")));
      bar.appendChild(button("看完整解答", level >= 3 ? "primary" : "", () => requestSolution(card.parent_id || card.id)));
    }
    if (card.mode === "translate") {
      bar.appendChild(button("给提示", "", () => requestMode(card, "hint")));
      bar.appendChild(button("讲解", "", () => requestMode(card, "explain")));
    }
    if (card.mode === "solution") {
      bar.appendChild(button("换个说法", "", () => redo(card)));
    }
    bar.appendChild(button("追问", "", () => openAsk(card)));
    bar.appendChild(button("复制", "", () => copyCard(card)));
    const del = button("删除", "danger", () => removeCard(card));
    del.style.marginLeft = "auto";
    bar.appendChild(del);
    return bar;
  }

  function setSelfCheck(el, text, kind) {
    if (!el) return;
    let line = el.querySelector(".selfcheck");
    if (!text) {
      if (line) line.remove();
      return;
    }
    if (!line) {
      line = document.createElement("div");
      line.className = "selfcheck";
      const actions = el.querySelector(".card-actions");
      if (actions) el.insertBefore(line, actions);
      else el.appendChild(line);
    }
    line.textContent = text;
    line.className = "selfcheck " + (kind || "");
  }

  function button(label, kind, onClick) {
    const b = document.createElement("button");
    b.className = "act " + (kind || "");
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  // ---------------------------------------------------------------- actions

  function newPendingCard(fields) {
    const id = "tmp-" + Math.random().toString(36).slice(2);
    const card = Object.assign({
      id,
      ts: Date.now(),
      status: "streaming",
      page: S.page,
      section: S.section && S.section.title,
      model: S.settings.model
    }, fields);
    const feed = $("#feed");
    $("#empty").style.display = "none";
    const el = buildCard(card, { streaming: true });
    feed.appendChild(el);
    S.els.set(id, el);
    scrollToCard(el);
    return { card, el, buf: "" };
  }

  function scrollToCard(el) {
    requestAnimationFrame(() => {
      const feed = $("#feed");
      const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 220;
      if (nearBottom) feed.scrollTop = feed.scrollHeight;
      else el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  async function runExplain(payload, pending) {
    const { card, el } = pending;
    const answerEl = $(".answer", el);
    let lastRender = 0;
    let renderQueued = false;

    const paint = () => {
      renderQueued = false;
      lastRender = Date.now();
      answerEl.innerHTML = pending.buf ? renderAnswer(pending.buf) : "";
      annotatePageRefs(answerEl, card);
      const feed = $("#feed");
      if (feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160) feed.scrollTop = feed.scrollHeight;
    };

    let thinkChars = 0;
    try {
      await streamPost("/api/explain", payload, (event, data) => {
        if (event === "thinking") {
          thinkChars += data.n || 0;
          const label = $(".thinking span:last-child", el);
          if (label) label.textContent = thinkChars ? "正在推理…" : "正在读你的讲义…";
        } else if (event === "ask") {
          renderAsk(el, data, card);
        } else if (event === "notice") {
          setSelfCheck(el, data.text || "正在自查…", "");
        } else if (event === "replace") {
          pending.buf = data.text || pending.buf;
          paint();
          setSelfCheck(el, "已自查修正：" + (data.issues || []).join("、"), "ok");
        } else if (event === "note") {
          setSelfCheck(el, data.text || "", "warn");
        } else if (event === "meta") {
          if (data.page) { S.page = data.page; renderChip(); renderPageInput(); }
          if (data.card) {
            card.page = data.card.page;
            card.section = data.card.section;
          }
        } else if (event === "delta") {
          pending.buf += data.text || "";
          if (!renderQueued) {
            renderQueued = true;
            setTimeout(() => { if (Date.now() - lastRender > 70) paint(); }, 70);
          }
        } else if (event === "done") {
          if (data.card) {
            const done = data.card;
            S.cards = S.cards.filter((c) => c.id !== done.id);
            S.cards.push(done);
            S.cards.sort((a, b) => a.ts - b.ts);
            replaceCard(card.id, done);
          }
        } else if (event === "error") {
          card.status = "error";
          card.error = data.message || "出错了";
          replaceCard(card.id, Object.assign({}, card, { answer: pending.buf }));
          toast(card.error, "error");
        }
      });
    } catch (err) {
      card.status = "error";
      card.error = err.message || String(err);
      replaceCard(card.id, Object.assign({}, card, { answer: pending.buf }));
      toast(card.error, "error");
    }
  }

  function replaceCard(oldId, card) {
    const oldEl = S.els.get(oldId);
    S.els.delete(oldId);
    const el = buildCard(card);
    if (oldEl && oldEl.parentNode) oldEl.parentNode.replaceChild(el, oldEl);
    else $("#feed").appendChild(el);
    S.els.set(card.id, el);
    scrollToCard(el);
  }

  function startExplain(fields) {
    if (!fields.image_id && !(fields.text || "").trim()) {
      toast("没拿到选中的文字，麻烦重新选一次", "error");
      return;
    }
    if (!S.settings.has_key) {
      toast("先填 API Key 才能讲解", "error");
      openPanel("settings");
      setTimeout(() => $("#apiKey").focus(), 260);
      return;
    }
    const pending = newPendingCard(fields);
    runExplain(Object.assign({}, fields, {
      page: fields.page || S.page,
      doc: (S.corpus && S.corpus.ready) ? S.corpus.current.doc : undefined
    }), pending);
  }

  function requestHint(parentId, level) {
    const parent = S.cards.find((c) => c.id === parentId) || {};
    startExplain({
      text: parent.selection || "",
      image_id: parent.image_id || "",
      mode: "hint",
      hint_level: level,
      parent_id: parentId,
      page: parent.page || S.page
    });
  }

  function requestSolution(parentId) {
    const parent = S.cards.find((c) => c.id === parentId) || {};
    startExplain({
      text: parent.selection || "",
      image_id: parent.image_id || "",
      mode: "solution",
      parent_id: parentId,
      page: parent.page || S.page
    });
  }

  function redo(card) {
    startExplain({
      text: card.selection || "",
      image_id: card.image_id || "",
      mode: card.mode,
      hint_level: card.hint_level || 1,
      parent_id: card.parent_id || "",
      page: card.page || S.page
    });
  }

  function openAsk(card) {
    const el = S.els.get(card.id);
    if (!el) return;
    let row = $(".ask-row", el);
    if (row) { $("input", row).focus(); return; }
    row = document.createElement("div");
    row.className = "ask-row";
    const input = document.createElement("input");
    input.placeholder = "追问一句…（用的是同一段原文）";
    const btn = document.createElement("button");
    btn.textContent = "问";
    row.appendChild(input);
    row.appendChild(btn);
    el.appendChild(row);
    input.focus();
    const send = () => {
      const q = input.value.trim();
      if (!q) return;
      input.value = "";
      askFollowUp(card, q, el);
      row.remove();
    };
    btn.addEventListener("click", send);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); send(); }
      if (e.key === "Escape") row.remove();
    });
  }

  async function askFollowUp(card, question, el) {
    if (!card.thread) card.thread = [];
    card.thread.push({ role: "user", text: question });
    if (card.answer) card.thread.push({ role: "assistant", text: "…", pending: true });
    const threadEl = (() => {
      let t = $(".thread", el);
      if (!t) {
        t = document.createElement("div");
        t.className = "thread";
        el.insertBefore(t, $(".card-actions", el));
      }
      return t;
    })();
    const userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.textContent = question;
    threadEl.appendChild(userMsg);
    const botMsg = document.createElement("div");
    botMsg.className = "msg assistant";
    botMsg.innerHTML = '<span class="dots"><span></span><span></span><span></span></span>';
    threadEl.appendChild(botMsg);

    let buf = "";
    try {
      await streamPost("/api/chat", { card_id: card.id, question, page: card.page || S.page }, (event, data) => {
        if (event === "delta") {
          buf += data.text || "";
          botMsg.innerHTML = renderAnswer(buf);
        } else if (event === "done") {
          if (data.message) {
            card.thread = card.thread.filter((m) => !m.pending);
            card.thread.push(data.message);
          }
          botMsg.innerHTML = renderAnswer(data.message ? data.message.text : buf);
        } else if (event === "error") {
          botMsg.innerHTML = '<span style="color:var(--danger)">' + escapeHtml(data.message || "出错了") + "</span>";
          card.thread = card.thread.filter((m) => !m.pending);
        }
      });
    } catch (err) {
      botMsg.textContent = err.message || String(err);
    }
  }

  function copyCard(card) {
    const text = (card.selection ? "原文：\n" + card.selection + "\n\n" : "") + (card.answer || "");
    navigator.clipboard.writeText(text).then(
      () => toast("已复制"),
      () => toast("复制失败", "error")
    );
  }

  async function removeCard(card) {
    const doomed = [card.id].concat(S.cards.filter((c) => c.parent_id === card.id).map((c) => c.id));
    for (const id of doomed) {
      const el = S.els.get(id);
      if (el) el.remove();
      S.els.delete(id);
    }
    S.cards = S.cards.filter((c) => !doomed.includes(c.id));
    if (card.id && !card.id.startsWith("tmp-")) {
      try { await api("/api/card/delete", { method: "POST", body: { id: card.id } }); } catch (e) {}
    }
    if (!S.cards.length) renderFeed();
  }

  // ---------------------------------------------------------------- capture

  function handleCapture(d) {
    if (!d) return;
    if (!S.settings.has_key) {
      toast("先填 API Key 才能讲解", "error");
      openPanel("settings");
      return;
    }
    // A copy made inside this window (e.g. the 复制 button) must not re-trigger.
    if (d.source === "clipboard" && document.hasFocus()) return;
    const text = (d.text || "").trim();
    if (d.image_id === undefined && !text) return;
    const key = text + "|" + (d.image_id || "");
    if (key === S.lastCapture.text && Date.now() - S.lastCapture.at < 2500) return;
    S.lastCapture = { text: key, at: Date.now() };

    if (d.page && (!S.handout || !S.handout.ready || d.score >= 0.45)) {
      S.page = d.page;
      S.section = d.section || S.section;
      renderChip();
      renderPageInput();
    }
    startExplain({
      text,
      image_id: d.image_id || "",
      mode: "auto",
      page: d.page || S.page
    });
  }

  function connectEvents() {
    const url = `/api/events?t=${encodeURIComponent(TOKEN)}`;
    let es;
    try { es = new EventSource(url); } catch (e) { return; }
    es.addEventListener("capture", (e) => {
      try { handleCapture(JSON.parse(e.data)); } catch (err) {}
    });
    es.addEventListener("handout", () => { pollHandoutStatus(); });
    es.onerror = () => {
      // EventSource retries by itself; nothing to do but stay quiet.
    };
  }

  // ---------------------------------------------------------------- handout

  async function uploadFiles(files) {
    const list = Array.from(files || []).filter((f) => /\.(pptx|pdf)$/i.test(f.name));
    if (!list.length) { toast("请选择 PPTX 或 PDF", "error"); return; }
    const dz = $("#handoutEmpty");
    let done = 0;
    for (const f of list) {
      if (dz) {
        dz.hidden = false;
        dz.innerHTML = "<strong>正在导入 " + (done + 1) + "/" + list.length +
          "</strong><span>" + escapeHtml(f.name) + "</span>";
      }
      try {
        const res = await fetch("/api/corpus/add", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Pangpi-Token": TOKEN,
            "X-Filename": encodeURIComponent(f.name)
          },
          body: f
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "导入失败");
        done++;
      } catch (err) {
        toast(f.name + "：" + err.message, "error");
      }
    }
    if (dz) dz.innerHTML = "<strong>导入课件</strong><span>PPTX / PDF，可一次多选；按讲次排好顺序</span>";
    await refreshState();
    if (done) toast("已导入 " + done + " 份课件");
  }

  async function uploadHandout(file) {
    if (!file) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      toast("请选择 PDF 文件", "error");
      return;
    }
    const drop = $("#handoutEmpty");
    drop.innerHTML = '<strong>正在上传…</strong><span>' + escapeHtml(file.name) + "</span>";
    try {
      const res = await fetch("/api/handout", {
        method: "POST",
        headers: {
          "Content-Type": "application/pdf",
          "X-Pangpi-Token": TOKEN,
          "X-Filename": encodeURIComponent(file.name)
        },
        body: file
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "上传失败");
      pollHandoutStatus();
    } catch (err) {
      toast(err.message, "error");
      $(".dropzone").innerHTML = "导入失败，点击重试";
    }
  }

  function pollHandoutStatus() {
    clearInterval(S.uploadTimer);
    const tick = async () => {
      let st;
      try { st = await api("/api/handout/status"); } catch (e) { return; }
      const drop = $("#handoutEmpty");
      if (st.state === "parsing") {
        if (drop) {
          drop.innerHTML = '<strong>正在解析讲义</strong><span>' + (st.message || "") + "</span>" +
            '<div class="skeleton" style="width:70%"></div>';
        }
      } else if (st.state === "ready") {
        clearInterval(S.uploadTimer);
        await refreshState();
        toast(st.message || "讲义已就绪");
      } else if (st.state === "error") {
        clearInterval(S.uploadTimer);
        toast(st.message || "解析失败", "error");
        if (drop) drop.innerHTML = "<strong>解析失败</strong><span>点这里重新选择文件</span>";
      }
    };
    tick();
    S.uploadTimer = setInterval(tick, 800);
  }

  function renderOutline() {
    const nav = $("#outline");
    const info = $("#handoutInfo");
    const dz = $("#handoutEmpty");
    const docs = $("#docList");
    nav.innerHTML = "";

    if (S.corpus && S.corpus.ready) {
      if (dz) dz.hidden = true;
      if (docs) { docs.hidden = false; renderDocs(docs); }
      const resetBtn = $("#resetBtn");
      if (resetBtn) resetBtn.hidden = false;
      const cur = S.corpus.current;
      const doc = S.corpus.docs[cur.doc] || {};
      if (info) {
        info.hidden = false;
        const warn = doc.quality && doc.quality !== "text"
          ? `<span class="warn">${escapeHtml(qualityNote(doc.quality))}</span>` : "";
        info.innerHTML = `<b>${escapeHtml(cur.name)}</b> · 第 ${cur.page}/${cur.pages} 页 · 共 ${S.corpus.docs.length} 份${warn}`;
      }
      const outline = doc.outline || [];
      $("#outlineCount").textContent = outline.length ? outline.length + " 节" : "本讲没有识别到小节";
      for (const item of outline) {
        nav.appendChild(outlineButton(item, item.page === cur.page));
      }
      return;
    }

    if (docs) { docs.hidden = true; docs.innerHTML = ""; }
    const resetBtn2 = $("#resetBtn");
    if (resetBtn2) resetBtn2.hidden = true;
    const h = S.handout;
    if (!h || !h.ready) {
      if (dz) dz.hidden = false;
      if (info) info.hidden = true;
      $("#outlineCount").textContent = "";
      return;
    }
    if (dz) dz.hidden = true;
    if (info) {
      info.hidden = false;
      const warn = h.quality && h.quality !== "text"
        ? `<span class="warn">${escapeHtml(qualityNote(h.quality))}</span>` : "";
      info.innerHTML = `<b>${escapeHtml(h.name || "讲义")}</b> · ${h.page_count} 页 · ${h.chars} 字${warn}`;
    }
    $("#outlineCount").textContent = (h.outline || []).length + " 节";
    for (const item of h.outline || []) {
      nav.appendChild(outlineButton(item, item.page === S.page));
    }
  }

  function outlineButton(item, current) {
    const b = document.createElement("button");
    b.className = "lvl-" + Math.min(3, item.level || 1) + (current ? " current" : "");
    const pg = document.createElement("span");
    pg.className = "pg";
    pg.textContent = "P" + item.page;
    const t = document.createElement("span");
    t.textContent = item.title;
    b.appendChild(pg);
    b.appendChild(t);
    b.addEventListener("click", () => setPage(item.page));
    return b;
  }

  function renderDocs(container) {
    container.innerHTML = "";
    S.corpus.docs.forEach((doc, idx) => {
      const row = document.createElement("div");
      row.className = "doc-item" + (idx === S.corpus.current.doc ? " current" : "");

      if (doc.ordinal) {
        const no = document.createElement("span");
        no.className = "doc-no";
        no.textContent = doc.ordinal;
        no.title = "识别到的讲次：" + doc.ordinal;
        row.appendChild(no);
      }

      const name = document.createElement("button");
      name.className = "doc-name";
      name.type = "button";
      name.textContent = doc.name.replace(/\.(pptx|pdf)$/i, "");
      name.title = doc.name + (doc.quality && doc.quality !== "text" ? "（文字层可能不完整）" : "");
      name.addEventListener("click", () => selectDoc(idx));

      const meta = document.createElement("span");
      meta.className = "doc-meta";
      meta.textContent = doc.pages + " 页";

      const ops = document.createElement("span");
      ops.className = "doc-ops";
      ops.appendChild(docButton("↑", "上移", () => moveDoc(idx, -1), idx === 0));
      ops.appendChild(docButton("↓", "下移", () => moveDoc(idx, 1), idx === S.corpus.docs.length - 1));
      ops.appendChild(docButton("×", "移除", () => deleteDoc(idx)));

      row.appendChild(name);
      row.appendChild(meta);
      row.appendChild(ops);
      container.appendChild(row);
    });
  }

  function docButton(label, title, onClick, disabled) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = title;
    b.disabled = !!disabled;
    b.addEventListener("click", onClick);
    return b;
  }

  async function selectDoc(idx) {
    try {
      const res = await api("/api/corpus/position", { method: "POST", body: { doc: idx, page: 1 } });
      applyCorpus(res.corpus);
      renderAll();
    } catch (err) { toast(err.message, "error"); }
  }

  async function moveDoc(idx, delta) {
    const docs = S.corpus.docs.slice();
    const target = idx + delta;
    if (target < 0 || target >= docs.length) return;
    const tmp = docs[idx]; docs[idx] = docs[target]; docs[target] = tmp;
    try {
      const res = await api("/api/corpus/reorder", { method: "POST", body: { order: docs.map((d) => d.id) } });
      applyCorpus(res.corpus);
      renderAll();
    } catch (err) { toast(err.message, "error"); }
  }

  async function deleteDoc(idx) {
    const doc = S.corpus.docs[idx];
    if (!doc) return;
    if (!confirm("从课件库移除《" + doc.name + "》？（不会删除原文件）")) return;
    try {
      const res = await api("/api/corpus/delete", { method: "POST", body: { id: doc.id } });
      applyCorpus(res.corpus);
      renderAll();
    } catch (err) { toast(err.message, "error"); }
  }

  function applyCorpus(corpus) {
    if (!corpus) return;
    S.corpus = corpus;
    if (corpus.ready && corpus.current) {
      S.page = corpus.current.page;
      S.section = { title: corpus.current.section };
    }
  }

  function qualityNote(q) {
    return {
      scanned: "没有文字层（扫描/手写）：页码需要手动指定，取词仍可用。",
      vector: "文字是矢量笔画：无法自动定位页码，取词仍可用。",
      poor: "文字层质量较差：页码定位可能不准。"
    }[q] || "";
  }

  async function setPage(page) {
    try {
      const res = await api("/api/page", { method: "POST", body: { page } });
      S.page = res.page;
      S.section = res.section;
      renderChip();
      renderPageInput();
      renderOutline();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ---------------------------------------------------------------- panels

  function openPanel(tab) {
    const panel = $("#panel");
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add("open"));
    if (tab) selectTab(tab);
    fillSettings();
  }

  function closePanel() {
    const panel = $("#panel");
    panel.classList.remove("open");
    setTimeout(() => { panel.hidden = true; }, 240);
  }

  function selectTab(tab) {
    for (const t of $$(".tab")) t.classList.toggle("active", t.dataset.tab === tab);
    for (const p of $$(".tabpane")) p.classList.toggle("active", p.id === "tab-" + tab);
  }

  function fillSettings() {
    const s = S.settings;
    const set = (id, v) => { const el = $("#" + id); if (el && document.activeElement !== el) el.value = v; };
    set("baseUrl", s.base_url || "");
    set("model", s.model || "");
    set("maxTokens", s.max_tokens || 1600);
    set("temperature", s.temperature != null ? s.temperature : 0.6);
    set("hotkey", s.hotkey || "Ctrl+Alt+D");
    set("fontSize", s.font_size || 15);
    const proto = $("#protocol"); if (proto && document.activeElement !== proto) proto.value = s.protocol || "anthropic";
    const theme = $("#theme"); if (theme && document.activeElement !== theme) theme.value = s.theme || "dark";
    const listen = $("#autoListen"); if (listen) listen.checked = s.auto_listen !== false;
    const think = $("#thinking"); if (think) think.checked = s.thinking === "enabled";
    const key = $("#apiKey");
    if (key && document.activeElement !== key) {
      key.value = "";
      key.placeholder = s.has_key ? ("已保存 " + (s.key_hint || "")) : "sk-…";
    }
    $("#dataDir").textContent = S.dataDir || "—";
    $("#ver").textContent = S.version || "1.0.0";
  }

  let saveTimer = null;
  function queueSave(patch) {
    Object.assign(S.settings, patch);
    applyTheme();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        const res = await api("/api/settings", { method: "POST", body: patch });
        if (res && res.settings) {
          const hasKey = res.settings.has_key;
          S.settings.has_key = hasKey;
          if (hasKey) S.settings.key_hint = res.settings.key_hint;
        }
      } catch (err) { toast(err.message, "error"); }
    }, 320);
  }

  async function refreshState() {
    const st = await api("/api/state");
    S.settings = st.settings || {};
    S.handout = st.handout || { ready: false };
    S.corpus = st.corpus || { ready: false, docs: [], current: { doc: 0, page: 1 } };
    S.page = st.page || 1;
    if (S.corpus.ready && S.corpus.current) S.page = S.corpus.current.page;
    S.section = st.section || null;
    S.cards = st.cards || [];
    S.dataDir = st.data_dir;
    S.version = st.version;
    applyTheme();
    renderAll();
    fillSettings();
    updateThinkBtn();
  }

  // ---------------------------------------------------------------- events

  function updateThinkBtn() {
    const btn = $("#thinkBtn");
    if (!btn) return;
    const on = S.settings.thinking === "enabled";
    btn.classList.toggle("on", on);
    btn.title = on
      ? "深度思考：开（先推理再作答，慢但更稳；点击关闭）"
      : "深度思考：关（三四秒出结果；点击开启，难题更准）";
  }

  function showWelcome(force) {
    if (!force && localStorage.getItem("pangbi_welcomed_v1")) return;
    const modal = $("#welcome");
    if (!modal) return;
    const cb = $("#welcomeThink");
    if (cb) cb.checked = S.settings.thinking === "enabled";
    modal.hidden = false;
    requestAnimationFrame(() => modal.classList.add("show"));
    // 窗口在后台时 rAF 会被节流，补一个定时器兜底
    setTimeout(() => modal.classList.add("show"), 300);
  }

  function welcomeOpen() {
    const modal = $("#welcome");
    return modal && !modal.hidden;
  }

  function closeWelcome() {
    const modal = $("#welcome");
    if (!modal) return;
    modal.classList.remove("show");
    setTimeout(() => { modal.hidden = true; }, 200);
    localStorage.setItem("pangbi_welcomed_v1", "1");
  }

  function on(target, event, handler, opts) {
    const el = typeof target === "string" ? $(target) : target;
    if (!el) {
      console.warn("缺少元素，跳过绑定：" + target);
      return null;
    }
    el.addEventListener(event, handler, opts);
    return el;
  }

  const UI_VERSION = "2026-10-22-1";

  function checkUIVersion() {
    const meta = document.querySelector('meta[name="pangbi-ui"]');
    const page = meta ? meta.getAttribute("content") : "";
    if (page !== UI_VERSION) {
      throw new Error(
        "界面文件版本不一致（HTML " + (page || "旧版") + " / JS " + UI_VERSION +
        "）。请把整个压缩包重新解压覆盖，不要只替换其中几个文件。"
      );
    }
  }

  function fatal(err) {
    try {
      const msg = err && (err.message || err.reason || err);
      const box = document.createElement("div");
      box.className = "fatal";
      box.textContent = "界面出错：" + msg + "（多半是 index.html 与 app.js 版本不一致，重新解压整个包即可）";
      document.body.appendChild(box);
    } catch (_) {}
  }

  function wire() {
    on("#settingsBtn", "click", () => openPanel("settings"));
    on("#helpBtn", "click", () => showWelcome(true));
    on("#welcomeOk", "click", closeWelcome);
    on("#welcomeThink", "change", (e) => {
      queueSave({ thinking: e.target.checked ? "enabled" : "disabled" });
      updateThinkBtn();
      toast(e.target.checked ? "已开启深度思考（会慢一些）" : "已关闭深度思考（更快）");
    });
    on("#thinkBtn", "click", () => {
      const next = S.settings.thinking !== "enabled";
      queueSave({ thinking: next ? "enabled" : "disabled" });
      S.settings.thinking = next ? "enabled" : "disabled";
      updateThinkBtn();
      toast(next ? "深度思考：开（每次多等十几秒，难题更稳）" : "深度思考：关（三四秒出结果）");
    });
    on("#resetBtn", "click", async () => {
      if (!confirm("清空当前课件库，重新导入？（不会删除你电脑上的原文件）")) return;
      try {
        window.__pangbiReset = true;
        const res = await api("/api/session/reset", { method: "POST", body: {} });
        S.cards = [];
        S.corpus = res.corpus || { ready: false, docs: [], current: { doc: 0, page: 1 } };
        S.handout = res.handout || { ready: false };
        S.page = 1;
        S.section = null;
        renderAll();
        openPanel("handout");
        toast("已清空，请导入新的课件");
      } catch (err) {
        toast(err.message, "error");
      }
    });
    on("#handoutChip", "click", () => openPanel("handout"));
    on("#panelClose", "click", closePanel);
    for (const t of $$(".tab")) t.addEventListener("click", () => selectTab(t.dataset.tab));

    on("#listenBtn", "click", () => {
      const next = S.settings.auto_listen === false;
      queueSave({ auto_listen: next });
      updateListenBtn();
      toast(next ? "已开启：复制即讲" : "已暂停自动讲解（快捷键仍可用）");
    });

    const input = $("#input");
    input.addEventListener("input", autoGrow);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        sendComposer();
      }
    });
    on("#sendBtn", "click", sendComposer);

    on("#handoutEmpty", "click", () => $("#filePicker").click());
    on("#addFilesBtn", "click", () => $("#filePicker").click());
    on("#addFolderBtn", "click", () => $("#folderPicker").click());
    on("#filePicker", "change", (e) => {
      uploadFiles(e.target.files);
      e.target.value = "";
    });
    on("#folderPicker", "change", (e) => {
      uploadFiles(e.target.files);
      e.target.value = "";
    });
    const panelBody = $(".panel-body");
    panelBody.addEventListener("dragover", (e) => e.preventDefault());
    panelBody.addEventListener("drop", (e) => {
      e.preventDefault();
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) uploadHandout(f);
    });

    for (const b of $$("[data-page]")) {
      b.addEventListener("click", () => setPage(Math.max(1, (parseInt($("#pageInput").value, 10) || 1) + parseInt(b.dataset.page, 10))));
    }
    on("#pageInput", "change", () => setPage(parseInt($("#pageInput").value, 10) || 1));

    on("#apiKey", "change", (e) => {
      const v = e.target.value.trim();
      if (v) { queueSave({ api_key: v }); e.target.value = ""; toast("Key 已保存"); }
    });
    on("#protocol", "change", (e) => {
      const proto = e.target.value;
      const preset = proto === "anthropic"
        ? { base_url: "https://api.deepseek.com/anthropic", model: "deepseek-flash" }
        : { base_url: "https://api.deepseek.com", model: "deepseek-chat" };
      queueSave(Object.assign({ protocol: proto }, preset));
      fillSettings();
    });
    on("#baseUrl", "change", (e) => queueSave({ base_url: e.target.value.trim() }));
    on("#model", "change", (e) => queueSave({ model: e.target.value.trim() }));
    on("#maxTokens", "change", (e) => queueSave({ max_tokens: parseInt(e.target.value, 10) || 1600 }));
    on("#temperature", "change", (e) => queueSave({ temperature: parseFloat(e.target.value) || 0 }));
    on("#hotkey", "change", (e) => queueSave({ hotkey: e.target.value.trim() }));
    on("#fontSize", "change", (e) => queueSave({ font_size: parseInt(e.target.value, 10) || 15 }));
    on("#theme", "change", (e) => queueSave({ theme: e.target.value }));
    on("#autoListen", "change", (e) => { queueSave({ auto_listen: e.target.checked }); updateListenBtn(); });
    on("#thinking", "change", (e) => {
      queueSave({ thinking: e.target.checked ? "enabled" : "disabled" });
      toast(e.target.checked ? "已开启深度思考（会慢一些）" : "已关闭深度思考");
    });

    on("#testBtn", "click", async () => {
      const out = $("#testResult");
      out.textContent = "正在连接…";
      try {
        const res = await api("/api/test", { method: "POST", body: {} });
        out.textContent = res.ok ? "连接正常：" + (res.reply || "") : "失败：" + (res.error || "");
        out.style.color = res.ok ? "var(--extra)" : "var(--danger)";
      } catch (err) {
        out.textContent = "失败：" + err.message;
        out.style.color = "var(--danger)";
      }
    });
    on("#pinBtn", "click", async () => {
      try { await api("/api/pin", { method: "POST", body: {} }); toast("已置顶"); }
      catch (e) { toast("置顶失败", "error"); }
    });
    on("#reopenBtn", "click", async () => {
      try { await api("/api/reopen", { method: "POST", body: {} }); } catch (e) {}
    });
    on("#quitBtn", "click", async () => {
      if (!confirm("退出旁批？窗口会自动关闭。")) return;
      try { await api("/api/shutdown", { method: "POST", body: {} }); } catch (e) {}
      setTimeout(() => window.close(), 300);
    });

    on("#welcome", "click", (e) => {
      if (e.target && e.target.id === "welcome") closeWelcome();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (welcomeOpen()) { closeWelcome(); return; }
        if ($("#panel").classList.contains("open")) closePanel();
      }
    });
  }

  function updateListenBtn() {
    const btn = $("#listenBtn");
    const on = S.settings.auto_listen !== false;
    btn.classList.toggle("active", on);
    btn.classList.toggle("off", !on);
    btn.title = on ? "自动监听剪贴板：开（点击暂停）" : "自动监听剪贴板：关（点击开启）";
  }

  function autoGrow() {
    const el = $("#input");
    el.style.height = "auto";
    el.style.height = Math.min(120, el.scrollHeight) + "px";
  }

  function sendComposer() {
    const el = $("#input");
    const text = el.value.trim();
    if (!text) return;
    el.value = "";
    el.style.height = "auto";
    startExplain({ text, mode: "auto", page: S.page });
  }

  // 关窗时告诉服务端“可以退了”：8 秒内没有新的 ping 就真正退出。
  // 刷新页面会先触发 pagehide，但重载后的页面 1 秒内就会 ping，从而取消退出。
  window.addEventListener("pagehide", () => {
    try {
      navigator.sendBeacon("/api/goodbye?t=" + encodeURIComponent(TOKEN));
    } catch (e) {}
  });

  // ---------------------------------------------------------------- boot

  window.addEventListener("error", (e) => {
    // A silent blank window is the worst failure mode; surface it instead.
    try {
      const box = document.createElement("div");
      box.style.cssText =
        "position:fixed;left:12px;right:12px;bottom:12px;z-index:99;padding:10px 12px;" +
        "border-radius:10px;background:#2a1b1b;border:1px solid #7a3b36;color:#f0c9c4;" +
        "font:12px/1.6 ui-monospace,Consolas,monospace;white-space:pre-wrap";
      box.textContent = "界面脚本出错：" + (e.message || e.error) + "（可关掉窗口，用「调试启动.bat」看详情）";
      document.body.appendChild(box);
    } catch (_) {}
  });

  async function boot() {
    checkUIVersion();
    wire();
    let lastError = null;
    let stateOk = false;
    for (const wait of [0, 300, 700, 1500, 2500]) {
      if (wait) await new Promise((r) => setTimeout(r, wait));
      try {
        await refreshState();
        stateOk = true;
        break;
      } catch (err) {
        lastError = err;
      }
    }
    if (!stateOk) {
      toast("连不上本地服务：" + (lastError ? lastError.message : "未知错误"), "error");
    }
    updateListenBtn();
    updateThinkBtn();
    showWelcome(false);
    connectEvents();
    setInterval(() => { fetch("/api/ping", { method: "POST" }).catch(() => {}); }, 4000);
    if (!S.settings.has_key) {
      setTimeout(() => {
        if (!S.settings.has_key) {
          openPanel("settings");
          toast("先填一个 API Key，讲解才能开始");
        }
      }, 700);
    }
  }

  window.addEventListener("unhandledrejection", (e) => fatal(e.reason));
  boot().catch(fatal);
})();
