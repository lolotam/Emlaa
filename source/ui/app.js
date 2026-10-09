/* إملاء — منطق الواجهة. كل البيانات بتيجي من Python عن طريق window.pywebview.api */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = () => window.pywebview && window.pywebview.api;

const S = {
  boot: null,
  page: "home",
  recMode: "normal",
  state: "ready",
  history: [],
  histFilter: "all",
  histSel: new Set(),
  clips: [],
  clipSel: new Set(),
  clipLimit: 200,
  provider: null,
  snipEditKey: null,
  offline: null,
  keyPools: {},          // pid → المفاتيح المموّهة وحالتها
  features: null,        // نسخة الإعدادات اللي بنعدّل فيها لحد «حفظ»
  feat: "normal",        // التاب المفتوح
  capturing: false,      // مستنيين المستخدم يدوس الزرار
};

const MODE_LABEL = { normal: "عادي", prompt: "برومبت", translate: "ترجمة", edit: "تعديل" };
const OFFLINE_MODEL_LABEL = { base: "أسرع وأقل دقة", "small-q5_1": "أدق — موصى بيه" };
const STATE_TEXT = {
  ready: "جاهز", rec: "بيسجّل…", work: "بيفرّغ الكلام…", prompt: "بيجهّز البرومبت…",
  translate: "بيترجم…", done: "اتبعت ✓", err: "في مشكلة", off: "محتاج مفتاح",
};
const ICON = {
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="m6 15 6-6 6 6"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
  eyeOff: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.9 9.9 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>',
};

/* ═══════════ أدوات ═══════════ */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(n) { return Number(n || 0).toLocaleString("en-US"); }
function parseTime(t) { return t ? new Date(t.replace(" ", "T")) : new Date(0); }
function dayKey(d) {   // التاريخ المحلي — toISOString كان بيحسب بتوقيت UTC فتسجيلات قبل ٣ الفجر تروح لليوم اللي قبله
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function dayLabel(d) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const that = new Date(d); that.setHours(0, 0, 0, 0);
  const diff = Math.round((today - that) / 86400000);
  if (diff === 0) return "النهارده";
  if (diff === 1) return "امبارح";
  return d.toLocaleDateString(LANG === "en" ? "en-US" : "ar-EG-u-nu-latn", { weekday: "long", day: "numeric", month: "long" });
}
function hhmm(d) {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}
function shortTime(d) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (d >= today) return hhmm(d);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" }) + " " + hhmm(d);
}
let toastT = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), 2200);
}
async function copyText(text, btn) {
  const ok = await api().copy(text);
  if (!btn) return toast(ok ? "اتنسخ ✓" : "مقدرتش أنسخ");
  const old = btn.innerHTML;
  btn.classList.add("ok");
  btn.innerHTML = btn.classList.contains("icon-btn") ? ICON.check : ICON.check + "<span>اتنسخ</span>";
  setTimeout(() => { btn.classList.remove("ok"); btn.innerHTML = old; }, 1300);
}

/* ═══════════ المظهر (فاتح / غامق / تلقائي) ═══════════ */
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme(pref) {
  const t = pref === "light" || pref === "dark" ? pref : (darkQuery.matches ? "dark" : "light");
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("emlaa-theme", t); } catch (e) {}
}
darkQuery.addEventListener("change", () => { if ((S.boot?.cfg.theme || "dark") === "system") applyTheme("system"); });
async function setTheme(pref) {
  applyTheme(pref);
  const r = await api().save_settings({ theme: pref });
  if (r.ok) { S.boot = r.boot; if (S.page === "settings") $("#sTheme").value = pref; }
}

/* ═══════════ التنقل ═══════════ */
function go(page) {
  if (!S.boot) return;
  if (!S.boot.canRun && page !== "welcome" && page !== "settings") page = "welcome";
  if (S.page === "settings" && page !== "settings") leaveSettings();
  S.page = page;
  $$(".page").forEach(p => p.classList.toggle("active", p.dataset.page === page));
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.go === page));
  $("#main").scrollTop = 0;
  if (page === "history") renderHistory();
  if (page === "clipboard") loadClips();
  if (page === "dictionary") { renderDict(); renderSnippets(); }
  if (page === "settings") { fillSettings(); startKeyPoolTimer(); }
  else stopKeyPoolTimer();
  updateBulk();
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-go]");
  if (g) { e.preventDefault(); go(g.dataset.go); }
});

/* ═══════════ الحالة ═══════════ */
function setState(st, msg) {
  S.state = st;
  const pill = $("#statusPill");
  pill.className = "status-pill " + ({ rec: "rec", work: "work", prompt: "work", translate: "work", err: "err", off: "off" }[st] || "");
  $("span", pill).textContent = msg || STATE_TEXT[st] || st;
  const btn = $("#recBtn");
  btn.classList.toggle("recording", st === "rec");
  btn.classList.toggle("working", ["work", "prompt", "translate"].includes(st));
  btn.disabled = ["work", "prompt", "translate"].includes(st);
  $("#recLabel").textContent = st === "rec" ? "إيقاف التسجيل" : btn.disabled ? "بيفرّغ الكلام…" : "ابدأ التسجيل";
}

/* ═══════════ الرئيسية ═══════════ */
function renderStats(st) {
  if (!st) return;
  $("#mWords").textContent = num(st.words);
  $("#mCount").textContent = num(st.count) + " تسجيل";
  $("#mSaved").innerHTML = (st.saved_min >= 60 ? (st.saved_min / 60).toFixed(1) + "<small>ساعة</small>"
                                               : num(Math.round(st.saved_min)) + "<small>دقيقة</small>");
  $("#mWpm").innerHTML = (st.wpm ? num(st.wpm) : "—") + "<small>WPM</small>";
  $("#mWpmFoot").textContent = st.wpm ? "كلمة في الدقيقة" : "بتتحسب من التسجيلات الجديدة";
  $("#navHistCount").textContent = st.count ? num(st.count) : "";
}
function renderKeys() {
  const toggle = S.boot.cfg.mode !== "hold";
  const f = S.boot.features;
  // التعديل بيظهر بس لو ليه زرار — من غيره مالوش طريقة يتشغّل بيها من الرئيسية
  const modes = ["normal", "prompt", "translate"].concat(f.edit.hotkey.length ? ["edit"] : []);
  $("#homeKeys").innerHTML = modes.map(m => `<div class="key-line"><i class="dot ${m}"></i><span class="grow">${MODE_LABEL[m]}</span><span class="kbd">${esc(f[m].label || "—")}</span></div>`).join("")
    + `<div class="kbd-hint">${toggle ? "دوسة على أي زرار من دول تبدأ، ودوسة تانية توقف." : "امسك الزرار واتكلم، وسيبه لما تخلص."}</div>`;
}
function renderLast() {
  const last = S.history[0];
  const el = $("#lastText");
  const text = (last && last.result) || S.boot.lastText || "";
  el.textContent = text || "لسه مفيش تسجيلات — جرّب دلوقتي.";
  el.classList.toggle("empty", !text);
  $("#copyLast").disabled = !text;
  $("#lastMeta").innerHTML = last
    ? `<span class="mode-tag"><i class="dot ${esc(last.mode)}"></i>${MODE_LABEL[last.mode] || ""}</span><span>${esc(dayLabel(parseTime(last.time)))} · ${esc(hhmm(parseTime(last.time)))}</span>`
    : "";
}
function renderRecent() {
  const items = S.history.slice(0, 4);
  $("#recentList").innerHTML = items.length
    ? items.map(i => `<div class="recent-row" data-go="history"><span class="r-time">${esc(hhmm(parseTime(i.time)))}</span><i class="dot ${esc(i.mode)}"></i><span class="r-text">${esc(i.result)}</span></div>`).join("")
    : `<div class="dict-empty">التسجيلات هتظهر هنا.</div>`;
}
$("#modeSeg").addEventListener("click", e => {
  const b = e.target.closest("button[data-mode]");
  if (!b) return;
  S.recMode = b.dataset.mode;
  $$("#modeSeg button").forEach(x => x.classList.toggle("active", x === b));
});
$("#recBtn").addEventListener("click", async () => {
  const ok = await api().record(S.recMode);
  if (!ok) toast("المحرّك لسه بيجهز…");
});
$("#copyLast").addEventListener("click", e => copyText($("#lastText").textContent, e.currentTarget));

/* ═══════════ السجل ═══════════ */
async function loadHistory() {
  const r = await api().history();
  S.history = r.items || [];
  renderStats(r.stats);
  renderLast();
  renderRecent();
  renderChart();
  if (S.page === "history") renderHistory();
}

/* آخر ٧ أيام — كلمات كل يوم من السجل الحقيقي (لون واحد للبيانات، النهارده أغمق) */
const DAY_SHORT = ["الأحد", "الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت"];
function itemWords(i) { return i.words || (i.raw || "").split(/\s+/).filter(Boolean).length; }
function renderChart() {
  const days = [];
  for (let k = 6; k >= 0; k--) {
    const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - k);
    days.push({ key: dayKey(d), d, words: 0 });
  }
  const byKey = Object.fromEntries(days.map(x => [x.key, x]));
  for (const i of S.history) {
    const x = byKey[dayKey(parseTime(i.time))];
    if (x) x.words += itemWords(i);
  }
  const max = Math.max(1, ...days.map(x => x.words));
  const total = days.reduce((a, x) => a + x.words, 0);
  $("#chartTotal").textContent = total ? `${num(total)} كلمة` : "";
  $("#weekChart").innerHTML = days.map((x, idx) => {
    const h = x.words ? Math.max(6, Math.round(x.words / max * 78)) : 3;
    return `<div class="bar-col${idx === 6 ? " today" : ""}" title="${num(x.words)} كلمة">
      <span class="bar-val">${x.words ? num(x.words) : ""}</span>
      <span class="bar${x.words ? "" : " empty"}" style="height:${h}px"></span>
      <span class="bar-day">${idx === 6 ? "النهارده" : DAY_SHORT[x.d.getDay()]}</span></div>`;
  }).join("");
}

/* مؤشّر طول التسجيل: أعمدة شكل موجة — عددها على قد المدة، وشكلها ثابت لكل تسجيل (من الـid).
   آخر ١٠ تسجيلات صوتها متخزّن (i.audio): الموجة بتبقى زرار تشغيل، والأعمدة بتتلوّن مع التقدّم. */
function waveHTML(i) {
  if (!i.dur && !i.audio) return "";
  const n = Math.max(8, Math.min(30, Math.round((i.dur || 0) * 1.6)));
  let seed = (i.id % 2147483647) || 7, bars = "";
  for (let k = 0; k < n; k++) {
    seed = (seed * 16807) % 2147483647;
    const env = Math.sin(Math.PI * (k + .5) / n);
    bars += `<i style="height:${Math.round(4 + (seed % 100) / 100 * 16 * (0.45 + env * .55))}px"></i>`;
  }
  const sec = Math.round(i.dur || 0);
  const dur = `<span class="wave-dur">${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}</span>`;
  if (!i.audio) return `<div class="wave" aria-hidden="true"><span class="wave-bars">${bars}</span>${dur}</div>`;
  return `<button class="wave playable" data-act="play" title="تشغيل التسجيل"><span class="wave-icon">${ICON.play}</span><span class="wave-bars">${bars}</span>${dur}</button>`;
}

/* مين فرّغ ومين نضّف: «Deepgram · nova-3 → Groq · qwen3.8-27b» (الموديل اللي اشتغل فعلًا) */
function engineHTML(i) {
  const e = i.engine;
  if (!e || !e.stt) return "";
  const short = m => String(m || "").split("/").pop();
  const parts = [e.stt + (e.stt_model ? " · " + short(e.stt_model) : "")];
  if (e.chat) parts.push(e.chat + (e.chat_model ? " · " + short(e.chat_model) : ""));
  const full = [e.stt + (e.stt_model ? " " + e.stt_model : ""), e.chat ? e.chat + " " + (e.chat_model || "") : ""]
    .filter(Boolean).join("  →  ");
  return `<span class="engine" title="${esc(full)}">${esc(parts.join("  →  "))}</span>`;
}

/* ═══════════ تشغيل صوت التسجيل ═══════════ */
const player = { id: null, audio: null };
let playToken = 0;
function paintWave(id) {
  const el = document.querySelector(`.frow[data-id="${id}"] .wave.playable`);
  if (!el) return;
  const a = player.id === id ? player.audio : null;
  const playing = !!a && !a.paused;
  el.classList.toggle("playing", playing);
  el.querySelector(".wave-icon").innerHTML = playing ? ICON.pause : ICON.play;
  el.title = playing ? "إيقاف" : "تشغيل التسجيل";
  const bars = el.querySelectorAll(".wave-bars i");
  const on = a && a.duration ? Math.round(a.currentTime / a.duration * bars.length) : 0;
  bars.forEach((b, k) => b.classList.toggle("on", k < on));
}
function stopPlayer() {
  const id = player.id;
  if (player.audio) player.audio.pause();
  player.id = null;
  player.audio = null;
  if (id != null) paintWave(id);
}
/* مسح صف من السجل لازم يبطل أي تشغيل/تحميل ليه لسه شغّال: بنزوّد التوكن
   عشان الرد الرايح يُهمَل، ونوقف أي Audio شغّال دلوقتي. */
function invalidatePlayback() {
  playToken++;
  stopPlayer();
}
async function togglePlay(id) {
  if (player.id === id && player.audio) {
    return player.audio.paused ? player.audio.play() : player.audio.pause();
  }
  // دوسة تانية سريعة لازم تلغي الرد اللي لسه رايح — كل نداء بياخد توكن،
  // وأي رد توكنه مش آخر واحد بيتهمل (غير كده كان اتنين Audio يشغلوا مع بعض).
  const token = ++playToken;
  stopPlayer();
  const r = await api().history_audio(id);
  if (token !== playToken) return;
  if (!r.ok) return toast("الصوت مش متاح");
  if (!S.history.some(i => i.id === id)) return;   // الصف اتمسح والرد لسه رايح
  stopPlayer();                                  // اتأكد من جديد قبل ما نعمل Audio جديد
  const a = new Audio(`data:${r.mime};base64,${r.data}`);
  player.id = id;
  player.audio = a;
  ["play", "pause", "timeupdate"].forEach(ev => a.addEventListener(ev, () => paintWave(id)));
  a.addEventListener("ended", stopPlayer);
  a.play().catch(() => { stopPlayer(); toast("مقدرتش أشغّل الصوت"); });
}
function histVisible() {
  const q = $("#histSearch").value.trim().toLowerCase();
  return S.history.filter(i => (S.histFilter === "all" || i.mode === S.histFilter)
    && (!q || (i.result || "").toLowerCase().includes(q) || (i.raw || "").toLowerCase().includes(q)));
}
function renderHistory() {
  const items = histVisible();
  const ids = new Set(S.history.map(i => i.id));
  S.histSel.forEach(id => { if (!ids.has(id)) S.histSel.delete(id); });
  let html = "", lastDay = "";
  for (const i of items) {
    const d = parseTime(i.time);
    const k = dayKey(d);
    if (k !== lastDay) {
      if (lastDay) html += `</div>`;
      html += `<div class="flat-title">${esc(dayLabel(d))}</div><div class="flat">`;
      lastDay = k;
    }
    const sel = S.histSel.has(i.id);
    const showRaw = i.raw && i.raw !== i.result;
    html += `<div class="frow${sel ? " selected" : ""}" data-id="${i.id}">
      <label class="check"><input type="checkbox" ${sel ? "checked" : ""}><span></span></label>
      <div class="row-body">
        <div class="row-meta"><span class="r-time">${esc(hhmm(d))}</span><span class="mode-tag"><i class="dot ${esc(i.mode)}"></i>${MODE_LABEL[i.mode] || ""}</span>${engineHTML(i)}</div>
        <div class="row-text">${esc(i.result)}</div>
        ${showRaw ? `<div class="row-raw"><b>الكلام زي ما اتقال</b>${esc(i.raw)}</div>` : ""}
      </div>
      ${waveHTML(i)}
      <div class="row-actions">
        ${i.audio ? `<button class="icon-btn" data-act="dl" title="تنزيل MP3">${ICON.download}</button>` : ""}
        <button class="icon-btn" data-act="copy" title="نسخ">${ICON.copy}</button>
        <button class="icon-btn del" data-act="del" title="مسح">${ICON.trash}</button>
      </div></div>`;
  }
  if (lastDay) html += `</div>`;
  $("#histList").innerHTML = html || `<div class="empty-state show">${S.history.length ? "مفيش نتايج للبحث ده." : "السجل فاضي — أول تسجيل هيظهر هنا."}</div>`;
  if (player.id != null) {
    // التسجيل اللي شغّال اتمسح → يقف؛ وإلا نرجّع شكله بعد ما الصف اتعمل من جديد
    S.history.some(i => i.id === player.id && i.audio) ? paintWave(player.id) : stopPlayer();
  }
  updateBulk();
}
$("#histSearch").addEventListener("input", renderHistory);
$("#histChips").addEventListener("click", e => {
  const c = e.target.closest(".chip");
  if (!c) return;
  S.histFilter = c.dataset.f;
  $$("#histChips .chip").forEach(x => x.classList.toggle("active", x === c));
  renderHistory();
});
$("#histList").addEventListener("click", async e => {
  const row = e.target.closest(".frow");
  if (!row) return;
  const id = Number(row.dataset.id);
  const item = S.history.find(i => i.id === id);
  if (e.target.closest(".check")) {
    if (e.target.tagName !== "INPUT") return;
    e.target.checked ? S.histSel.add(id) : S.histSel.delete(id);
    row.classList.toggle("selected", e.target.checked);
    return updateBulk();
  }
  const act = e.target.closest("[data-act]");
  if (act?.dataset.act === "play") return togglePlay(id);
  if (act?.dataset.act === "dl") {
    const r = await api().history_audio_save(id);
    if (r.ok) toast("اتحفظ ✓");
    else if (!r.cancelled) toast("مقدرتش أحفظ الملف");
    return;
  }
  if (act?.dataset.act === "copy") return copyText(item.result, act);
  if (act?.dataset.act === "del") {
    invalidatePlayback();
    const r = await api().history_delete([id]);
    S.history = r.items; renderStats(r.stats); renderLast(); renderRecent(); renderHistory();
    return toast("اتمسح");
  }
  if (e.target.closest(".row-body") && !window.getSelection().toString()) row.classList.toggle("open");
});
/* ═══════════ شريط التحديد العائم (السجل والحافظة) ═══════════ */
function bulkCtx() {
  if (S.page === "history") return { set: S.histSel, vis: histVisible(), unit: "تسجيل", render: renderHistory };
  if (S.page === "clipboard") return { set: S.clipSel, vis: clipVisible(), unit: "نسخة", render: renderClips };
  return null;
}
function updateBulk() {
  const c = bulkCtx();
  const bar = $("#bulkbar");
  const n = c ? c.set.size : 0;
  bar.hidden = !n;
  if (c && S.page === "clipboard") {
    const visSel = c.vis.filter(x => c.set.has(x.id)).length, box = $("#clipAll");
    box.checked = c.vis.length > 0 && visSel === c.vis.length;
    box.indeterminate = visSel > 0 && visSel < c.vis.length;
  }
  if (!n) return;
  const visSel = c.vis.filter(x => c.set.has(x.id)).length;
  const all = $("#bulkAll");
  all.checked = c.vis.length > 0 && visSel === c.vis.length;
  all.indeterminate = visSel > 0 && visSel < c.vis.length;
  $("#bulkText").textContent = `${num(n)} ${c.unit} متحدد`;
  disarm($("#bulkDel"), "مسح");
}
$("#bulkAll").addEventListener("change", e => {
  const c = bulkCtx(); if (!c) return;
  c.vis.forEach(x => e.target.checked ? c.set.add(x.id) : c.set.delete(x.id));
  c.render();
});
$("#bulkCancel").addEventListener("click", () => {
  const c = bulkCtx(); if (!c) return;
  c.set.clear(); c.render();
});
$("#bulkDel").addEventListener("click", async e => {
  const c = bulkCtx(); if (!c || !c.set.size) return;
  let n = c.set.size;
  // المفضلة في الحافظة مش بتتمسح — بنعدّ اللي هيتمسح فعلًا بس
  const favSel = S.page === "clipboard" ? S.clips.filter(x => x.fav && c.set.has(x.id)).length : 0;
  if (favSel && favSel === n) return toast("المفضلة مش بتتمسح — شيل النجمة الأول");
  n -= favSel;
  if (!armed(e.currentTarget, `تأكيد مسح ${num(n)}`)) return;
  if (S.page === "history") {
    invalidatePlayback();
    const r = await api().history_delete([...S.histSel]);
    S.histSel.clear();
    S.history = r.items; renderStats(r.stats); renderLast(); renderRecent(); renderChart(); renderHistory();
  } else {
    S.clips = await api().clips_delete([...S.clipSel]);
    S.clipSel.clear();
    fillClipApps(); renderClips();
  }
  toast(`اتمسح ${num(n)} ${c.unit}` + (favSel ? ` · ${num(favSel)} مفضّلة فضلت` : ""));
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("#bulkbar").hidden) $("#bulkCancel").click();
});

/* زرار المسح بيتطلب دوستين: الأولى «تأكيد»، التانية تمسح فعلًا (من غير نوافذ تأكيد) */
function armed(btn, confirmText) {
  if (btn.dataset.armed === "1") { disarm(btn); return true; }
  btn.dataset.armed = "1";
  btn.classList.add("confirm");
  const label = btn.querySelector("span") || btn;
  btn.dataset.orig = btn.dataset.orig || label.textContent;
  setLabel(btn, confirmText);
  clearTimeout(btn._t);
  btn._t = setTimeout(() => disarm(btn), 3500);
  return false;
}
function disarm(btn, text) {
  btn.dataset.armed = "";
  btn.classList.remove("confirm");
  if (text || btn.dataset.orig) setLabel(btn, text || btn.dataset.orig);
}
function setLabel(btn, text) {
  const span = btn.querySelector("span");
  if (span) span.textContent = text;
  else btn.lastChild.textContent = text;
}

/* ═══════════ الحافظة ═══════════ */
// قيمة فلتر «المفضلة» في قايمة البرامج — أسماء البرامج (chrome.exe…) عمرها ما فيها ★
const CLIP_FAV = "★fav";
async function loadClips() {
  S.clips = await api().clips();
  fillClipApps();
  renderClips();
}
function fillClipApps() {
  const sel = $("#clipApp");
  const cur = sel.value;
  const apps = [...new Set(S.clips.map(c => c.source).filter(Boolean))].sort();
  const favs = S.clips.filter(c => c.fav).length;
  sel.innerHTML = `<option value="">كل البرامج</option>`
    + `<option value="${CLIP_FAV}">⭐ المفضلة${favs ? ` (${num(favs)})` : ""}</option>`
    + apps.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join("");
  if (cur === CLIP_FAV || apps.includes(cur)) sel.value = cur;
  $("#navClipCount").textContent = S.clips.length ? num(S.clips.length) : "";
}
function clipVisible() {
  const q = $("#clipSearch").value.trim().toLowerCase();
  const app = $("#clipApp").value;
  const days = $("#clipDate").value;
  let since = 0;
  if (days !== "all") {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - (Number(days) - 1));
    since = d.getTime();
  }
  return S.clips.filter(c => (!q || c.text.toLowerCase().includes(q))
    && (!app || (app === CLIP_FAV ? c.fav : c.source === app)) && (!since || parseTime(c.time).getTime() >= since));
}
function renderClips() {
  const all = clipVisible();
  const items = all.slice(0, S.clipLimit);
  const ids = new Set(S.clips.map(c => c.id));
  S.clipSel.forEach(id => { if (!ids.has(id)) S.clipSel.delete(id); });
  $("#clipBody").innerHTML = items.map(c => {
    const sel = S.clipSel.has(c.id);
    return `<tr data-id="${c.id}" class="${sel ? "selected" : ""}">
      <td><label class="check"><input type="checkbox" ${sel ? "checked" : ""}><span></span></label></td>
      <td class="c-fav"><button class="icon-btn fav${c.fav ? " on" : ""}" data-act="fav" aria-pressed="${c.fav ? "true" : "false"}"
        title="${c.fav ? "شيل من المفضلة" : "ضيف للمفضلة — مش هتتمسح"}">${ICON.star}</button></td>
      <td><div class="clip-text" title="دوسة تفتح النص كله">${esc(c.text.length > 4000 ? c.text.slice(0, 4000) + "…" : c.text)}</div></td>
      <td>${c.source ? `<span class="app-tag" title="${esc(c.source)}">${esc(c.source)}</span>` : `<span class="muted">—</span>`}</td>
      <td class="t-time">${esc(shortTime(parseTime(c.time)))}</td>
      <td><div class="t-actions">
        <button class="icon-btn" data-act="copy" title="نسخ تاني">${ICON.copy}</button>
        <button class="icon-btn del" data-act="del" ${c.fav ? 'disabled title="المفضلة مش بتتمسح — شيل النجمة الأول"' : 'title="مسح"'}>${ICON.trash}</button>
      </div></td></tr>`;
  }).join("");
  $("#clipEmpty").classList.toggle("show", !items.length);
  $("#clipEmpty").textContent = S.clips.length ? "مفيش نسخ بالفلتر ده." : "مفيش نسخ لسه — انسخ أي نص في أي برنامج وهيظهر هنا.";
  $("#clipCount").textContent = all.length === S.clips.length
    ? `${num(S.clips.length)} نسخة` : `${num(all.length)} من ${num(S.clips.length)} نسخة`;
  $("#clipMore").hidden = all.length <= S.clipLimit;
  updateBulk();
}
["input", "change"].forEach(ev => {
  $("#clipSearch").addEventListener(ev, () => { S.clipLimit = 200; renderClips(); });
  $("#clipApp").addEventListener(ev, () => { S.clipLimit = 200; renderClips(); });
  $("#clipDate").addEventListener(ev, () => { S.clipLimit = 200; renderClips(); });
});
$("#clipMore").addEventListener("click", () => { S.clipLimit += 200; renderClips(); });
$("#clipAll").addEventListener("change", e => {
  clipVisible().forEach(c => e.target.checked ? S.clipSel.add(c.id) : S.clipSel.delete(c.id));
  renderClips();
});
$("#clipBody").addEventListener("click", async e => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  const id = Number(tr.dataset.id);
  const clip = S.clips.find(c => c.id === id);
  if (e.target.closest(".check")) {
    if (e.target.tagName !== "INPUT") return;
    e.target.checked ? S.clipSel.add(id) : S.clipSel.delete(id);
    tr.classList.toggle("selected", e.target.checked);
    return updateBulk();
  }
  const act = e.target.closest("[data-act]");
  if (act?.dataset.act === "copy") return copyText(clip.text, act);
  if (act?.dataset.act === "fav") {
    const r = await api().clips_fav(id, !clip.fav);
    if (!r || !r.ok) return toast((r && r.err) || "مقدرتش أغيّر المفضلة");
    S.clips = r.items;
    fillClipApps(); renderClips();
    return toast(clip.fav ? "اتشالت من المفضلة" : "اتضافت للمفضلة ⭐");
  }
  if (act?.dataset.act === "del") {
    if (clip.fav) return toast("المفضلة مش بتتمسح — شيل النجمة الأول");
    S.clips = await api().clips_delete([id]);
    fillClipApps(); renderClips();
    return toast("اتمسح");
  }
  if (e.target.closest(".clip-text") && !window.getSelection().toString()) tr.classList.toggle("open");
});
$("#clipToggle").addEventListener("change", async e => {
  const r = await api().save_settings({ clipboard_history: e.target.checked });
  if (r.ok) { S.boot = r.boot; toast(e.target.checked ? "حفظ النسخ اشتغل" : "حفظ النسخ اتقفل"); }
});

/* ═══════════ القاموس ═══════════ */
function renderDict() {
  const words = S.boot.cfg.dictionary || [];
  $("#dictCount").textContent = `${num(words.length)} كلمة`;
  $("#dictList").innerHTML = words.length
    ? words.map((w, i) => `<span class="word">${esc(w)}<button data-i="${i}" title="مسح">${ICON.x}</button></span>`).join("")
    : `<div class="dict-empty">القاموس فاضي. ضيف الأسماء والمصطلحات اللي الموديل بيغلط فيها.</div>`;
}
async function saveDict(words) {
  S.boot.cfg.dictionary = await api().dictionary_set(words);
  renderDict();
}
$("#dictForm").addEventListener("submit", async e => {
  e.preventDefault();
  const inp = $("#dictInput");
  const parts = inp.value.split(/[،,\n]/).map(s => s.trim()).filter(Boolean);
  if (!parts.length) return;
  const words = S.boot.cfg.dictionary || [];
  const before = words.length;
  await saveDict([...words, ...parts]);
  inp.value = "";
  inp.focus();
  if (S.boot.cfg.dictionary.length === before) toast("الكلمة موجودة بالفعل");
});
$("#dictList").addEventListener("click", e => {
  const b = e.target.closest("button[data-i]");
  if (!b) return;
  const words = [...(S.boot.cfg.dictionary || [])];
  words.splice(Number(b.dataset.i), 1);
  saveDict(words);
});

/* ═══════════ الاختصارات الصوتية F8 ═══════════ */
function snippetRowHTML(sn, i) {
  const flat = String(sn.text || "").replace(/\s+/g, " ").trim();
  const preview = flat.length > 40 ? flat.slice(0, 40) + "…" : flat;
  return `<div class="snip-row" data-i="${i}">
    <span class="snip-trigger">${esc(sn.trigger)}</span>
    <span class="snip-text">${esc(preview)}</span>
    <button class="icon-btn snip-edit" type="button" title="تعديل">${ICON.edit}</button>
    <button class="icon-btn del snip-del" type="button" title="مسح">${ICON.x}</button>
  </div>`;
}
function renderSnippets() {
  const list = S.boot.cfg.snippets || [];
  $("#snipList").innerHTML = list.length
    ? list.map(snippetRowHTML).join("")
    : `<div class="dict-empty">مفيش اختصارات لسه. ضيف جملة قصيرة والنص اللي بيتكتب مكانها.</div>`;
}
function snipFormReset() {
  S.snipEditKey = null;
  $("#snipInput").value = "";
  $("#snipText").value = "";
  $("#snipAddBtn").textContent = "إضافة";
}
/* N6: سلسلة حفظ الاختصارات — التعديلات بتتنفّذ واحدة واحدة، وكل تعديل بيقرا
   القايمة اللي رجّعها آخر حفظ ناجح (S.boot.cfg.snippets) مش القايمة القديمة
   وقت الدوسة. كده حذفين متتاليين سريعين عمرهم ما يرجّعوا اختصار اتمسح. */
let snipChain = Promise.resolve();
function queueSnippetMutation(mutator) {
  // .catch: لو حفظ فشل، السلسلة متقفش — غير كده كل تعديل بعده كان بيتجاهل بصمت
  const done = snipChain.then(async () => {
    const next = mutator([...(S.boot.cfg.snippets || [])]);
    if (!next) return false;
    const r = await api().snippets_set(next);
    if (!Array.isArray(r)) {                       // رفض من الحفظ (زي مفتاح متكرر)
      toast((r && r.err) || "مقدرتش أحفظ الاختصارات — جرّب تاني");
      return false;
    }
    S.boot.cfg.snippets = r;
    renderSnippets();
    return true;
  }).catch(() => { toast("مقدرتش أحفظ الاختصارات — جرّب تاني"); renderSnippets(); return false; });
  snipChain = done;
  return done;
}
// التعديلات بتمسك الاختصار بمفتاحه (trigger) مش برقم الصف: الطابور بيتنفّذ على القايمة
// بعد آخر حفظ، فرقم صف اتقرا قبل حذف سابق ممكن يشاور على اختصار تاني خالص
const snipIndex = (items, key) => items.findIndex(s => s.trigger === key);
$("#snipForm").addEventListener("submit", e => {
  e.preventDefault();
  const trigger = $("#snipInput").value.trim();
  const text = $("#snipText").value;
  if (!trigger || !text.trim()) return;
  const editKey = S.snipEditKey;
  queueSnippetMutation(items => {
    const i = editKey == null ? -1 : snipIndex(items, editKey);
    if (i >= 0) items[i] = { trigger, text };
    else items.push({ trigger, text });
    return items;
  }).then(ok => {
    // الفورم بيتفضّى بس لما الحفظ ينجح — لو اترفض، المستخدم ميخسرش اللي كتبه
    if (ok) snipFormReset();
    $("#snipInput").focus();
  });
});
$("#snipList").addEventListener("click", e => {
  const row = e.target.closest(".snip-row");
  if (!row) return;
  const sn = (S.boot.cfg.snippets || [])[Number(row.dataset.i)];
  if (!sn) return;
  if (e.target.closest(".snip-del")) {
    const key = sn.trigger;
    queueSnippetMutation(items => {
      const i = snipIndex(items, key);
      if (i < 0) return null;                 // اتمسح قبل كده
      items.splice(i, 1);
      return items;
    });
    if (S.snipEditKey === key) snipFormReset();
    return;
  }
  if (e.target.closest(".snip-edit")) {
    S.snipEditKey = sn.trigger;
    $("#snipInput").value = sn.trigger;
    $("#snipText").value = sn.text;
    $("#snipAddBtn").textContent = "حفظ";
    $("#snipInput").focus();
  }
});

/* ═══════════ الإعدادات ═══════════ */
function provCards(container, onPick) {
  container.innerHTML = S.boot.providers.map(p => `
    <button type="button" class="prov${p.id === S.provider ? " active" : ""}" data-p="${p.id}">
      <span class="prov-top"><span class="prov-name">${esc(p.name)}</span><span class="prov-tag">${esc(p.tag)}</span></span>
      <span class="prov-desc">${esc(p.desc)}</span>
      <span class="prov-key${p.hasKey ? "" : " no"}">${p.hasKey ? "✓ المفتاح محفوظ" : "مفيش مفتاح"}</span>
    </button>`).join("");
  container.onclick = e => {
    const b = e.target.closest(".prov");
    if (!b) return;
    S.provider = b.dataset.p;
    $$(".prov", container).forEach(x => x.classList.toggle("active", x === b));
    onPick && onPick();
  };
}
function curProv() { return S.boot.providers.find(p => p.id === S.provider) || S.boot.providers[0]; }

/* ── دليل المفتاح لكل مزوّد ── */
function renderGuide(el, p) {
  const g = p.guide || {};
  el.innerHTML = `
    <summary><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 0 1 4.8 1c0 1.7-2.4 2.2-2.4 3.5"/><path d="M12 17h.01"/></svg>
      <span>إزاي أجيب مفتاح</span> <bdi class="g-name">${esc(p.name)}</bdi>${g.free ? `<span class="g-free">${esc(g.free)}</span>` : ""}</summary>
    <ol>${(g.steps || []).map(s => `<li>${esc(s)}</li>`).join("")}</ol>
    <div class="g-links">
      <button type="button" class="ghost-btn" data-url="${esc(p.keyUrl)}">صفحة المفاتيح ↗</button>
      ${g.docs ? `<button type="button" class="ghost-btn" data-url="${esc(g.docs)}">التوثيق ↗</button>` : ""}
    </div>`;
  el.onclick = e => { const b = e.target.closest("[data-url]"); if (b) api().open_url(b.dataset.url); };
}
function fillSelect(sel, list, value) {
  sel.innerHTML = list.map(o => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join("");
  sel.value = value ?? "";
}

/* ── الميزات الأربعة: زرار + قايمة تفريغ + قايمة معالجة لكل ميزة ──
   S.features نسخة بنعدّل فيها لحد «حفظ»؛ كل قايمة بتتجرّب بالترتيب (البديل لو اللي قبله فشل) */
const FEAT_DESC = {
  normal: "بيكتب كلامك زي ما هو بعد التنظيف",
  prompt: "بيرتّب كلامك كطلب واضح للـAI",
  translate: "عربي ← إنجليزي والعكس",
  edit: "حدّد نص، دوس الزرار، واتكلم بالتعليمات — إملاء يعدّل التحديد",
};
const AI_EMPTY = {
  normal: "مفيش معالجة — الكلام بيتكتب زي ما اتقال",
  prompt: "مفيش موديل — الكلام بيتكتب زي ما اتقال من غير تحويل",
  translate: "مفيش موديل — الكلام بيتكتب زي ما اتقال من غير تحويل",
  edit: "مفيش موديل — التعديل مش هيشتغل لحد ما تضيف واحد",
};
const LOCAL = "local";
const CAPTURE_WAIT = "دوس الزرار دلوقتي… (Esc للإلغاء)";

function feat() { return S.features[S.feat]; }
function catalog(pid) { return (S.boot.catalog || {})[pid] || {}; }
function chainModels(kind, pid) {
  const c = catalog(pid);
  return (kind === "stt" ? c.sttModels : c.chatModels) || [];
}
// اللي ينفع يتختار في القايمة: المعالجة بمزوّد بيكتب بس، والمحلي للتفريغ بس (ومش في نسخة الـStore)
function chainProviders(kind, current) {
  return Object.keys(S.boot.catalog || {}).filter(pid => {
    if (pid === LOCAL) return kind === "stt" && (!S.boot.offline?.packaged || current === LOCAL);
    return kind === "stt" || !catalog(pid).sttOnly;
  });
}
function chainWarn(item) {
  if (item.provider === LOCAL) return catalog(LOCAL).installed ? "" : "مش متثبّت — نزّله من تحت";
  return catalog(item.provider).hasKey ? "" : "مفيش مفتاح";
}
function chainRowHTML(kind, item, i, n, canRemove) {
  const provs = chainProviders(kind, item.provider).map(pid =>
    `<option value="${esc(pid)}"${pid === item.provider ? " selected" : ""}>${esc(catalog(pid).name || pid)}</option>`).join("");
  let models = "";
  if (item.provider !== LOCAL) {
    const list = chainModels(kind, item.provider).slice();
    if (item.model && !list.includes(item.model)) list.unshift(item.model);   // الموديل المحفوظ دايمًا ظاهر
    models = `<select class="select chain-model">${list.map(m =>
      `<option value="${esc(m)}"${m === item.model ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>`;
  } else {
    const inst = catalog(LOCAL).installed;
    models = `<span class="chain-local">${inst ? esc(inst) : ""}</span>`;
  }
  const warn = chainWarn(item);
  return `<div class="chain-row" data-i="${i}">
    <span class="chain-n">${i + 1}</span>
    <select class="select chain-prov">${provs}</select>
    ${models}
    ${warn ? `<span class="chain-warn">${esc(warn)}</span>` : ""}
    <span class="chain-acts">
      <button class="icon-btn chain-up" type="button" title="لفوق"${i === 0 ? " disabled" : ""}>${ICON.up}</button>
      <button class="icon-btn chain-down" type="button" title="لتحت"${i === n - 1 ? " disabled" : ""}>${ICON.down}</button>
      <button class="icon-btn del chain-del" type="button" title="حذف"${canRemove ? "" : " disabled"}>${ICON.x}</button>
    </span>
  </div>`;
}
function renderChain(kind) {
  const list = feat()[kind];
  // التفريغ لازم يفضل فيه عنصر؛ المعالجة ممكن تفضى (اختيار خصوصية)
  const minLen = kind === "stt" ? 1 : 0;
  const box = $(kind === "stt" ? "#sttList" : "#aiList");
  box.innerHTML = list.length
    ? list.map((it, i) => chainRowHTML(kind, it, i, list.length, list.length > minLen)).join("")
    : `<div class="chain-empty">${AI_EMPTY[S.feat]}</div>`;
}
function renderFeat() {
  const f = feat();
  $$("#featTabs [data-feat]").forEach(b => b.classList.toggle("active", b.dataset.feat === S.feat));
  $("#featDesc").textContent = FEAT_DESC[S.feat];
  $("#hkLabel").textContent = S.capturing ? CAPTURE_WAIT : (f.label || "—");
  $("#hkLabel").classList.toggle("wait", !!S.capturing);
  $("#hkClear").disabled = !!S.capturing || !f.hotkey.length;
  $("#aiHint").textContent = S.feat === "normal"
    ? "التنظيف والتصحيح — لو شلت كل الموديلات الكلام بيتكتب زي ما اتقال"
    : "بيتجرّب بالترتيب — من غير موديل الميزة دي مبتحوّلش الكلام";
  renderChain("stt");
  renderChain("ai");
}
// عنصر جديد: أول مزوّد/موديل مش في القايمة — المزوّدين اللي ليهم مفتاح الأول
function newChainItem(kind) {
  const list = feat()[kind];
  const provs = chainProviders(kind).filter(p => p !== LOCAL || catalog(LOCAL).installed);
  provs.sort((a, b) => Number(!!catalog(b).hasKey || b === LOCAL) - Number(!!catalog(a).hasKey || a === LOCAL));
  const options = provs.flatMap(pid => pid === LOCAL ? [{ provider: LOCAL, model: "" }]
    : chainModels(kind, pid).map(model => ({ provider: pid, model })));
  return options.find(o => !list.some(x => x.provider === o.provider && x.model === o.model)) || options[0];
}
function chainEdit(kind, e) {
  const row = e.target.closest(".chain-row");
  if (!row) return;
  const list = feat()[kind], i = Number(row.dataset.i);
  if (e.type === "change") {
    if (e.target.classList.contains("chain-prov")) {
      const pid = e.target.value;
      list[i] = { provider: pid, model: pid === LOCAL ? "" : (chainModels(kind, pid)[0] || "") };
    } else if (e.target.classList.contains("chain-model")) {
      list[i].model = e.target.value;
    }
  } else if (e.target.closest(".chain-up") && i > 0) {
    [list[i - 1], list[i]] = [list[i], list[i - 1]];
  } else if (e.target.closest(".chain-down") && i < list.length - 1) {
    [list[i + 1], list[i]] = [list[i], list[i + 1]];
  } else if (e.target.closest(".chain-del")) {
    list.splice(i, 1);
  } else {
    return;
  }
  renderChain(kind);
  scheduleSave();
}
["stt", "ai"].forEach(kind => {
  const box = $(kind === "stt" ? "#sttList" : "#aiList");
  box.addEventListener("change", e => chainEdit(kind, e));
  box.addEventListener("click", e => chainEdit(kind, e));
  $(kind === "stt" ? "#sttAdd" : "#aiAdd").addEventListener("click", () => {
    const item = newChainItem(kind);
    if (!item) return;
    feat()[kind].push({ ...item });
    renderChain(kind);
    scheduleSave();
  });
});
$("#featTabs").addEventListener("click", e => {
  const b = e.target.closest("[data-feat]");
  if (!b || S.capturing) return;
  S.feat = b.dataset.feat;
  renderFeat();
});

/* ── تسجيل الزرار من الكيبورد ── النتيجة بتروح للميزة اللي طلبت (r.feature) */
function setCapturing(on) {
  S.capturing = on;
  $$("#featTabs [data-feat], #hkRec1, #hkRec2").forEach(b => { b.disabled = on; });
  renderFeat();
}
async function captureHotkey(count) {
  setCapturing(true);
  let r;
  try { r = await api().capture_hotkey(S.feat, count); }
  catch (e) { r = { ok: false, err: "مقدرتش أسجّل الزرار — جرّب تاني" }; }
  if (r && r.ok) Object.assign(S.features[r.feature], { hotkey: r.keys, label: r.label });
  setCapturing(false);
  if (r && r.ok) scheduleSave(0);
  if (!r || !r.ok) toast((r && r.err) || "مقدرتش أسجّل الزرار — جرّب تاني");
}
$("#hkRec1").addEventListener("click", () => captureHotkey(1));
$("#hkRec2").addEventListener("click", () => captureHotkey(2));
$("#hkClear").innerHTML = ICON.x;
$("#hkClear").addEventListener("click", () => {
  Object.assign(feat(), { hotkey: [], label: "" });
  renderFeat();
  scheduleSave();
});

/* ── أساليب السياق F5: override لكل برنامج (اسم exe بدون امتداد ← dev/chat/formal) ── */
const STYLE_OPTS = [["dev", "تطوير"], ["chat", "شات"], ["formal", "رسمي"]];
function styleRowHTML(exe, prof) {
  const opts = STYLE_OPTS.map(([v, ar]) => `<option value="${v}"${v === prof ? " selected" : ""}>${ar}</option>`).join("");
  return `<div class="style-row">
    <input class="input style-exe" value="${esc(exe)}" placeholder="اسم البرنامج" maxlength="60" autocomplete="off">
    <select class="select style-prof">${opts}</select>
    <button class="icon-btn del style-del" type="button" title="حذف">${ICON.x}</button>
  </div>`;
}
function renderStyleRows() {
  const rows = S.boot.cfg.app_profiles || {};
  const keys = Object.keys(rows);
  $("#styleList").innerHTML = keys.length
    ? keys.map(k => styleRowHTML(k, rows[k])).join("")
    : `<div class="dict-empty">مفيش استثناءات — البرامج المعروفة (VS Code، واتساب، Outlook…) ليها أسلوب جاهز.</div>`;
  $("#styleBox").hidden = !S.boot.cfg.context_styles;
}
function collectStyles() {
  const out = {};
  $$("#styleList .style-row").forEach(r => {
    const exe = r.querySelector(".style-exe").value.trim().toLowerCase();
    const prof = r.querySelector(".style-prof").value;
    if (exe && prof) out[exe] = prof;
  });
  return out;
}
/* ── التفريغ من غير إنترنت (F9) ── */
// keepForm: تحديث الحالة بس (بعد تنزيل/إزالة) — الموديل اللي المستخدم اختاره ولسه
// ماحفظهوش بيفضل زي ما هو
function renderOffline(keepForm) {
  const o = S.offline;
  if (!o) return;
  const packaged = !!(S.boot.offline && S.boot.offline.packaged);
  $("#offlineHead").hidden = packaged;
  $("#offlineBox").hidden = packaged;
  if (packaged) return;
  const installed = o.installed;
  const sz = installed ? ((o.models || []).find(m => m.id === installed) || {}).size : null;
  // T20: الموديل اتلف (الفحص رجّع false) — نعرض حالة «بايظ» مع إبقاء زرار الإزالة متاح
  $("#offlineStatus").textContent = o.verified === false
    ? "الموديل بايظ — شيله ونزّله تاني"
    : (installed ? `مثبّت: ${installed}، ${sz} MB` : "الموديل مش متثبّت");
  $("#offlineRemove").disabled = !installed && !o.residual;
  const prevModel = $("#offlineModel").value;
  $("#offlineModel").innerHTML = (o.models || []).map(m =>
    `<option value="${esc(m.id)}">${esc(m.id)} ≈ ${m.size} MB — ${OFFLINE_MODEL_LABEL[m.id] || ""}</option>`).join("");
  if (keepForm && (o.models || []).some(m => m.id === prevModel)) {
    $("#offlineModel").value = prevModel;
    return;
  }
  $("#offlineModel").value = (o.model && (o.models || []).some(m => m.id === o.model)) ? o.model : (installed || "small-q5_1");
}
async function refreshOffline(keepForm) {
  S.offline = await api().offline_status();
  renderOffline(keepForm);
}
function setOfflineDownloading(on) {
  $("#offlineDownload").disabled = on;
  $("#offlineBar").hidden = !on;
  $("#offlineBar i").style.width = "0%";
  $("#offlineDownloadNote").textContent = on ? "بينزّل… 0%" : "بيتنزّل مرة واحدة ويتخزّن على جهازك";
}
$("#offlineDownload").addEventListener("click", async () => {
  const model = $("#offlineModel").value;
  // حالة «بينزّل» قبل النداء: onOfflineDone ممكن يوصل قبل ما الـpromise يرجع (فشل
  // فوري)، ولو علّمناها بعده كان الزرار بيفضل مقفول للأبد ومفيش حدث تاني جاي
  setOfflineDownloading(true);
  let r;
  try {
    r = await api().offline_download(model);
  } catch (e) {
    r = { ok: false };
  }
  if (!r.ok) { setOfflineDownloading(false); toast(r.err || "مقدرتش أنزّل الموديل"); }
});
$("#offlineRemove").addEventListener("click", async () => {
  await api().offline_remove();
  refreshOffline(true);
  refreshCatalog();       // لو المحلي كان الوحيد اللي بيفرّغ، البرنامج مبقاش يقدر يشتغل
  toast("اتشال الموديل");
});

function fillSettings() {
  const c = S.boot.cfg;
  S.features = JSON.parse(JSON.stringify(S.boot.features));
  S.feat = S.feat || "normal";
  S.capturing = false;
  renderFeat();
  renderKeysSection();
  refreshKeyPools();
  fillSelect($("#hkOpen"), S.boot.openHotkeys, c.open_hotkey || "");
  $("#recMode").value = c.mode === "hold" ? "hold" : "toggle";
  $("#sInsert").value = c.insert_method === "auto" || c.insert_method === "paste" ? c.insert_method : "type";
  $("#sTheme").value = c.theme || "dark";
  $("#sLang").value = c.lang === "en" ? "en" : "ar";
  $("#sKeep10").checked = !!c.history_keep_last10;
  $("#sTheme").onchange = e => applyTheme(e.target.value);      // معاينة فورية قبل الحفظ
  const sw = { sPolish: "polish", sStyle: "context_styles", sPaste: "auto_paste", sTray: "minimize_to_tray", sFloat: "floating_button",
                sClip: "clipboard_history", sBeep: "beep", sUpd: "check_updates", sAutoUpd: "auto_update" };
  Object.entries(sw).forEach(([id, k]) => { $("#" + id).checked = !!c[k]; });
  renderStyleRows();
  $("#saveMsg").textContent = "";
  $("#saveMsg").className = "save-msg";
  refreshOffline();
}
// المفاتيح أو الموديل المحلي اتغيّروا: الكتالوج (مين ليه مفتاح) بيتحدّث من غير ما نلمس
// تعديلات الميزات اللي لسه ماتحفظتش
async function refreshCatalog() {
  await refreshBoot();
  if (S.page === "settings" && S.features) renderFeat();
}

/* ═══════════ المفاتيح: مجمّعة لكل مزوّد، مشتركة بين كل الميزات (Task 24) ═══════════ */
const KEY_BADGE = { active: "🟢 نشط", rate_limited: "🔴 نفدت الكوتا مؤقتاً", invalid: "⚠️ غير صالح" };
let keyPoolTimer = null;

function keyBlock(pid) { return $(`#keysSection .key-block[data-pid="${pid}"]`); }
function renderKeysSection() {
  $("#keysSection").innerHTML = S.boot.providers.map(p => `
    <div class="srow srow-stack key-block" data-pid="${esc(p.id)}">
      <span class="srow-text"><b>${esc(p.name)} <span class="prov-tag">${esc(p.tag)}</span></b><small>${esc(p.keyHint)}</small></span>
      <div class="key-pool">
        <div class="key-list"></div>
        <button class="ghost-btn key-add" type="button">+ إضافة مفتاح</button>
        <div class="key-add-row" hidden>
          <div class="key-add-line">
            <input class="input key-add-input" type="password" placeholder="الصق المفتاح هنا" autocomplete="off" spellcheck="false">
            <button class="cta cta-sm key-add-go" type="button">تحقق وأضف</button>
            <button class="ghost-btn key-add-cancel" type="button">إلغاء</button>
          </div>
          <div class="key-add-err" hidden></div>
        </div>
      </div>
      <details class="guide"></details>
    </div>`).join("");
  S.boot.providers.forEach(p => renderGuide($(".guide", keyBlock(p.id)), p));
}
function keyBadgeHTML(st, retryIn) {
  const label = KEY_BADGE[st] || KEY_BADGE.active;
  // الوقت المتبقي في title بس — النص الظاهر لسه قابل للترجمة
  const title = st === "rate_limited" && retryIn != null ? `⏱ ${Math.max(0, Math.round(retryIn))}s` : "";
  return `<span class="key-badge ${esc(st)}"${title !== "" ? ` title="${title}"` : ""}>${label}</span>`;
}
function renderKeyPool(pid) {
  const block = keyBlock(pid);
  if (!block) return;
  const keys = S.keyPools[pid] || [];
  $(".key-add", block).textContent = keys.length ? "+ إضافة مفتاح إضافي" : "+ إضافة مفتاح";
  $(".key-list", block).innerHTML = keys.length ? keys.map(k => `
    <div class="key-item" data-i="${k.index}" data-id="${esc(k.id)}">
      <span class="key-val" data-masked="${esc(k.masked)}">${esc(k.masked)}</span>
      ${keyBadgeHTML(k.status, k.retryIn)}
      <span class="key-acts">
        <button class="icon-btn" data-act="reveal" title="إظهار المفتاح">${ICON.eye}</button>
        <button class="icon-btn del" data-act="remove" title="مسح">${ICON.trash}</button>
      </span>
    </div>`).join("") : `<div class="key-empty">مفيش مفاتيح محفوظة للمزوّد ده</div>`;
}
function applyKeyPool(pid, r) {
  S.keyPools[pid] = (r && r.keys) || [];
  renderKeyPool(pid);
}
// soft (تحديث الحالة الدوري): لو القايمة نفسها متغيّرتش بنحدّث الشارات بس — إعادة رسم
// كاملة كانت بتخفي المفتاح المعروض وبتلغي «متأكد؟» في نص التأكيد
function softKeyPool(pid, r) {
  const keys = (r && r.keys) || [];
  const block = keyBlock(pid);
  const rows = block ? $$(".key-item", block) : [];
  const same = rows.length === keys.length && keys.every((k, i) => rows[i].dataset.id === k.id);
  if (!same) { applyKeyPool(pid, r); return; }
  S.keyPools[pid] = keys;
  keys.forEach((k, i) => { rows[i].querySelector(".key-badge").outerHTML = keyBadgeHTML(k.status, k.retryIn); });
}
async function refreshKeyPools(soft = false) {
  await Promise.all(S.boot.providers.map(async p => {
    const r = await api().key_pool(p.id);
    if (soft) softKeyPool(p.id, r); else applyKeyPool(p.id, r);
  }));
}
function startKeyPoolTimer() {
  stopKeyPoolTimer();
  keyPoolTimer = setInterval(() => { if (S.page === "settings") refreshKeyPools(true); }, 15000);
}
function stopKeyPoolTimer() {
  if (keyPoolTimer) { clearInterval(keyPoolTimer); keyPoolTimer = null; }
}
function keyTrashDisarm(btn) {
  btn.dataset.armed = "";
  btn.classList.remove("confirm");
  if (btn.dataset.orig) { btn.innerHTML = btn.dataset.orig; delete btn.dataset.orig; }
}
function collapseKeyAdd(block) {
  $(".key-add-row", block).hidden = true;
  const err = $(".key-add-err", block);
  err.hidden = true; err.textContent = "";
  $(".key-add-input", block).value = "";
}
async function keyAddGo(block) {
  const pid = block.dataset.pid;
  const key = $(".key-add-input", block).value.trim();
  if (!key) return;
  const btn = $(".key-add-go", block), errEl = $(".key-add-err", block);
  btn.disabled = true;
  btn.textContent = "بيتأكد…";
  errEl.hidden = true;
  let r;
  try { r = await api().key_add(pid, key); }
  catch (e) { r = { ok: false, err: "مقدرتش أضيف المفتاح" }; }
  btn.disabled = false;
  btn.textContent = "تحقق وأضف";
  if (!r || !r.ok) {
    errEl.textContent = (r && r.err) || "مقدرتش أضيف المفتاح";
    errEl.hidden = false;
    return;
  }
  collapseKeyAdd(block);
  applyKeyPool(pid, r);
  refreshCatalog();
  toast("اتضاف المفتاح ✓");
}
async function keyItemAction(block, act, item) {
  const pid = block.dataset.pid;
  const i = Number(item.dataset.i);
  // بصمة المفتاح اللي في الصف: السيرفر بيرفض لو الفهرس بقى بيشاور على مفتاح تاني
  const id = item.dataset.id;
  if (act.dataset.act === "reveal") {
    const val = item.querySelector(".key-val");
    if (val.dataset.revealed === "1") {
      val.textContent = val.dataset.masked;
      delete val.dataset.revealed;
      act.innerHTML = ICON.eye;
      act.title = "إظهار المفتاح";
      return;
    }
    const r = await api().key_reveal(pid, i, id);
    if (!r || !r.ok) { toast((r && r.err) || "مقدرتش أعرض المفتاح"); refreshKeyPools(); return; }
    val.textContent = r.key;
    val.dataset.revealed = "1";
    act.innerHTML = ICON.eyeOff;
    act.title = "إخفاء المفتاح";
    return;
  }
  if (act.dataset.armed !== "1") {
    act.dataset.armed = "1";
    act.classList.add("confirm");
    act.dataset.orig = act.innerHTML;
    act.innerHTML = "<span>متأكد؟</span>";
    clearTimeout(act._t);
    act._t = setTimeout(() => keyTrashDisarm(act), 3000);
    return;
  }
  keyTrashDisarm(act);
  const r = await api().key_remove(pid, i, id);
  if (!r || !r.ok) { toast((r && r.err) || "مقدرتش أمسح المفتاح"); refreshKeyPools(); return; }
  applyKeyPool(pid, r);
  refreshCatalog();
}
$("#keysSection").addEventListener("click", e => {
  const block = e.target.closest(".key-block");
  if (!block) return;
  if (e.target.closest(".key-add")) {
    $(".key-add-row", block).hidden = false;
    $(".key-add-input", block).focus();
  } else if (e.target.closest(".key-add-cancel")) {
    collapseKeyAdd(block);
  } else if (e.target.closest(".key-add-go")) {
    keyAddGo(block);
  } else {
    const act = e.target.closest("[data-act]"), item = e.target.closest(".key-item");
    if (act && item) keyItemAction(block, act, item);
  }
});
$("#sStyle").addEventListener("change", e => { $("#styleBox").hidden = !e.target.checked; });
$("#styleAdd").addEventListener("click", () => {
  const empty = $("#styleList .dict-empty");
  if (empty) empty.remove();
  const wrap = document.createElement("div");
  wrap.innerHTML = styleRowHTML("", "dev");
  const row = wrap.firstElementChild;
  $("#styleList").appendChild(row);
  row.querySelector(".style-exe").focus();
});
$("#styleList").addEventListener("click", e => {
  const b = e.target.closest(".style-del");
  if (!b) return;
  b.closest(".style-row").remove();
  scheduleSave();
  // آخر صف اتشال: اعرض placeholder فاضي من غير ما تعيد البناء من S.boot.cfg —
  // (renderStyleRows كانت هترجّع الاستثناء المحذوف تاني، فما كنش ممكن يتشال)
  if (!$("#styleList .style-row")) {
    $("#styleList").innerHTML = `<div class="dict-empty">مفيش استثناءات — البرامج المعروفة (VS Code، واتساب، Outlook…) ليها أسلوب جاهز.</div>`;
  }
});
/* ── الحفظ التلقائي: أي تغيير في الإعدادات بيتحفظ لوحده بعد لحظة (من غير زرار) ──
   حفظ واحد في نفس الوقت؛ تغيير جه وهو شغّال بيعمل حفظة تانية بعده بالقيم الأحدث.
   الفورم مبيتعادش بناؤه بعد الحفظ — المستخدم ممكن يكون لسه بيعدّل. */
const SAVE = { timer: null, running: false, again: false, err: null };
function settingsPayload() {
  return {
    features: S.features,
    open_hotkey: $("#hkOpen").value, mode: $("#recMode").value, insert_method: $("#sInsert").value,
    polish: $("#sPolish").checked, context_styles: $("#sStyle").checked, app_profiles: collectStyles(),
    auto_paste: $("#sPaste").checked, minimize_to_tray: $("#sTray").checked,
    floating_button: $("#sFloat").checked, clipboard_history: $("#sClip").checked, beep: $("#sBeep").checked,
    check_updates: $("#sUpd").checked, auto_update: $("#sAutoUpd").checked, theme: $("#sTheme").value,
    lang: $("#sLang").value, history_keep_last10: $("#sKeep10").checked,
    // قايمة الموديل المحلي بتتملى بعد ما offline_status يرجع — قبلها مانبعتهاش، غير كده
    // حفظة بدري كانت هتمسح الموديل اللي المستخدم اختاره قبل كده
    ...($("#offlineModel").options.length ? { offline_model: $("#offlineModel").value } : {}),
  };
}
function scheduleSave(delay = 400) {
  if (!S.features) return;
  clearTimeout(SAVE.timer);
  SAVE.timer = setTimeout(saveSettings, delay);
}
async function saveSettings() {
  SAVE.timer = null;
  if (SAVE.running) { SAVE.again = true; return; }
  SAVE.running = true;
  const msg = $("#saveMsg");
  msg.className = "save-msg";
  msg.textContent = "بيتحفظ…";
  let r;
  try { r = await api().save_settings(settingsPayload()); }
  catch (e) { r = { ok: false, err: "مقدرتش أحفظ — جرّب تاني" }; }
  SAVE.running = false;
  if (r.ok) {
    SAVE.err = null;
    S.boot = r.boot;
    applyBoot();                    // المظهر واللغة والزراير في الرئيسية
    loadHistory();                  // لو «آخر 10» اتفعّل، القديم اتمسح
    msg.className = "save-msg ok";
    msg.textContent = "اتحفظ ✓";
  } else {
    // الغلط (زي زرار مكرر) بيفضل ظاهر لحد التعديل الجاي — اللي بيحفظ تاني لوحده
    SAVE.err = r.err;
    msg.className = "save-msg err";
    msg.textContent = r.err;
  }
  if (SAVE.again) { SAVE.again = false; saveSettings(); }
}
// الحفظ اللي لسه مستني (أو شغّال) يخلص — قبل الخروج من الصفحة أو قفل البرنامج
async function flushSave() {
  if (SAVE.timer) { clearTimeout(SAVE.timer); await saveSettings(); }
  while (SAVE.running) await new Promise(r => setTimeout(r, 50));
}
function leaveSettings() {
  if (SAVE.timer) flushSave();
  else if (SAVE.err) toast("الإعدادات ماتحفظتش: " + SAVE.err);
}
(() => {
  const page = $('.page[data-page="settings"]');
  // المفاتيح بتتحفظ من أزرارها (تحقق وأضف) — ومش جزء من الإعدادات دي
  page.addEventListener("change", e => { if (!e.target.closest("#keysSection")) scheduleSave(); });
  page.addEventListener("input", e => { if (e.target.matches(".style-exe")) scheduleSave(800); });
})();

/* ═══════════ أول مرة ═══════════ */
function fillWelcome() {
  S.provider = S.boot.cfg.provider || S.boot.providers[0].id;
  const hint = () => { $("#welHint").textContent = curProv().keyHint; renderGuide($("#welGuide"), curProv()); };
  provCards($("#welProviders"), hint);
  hint();
  // نسخة الـStore: مفيش تفريغ من غير إنترنت — بنخبّي الزرار زي قسم الـoffline
  $("#welOffline").hidden = !!(S.boot.offline && S.boot.offline.packaged);
}
$("#welGetKey").addEventListener("click", () => api().open_url(curProv().keyUrl));
$("#welGo").addEventListener("click", async () => {
  const key = $("#welKey").value.trim();
  const msg = $("#welMsg");
  if (!key) { msg.className = "save-msg err"; msg.textContent = "الصق المفتاح الأول"; return; }
  const btn = $("#welGo");
  btn.disabled = true;
  msg.className = "save-msg";
  msg.textContent = "بتأكد من المفتاح…";
  const r = await api().save_settings({ provider: S.provider, key });
  btn.disabled = false;
  if (!r.ok) { msg.className = "save-msg err"; msg.textContent = r.err; return; }
  S.boot = r.boot;
  applyBoot();
  go("home");
  toast("تمام — دوس على زرار التسجيل واتكلم");
});
$("#welOffline").addEventListener("click", () => {
  go("settings");
  requestAnimationFrame(() => {
    const el = $("#offlineHead");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

/* ═══════════ الشريط الجانبي والنافذة ═══════════ */
$("#btnMin").addEventListener("click", () => api().minimize());
$("#btnLang").addEventListener("click", () => switchLang(LANG === "en" ? "ar" : "en"));
async function switchLang(lang) {
  setLang(lang);
  if (S.page === "history") renderHistory();                     // التواريخ بتتكتب بلغة الواجهة
  const r = await api().save_settings({ lang });
  if (r.ok) { S.boot = r.boot; if (S.page === "settings") $("#sLang").value = lang; }
}
$("#btnTheme").addEventListener("click", () =>
  setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
$("#btnClose").addEventListener("click", async () => { await flushSave(); api().close(); });
$("#promo").addEventListener("click", e => { e.preventDefault(); api().open_url(e.currentTarget.dataset.url); });
$("#checkUpdate").addEventListener("click", async e => {
  const b = e.currentTarget;
  if (S.update) return openUpdate();
  b.textContent = "بدوّر…";
  const info = await api().check_update();
  b.textContent = "تحقق من التحديثات";
  if (info) { showUpdate(info); openUpdate(); }
  else toast("عندك آخر إصدار ✓");
});

/* ── التحديث: نافذة «نزّل وثبّت» ── */
function showUpdate(info) {
  S.update = info;
  $("#checkUpdate").textContent = `حدّث لـ v${info.version}`;
  let dismissed = "";
  try { dismissed = localStorage.getItem("emlaa-upd-later") || ""; } catch (e) {}
  if (info.auto) {                                                // التحديث التلقائي: نعرض التقدّم بس
    openUpdate();
    $("#updGo").disabled = true; $("#updLater").disabled = true;
    $("#updBar").hidden = false; setUpdProgress(0);
    return;
  }
  if (dismissed !== info.version) openUpdate();                  // «بعدين» = متسألش تاني على نفس الإصدار
}
function openUpdate() {
  const u = S.update; if (!u) return;
  $("#updTitle").textContent = `الإصدار v${u.version}`;
  $("#updNotes").textContent = u.notes || "";
  $("#updNotes").hidden = !u.notes;
  $("#updBar").hidden = true;
  $("#updMsg").textContent = u.can_install ? "" : "التثبيت التلقائي مش متاح هنا — نزّله من صفحة الإصدار";
  $("#updMsg").className = "upd-msg";
  $("#updGo").textContent = u.can_install ? "نزّل وثبّت" : "نزّل من GitHub ↗";
  $("#updGo").disabled = false; $("#updLater").disabled = false;
  $("#updModal").hidden = false;
}
$("#updLater").addEventListener("click", () => {
  try { localStorage.setItem("emlaa-upd-later", S.update.version); } catch (e) {}
  $("#updModal").hidden = true;
});
$("#updPage").addEventListener("click", () => api().open_url(S.update.url));
$("#updGo").addEventListener("click", async () => {
  if (!S.update.can_install) return api().open_url(S.update.url);
  $("#updGo").disabled = true; $("#updLater").disabled = true;
  $("#updBar").hidden = false; setUpdProgress(0);
  const ok = await api().install_update();
  if (!ok) updFail("معرفناش نبدأ التحديث");
});
function setUpdProgress(p) {
  $("#updBar i").style.width = p + "%";
  $("#updMsg").className = "upd-msg";
  $("#updMsg").textContent = p >= 100 ? "بيثبّت ويعيد التشغيل…" : `بينزّل… ${p}%`;
}
function updFail(err) {
  $("#updMsg").className = "upd-msg err";
  $("#updMsg").textContent = "التحديث فشل — " + err;
  $("#updGo").disabled = false; $("#updLater").disabled = false;
  $("#updGo").textContent = "جرّب تاني";
}

async function refreshBoot() {
  S.boot = await api().bootstrap();
  applyBoot();
}

function applyBoot() {
  const b = S.boot;
  applyTheme(b.cfg.theme || "dark");
  if ((b.cfg.lang || "ar") !== LANG) setLang(b.cfg.lang);
  $("#versionLabel").textContent = `الإصدار v${b.version}`;
  // نسخة الـStore: التحديثات بتيجي من الـStore — مفيش زرار تحديث ولا إعداداته
  document.documentElement.classList.toggle("store", !!b.store);
  $("#promoName").textContent = b.brand.name;
  $("#promo").dataset.url = b.brand.url;
  $("#clipToggle").checked = !!b.cfg.clipboard_history;
  $$(".nav-item").forEach(n => { n.disabled = !b.canRun; });
  renderKeys();
  renderStats(b.stats);
  if (!b.canRun) setState("off");
  else if (S.state === "off") setState("ready");
}

/* ═══════════ أحداث من Python ═══════════ */
window.emlaa = {
  onState(p) {
    setState(p.state, p.msg);
    if (p.state === "done" || p.state === "err") loadHistory();
  },
  onHistory() { loadHistory(); },
  onClip(entry) {
    S.clips = [entry, ...S.clips.filter(c => c.id !== entry.id && c.text !== entry.text)];
    fillClipApps();
    if (S.page === "clipboard") renderClips();
  },
  onConfig(cfg) {
    // تغيير سريع جاي من قايمة التراي («تفريغ حرفي») من غير ما المستخدم يفتح
    // الإعدادات — بنحدّث الإعدادات المحفوظة ونحدّث مفتاح «تنظيف النص» بس،
    // من غير ما نلمس بقية الحقول (ممكن يكون المستخدم لسه بيفضّلها في الصفحة)
    if (!S.boot || !S.boot.cfg) return;
    Object.assign(S.boot.cfg, cfg);
    const sw = $("#sPolish");
    if (sw) sw.checked = !!S.boot.cfg.polish;
  },
  onUpdate(info) { showUpdate(info); },
  onUpdateProgress(p) { setUpdProgress(p); },
  onUpdateError(err) { updFail(err); },
  onOfflineProgress(p) {
    const f = Math.max(0, Math.min(1, Number(p.fraction) || 0));
    const bar = $("#offlineBar");
    bar.hidden = false;
    bar.querySelector("i").style.width = (f * 100) + "%";
    $("#offlineDownloadNote").textContent = `بينزّل… ${Math.round(f * 100)}%`;
  },
  onOfflineDone(r) {
    setOfflineDownloading(false);
    if (r.ok) {
      toast("اتنزّل ✓");
      refreshOffline(true);
      refreshCatalog();
    } else {
      toast(r.err || "مقدرتش أنزّل الموديل");
    }
  },
  go(page) { go(page); },
};

/* ═══════════ البداية ═══════════ */
async function start() {
  S.boot = await api().bootstrap();
  applyBoot();
  setState(S.boot.canRun ? S.boot.state : "off");
  fillWelcome();
  await loadHistory();
  S.clips = await api().clips();
  fillClipApps();
  if (S.boot.update) showUpdate(S.boot.update);
  go(S.boot.canRun ? "home" : "welcome");
}
if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start);
