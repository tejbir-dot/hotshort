/* dashboard.js — HotShort Studio (elite)
   Cleaned, consolidated, and hardened version.
   - Single init() wiring (no cloneNode/double listeners)
   - Single-flight analyze (prevents double requests)
   - Premium Aurora loader with multi-stage progress
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
    loader: "#hs-analyze-overlay",
    loaderText: "#hs-loading-message",
    carousel: "#carousel",
    header: "header",
    hero: ".hero",
  };

  /* =====================
     LOADER TEXT STAGES
     ===================== */
  const LOADING_STAGES = [
    { key: "upload", message: "Preparing your video for analysis...", percent: 18, time: "1 min 40 sec" },
    { key: "transcribe", message: "Converting speech into searchable text...", percent: 36, time: "1 min 12 sec" },
    { key: "analyze", message: "Understanding your content and story flow...", percent: 68, time: "1 min 24 sec" },
    { key: "score", message: "Ranking the strongest viral moments...", percent: 84, time: "54 sec" },
    { key: "clips", message: "Extracting the best short-form moments...", percent: 96, time: "12 sec" }
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
      const normalized = raw.replace(/\/+$/, "");
      if (!normalized) return "";
      try {
        const candidate = new URL(normalized, window.location.origin);
        if (candidate.origin !== window.location.origin) {
          return "";
        }
      } catch (e) {
        return "";
      }
      return normalized;
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

  function getDashboardTemplateId() {
    try {
      const ctx = document.getElementById("dashboardContext");
      const v = (ctx && ctx.dataset && ctx.dataset.templateId) ? String(ctx.dataset.templateId).trim() : "";
      return v || "";
    } catch (e) {
      return "";
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
      if (window.showToast) {
        window.showToast(msg, 'info', ms);
        return;
      }
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
     LOADER UI (AURORA)
     ===================== */
  function showLoader() {
    const loader = $id(SEL.loader.replace("#", ""));
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!loader) return;

    loader.hidden = false;
    document.body.classList.add("dashboard-aurora");
    if (analyzeBtn) {
      analyzeBtn.classList.add("thinking");
      analyzeBtn.disabled = true;
    }

    let stageIdx = 0;
    const updateUI = (idx) => {
      const stage = LOADING_STAGES[idx];
      const stageMap = ["upload", "transcribe", "analyze", "score", "clips"];

      stageMap.forEach((key, i) => {
        const el = $id(`hs-stage-${key}`);
        if (!el) return;
        el.classList.remove("is-done", "is-active");
        if (i < idx) el.classList.add("is-done");
        if (i === idx) el.classList.add("is-active");
      });

      const msg = $id("hs-loading-message");
      const pct = $id("hs-loading-percent");
      const fill = $id("hs-loading-fill");
      const time = $id("hs-loading-time");
      const foot = $id("hs-progress-foot");

      if (msg) msg.textContent = stage.message;
      if (pct) pct.textContent = `${stage.percent}%`;
      if (fill) fill.style.width = `${stage.percent}%`;
      if (time) time.textContent = stage.time;
      if (foot) foot.textContent = stage.message;
    };

    updateUI(0);

    if (loaderInterval) clearInterval(loaderInterval);
    loaderInterval = setInterval(() => {
      stageIdx = Math.min(stageIdx + 1, LOADING_STAGES.length - 1);
      updateUI(stageIdx);
    }, 2200);
  }

  function hideLoader() {
    const loader = $id(SEL.loader.replace("#", ""));
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!loader) return;
    
    loader.hidden = true;
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

  /* =====================
     INSIGHT LOGIC
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
    if (insight.label.includes("Viral Hook") || c.hook > 0.15) {
      intel.push({ icon: "🧠", title: "Curiosity Gap", text: "Viewer must stay to resolve missing information." });
    }
    if (c.authority > 0.25 || insight.label.includes("Authority")) {
      intel.push({ icon: "🎓", title: "Authority Signal", text: "Speaker is perceived as knowledgeable or experienced." });
    }
    if (c.contradiction > 0.2 || insight.label.includes("Experimental")) {
      intel.push({ icon: "⚡", title: "Pattern Break", text: "Unexpected idea interrupts scrolling behavior." });
    }
    if (c.emotion > 0.3) {
      intel.push({ icon: "❤️", title: "Emotional Pull", text: "Emotion anchors memory and boosts shares." });
    }
    if (c.continuity > 0.4) {
      intel.push({ icon: "🔁", title: "Retention Loop", text: "Story structure encourages continued watching." });
    }
    if (intel.length === 0) {
      intel.push({ icon: "🧪", title: "Test Clip", text: "Worth testing for niche audience response." });
    }
    return intel.slice(0, 3);
  }

  function reduceTranscript(text, maxChars = 260) {
    if (!text) return "";
    return text.length > maxChars ? text.slice(0, maxChars).trim() + "…" : text;
  }

  function renderConfidenceBar(pct = 0) {
    const value = Math.max(0, Math.min(100, Number(pct) || 0));
    let color = value >= 80 ? "linear-gradient(90deg,#3cff8f,#00c853)" :
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
    if (insight.label?.includes("Viral Hook")) return "Opens with a hook that forces viewers to stay.";
    if (insight.label?.includes("High-Retention")) return "Strong flow keeps attention through the middle.";
    if (insight.label?.includes("Story Builder")) return "Narrative momentum builds curiosity step by step.";
    if (insight.label?.includes("Experimental")) return "Unusual idea that interrupts scrolling behavior.";
    return "Clear idea with potential for short-form growth.";
  }

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

  function extractSmartTranscriptHook(text, maxChars = 180) {
    if (!text) return "";
    const clean = text.replace(/\s+/g, " ").replace(/\n+/g, " ").trim();
    if (!clean) return "";
    const sentences = clean.split(/(?<=[.!?])\s+/);
    function scoreSentence(s) {
      let score = 0;
      const lower = s.toLowerCase();
      if (s.includes("?")) score += 3;
      if (lower.includes("but") || lower.includes("most people") || lower.includes("nobody") || lower.includes("wrong") || lower.includes("stop") || lower.includes("fail")) score += 3;
      if (lower.startsWith("this") || lower.startsWith("here") || lower.startsWith("why") || lower.startsWith("what if")) score += 2;
      if (s.length < 140) score += 2;
      return score;
    }
    let best = sentences[0];
    let bestScore = 0;
    for (const s of sentences.slice(0, 6)) {
      const score = scoreSentence(s);
      if (score > bestScore) {
        bestScore = score;
        best = s;
      }
    }
    return best.length > maxChars ? best.slice(0, maxChars).trim() + "…" : best;
  }

  function buildClipHeader(c, insight, safeName) {
    return `
      <h3 class="clip-title">${esc(c.title || "Viral Moment")}</h3>
      <div class="clip-meta">
        <span class="clip-label">${esc(insight.label || "")}</span>
        <span class="clip-confidence">${insight.confidencePct || 0}%</span>
        <span class="clip-duration">${((c.end || 0) - (c.start || 0)).toFixed(1)}s</span>
        <a class="download-btn" href="${esc(c.clip_url)}" download="${safeName}.mp4">Download</a>
      </div>
    `;
  }

  function buildClipIntelligence(c, insight) {
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
    const whyBtn = card.querySelector(".why-toggle");
    const whyPanel = card.querySelector(".why-panel");
    if (whyBtn && whyPanel) {
      whyBtn.addEventListener("click", () => {
        const open = whyPanel.style.display === "block";
        whyPanel.style.display = open ? "none" : "block";
        whyBtn.textContent = open ? "Why this clip works ▾" : "Why this clip works ▴";
      });
    }
    const tBtn = card.querySelector(".transcript-toggle");
    const tPanel = card.querySelector(".transcript-panel");
    if (tBtn && tPanel) {
      tBtn.addEventListener("click", () => {
        const open = tPanel.classList.toggle("open");
        tPanel.style.maxHeight = open ? "220px" : "0";
        tBtn.textContent = open ? "Hide transcript ▴" : "View transcript ▾";
      });
    }
  }

  function renderClipCard(c, index, bestIndex) {
    const card = el("div", { cls: "clip-card" });
    const body = el("div", { cls: "clip-body" });
    const insight = generateInsight(c);
    const confPct = Math.max(0, Math.min(100, insight.confidencePct || 0));
    const safeName = (c.title || "clip").replace(/[^\w]+/g, "_").toLowerCase();
    const smartTranscript = extractSmartTranscriptHook(c.text);

    body.innerHTML = `
      ${buildClipHeader(c, insight, safeName)}
      <h3 class="clip-title">${esc(c.title || "Viral Moment")}</h3>
      <div class="clip-meta">
        <span class="clip-label">${esc(insight.label || "")}</span>
        <span class="clip-duration">${((c.end || 0) - (c.start || 0)).toFixed(1)}s</span>
      </div>
      ${renderConfidenceBar(confPct)}
      <div class="clip-hook">${esc(generateHookLine(c, insight))}</div>
      <div class="micro-summary">${esc(generateMicroSummary(c, insight))}</div>
      ${smartTranscript ? `<button class="transcript-toggle">Why people stop here ▾</button><div class="transcript-panel">${esc(smartTranscript)}</div>` : ""}
      ${buildClipIntelligence(c, insight)}
      ${Array.isArray(c.why) && c.why.length ? `<button class="why-toggle">Why this clip works ▾</button><div class="why-panel"><ul>${c.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    `;
    card.appendChild(body);
    bindClipInteractions(card);
    return card;
  }

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
        analyzeBtn.style.opacity = 0.7;
      }
    } else {
      const analyzeBtn = document.querySelector(SEL.analyzeBtn);
      if (analyzeBtn) {
        analyzeBtn.disabled = false;
        analyzeBtn.style.opacity = 1;
      }
      container.appendChild(badge);
      container.appendChild(rem);
    }
    header.style.position = header.style.position || "relative";
    header.appendChild(container);
  }

  /* =====================
     MAIN ANALYZE FLOW
     ===================== */
  async function handleAnalyzeClick(e) {
    e && e.preventDefault && e.preventDefault();
    if (_isAnalyzing) return;
    const ytInput = document.querySelector(SEL.yt);
    const ytUrl = (ytInput && ytInput.value || "").trim();
    if (!ytUrl) {
      toast("Please paste a YouTube link.");
      return;
    }
    _isAnalyzing = true;
    showLoader();
    try {
      persistLastUrl(ytUrl);
      analyticsPing("analyze_click", { youtube_url: ytUrl });
      const fd = new FormData();
      fd.append("youtube_url", ytUrl);
      fd.append("mode", "final");
      const templateId = getDashboardTemplateId();
      if (templateId) fd.append("template_id", templateId);
      const resp = await fetch(backendUrl("/analyze"), {
        method: "POST",
        headers: { "Accept": "application/json" },
        credentials: "include",
        body: fd
      });
      if (resp.redirected && resp.url) {
        window.location.href = resp.url;
        return;
      }
      const data = await readJsonResponse(resp);
      if (data && data.action === "show_pricing_modal") {
        hideLoader();
        if (typeof window.showPricingModal === "function") window.showPricingModal();
        return;
      }
      const nextRedirect = data && (data.redirect || data.redirect_url || data.results_url || (data.job_id ? `/results/${encodeURIComponent(data.job_id)}` : ""));
      if (nextRedirect) {
        toast("Analysis complete!", "success");
        setTimeout(() => {
          window.location.href = String(nextRedirect).startsWith("http") ? nextRedirect : backendUrl(nextRedirect);
        }, 600);
        return;
      }
      if (data && data.error) toast(`Error: ${data.error}`);
    } catch (err) {
      hideLoader();
      toast("Error: " + (err.message || String(err)));
    } finally {
      _isAnalyzing = false;
    }
  }

  /* =====================
     INIT
     ===================== */
  function init() {
    const analyzeBtn = document.querySelector(SEL.analyzeBtn);
    if (!analyzeBtn) return;
    analyzeBtn.addEventListener("click", handleAnalyzeClick);
    try {
      const yt = document.querySelector(SEL.yt);
      if (yt) {
        const scoped = localStorage.getItem(getScopedLastUrlKey());
        if (scoped) yt.value = scoped;
        yt.addEventListener("input", () => syncInputState(yt.value));
        yt.addEventListener("keydown", (e) => { if (e.key === "Enter") handleAnalyzeClick(e); });
      }
    } catch (e) {}
    ensurePreviewModal();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
