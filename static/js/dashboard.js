/* dashboard.js — HotShort Studio (elite)
   Cleaned, consolidated, and hardened version.
   - Single init() wiring (no cloneNode/double listeners)
   - Single-flight analyze (prevents double requests)
   - Friendly loader text stages + accessible loader text
   - Robust response parsing and defensive DOM checks
   - Small utilities & preview modal included
*/

(() => {
  "use strict";

  /* =====================
     CONFIG / SELECTORS
     ===================== */
  const SEL = {
    yt: "#yt",
    analyzeBtn: "#analyzeBtn",
    loader: "#loader",
    loaderText: "#loaderText",
    carousel: "#carousel",
    header: "header",
    hero: ".hero",
  };

  /* =====================
     LOADER TEXT STAGES
     ===================== */
  const LOADING_STAGES = [
    "Extracting narrative structure...",
    "Finding high-retention hooks...",
    "Scoring viral potential...",
    "Building clips...",
  ];
  let loaderInterval = null;

  /* =====================
     STATE
     ===================== */
  let _isAnalyzing = false;
  const GLOBAL_LAST_URL_KEY = "last_analyzed_url";

  function getBackendBaseUrl() {
    try {
      const body = document.body;
      const raw = body && body.dataset ? String(body.dataset.backendUrl || "").trim() : "";
      return raw.replace(/\/+$/, "");
    } catch (e) {
      return "";
    }
  }

  function backendUrl(path) {
    const normalizedPath = String(path || "");
    const base = getBackendBaseUrl();
    if (!base) return normalizedPath;
    return `${base}${normalizedPath.startsWith("/") ? normalizedPath : `/${normalizedPath}`}`;
  }

  function getDashboardUserId() {
    try {
      const ctx = document.getElementById("dashboardContext");
      const v = (ctx && ctx.dataset && ctx.dataset.userId) ? String(ctx.dataset.userId).trim() : "";
      return v || "anon";
    } catch (e) {
      return "anon";
    }
  }

  function getScopedLastUrlKey() {
    return `${GLOBAL_LAST_URL_KEY}:u:${getDashboardUserId()}`;
  }

  /* =====================
     UTILITIES
     ===================== */
  function $(sel) {
    return document.querySelector(sel);
  }
  function $id(id) {
    return document.getElementById(id);
  }
  function esc(s) {
    if (s === undefined || s === null) return "";
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
  function el(tag, { cls = "", attrs = {}, html = "" } = {}) {
    const d = document.createElement(tag);
    if (cls) d.className = cls;
    if (html) d.innerHTML = html;
    Object.keys(attrs || {}).forEach((k) => d.setAttribute(k, attrs[k]));
    return d;
  }

  function toast(msg, ms = 2200) {
    try {
      let t = document.getElementById("hs-toast");
      if (!t) {
        t = el("div", { attrs: { id: "hs-toast" }, cls: "hs-toast" });
        Object.assign(t.style, {
          position: "fixed",
          right: "20px",
          top: "24px",
          padding: "10px 14px",
          background: "rgba(0,0,0,0.6)",
          color: "#fff",
          borderRadius: "8px",
          zIndex: 9999,
          fontFamily: "Inter, sans-serif",
          transition: "opacity 260ms ease",
          opacity: 0,
        });
        document.body.appendChild(t);
      }
      t.textContent = msg;
      t.style.opacity = 1;
      setTimeout(() => (t.style.opacity = 0), ms);
    } catch (e) {
      // noop
    }
  }

  function analyticsPing(evt, payload = {}) {
    try {
      fetch(backendUrl("/analytics"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ event: evt, ...payload }),
      }).catch(() => {});
    } catch (e) {}
  }

  async function readJsonResponse(resp) {
    const contentType = (resp.headers.get("content-type") || "").toLowerCase();
    if (!contentType.includes("application/json")) {
      const txt = await resp.text().catch(() => "");
      throw new Error("Invalid JSON response: " + (txt || "").slice(0, 160));
    }
    return resp.json();
  }

  /* =====================
     LOADER UI (text + active class)
     ===================== */
  function showLoader() {
    const loader = $id(SEL.loader.replace("#", "")) || elCreateLoader();
    const loaderText = $id(SEL.loaderText.replace("#", "")) || null;
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!loader) return;
    let stage = 0;
    loader.classList.add("active");
    loader.classList.add("thinking");
    loader.setAttribute("aria-hidden", "false");
    document.body.classList.add("dashboard-aurora");
    if (analyzeBtn) {
      analyzeBtn.classList.add("thinking");
      analyzeBtn.disabled = true;
    }
    if (loaderText) loaderText.textContent = LOADING_STAGES[stage];

    // rotate text stages
    if (loaderInterval) clearInterval(loaderInterval);
    loaderInterval = setInterval(() => {
      stage = (stage + 1) % LOADING_STAGES.length;
      if (loaderText) loaderText.textContent = LOADING_STAGES[stage];
    }, 1400);
  }

  function hideLoader() {
    const loader = $id(SEL.loader.replace("#", "")) || null;
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!loader) return;
    loader.classList.remove("active");
    loader.classList.remove("thinking");
    loader.setAttribute("aria-hidden", "true");
    document.body.classList.remove("dashboard-aurora");
    if (analyzeBtn) {
      analyzeBtn.classList.remove("thinking");
      analyzeBtn.disabled = false;
    }
    if (loaderInterval) {
      clearInterval(loaderInterval);
      loaderInterval = null;
    }
  }

  function persistLastUrl(value) {
    try {
      const trimmed = String(value || "").trim();
      if (!trimmed) {
        localStorage.removeItem(getScopedLastUrlKey());
        return;
      }
      localStorage.setItem(getScopedLastUrlKey(), trimmed);
    } catch (e) {}
  }

  function syncInputState(value) {
    if (_isAnalyzing) return;
    hideLoader();
    persistLastUrl(value);
  }

  function elCreateLoader() {
    // creates a loader fallback if the dashboard template is missing it
    const loader = el("div", { attrs: { id: "loader" }, cls: "loader" });
    loader.setAttribute("aria-hidden", "true");
    loader.style.display = "none";
    loader.style.margin = "30px auto";
    loader.style.textAlign = "center";
    const caption = el("p", { cls: "loader-caption", html: "HotShort Intelligence" });
    const visual = el("div", { cls: "loader-visual" });
    const img = el("img", {
      cls: "loader-animation",
      attrs: {
        src: "/static/media/hotshort-thinking.gif",
        alt: "HotShort AI analyzing video structure",
      },
    });
    const wave = el("div", { cls: "wave" });
    const text = el("p", { attrs: { id: "loaderText" }, cls: "loader-text", html: "Preparing analysis..." });
    const subtext = el("p", {
      cls: "loader-subtext",
      html: "Signal emerging from noise. Hooks, insights, and structure are being assembled.",
    });
    visual.appendChild(img);
    loader.appendChild(caption);
    loader.appendChild(visual);
    loader.appendChild(wave);
    loader.appendChild(text);
    loader.appendChild(subtext);
    return loader;
  }

  /* =====================
     INSIGHT LOGIC (frontend heuristic)
     ===================== */
  function generateInsight(c) {
    const score = Number(c.score || 0);
    const impact = Number(c.impact || 0);
    const hook = Number(c.hook || 0);
    const continuity = Number(c.continuity || 0);
    const audio = Number(c.audio || 0);
    const motion = Number(c.motion || 0);
    const duration = Number((c.end || 0) - (c.start || 0)) || 0;

    const confRaw = 0.42 * score + 0.28 * impact + 0.12 * hook + 0.08 * continuity + 0.05 * audio + 0.05 * motion;
    const confidence = Math.min(1, Math.max(0, confRaw));
    const confPct = Math.round(confidence * 100);

    let label = "🧠 Idea Foundation";
    let advice = "Pair with a follow-up or cut a shorter hook.";

    if (confidence >= 0.88 && duration <= 45) {
      label = "🔥 Viral Hook";
      advice = "Post immediately as a Short / Reels.";
    } else if (confidence >= 0.72) {
      label = "🚀 High-Retention Moment";
      advice = "Great for Shorts / Reels — strong retention.";
    } else if (confidence >= 0.58) {
      label = "📖 Story Builder";
      advice = "Use as Part 1 in a multi-post story.";
    } else if (confidence >= 0.40) {
      label = "🔧 Edit-Ready Insight";
      advice = "Good building block — trim or add B-roll.";
    } else {
      label = "🧪 Experimental Clip";
      advice = "Test internally or boost with a small audience.";
    }

    if (duration > 60) advice += " (Consider trimming to 15-30s.)";
    if (hook > 0.15) advice += " (Add text overlay for hook.)";
    if (continuity > 0.4 && confidence >= 0.55) advice += " (Consider 'Part 1 / Part 2'.)";

    return { label, advice, confidencePct: confPct };
  }

  /* =====================
     PREVIEW MODAL
     ===================== */
  function ensurePreviewModal() {
    if (document.getElementById("preview-modal")) return;
    const modal = el("div", { attrs: { id: "preview-modal" }, cls: "preview-modal" });
    Object.assign(modal.style, {
      position: "fixed",
      inset: 0,
      display: "none",
      alignItems: "center",
      justifyContent: "center",
      background: "rgba(0,0,0,0.65)",
      zIndex: 9998,
    });

    const container = el("div", { cls: "preview-container" });
    Object.assign(container.style, { width: "min(960px,92%)", background: "#111", borderRadius: "12px", padding: "12px" });

    const video = el("video", { attrs: { id: "preview-video", controls: true } });
    Object.assign(video.style, { width: "100%", borderRadius: "8px", background: "#000" });

    const meta = el("div", { cls: "preview-meta" });
    Object.assign(meta.style, { color: "#ddd", marginTop: "8px", fontSize: "13px" });

    const closeBtn = el("button", { cls: "btn-close", html: "Close" });
    closeBtn.addEventListener("click", () => {
      modal.style.display = "none";
      video.pause();
      video.src = "";
    });

    container.appendChild(video);
    container.appendChild(meta);
    container.appendChild(closeBtn);
    modal.appendChild(container);
    document.body.appendChild(modal);
  }
  function generateIntelligence(c, insight) {
  const intel = [];

  // CURIOUSITY
  if (insight.label.includes("Viral Hook") || c.hook > 0.15) {
    intel.push({
      icon: "🧠",
      title: "Curiosity Gap",
      text: "Viewer must stay to resolve missing information."
    });
  }

  // AUTHORITY
  if (c.authority > 0.25 || insight.label.includes("Authority")) {
    intel.push({
      icon: "🎓",
      title: "Authority Signal",
      text: "Speaker is perceived as knowledgeable or experienced."
    });
  }

  // CONTRADICTION / SHOCK
  if (c.contradiction > 0.2 || insight.label.includes("Experimental")) {
    intel.push({
      icon: "⚡",
      title: "Pattern Break",
      text: "Unexpected idea interrupts scrolling behavior."
    });
  }

  // EMOTION
  if (c.emotion > 0.3) {
    intel.push({
      icon: "❤️",
      title: "Emotional Pull",
      text: "Emotion anchors memory and boosts shares."
    });
  }

  // RETENTION
  if (c.continuity > 0.4) {
    intel.push({
      icon: "🔁",
      title: "Retention Loop",
      text: "Story structure encourages continued watching."
    });
  }

  // FALLBACK (never empty)
  if (intel.length === 0) {
    intel.push({
      icon: "🧪",
      title: "Test Clip",
      text: "Worth testing for niche audience response."
    });
  }

  return intel.slice(0, 3); // MAX 3 → SMALL & CLEAN
}
  function reduceTranscript(text, maxChars = 260) {
  if (!text) return "";
  return text.length > maxChars
    ? text.slice(0, maxChars).trim() + "…"
    : text;
}
  function renderConfidenceBar(pct = 0) {
  const value = Math.max(0, Math.min(100, Number(pct) || 0));

  let color =
    value >= 80 ? "linear-gradient(90deg,#3cff8f,#00c853)" :
    value >= 55 ? "linear-gradient(90deg,#ffd54f,#ffb300)" :
                  "linear-gradient(90deg,#ff8a80,#d50000)";

  return `
    <div class="confidence-wrap">
      <div class="confidence-track">
        <div class="confidence-fill" style="width:${value}%;background:${color}"></div>
      </div>
      <span class="confidence-text">${value}% confidence</span>
    </div>
  `;
}

  function generateMicroSummary(c = {}, insight = {}) {
  if (insight.label?.includes("Viral Hook"))
    return "Opens with a hook that forces viewers to stay.";

  if (insight.label?.includes("High-Retention"))
    return "Strong flow keeps attention through the middle.";

  if (insight.label?.includes("Story Builder"))
    return "Narrative momentum builds curiosity step by step.";

  if (insight.label?.includes("Experimental"))
    return "Unusual idea that interrupts scrolling behavior.";

  return "Clear idea with potential for short-form growth.";
}

  /* =====================
     RENDER: SINGLE CLIP CARD
  /* ===================== 
  
  /* lightweight helper functions used above */
  function generateHookLine(c, insight) {
    if (!insight || !insight.label) return "Here’s something most people miss.";
    if (insight.label.includes("Viral Hook")) return "Most people get this wrong. --- here's why";
    if (insight.label.includes("High-Retention")) return "This is why most people fail at this.";
    if (insight.label.includes("Story Builder")) return "This changes how you think about it.";
    if (insight.label.includes("Experimental")) return "This idea is underrated.";
    return "Here’s something most people miss.";
  }

  function compressCaption(text, maxChars = 220) {
    if (!text) return "";
    const sentences = text.replace(/\n+/g, " ").split(/(?<=[.!?])\s+/);
    let out = sentences[0] || "";
    for (let i = 1; i < sentences.length; i++) {
      if (out.length + sentences[i].length > maxChars) break;
      out += " " + sentences[i];
    }
    return out.slice(0, maxChars).trim();
  }

  /* =====================
     MIND FILTER CHIPS
     ===================== */
  const MIND_KEYS = ["all", "curiosity", "contradiction", "authority", "emotion", "specificity"];
  let activeMind = "all";

  function renderMindChips(container) {
    if (!container) return;
    if (document.querySelector(".mind-chips")) return;
    const wrap = el("div", { cls: "mind-chips" });
    Object.assign(wrap.style, { display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "12px" });
    MIND_KEYS.forEach((k) => {
      const chip = el("button", { cls: "mind-chip", html: k.charAt(0).toUpperCase() + k.slice(1) });
      Object.assign(chip.style, {
        padding: "8px 12px",
        borderRadius: "999px",
        background: k === "all" ? "#4b2f1f" : "rgba(0,0,0,0.25)",
        color: "#f6d89e",
        border: "none",
        cursor: "pointer",
      });
      chip.addEventListener("click", () => {
        activeMind = k;
        document.querySelectorAll(".mind-chip").forEach((b) => (b.style.background = "rgba(0,0,0,0.25)"));
        chip.style.background = "#4b2f1f";
        filterByMind();
      });
      wrap.appendChild(chip);
    });
    // best location: before carousel in DOM
    const parent = container.parentNode || container;
    parent.insertBefore(wrap, container);
  }

  function clipMatchesActiveMind(cardNode) {
    if (!cardNode) return false;
    if (activeMind === "all") return true;
    const ms = cardNode._mind_scores || {};
    const key = Object.keys(ms).find((k) => k.toLowerCase().includes(activeMind));
    if (key) return (ms[key] || 0) > 0.2;
    const text = (cardNode.textContent || "").toLowerCase();
    return text.includes(activeMind);
  }

  function filterByMind() {
    const carousel = $id(SEL.carousel.replace("#", "")) || null;
    if (!carousel) return;
    Array.from(carousel.children).forEach((card) => {
      card.style.display = clipMatchesActiveMind(card) ? "" : "none";
    });
  }
  function buildClipHeader(c, insight, safeName) {
  return `
    <h3 class="clip-title">${esc(c.title || "Viral Moment")}</h3>

    <div class="clip-meta">
      <span class="clip-label">${esc(insight.label || "")}</span>
      <span class="clip-confidence">${insight.confidencePct || 0}%</span>
      <span class="clip-duration">
        ${((c.end || 0) - (c.start || 0)).toFixed(1)}s
      </span>

      <div class="download-group">
        <a class="download-main"
           href="${esc(c.clip_url)}"
           download="${safeName}.mp4">
          Download
        </a>

        <button class="download-menu-btn">▾</button>
        <div class="download-menu">
          <button data-format="original">Original</button>
          <button data-format="reels">Reels</button>
          <button data-format="tiktok">TikTok</button>
        </div>
      </div>
    </div>
  `;
}
  function extractSmartTranscriptHook(text, maxChars = 180) {
  if (!text) return "";

  // clean text
  const clean = text
    .replace(/\s+/g, " ")
    .replace(/\n+/g, " ")
    .trim();

  if (!clean) return "";

  // split into sentences
  const sentences = clean.split(/(?<=[.!?])\s+/);

  // priority scoring
  function scoreSentence(s) {
    let score = 0;
    const lower = s.toLowerCase();

    // questions hook attention
    if (s.includes("?")) score += 3;

    // contradiction / shock words
    if (
      lower.includes("but") ||
      lower.includes("most people") ||
      lower.includes("nobody") ||
      lower.includes("wrong") ||
      lower.includes("stop") ||
      lower.includes("fail")
    ) score += 3;

    // strong opener words
    if (
      lower.startsWith("this") ||
      lower.startsWith("here") ||
      lower.startsWith("why") ||
      lower.startsWith("what if")
    ) score += 2;

    // short & punchy
    if (s.length < 140) score += 2;

    return score;
  }

  // find best sentence
  let best = sentences[0];
  let bestScore = 0;

  for (const s of sentences.slice(0, 6)) {
    const score = scoreSentence(s);
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }

  // fallback safety
  const output = best.length > maxChars
    ? best.slice(0, maxChars).trim() + "…"
    : best;

  return output;
}

  function buildClipIntelligence(c, insight) {
  if (typeof generateIntelligence !== "function") return "";

  const intel = generateIntelligence(c, insight);
  if (!Array.isArray(intel) || !intel.length) return "";

  return `
    <div class="intel-stack">
      ${intel.map(i => `
        <div class="intel-row">
          <span class="intel-icon">${esc(i.icon)}</span>
          <div>
            <div class="intel-title">${esc(i.title)}</div>
            <div class="intel-text">${esc(i.text)}</div>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}
  function bindClipInteractions(card) {
  // WHY toggle
  const whyBtn = card.querySelector(".why-toggle");
  const whyPanel = card.querySelector(".why-panel");

  if (whyBtn && whyPanel) {
    whyBtn.addEventListener("click", () => {
      const open = whyPanel.style.display === "block";
      whyPanel.style.display = open ? "none" : "block";
      whyBtn.textContent = open
        ? "Why this clip works ▾"
        : "Why this clip works ▴";
    });
  }

  // Transcript toggle
  const tBtn = card.querySelector(".transcript-toggle");
  const tPanel = card.querySelector(".transcript-panel");

  if (tBtn && tPanel) {
    tBtn.addEventListener("click", () => {
      const open = tPanel.classList.toggle("open");
      tPanel.style.maxHeight = open ? "220px" : "0";
      tBtn.textContent = open
        ? "Hide transcript ▴"
        : "View transcript ▾";
    });
  }

  // Download menu
  const menuBtn = card.querySelector(".download-menu-btn");
  const menu = card.querySelector(".download-menu");

  if (menuBtn && menu) {
    menuBtn.addEventListener("click", e => {
      e.stopPropagation();
      menu.style.display = menu.style.display === "block" ? "none" : "block";
    });

    document.addEventListener("click", () => {
      menu.style.display = "none";
    });
  }
}
 function renderClipCard(c, index, bestIndex) {
  const card = el("div", { cls: "clip-card" });
  const body = el("div", { cls: "clip-body" });

  // ---------- Insight (safe) ----------
  const insight = typeof generateInsight === "function"
    ? generateInsight(c)
    : { label: "", confidencePct: 0 };

  const confPct = Math.max(0, Math.min(100, insight.confidencePct || 0));

  const safeName = (c.title || "clip")
    .replace(/[^\w]+/g, "_")
    .toLowerCase();

  const transcript = (c.text || "").trim();
  const smartTranscript = extractSmartTranscriptHook(c.text);


  // ---------- HTML ----------
  body.innerHTML = `
    ${buildClipHeader(c, insight, safeName)}

    <h3 class="clip-title">
      ${esc(c.title || "Viral Moment")}
    </h3>

    <div class="clip-meta">
      <span class="clip-label">${esc(insight.label || "")}</span>
      <span class="clip-duration">
        ${((c.end || 0) - (c.start || 0)).toFixed(1)}s
      </span>
    </div>

    ${renderConfidenceBar(confPct)}

    <div class="clip-hook">
      ${esc(generateHookLine(c, insight))}
    </div>

    <div class="micro-summary">
      ${esc(generateMicroSummary(c, insight))}
    </div>

    ${smartTranscript ? `
  <button class="transcript-toggle">Why people stop here ▾</button>
  <div class="transcript-panel">
    ${esc(smartTranscript)}
  </div>
` : ""}


    ${buildClipIntelligence(c, insight)}

    ${
      Array.isArray(c.why) && c.why.length
        ? `
        <button class="why-toggle">Why this clip works ▾</button>
        <div class="why-panel">
          <ul>
            ${c.why.map(w => `<li>${esc(w)}</li>`).join("")}
          </ul>
        </div>
      `
        : ""
    }
  `;

  card.appendChild(body);
  bindClipInteractions(card);

  return card;
}



  /* =====================
     TIER UI (badge + remaining)
     ===================== */
  function showTierUI(plan, remaining, upgrade_hint) {
    const header = document.querySelector(SEL.header) || document.querySelector(SEL.hero) || document.body;
    const existing = document.getElementById("hs-tier-ui");
    if (existing) existing.remove();

    const container = el("div", { attrs: { id: "hs-tier-ui" }, cls: "hs-tier-ui" });
    Object.assign(container.style, { position: "absolute", right: "22px", top: "18px", zIndex: 999, display: "flex", gap: "10px", alignItems: "center" });

    const badge = el("div", { cls: "hs-badge", html: esc(String(plan || "free").toUpperCase()) });
    Object.assign(badge.style, {
      background: plan === "free" ? "rgba(0,0,0,0.45)" : "linear-gradient(90deg,#ffd89b,#f6d89e)",
      color: plan === "free" ? "#f6d89e" : "#111",
      padding: "8px 12px",
      borderRadius: "999px",
      fontWeight: 700,
    });

    const rem = el("div", { cls: "hs-remaining", html: `Remaining: ${remaining === Infinity ? "∞" : remaining}` });
    Object.assign(rem.style, { background: "rgba(0,0,0,0.45)", color: "#ffdca8", padding: "8px 12px", borderRadius: "10px" });

    if (Number.isFinite(remaining) && remaining <= 0) {
      const up = el("a", { attrs: { href: "/subscription" }, html: "Upgrade" });
      Object.assign(up.style, { background: "linear-gradient(90deg,#ffd89b,#f6d89e)", color: "#111", padding: "8px 12px", borderRadius: "10px", textDecoration: "none" });
      container.appendChild(badge);
      container.appendChild(rem);
      container.appendChild(up);
      const analyzeBtn = document.querySelector(SEL.analyzeBtn);
      if (analyzeBtn) {
        analyzeBtn.disabled = true;
        analyzeBtn.title = "Weekly clip limit reached — upgrade to generate more.";
        analyzeBtn.style.opacity = 0.7;
      }
    } else {
      const analyzeBtn = document.querySelector(SEL.analyzeBtn);
      if (analyzeBtn) {
        analyzeBtn.disabled = false;
        analyzeBtn.title = "";
        analyzeBtn.style.opacity = 1;
      }
      container.appendChild(badge);
      container.appendChild(rem);
    }

    header.style.position = header.style.position || "relative";
    header.appendChild(container);
  }

  /* =====================
     MAIN ANALYZE FLOW (single-flight, robust)
     ===================== */
  async function handleAnalyzeClick(e) {
    e && e.preventDefault && e.preventDefault();
    if (_isAnalyzing) {
      toast("Analysis already running…");
      return;
    }

    const ytInput = document.querySelector(SEL.yt);
    const ytUrl = (ytInput && ytInput.value || "").trim();
    if (!ytUrl) {
      toast("Please paste a YouTube link.");
      return;
    }

    if (ytInput) ytInput.value = ytUrl;

    _isAnalyzing = true;
    showLoader();

    // prepare carousel container
    let carousel = $id(SEL.carousel.replace("#", ""));
    if (!carousel) {
      carousel = el("div", { cls: "carousel", attrs: { id: SEL.carousel.replace("#", "") } });
    }
    carousel.innerHTML = "";

    try {
      persistLastUrl(ytUrl);
      analyticsPing("analyze_click", { youtube_url: ytUrl });

      // build FormData
      const fd = new FormData();
      fd.append("youtube_url", ytUrl);
      fd.append("mode", "final");

      const resp = await fetch(backendUrl("/analyze"), {
        method: "POST",
        headers: { "Accept": "application/json" },
        credentials: "include",
        body: fd
      });
      
      // Check if response is OK
      if (!resp.ok && resp.status !== 302) {
        const txt = await resp.text().catch(() => "");
        throw new Error(`Server error (${resp.status}): ${txt.substring(0, 100)}`);
      }
      
      // Handle redirect-style responses defensively.
      if (resp.redirected && resp.url) {
        hideLoader();
        window.location.href = resp.url;
        return;
      }

      const data = await readJsonResponse(resp);

      if (data && data.action === "show_pricing_modal") {
        hideLoader();
        if (typeof window.showPricingModal === "function") {
          window.showPricingModal();
        } else {
          toast("Upgrade required to analyze again.");
        }
        return;
      }

      hideLoader();
      
      const nextRedirect = data && (data.redirect || data.redirect_url || data.results_url);
      if (nextRedirect) {
         // ✅ Truthful UI feedback
        toast(`Analysis complete! Clips: ${data.clips_count}`, "success");

  // ✅ Short pause so user sees feedback
        setTimeout(() => {
          window.location.href = String(nextRedirect).startsWith("http") ? nextRedirect : backendUrl(nextRedirect);
        }, 600);

        return;
      }

      if (data && data.error) {
        toast(`Error: ${data.error}`);
        return;
      }

      // If we get here without a redirect or an explicit error, stop safely.
      return;

    } catch (err) {
      hideLoader();
      console.error("Analyze error:", err);
      toast("Error: " + (err && err.message ? err.message : String(err)));
      analyticsPing("analyze_error", { message: (err && err.message) || String(err) });
    } finally {
      _isAnalyzing = false;
    }
  }

  /* =====================
     INIT (single place to wire everything)
     ===================== */
  function init() {
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!analyzeBtn) {
      console.warn("Analyze button not found:", SEL.analyzeBtn);
      return;
    }

    // wire click once
    analyzeBtn.addEventListener("click", handleAnalyzeClick);

    // restore last url (scoped by logged-in user id)
    try {
      const yt = document.querySelector(SEL.yt);
      if (yt) yt.value = "";
      const scoped = localStorage.getItem(getScopedLastUrlKey());
      if (scoped && yt) yt.value = scoped;
      if (yt) {
        yt.addEventListener("input", () => syncInputState(yt.value));
        yt.addEventListener("change", () => syncInputState(yt.value));
        yt.addEventListener("paste", () => {
          requestAnimationFrame(() => {
            if (document.querySelector(SEL.yt) === yt) syncInputState(yt.value);
          });
        });
        yt.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleAnalyzeClick(e);
          }
        });
      }
      // Clean old global key to avoid cross-account leakage on shared browsers.
      localStorage.removeItem(GLOBAL_LAST_URL_KEY);
    } catch (e) {}

    ensurePreviewModal();

    // video hover play/pause (delegated): only hovered clip plays
    function pauseOtherClipVideos(except) {
      document.querySelectorAll(".clip-card video").forEach((v) => {
        if (except && v === except) return;
        try {
          v.pause();
          v.currentTime = 0;
        } catch (e) {}
      });
    }

    document.addEventListener("mouseover", (e) => {
      const card = e.target.closest(".clip-card");
      if (!card) return;
      if (e.relatedTarget && card.contains(e.relatedTarget)) return; // moving within the same card
      const v = card.querySelector("video");
      if (!v) return;
      pauseOtherClipVideos(v);
      v.play().catch(() => {});
    });

    document.addEventListener("mouseout", (e) => {
      const card = e.target.closest(".clip-card");
      if (!card) return;
      if (e.relatedTarget && card.contains(e.relatedTarget)) return; // still inside card
      const v = card.querySelector("video");
      if (!v) return;
      try {
        v.pause();
        v.currentTime = 0;
      } catch (err) {}
    });

    console.info("[HotShort] Dashboard JS initialized (elite)");
  }

  document.addEventListener("DOMContentLoaded", init);

  // expose small API for console/testing
  window._hotshort = { analyze: handleAnalyzeClick, genInsight: generateInsight };
})();
