/* Procurement audit planner: the web UI for app/server.py. Plain JavaScript, no build step.
 *
 * Routes (hash): #/overview, #/rules, #/spend, #/history, #/register, #/gate1, #/team, #/gate2.
 * Read-only without an access code; the code is kept in sessionStorage and sent as X-Access-Code.
 */
"use strict";

// ---------------------------------------------------------------- small helpers

const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const GBP = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
const NUM = new Intl.NumberFormat("en-GB");
const fmtGBP = (n) => (typeof n === "number" ? GBP.format(n) : "—");
const fmtNum = (n) => (typeof n === "number" ? NUM.format(n) : String(n ?? "—"));
function fmtUSD(n) {
  if (typeof n !== "number") return "—";
  return "$" + n.toFixed(n > 0 && n < 0.01 ? 4 : 2);
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
function fmtClock(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("en-GB", { hour12: false });
}
function fmtBytes(n) {
  if (typeof n !== "number") return "";
  return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

function toast(message, kind = "") {
  const t = $("#toast");
  t.textContent = message;
  t.className = "toast" + (kind ? " " + kind : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), kind === "bad" ? 8000 : 4000);
}

// ---------------------------------------------------------------- access code (sessionStorage only)

const CODE_KEY = "auditPlanner.accessCode";
const codeStore = {
  get() { try { return sessionStorage.getItem(CODE_KEY) || ""; } catch { return ""; } },
  set(v) { try { sessionStorage.setItem(CODE_KEY, v); } catch { /* private mode: kept in memory only */ } },
  clear() { try { sessionStorage.removeItem(CODE_KEY); } catch { /* ignore */ } },
};
let accessCode = codeStore.get();
const canEdit = () => Boolean(accessCode);
const READ_ONLY_TIP = "Read-only: enter the access code in the header to enable this";

// ---------------------------------------------------------------- API

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body, auth = false, code } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const sendCode = code ?? (auth ? accessCode : "");
  if (sendCode) headers["X-Access-Code"] = sendCode;
  const r = await fetch(path, { method, headers, cache: "no-cache", body: body === undefined ? undefined : JSON.stringify(body) });
  const isJson = (r.headers.get("content-type") || "").includes("json");
  const data = isJson ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = isJson && data && data.detail !== undefined ? data.detail : `${r.status} ${r.statusText}`;
    if (typeof msg !== "string") msg = Array.isArray(msg) ? msg.map((d) => d.msg || JSON.stringify(d)).join("; ") : JSON.stringify(msg);
    if (r.status === 401 && auth && code === undefined) {
      setCode("");
      msg += " The access code was cleared; enter it again.";
    }
    throw new ApiError(r.status, msg);
  }
  return data;
}

const fileUrl = (rel) => "/api/files/" + rel.split("/").map(encodeURIComponent).join("/");

const textCache = new Map();
async function fetchText(rel, version = "") {
  const key = rel + "@" + version;
  if (textCache.has(key)) return textCache.get(key);
  const r = await fetch(fileUrl(rel), { cache: "no-cache" });
  if (!r.ok) throw new ApiError(r.status, `outputs/${rel}: ${r.status} ${r.statusText}`);
  const text = await r.text();
  if (version) textCache.set(key, text);
  return text;
}
async function fetchJson(rel, version = "") {
  return JSON.parse(await fetchText(rel, version));
}

// ---------------------------------------------------------------- app state

let state = null;
let pageCtl = null; // AbortController for the page's streams
const runButtons = new Set(); // {wrap, btn, reasonFn}

async function refreshState() {
  const prev = state;
  state = await api("/api/state");
  renderChrome();
  updateRunButtons();
  return prev;
}

const stageOf = (name) => state?.stages.find((s) => s.stage === name);

function tone(status) {
  const s = String(status || "").toLowerCase();
  if (["succeeded", "signed-off run", "ready", "signed", "closed", "pass", "ready for sign-off"].includes(s)) return "ok";
  if (s === "running") return "run";
  if (["failed", "error", "blocked", "interrupted", "fail"].includes(s)) return "bad";
  if (["not ready", "open", "undecided", "to apply"].some((w) => s.includes(w))) return "warn";
  return "";
}
const pill = (text, t = tone(text)) => h("span", { class: "pill" + (t ? " pill-" + t : "") }, text);

// ---------------------------------------------------------------- pages and stage descriptions

const PAGES = [
  { id: "overview", label: "Overview" },
  { id: "rules", step: "1", label: "Rules", sub: "Contract Procedure Rules", stage: "rules" },
  { id: "spend", step: "2", label: "Spend", sub: "Spend analytics", stage: "spend" },
  { id: "history", step: "3", label: "History", sub: "Audit history", stage: "history" },
  { id: "register", step: "4", label: "Register", sub: "Risk register", stage: "register" },
  { id: "gate1", step: "G1", label: "Gate 1", sub: "Auditor decisions", gate: true },
  { id: "team", step: "5", label: "Team", sub: "Planning pack", stage: "team" },
  { id: "gate2", step: "G2", label: "Gate 2", sub: "Sign-off", gate: true },
];

const STAGE_INFO = {
  rules: {
    title: "Rules",
    line: "Turns the Contract Procedure Rules PDF into testable rules, each with its clause, value band, required action and a verbatim quote.",
    runLabel: "Run rule extraction",
    order: ["rules.json"],
  },
  spend: {
    title: "Spend analytics",
    line: "Cleans three months of spend over £500, tags every row and runs seven risk-indicator tests against the rules' thresholds; Python computes every number.",
    runLabel: "Run spend analytics",
    order: ["analytics.json", "analytics-full"],
  },
  history: {
    title: "Audit history",
    line: "Reads the Governance Committee papers for past audit opinions, risk themes and the council's own risk-scoring method, each item quoted from its source page.",
    runLabel: "Run history extraction",
    order: ["history.json"],
  },
  register: {
    title: "Risk register",
    line: "Rates each risk on the council's 5×5 likelihood × impact scale; every rating cites a rule, an analytics metric or a past audit, or the risk is excluded.",
    runLabel: "Build register (r0)",
    order: ["risk-register.md", "auditor-comments.md", "risk-ratings.json", "register-snapshots"],
  },
  revise: {
    title: "Register revision",
    line: "The risk-assessor applies the auditor's decisions as a new register revision.",
    runLabel: "Run revision",
  },
  team: {
    title: "Agent team",
    line: "A planner, a challenger and a QA reviewer build and cross-check the audit planning pack for the approved risks only.",
    runLabel: "Run agent team",
    order: ["planning-memo.md", "risk-control-matrix.md", "audit-program.md", "samples", "challenges.md",
            "review.md", "audit-plan.json", "pack-figures.json"],
  },
};

// ---------------------------------------------------------------- chrome: header and sidebar

function pageStatus(p) {
  if (!state) return "";
  if (p.stage) return stageOf(p.stage)?.status;
  if (p.id === "gate1") return gate1Status().text;
  if (p.id === "gate2") return stageOf("signoff")?.status;
  return "";
}

function gate1Status() {
  const g = state?.gate1 || {};
  if (stageOf("revise")?.status === "running") return { text: "running", tone: "run" };
  if (!g.exists) return { text: "not ready", tone: "" };
  if (g.error) return { text: "error", tone: "bad" };
  if (!g.closed) return { text: `${g.undecided.length} undecided`, tone: "warn" };
  if (g.pending?.length) return { text: `closed · ${g.pending.length} to apply`, tone: "warn" };
  return { text: "closed", tone: "ok" };
}

function renderChrome() {
  const route = currentRoute();
  const nav = $("#sidebar");
  nav.replaceChildren();
  for (const p of PAGES) {
    if (p.id === "rules") nav.append(h("div", { class: "nav-group" }, "Pipeline"));
    const status = pageStatus(p);
    const t = p.id === "gate1" ? gate1Status().tone : tone(status);
    nav.append(h("a", {
      class: "nav-item" + (p.gate ? " gate" : "") + (route === p.id ? " active" : ""),
      href: "#/" + p.id, "aria-current": route === p.id ? "page" : null,
    },
    h("span", { class: "nav-num" }, p.step || "◎"),
    h("span", { class: "nav-label" }, p.label, p.sub ? h("span", { class: "nav-sub" }, p.sub) : null),
    p.id !== "overview" ? h("span", { class: "dot" + (t ? " " + t : ""), title: status || "" }) : null));
  }
  if (!state) return;
  const sp = state.spend || {};
  $("#spend-pill").textContent = `Spend ${fmtUSD(sp.total_usd ?? 0)}`;
  $("#spend-pill").title = `Total model spend across ${sp.runs ?? 0} run${sp.runs === 1 ? "" : "s"} in this workspace`;
  const rp = $("#running-pill");
  if (state.running) {
    rp.hidden = false;
    rp.textContent = `Running: ${state.running.stage}`;
  } else rp.hidden = true;
  renderAccess();
}

function renderAccess() {
  $("#access-form").hidden = canEdit();
  $("#access-on").hidden = !canEdit();
  const busy = Boolean(state?.running);
  const reset = $("#reset-btn");
  reset.disabled = busy;
  reset.title = busy ? "A run is in progress; reset when it finishes"
    : "Restore outputs, scripts and agent memory to the signed-off run; run logs are kept";
}

function setCode(code) {
  accessCode = code;
  if (code) codeStore.set(code); else codeStore.clear();
  renderAccess();
  updateRunButtons();
  document.dispatchEvent(new CustomEvent("access-changed"));
}

function initAccess() {
  $("#access-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#access-code");
    const msg = $("#access-msg");
    const code = input.value.trim();
    msg.textContent = "";
    if (!code) return;
    try {
      await api("/api/access", { code });
      input.value = "";
      setCode(code);
      toast("Access code accepted: runs and gates are enabled.", "ok");
    } catch (err) {
      msg.textContent = err.status === 401 ? "Wrong code" : err.message;
    }
  });
  $("#lock-btn").addEventListener("click", () => { setCode(""); toast("Locked: the app is read-only."); });
  $("#reset-btn").addEventListener("click", async () => {
    if (!confirm("Reset the workspace to the signed-off run?\n\nEvery output, script and agent memory change since then is replaced; run logs are kept.")) return;
    try {
      await api("/api/reset", { method: "POST", auth: true });
      textCache.clear();
      toast("Workspace reset to the signed-off run.", "ok");
      await refreshState();
      renderPage();
    } catch (err) {
      toast(`Reset failed: ${err.message}`, "bad");
    }
  });
}

// ---------------------------------------------------------------- run buttons

function runDisabledReason(stage) {
  if (!canEdit()) return "Read-only: enter the access code in the header to run stages";
  if (state?.running) return `A ${state.running.stage} run is in progress; one run at a time`;
  const g = state?.gate1 || {};
  if (stage === "register" && g.decided) {
    return "The auditor has already recorded decisions, so the register is revised rather than rebuilt: use Run revision on Gate 1, or reset";
  }
  if (stage === "revise") {
    if (!g.closed) return "Every row needs a decision before the revision can run";
    if (!g.pending?.length) return "Nothing to revise: no Amend, Reject or Add to scope decision is waiting to be applied";
  }
  return "";
}

function runButton(stage, label, onStarted) {
  const btn = h("button", { class: "btn", type: "button" }, label);
  const wrap = h("span", { class: "btn-wrap" }, btn);
  const entry = { wrap, btn, reasonFn: () => runDisabledReason(stage) };
  runButtons.add(entry);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const r = await api(`/api/run/${stage}`, { method: "POST", auth: true });
      toast(`Started ${stage}: run ${r.run_id}`);
      await refreshState();
      onStarted?.(r);
    } catch (err) {
      toast(`Could not start ${stage}: ${err.message}`, "bad");
      updateRunButtons();
    }
  });
  updateRunButton(entry);
  return wrap;
}

function updateRunButton(entry) {
  const reason = entry.reasonFn();
  entry.btn.disabled = Boolean(reason);
  if (reason) entry.wrap.title = reason; else entry.wrap.removeAttribute("title");
}

function updateRunButtons() {
  for (const e of runButtons) {
    if (!e.wrap.isConnected) runButtons.delete(e);
    else updateRunButton(e);
  }
}

function runPanel(stage, onStarted) {
  const s = stageOf(stage) || {};
  const info = STAGE_INFO[stage];
  const last = s.last_run;
  const cap = s.max_budget_usd;
  const model = s.kind === "team" ? `planner ${s.planner_model}, challenger ${s.challenger_model}` : s.model;
  return h("div", { class: "run-panel" },
    runButton(stage, info.runLabel, onStarted),
    h("div", { class: "run-meta" },
      h("span", {}, "Cost cap ", h("b", {}, fmtUSD(cap))),
      model ? h("span", {}, "Model ", h("b", {}, model)) : null,
      last ? h("span", {}, "Last run ", h("b", {}, fmtTime(last.finished_at || last.started_at)), " · ", last.status,
        " · ", h("b", {}, fmtUSD(last.cost_usd))) : h("span", {}, "No run recorded in this workspace")));
}

// ---------------------------------------------------------------- renderers: markdown, JSON tree, CSV

function markdown(text) {
  const div = h("div", { class: "md" });
  if (window.marked && window.DOMPurify) {
    div.innerHTML = DOMPurify.sanitize(marked.parse(text, { gfm: true }));
    for (const a of div.querySelectorAll("a[href]")) {
      if (!a.getAttribute("href").startsWith("#")) { a.target = "_blank"; a.rel = "noopener"; }
    }
  } else {
    div.append(h("pre", {}, text));
  }
  return div;
}

function jsonTree(value, { key = null, open = true, depth = 0 } = {}) {
  const wrap = h("div", { class: "tree" });
  wrap.append(treeNode(value, key, open, depth));
  return wrap;
}

function treeNode(value, key, open, depth) {
  const keyEl = key !== null ? [h("span", { class: "k" }, typeof key === "number" ? `[${key}]` : key), ": "] : [];
  if (value !== null && typeof value === "object") {
    const isArr = Array.isArray(value);
    const entries = isArr ? value.map((v, i) => [i, v]) : Object.entries(value);
    const meta = isArr ? `[${entries.length}]` : `{${entries.length} key${entries.length === 1 ? "" : "s"}}`;
    const det = h("details", {}, h("summary", {}, keyEl, h("span", { class: "meta" }, meta)));
    let filled = false;
    const fill = () => {
      if (filled) return;
      filled = true;
      for (const [k, v] of entries) det.append(treeNode(v, k, false, depth + 1));
    };
    det.addEventListener("toggle", () => det.open && fill());
    if (open) { det.open = true; fill(); }
    return det;
  }
  const cls = typeof value === "string" ? "s" : typeof value === "number" ? "n" : value === null ? "null" : "b";
  const shown = typeof value === "string" ? JSON.stringify(value) : String(value);
  return h("div", { class: "leaf" }, keyEl, h("span", { class: cls }, shown));
}

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", i = 0, quoted = false;
  while (i < text.length) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        quoted = false; i++; continue;
      }
      field += c; i++; continue;
    }
    if (c === '"') { quoted = true; i++; continue; }
    if (c === ",") { row.push(field); field = ""; i++; continue; }
    if (c === "\n" || c === "\r") {
      row.push(field); rows.push(row); row = []; field = "";
      if (c === "\r" && text[i + 1] === "\n") i++;
      i++; continue;
    }
    field += c; i++;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

const CSV_ROW_CAP = 200;

async function csvView(rel, signal) {
  const r = await fetch(fileUrl(rel), { signal, cache: "no-cache" });
  if (!r.ok) throw new ApiError(r.status, `outputs/${rel}: ${r.status}`);
  const size = Number(r.headers.get("content-length")) || null;
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let text = "", complete = false, lines = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) { complete = true; break; }
    const chunk = dec.decode(value, { stream: true });
    text += chunk;
    for (const ch of chunk) if (ch === "\n") lines++;
    if (lines > CSV_ROW_CAP + 20 || text.length > 2_000_000) { reader.cancel(); break; }
  }
  let rows = parseCsv(text);
  if (!complete) rows = rows.slice(0, -1); // the last row may be cut off
  const header = rows[0] || [];
  const body = rows.slice(1).filter((r) => !(r.length === 1 && r[0] === ""));
  const shown = body.slice(0, CSV_ROW_CAP);
  const numeric = header.map((_, j) => {
    const vals = shown.map((r) => r[j]).filter((v) => v !== undefined && v !== "");
    return vals.length > 0 && vals.every((v) => /^-?\d+(\.\d+)?$/.test(v));
  });
  const note = complete
    ? (body.length > CSV_ROW_CAP ? `First ${CSV_ROW_CAP} of ${fmtNum(body.length)} rows` : `${fmtNum(body.length)} rows`)
    : `First ${CSV_ROW_CAP} rows of a ${fmtBytes(size)} file`;
  return h("div", {},
    h("p", { class: "muted small" }, note, " · ", h("a", { href: fileUrl(rel), target: "_blank", rel: "noopener" }, "open the full file")),
    h("div", { class: "table-wrap capped" },
      h("table", { class: "data" },
        h("thead", {}, h("tr", {}, header.map((c, j) => h("th", { class: numeric[j] ? "num" : null }, c)))),
        h("tbody", {}, shown.map((r) => h("tr", {}, header.map((_, j) => h("td", { class: numeric[j] ? "num" : null }, r[j] ?? ""))))))));
}

function table(columns, rows, { capped = false } = {}) {
  return h("div", { class: "table-wrap" + (capped ? " capped" : "") },
    h("table", { class: "data" },
      h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.num ? "num" : null }, c.label)))),
      h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, columns.map((c) => {
        const v = c.get(r);
        return h("td", { class: c.num ? "num" : c.nowrap ? "nowrap" : null }, v instanceof Node ? v : v ?? "");
      }))) : h("tr", {}, h("td", { colspan: columns.length, class: "muted" }, "None")))));
}

const stat = (v, l) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l));

// ---------------------------------------------------------------- JSON summaries

function countBy(list, fn) {
  const out = {};
  for (const x of list) { const k = fn(x); out[k] = (out[k] || 0) + 1; }
  return out;
}

function rulesSummary(j) {
  const rules = j.rules || [];
  const types = countBy(rules, (r) => r.type);
  const param = Object.entries(j.parameters || {});
  return h("div", {},
    h("div", { class: "stat-row" },
      stat(fmtNum(rules.length), "testable rules"),
      ...Object.entries(types).map(([t, n]) => stat(fmtNum(n), t)),
      stat(fmtNum((j.excluded || []).length), "clauses excluded"),
      stat(fmtNum((j.notes || []).length), "drafting notes")),
    j.source ? h("p", { class: "muted small" }, `Source: ${j.source.file} · ${j.source.pages} pages · sha256 ${String(j.source.sha256 || "").slice(0, 12)}`) : null,
    param.length ? [h("h2", { class: "section" }, "Named parameters"),
      table([
        { label: "Parameter", get: ([k]) => h("span", { class: "mono" }, k) },
        { label: "Values", get: ([, p]) => Object.entries(p.values || {}).map(([k, v]) => `${k}: ${v ?? "not stated"}`).join(" · ") },
        { label: "Description", get: ([, p]) => p.description },
      ], param)] : null,
    h("h2", { class: "section" }, "Rules"),
    table([
      { label: "ID", get: (r) => r.rule_id, nowrap: true },
      { label: "Clause", get: (r) => r.clause, nowrap: true },
      { label: "Page", get: (r) => r.page, num: true },
      { label: "Type", get: (r) => r.type, nowrap: true },
      { label: "Band", get: (r) => r.band_printed },
      { label: "Required action", get: (r) => r.required_action },
      { label: "Approver", get: (r) => r.approver },
    ], rules, { capped: true }),
    (j.notes || []).length ? [h("h2", { class: "section" }, "Notes: gaps and contradictions"),
      table([
        { label: "Kind", get: (n) => n.kind, nowrap: true },
        { label: "Clauses", get: (n) => (n.clauses || []).join(", "), nowrap: true },
        { label: "Issue", get: (n) => n.issue },
      ], j.notes, { capped: true })] : null);
}

function flatCounts(obj, prefix = "") {
  const out = [];
  for (const [k, v] of Object.entries(obj || {})) {
    if (v !== null && typeof v === "object") out.push(...flatCounts(v, prefix + k + " · "));
    else out.push(`${prefix}${k}: ${typeof v === "number" ? fmtNum(v) : v}`);
  }
  return out;
}

const TEST_NAMES = {
  threshold_clustering: "Threshold clustering", split_purchases: "Split purchases",
  no_published_notice: "No published notice found", duplicates: "Possible duplicates",
  expired_notice_spend: "Spend after notice expiry", spend_vs_award: "Spend vs award",
  high_value_suppliers: "High-value suppliers",
};

function analyticsSummary(j) {
  const tests = Object.entries(j.tests || {});
  const checks = j.reconciliation?.checks || [];
  const passed = checks.filter((c) => c.passed).length;
  const w = j.window || {};
  return h("div", {},
    h("div", { class: "stat-row" },
      stat(`${w.start || "?"} → ${w.end || "?"}`, `spend window (${w.months ?? "?"} months)`),
      stat(fmtNum(j.reconciliation?.raw_rows), "raw rows read"),
      stat(fmtGBP(j.reconciliation?.raw_net_total), "raw net total"),
      stat(`${passed} / ${checks.length}`, "reconciliation checks passed"),
      stat(fmtNum(tests.filter(([, t]) => t.status === "run").length) + " / " + tests.length, "tests run")),
    j.language_note ? h("p", { class: "muted small" }, j.language_note) : null,
    h("h2", { class: "section" }, "Tests"),
    table([
      { label: "Test", get: ([k, t]) => h("span", { title: t.description || "" }, TEST_NAMES[k] || k), nowrap: true },
      { label: "Status", get: ([, t]) => pill(t.status, t.status === "run" ? "ok" : "warn") },
      { label: "Counts", get: ([, t]) => flatCounts(t.counts).join(" · ") },
      { label: "Flagged £", get: ([, t]) => fmtGBP(t.totals?.flagged), num: true },
      { label: "General procurement", get: ([, t]) => {
        const g = t.by_tag?.general_procurement;
        return g ? `${fmtNum(g.count)} · ${fmtGBP(g.total)}` : "—";
      }, num: true },
    ], tests),
    h("p", { class: "muted small" }, "Ratings rest on the general procurement figures; placements, grants, agency staff and premises are context only. Counts are risk indicators to investigate, not findings."),
    h("h2", { class: "section" }, "Parameters"),
    table([
      { label: "Parameter", get: ([k]) => h("span", { class: "mono" }, k) },
      { label: "Value", get: ([, v]) => String(v), num: true },
      { label: "Definition", get: ([k]) => (j.parameter_definitions || {})[k] ?? "" },
    ], Object.entries(j.parameters || {})));
}

function historySummary(j) {
  const audits = j.audits || [];
  const sm = j.risk_scoring_method || {};
  return h("div", {},
    h("div", { class: "stat-row" },
      stat(fmtNum(audits.length), "audits recorded"),
      stat(fmtNum(audits.filter((a) => /limited|weak|no assurance/i.test(a.opinion || "")).length), "Limited or worse"),
      stat(fmtNum((j.agreed_actions || []).length), "agreed actions"),
      stat(fmtNum((j.risk_themes || []).length), "risk themes"),
      stat(fmtNum((j.discrepancies || []).length), "discrepancies"),
      stat(fmtNum((j.gaps || []).length), "gaps")),
    h("dl", { class: "kv" },
      h("dt", {}, "Risk scoring method"), h("dd", {}, sm.status === "found" ? "Found in the Risk Management Strategy 2024–27" : (sm.status || "—") + (sm.not_found_reason ? `: ${sm.not_found_reason}` : "")),
      h("dt", {}, "Corporate Risk Register"), h("dd", {}, j.risk_register_access?.status || "—", j.risk_register_access?.note ? h("span", { class: "muted" }, " · " + j.risk_register_access.note) : null)),
    h("h2", { class: "section" }, "Audits and opinions"),
    table([
      { label: "ID", get: (a) => a.id, nowrap: true },
      { label: "Period", get: (a) => a.report_period, nowrap: true },
      { label: "Service", get: (a) => a.service },
      { label: "Audit", get: (a) => a.title },
      { label: "Opinion", get: (a) => a.opinion ? pill(a.opinion, /limited|weak|no assurance/i.test(a.opinion) ? "bad" : /substantial|reasonable/i.test(a.opinion) ? "ok" : "") : "—" },
      { label: "Follow-up progress", get: (a) => a.implementation_progress },
      { label: "Source", get: (a) => (a.cites || []).map((c) => `${c.file.split("/").pop()} p${c.pdf_page}`).join("; "), nowrap: true },
    ], audits, { capped: true }),
    h("h2", { class: "section" }, "Gaps"),
    table([
      { label: "ID", get: (g) => g.id, nowrap: true },
      { label: "Topic", get: (g) => g.topic, nowrap: true },
      { label: "Detail", get: (g) => g.detail },
    ], j.gaps || []),
    h("h2", { class: "section" }, "Discrepancies inside the papers (left unresolved)"),
    table([
      { label: "ID", get: (d) => d.id, nowrap: true },
      { label: "Kind", get: (d) => d.kind, nowrap: true },
      { label: "Description", get: (d) => d.description },
    ], j.discrepancies || [], { capped: true }));
}

const SUMMARIES = { "rules.json": rulesSummary, "analytics.json": analyticsSummary, "history.json": historySummary };

// ---------------------------------------------------------------- output viewer (tabs)

async function renderFile(rel, version, container, signal) {
  container.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    let el;
    const ext = rel.slice(rel.lastIndexOf(".")).toLowerCase();
    if (ext === ".md") el = markdown(await fetchText(rel, version));
    else if (ext === ".json") {
      const j = await fetchJson(rel, version);
      const name = rel.split("/").pop();
      el = SUMMARIES[name]
        ? h("div", {}, SUMMARIES[name](j), h("h2", { class: "section" }, "Raw JSON"), jsonTree(j, { open: false, key: name }))
        : jsonTree(j, { open: true });
    } else if (ext === ".csv") el = await csvView(rel, signal);
    else el = h("pre", {}, await fetchText(rel, version));
    container.replaceChildren(el);
  } catch (err) {
    if (err.name === "AbortError") return;
    container.replaceChildren(h("p", { class: "run-error" }, err.message));
  }
}

async function renderDir(rel, container, signal) {
  container.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try {
    const listing = await api(fileUrl(rel));
    const files = listing.entries.filter((e) => !e.endsWith("/"));
    if (!files.length) { container.replaceChildren(h("p", { class: "empty" }, "This folder is empty.")); return; }
    const view = h("div", {});
    const select = h("select", { "aria-label": "File" }, files.map((f) => h("option", { value: f }, f)));
    select.addEventListener("change", () => renderFile(`${rel}/${select.value}`, "", view, signal));
    container.replaceChildren(h("div", { class: "picker" }, h("label", { class: "small muted" }, "File"), select,
      h("span", { class: "muted small" }, `${files.length} file${files.length === 1 ? "" : "s"}`)), view);
    renderFile(`${rel}/${files[0]}`, "", view, signal);
  } catch (err) {
    container.replaceChildren(h("p", { class: "run-error" }, err.message));
  }
}

function outputTabs(stage, signal) {
  const s = stageOf(stage);
  const order = STAGE_INFO[stage].order || [];
  const outputs = [...(s?.outputs || [])].sort((a, b) => order.indexOf(a.path) - order.indexOf(b.path));
  const wrap = h("div", {});
  if (!outputs.length) return wrap;
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const body = h("div", { class: "tab-body" });
  let active = null;
  const show = (o, btn) => {
    if (active) active.classList.remove("active");
    btn.classList.add("active");
    active = btn;
    if (!o.exists) body.replaceChildren(h("p", { class: "empty" }, `outputs/${o.path} has not been produced yet.`));
    else if (o.files !== undefined) renderDir(o.path, body, signal);
    else renderFile(o.path, o.modified, body, signal);
  };
  for (const o of outputs) {
    const note = !o.exists ? "missing" : o.files !== undefined ? `${o.files} files` : "";
    const btn = h("button", { class: "tab", role: "tab", type: "button" }, o.path, note ? h("span", { class: "tab-note" }, note) : null);
    btn.addEventListener("click", () => show(o, btn));
    tabs.append(btn);
  }
  wrap.append(tabs, body);
  const first = outputs.find((o) => o.exists) || outputs[0];
  show(first, tabs.children[outputs.indexOf(first)]);
  return wrap;
}

// ---------------------------------------------------------------- run log (server-sent events over fetch)

function parseSse(block) {
  const ev = { event: "message", data: "", id: null };
  let any = false;
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const i = line.indexOf(":");
    const field = i < 0 ? line : line.slice(0, i);
    const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
    if (field === "event") ev.event = value;
    else if (field === "data") ev.data += (ev.data ? "\n" : "") + value;
    else if (field === "id") ev.id = value;
    any = true;
  }
  if (!any) return null;
  try { ev.data = JSON.parse(ev.data); } catch { /* keep text */ }
  return ev;
}

async function streamRun(runId, { onEvent, onEnd, signal }) {
  let lastId = 0;
  for (let attempt = 0; attempt < 30 && !signal.aborted; attempt++) {
    try {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/events`, {
        signal, cache: "no-store", headers: lastId ? { "Last-Event-ID": String(lastId) } : {},
      });
      if (!r.ok) { onEnd({ error: r.status === 404 ? "This run's log is not in this workspace." : `${r.status} ${r.statusText}` }); return; }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const ev = parseSse(buf.slice(0, i));
          buf = buf.slice(i + 2);
          if (!ev) continue;
          if (ev.event === "end") { onEnd(ev.data || {}); return; }
          if (ev.id) lastId = Number(ev.id);
          onEvent(ev.data);
        }
      }
    } catch (err) {
      if (signal.aborted) return;
    }
    await sleep(2000);
  }
}

function clipText(text, n = 700) {
  text = String(text ?? "");
  if (text.length <= n) return h("span", {}, text);
  return h("span", {}, text.slice(0, n), "… ",
    h("details", { style: "display:inline" }, h("summary", { style: "display:inline" }, `show all ${fmtNum(text.length)} chars`), h("pre", {}, text)));
}

function toolSummary(name, input) {
  const i = input || {};
  return i.command || i.file_path || i.pattern || i.skill || (i.subagent_type ? `${i.subagent_type}: ${i.description || ""}` : "") || i.path || i.description || "";
}

function logRow(ev) {
  const who = ev.agent || ev.role || (ev.type === "protocol" ? ev.from : "harness");
  let cls = "", body;
  switch (ev.type) {
    case "run_started":
      body = `Run started · ${ev.model} · cost cap ${fmtUSD(ev.max_budget_usd)}`; break;
    case "session":
      body = `Session: ${ev.model} · ${(ev.tools || []).length} tools · agents ${(ev.agents || []).join(", ") || "none"}`; cls = "thinking"; break;
    case "system":
      body = `${ev.subtype}${ev.data?.description ? ": " + ev.data.description : ""}`; cls = "thinking"; break;
    case "text":
      body = clipText(ev.text); break;
    case "thinking":
      body = clipText(ev.text, 300); cls = "thinking"; break;
    case "tool_use":
      cls = "tool";
      body = [h("span", { class: "tool-name" }, ev.name), clipText(toolSummary(ev.name, ev.input), 400),
        h("details", {}, h("summary", {}, "input"), h("pre", {}, JSON.stringify(ev.input, null, 1)))];
      break;
    case "tool_result":
      cls = ev.is_error ? "err" : "";
      body = h("details", {}, h("summary", {}, ev.is_error ? "tool error" : "result"), h("pre", {}, ev.content || ""));
      break;
    case "result":
      cls = ev.is_error ? "err" : "res";
      body = [`Finished: ${ev.subtype} · ${fmtUSD(ev.cost_usd)} · ${ev.num_turns ?? "?"} turns · ${Math.round((ev.duration_ms || 0) / 1000)} s`,
        ev.text ? h("details", {}, h("summary", {}, "final report"), h("pre", {}, ev.text)) : null];
      break;
    case "error":
      cls = "err"; body = ev.message; break;
    case "guard":
      cls = "err"; body = `Blocked by the guard (${ev.tool}): ${ev.reason}`; break;
    case "run_finished":
      cls = ev.status === "succeeded" ? "res" : "err";
      body = `Run finished: ${ev.status} · ${fmtUSD(ev.cost_usd)}` + (ev.outputs_changed?.length ? ` · outputs changed: ${ev.outputs_changed.join(", ")}` : "");
      break;
    case "team_started":
      body = `Team started · cap ${fmtUSD(ev.cap_usd)} · planner ${ev.planner_model} · challenger ${ev.challenger_model}`; break;
    case "call":
      body = `Model call: ${ev.purpose} (attempt ${ev.attempt}) · ${ev.model} · ${fmtUSD(ev.max_budget_usd)} left`; break;
    case "cost":
      body = `Cost: ${ev.purpose} ${fmtUSD(ev.call_usd)} · ${fmtUSD(ev.spent_usd)} of ${fmtUSD(ev.cap_usd)} spent`; cls = "thinking"; break;
    case "protocol":
      body = [h("b", {}, `→ ${(ev.to || []).join(", ")}: ${ev.kind}`), h("pre", {}, ev.text || "")]; break;
    case "reply_refused": case "challenge_refused":
      cls = "err"; body = `${ev.type.replace("_", " ")}: ${(ev.errors || ev.reasons || []).join("; ")}`; break;
    case "plan_backup":
      body = ev.folder ? `Previous plan moved to ${ev.folder}/ (${ev.files.length} files)` : "No previous plan to back up"; break;
    default:
      body = h("pre", {}, JSON.stringify(ev));
  }
  return h("div", { class: "log-row " + cls }, h("span", { class: "log-t" }, fmtClock(ev.t)), h("span", { class: "log-who", title: who }, who), h("div", { class: "log-body" }, body));
}

// A log panel that follows a run: live while it runs, replayed from the run file afterwards.
function logPanel(runId, { title = "Run log", onEvent, onEnd, signal, collapsed = false,
  emptyText = "No run of this stage in this workspace yet. The outputs below are from the signed-off run." } = {}) {
  const log = h("div", { class: "log", "aria-live": "polite" });
  const status = h("span", { class: "muted small" });
  const head = h("div", { class: "log-head" }, h("h2", { class: "section" }, title), status);
  const wrap = collapsed ? h("details", { class: "card" }, h("summary", {}, h("b", {}, title), " ", status), log) : h("div", {}, head, log);
  if (!runId) {
    log.append(h("div", { class: "log-empty" }, emptyText));
    return wrap;
  }
  status.textContent = `run ${runId}`;
  let count = 0;
  streamRun(runId, {
    signal,
    onEvent(ev) {
      const near = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      log.append(logRow(ev));
      count++;
      if (near) log.scrollTop = log.scrollHeight;
      onEvent?.(ev);
    },
    onEnd(end) {
      if (end.error) log.append(h("div", { class: "log-empty" }, end.error));
      else if (!count) log.append(h("div", { class: "log-empty" }, "This run recorded no events."));
      status.textContent = `run ${runId} · ${end.status || "ended"}`;
      onEnd?.(end);
    },
  });
  return wrap;
}

// ---------------------------------------------------------------- team conversation

const ROLE_ORDER = ["lead", "planner", "challenger", "qa-reviewer"];

function protocolTitle(ev) {
  const first = String(ev.text || "").split("\n")[0];
  if (["QA", "PACK READY", "CHALLENGE", "RESPONSE", "PLANNER DONE", "VERIFIED", "NOT FOUND", "PLANNER BLOCKED"].includes(ev.kind) && first.length < 90) return first;
  if (ev.kind === "QA DONE" && ev.verdict) return `QA DONE · ${ev.verdict}`;
  return ev.kind + (ev.version ? ` v${ev.version}` : "") + (ev.n ? ` #${ev.n}` : "");
}

function protocolTone(ev) {
  const t = protocolTitle(ev);
  if (ev.kind === "QA") return /PASS/.test(t) ? "ok" : "bad";
  if (ev.kind === "QA DONE") return ev.verdict === "READY FOR SIGN-OFF" ? "ok" : "bad";
  if (["STOPPED", "BUILD FAILED", "PLANNER BLOCKED", "NOT FOUND"].includes(ev.kind)) return "bad";
  if (ev.kind === "CHALLENGE") return "warn";
  if (["PACK READY", "VERIFIED"].includes(ev.kind)) return "run";
  return "";
}

function conversation() {
  const box = h("div", { class: "convo" });
  const empty = h("div", { class: "log-empty" }, "Waiting for the first protocol message…");
  box.append(empty);
  return {
    el: box,
    add(ev) {
      if (ev.type === "protocol") {
        empty.remove();
        const lines = String(ev.text || "").split("\n");
        const title = protocolTitle(ev);
        const rest = lines[0] === title ? lines.slice(1).join("\n") : ev.text;
        box.append(h("div", { class: "msg" },
          h("div", { class: "msg-who" }, ev.from, h("span", { class: "to" }, "→ " + (ev.to || []).join(", "))),
          h("div", { class: "bubble role-" + (ROLE_ORDER.includes(ev.from) ? ev.from : "lead") },
            h("div", { class: "bubble-head" }, pill(title, protocolTone(ev)), h("span", { class: "muted small" }, fmtClock(ev.t))),
            rest.trim() ? h("pre", {}, rest) : null)));
      } else if (ev.type === "cost") {
        box.append(h("div", { class: "convo-note" }, `${ev.role} · ${ev.purpose}: ${fmtUSD(ev.call_usd)} · ${fmtUSD(ev.spent_usd)} of ${fmtUSD(ev.cap_usd)} cap spent`));
      } else if (ev.type === "challenge_refused" || ev.type === "reply_refused") {
        box.append(h("div", { class: "convo-note", style: "color:var(--bad)" }, `${ev.type.replace("_", " ")} by the harness: ${(ev.reasons || ev.errors || []).join("; ")}`));
      }
    },
    end(endInfo) {
      if (endInfo.error) empty.textContent = endInfo.error;
      else if (empty.isConnected) empty.textContent = "This run sent no protocol messages.";
    },
  };
}

// ---------------------------------------------------------------- pages

function pageHead(title, line, statusText, statusTone) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, title), line ? h("p", { class: "lede" }, line) : null),
    statusText ? pill(statusText, statusTone ?? tone(statusText)) : null);
}

const BANNER = () => h("div", { class: "banner", role: "note" }, "Everything here is a risk indicator to investigate, not a finding.");

function cardMeta(s) {
  if (!s) return "—";
  const last = s.last_run;
  if (s.status === "signed-off run" || (!last && s.outputs?.some((o) => o.exists))) {
    const dated = s.outputs?.filter((o) => o.modified).map((o) => o.modified).sort().pop();
    return [`From the signed-off run`, h("br"), dated ? `Outputs ${fmtTime(dated)}` : "", last ? [h("br"), `Last run ${fmtTime(last.finished_at || last.started_at)} · ${fmtUSD(last.cost_usd)}`] : ""];
  }
  if (!last) return "No run yet";
  return [`Last run ${fmtTime(last.finished_at || last.started_at)}`, h("br"), `Cost ${fmtUSD(last.cost_usd)} · cap ${fmtUSD(s.max_budget_usd)}`];
}

function renderOverview(main) {
  const card = (p, statusText, statusTone, meta) => h("a", { class: "stage-card" + (p.gate ? " gate" : ""), href: "#/" + p.id },
    h("span", { class: "sc-step" }, p.gate ? p.label : `Stage ${p.step}`),
    h("span", { class: "sc-name" }, p.gate ? p.sub : p.sub),
    pill(statusText || "—", statusTone),
    h("span", { class: "sc-meta" }, meta));
  const cards = PAGES.filter((p) => p.id !== "overview").map((p) => {
    if (p.stage) {
      const s = stageOf(p.stage);
      return card(p, s?.status, tone(s?.status), cardMeta(s));
    }
    if (p.id === "gate1") {
      const g = gate1Status();
      const rev = stageOf("revise");
      const gs = state.gate1 || {};
      return card(p, g.text, g.tone, [gs.exists ? `${gs.decided ?? 0} of ${gs.rows ?? 0} rows decided` : "No decision file yet", h("br"),
        rev?.last_run ? `Revision run ${fmtTime(rev.last_run.finished_at || rev.last_run.started_at)} · ${fmtUSD(rev.last_run.cost_usd)}` : "Revision: no run in this workspace"]);
    }
    const s = stageOf("signoff");
    const r = s?.review || {};
    return card(p, s?.status, tone(s?.status), [r.verdict ? `QA: ${r.verdict}` : "No QA review yet", h("br"),
      r.signed ? `${r.decision} · ${r.date}` : "Not signed"]);
  });
  const ws = state.workspace || {};
  main.append(
    pageHead("Procurement audit planning", null),
    h("p", { class: "intro" },
      "This tool plans an internal audit of West Berkshire Council's procurement from public data: it turns the Contract Procedure Rules into testable rules, tests three months of spend over £500 against them in Python, and reads past audit reports and the council's own risk-scoring method. ",
      "A risk-assessor agent rates each risk with cited evidence, and the auditor approves, amends or rejects every risk at Gate 1. ",
      "A planner, a challenger and a QA reviewer then build and cross-check the audit planning pack, which the auditor signs off at Gate 2."),
    BANNER(),
    h("h2", { class: "section" }, "Pipeline"),
    h("div", { class: "pipeline" }, cards),
    h("h2", { class: "section" }, "Workspace"),
    h("div", { class: "card" }, h("dl", { class: "kv" },
      h("dt", {}, "Seeded from the signed-off run"), h("dd", {}, fmtTime(ws.seeded_at), ws.source_commit ? h("span", { class: "muted mono" }, ` · commit ${ws.source_commit.slice(0, 10)}`) : null),
      h("dt", {}, "Runs recorded"), h("dd", {}, fmtNum(state.spend?.runs ?? 0)),
      h("dt", {}, "Model spend, all runs"), h("dd", {}, fmtUSD(state.spend?.total_usd ?? 0)),
      h("dt", {}, "Mode"), h("dd", {}, canEdit() ? "Editing enabled: runs and gates are available" : "Read-only: enter the access code in the header to run stages or record decisions"))));
}

function renderStage(main, stage, signal) {
  const info = STAGE_INFO[stage];
  const s = stageOf(stage);
  const p = PAGES.find((x) => x.stage === stage);
  main.append(pageHead(`${p.step}. ${info.title}`, info.line, s?.status), BANNER());
  const outputsBox = h("div", {});
  const rerenderOutputs = async () => {
    await sleep(500); // the server commits the workspace after the stream ends
    await refreshState();
    if (!signal.aborted) renderPage();
  };
  main.append(runPanel(stage, () => renderPage()));
  const running = state.running?.stage === stage;
  const runId = running ? state.running.id : s?.last_run?.id;
  if (stage === "team") {
    const convo = conversation();
    append(main, [h("h2", { class: "section" }, "Team conversation"),
      runId ? null : h("p", { class: "muted small" }, "No team run in this workspace yet. The pack below is from the signed-off run; its challenges and QA results are in challenges.md and review.md.")]);
    if (runId) main.append(convo.el);
    main.append(h("div", { style: "margin-top:16px" }, logPanel(runId, {
      title: "Full run log", collapsed: !running, signal,
      onEvent: (ev) => convo.add(ev),
      onEnd: (end) => { convo.end(end); if (running) rerenderOutputs(); },
    })));
  } else {
    main.append(logPanel(runId, { signal, onEnd: () => running && rerenderOutputs() }));
  }
  outputsBox.append(h("h2", { class: "section" }, "Outputs"), outputTabs(stage, signal));
  main.append(outputsBox);
}

// ---------------------------------------------------------------- gate 1

function splitCells(line) {
  return line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim());
}

function parseComments(text) {
  const out = { revision: (text.match(/Register revision:\s*(r\d+)/) || [])[1] || null, rated: [], noted: [] };
  let table = null, header = null;
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (s.startsWith("## ")) {
      const t = s.slice(3).toLowerCase();
      table = t.startsWith("rated") ? "rated" : t.startsWith("noted") ? "noted" : null;
      header = null;
      continue;
    }
    if (!table || !s.startsWith("|")) continue;
    const cells = splitCells(s);
    if (!header) { header = cells.map((c) => c.toLowerCase()); continue; }
    if (cells.every((c) => /^[-: ]*$/.test(c))) continue;
    const row = {};
    header.forEach((k, i) => (row[k] = cells[i] ?? ""));
    row.id = table === "rated" ? row.risk : row.item;
    out[table].push(row);
  }
  return out;
}

const RATED = ["Approve", "Amend", "Reject"];
const NOTED = ["Add to scope", "Leave out"];

function gateRow(row, options, kind, model) {
  const name = `d-${row.id}`;
  const tr = h("tr", {});
  const err = h("div", { class: "row-err" });
  const comment = h("textarea", { rows: "2", "aria-label": `Comment for ${row.id}`, maxlength: "600" });
  comment.value = row.comment;
  comment.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
  const fit = () => { comment.style.height = "auto"; comment.style.height = comment.scrollHeight + 2 + "px"; };
  comment.addEventListener("input", fit);
  requestAnimationFrame(fit);
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": `Decision for ${row.id}` }, options.map((o) =>
    h("label", {}, h("input", { type: "radio", name, value: o, checked: row.decision === o }), h("span", {}, o))));
  const clear = row.applied ? h("label", { class: "small muted", title: "Set the Decision again and clear Applied to ask for a further change to this row" },
    h("input", { type: "checkbox" }), " ask again") : null;
  const item = { row, kind, comment, seg, clear, err, tr,
    decision: () => (seg.querySelector("input:checked") || {}).value || "",
    changed() {
      return this.decision() !== row.decision || comment.value.trim() !== row.comment || Boolean(clear?.querySelector("input").checked);
    },
    validate() {
      const c = comment.value;
      let msg = "";
      if (/[|\n\r]/.test(c)) msg = "A comment may not contain the | character or a line break.";
      else if (this.decision() === "Amend" && !c.trim()) msg = "Amend needs a comment saying exactly what to change.";
      err.textContent = msg;
      comment.classList.toggle("invalid", Boolean(msg));
      return !msg;
    },
  };
  const onChange = () => { tr.classList.toggle("changed", item.changed()); item.validate(); model.onChange(); };
  seg.addEventListener("change", onChange);
  comment.addEventListener("input", onChange);
  clear?.addEventListener("change", onChange);
  const cells = kind === "rated"
    ? [h("td", { class: "nowrap" }, h("b", {}, row.id)), h("td", { class: "title" }, row.title), h("td", {}, row.likelihood),
       h("td", {}, row.impact), h("td", { class: "num" }, row.score), h("td", {}, row.band)]
    : [h("td", { class: "nowrap" }, h("b", {}, row.id)), h("td", { class: "title" }, row.area), h("td", { class: "nowrap" }, row.opinion)];
  append(tr, [cells, h("td", { class: "nowrap" }, seg), h("td", {}, comment, err), h("td", { class: "nowrap" }, row.applied || h("span", { class: "muted" }, "—"), clear ? h("br") : null, clear)]);
  return item;
}

async function renderGate1(main, signal) {
  const g = gate1Status();
  main.append(pageHead("Gate 1 · Auditor decisions",
    "Approve, amend or reject each rated risk, and decide whether each noted item joins the scope. Decisions are written to auditor-comments.md; the risk-assessor then applies them as a register revision.",
    g.text, g.tone), BANNER());
  const body = h("div", {}, h("p", { class: "muted" }, "Loading the decision file…"));
  main.append(body);
  const out = stageOf("register")?.outputs?.find((o) => o.path === "auditor-comments.md");
  if (!out?.exists) { body.replaceChildren(h("p", { class: "empty" }, "There is no auditor-comments.md yet: build the register first.")); return; }
  let parsed;
  try { parsed = parseComments(await fetchText("auditor-comments.md", out.modified)); }
  catch (err) { body.replaceChildren(h("p", { class: "run-error" }, err.message)); return; }
  const gs = state.gate1 || {};
  const items = [];
  const saveBtn = h("button", { class: "btn", type: "submit" }, "Save decisions");
  const saveWrap = h("span", { class: "btn-wrap" }, saveBtn);
  const saveNote = h("span", { class: "muted small" });
  const model = {
    onChange() {
      const n = items.filter((i) => i.changed()).length;
      saveNote.textContent = n ? `${n} row${n === 1 ? "" : "s"} changed, not saved` : "No unsaved changes";
      refreshSave();
    },
  };
  const refreshSave = () => {
    const reason = !canEdit() ? READ_ONLY_TIP : state.running ? `A ${state.running.stage} run is in progress` : "";
    saveBtn.disabled = Boolean(reason) || !items.some((i) => i.changed());
    if (reason) saveWrap.title = reason; else saveWrap.removeAttribute("title");
    for (const i of items) {
      for (const inp of i.tr.querySelectorAll("input, textarea")) inp.disabled = Boolean(reason);
    }
  };
  const rated = parsed.rated.map((r) => gateRow(r, RATED, "rated", model));
  const noted = parsed.noted.map((r) => gateRow(r, NOTED, "noted", model));
  items.push(...rated, ...noted);
  const tbl = (cols, rows) => h("div", { class: "table-wrap" }, h("table", { class: "data gate-table" },
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c === "Score" ? "num" : null }, c)))), h("tbody", {}, rows.map((i) => i.tr))));
  const form = h("form", {},
    h("div", { class: "gate-status" },
      pill(`Register ${parsed.revision || "?"}`, ""),
      pill(`${gs.decided ?? 0} of ${gs.rows ?? 0} decided`, gs.closed ? "ok" : "warn"),
      pill(gs.closed ? "Gate closed" : "Gate open", gs.closed ? "ok" : "warn"),
      gs.pending?.length ? pill(`Waiting to be applied: ${gs.pending.join(", ")}`, "warn") : null,
      h("a", { href: "#/register", class: "small" }, "Read the full register")),
    h("h2", { class: "section" }, "Rated risks"),
    tbl(["Risk", "Title", "Likelihood", "Impact", "Score", "Band", "Decision", "Comment", "Applied"], rated),
    h("h2", { class: "section" }, "Noted, not rated"),
    h("p", { class: "muted small", style: "margin-top:-4px" }, "Past audits with a Limited (or worse) opinion in areas the spend tests exclude. Add to scope and they are rated in the next revision."),
    tbl(["Item", "Area", "Opinion", "Decision", "Comment", "Applied"], noted),
    h("div", { class: "actions" }, saveWrap, saveNote));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const changed = items.filter((i) => i.changed());
    if (!changed.every((i) => i.validate())) { toast("Fix the highlighted comments first.", "bad"); return; }
    const missing = changed.filter((i) => !i.decision());
    if (missing.length) { toast(`Choose a decision for ${missing.map((i) => i.row.id).join(", ")}.`, "bad"); return; }
    saveBtn.disabled = true;
    try {
      const res = await api("/api/gate1", { method: "POST", auth: true, body: { decisions: changed.map((i) => ({
        id: i.row.id, decision: i.decision(), comment: i.comment.value.trim(),
        clear_applied: Boolean(i.clear?.querySelector("input").checked),
      })) } });
      toast(`Saved ${changed.length} decision${changed.length === 1 ? "" : "s"}. ${res.closed ? "The gate is closed." : `${res.undecided.length} rows still undecided.`}`, "ok");
      await refreshState();
      renderPage();
    } catch (err) {
      toast(`Not saved: ${err.message}`, "bad");
      refreshSave();
    }
  });
  const rev = stageOf("revise");
  const revRunning = state.running?.stage === "revise";
  body.replaceChildren(form,
    h("h2", { class: "section" }, "Apply the decisions"),
    h("p", { class: "muted small", style: "margin-top:-4px" }, STAGE_INFO.revise.line, " It runs once the gate is closed and an Amend, Reject or Add to scope decision is waiting."),
    runPanel("revise", () => renderPage()),
    logPanel(revRunning ? state.running.id : rev?.last_run?.id, { title: "Revision run log", signal, emptyText: "No revision run in this workspace yet.",
      onEnd: () => revRunning && sleep(500).then(refreshState).then(() => !signal.aborted && renderPage()) }));
  model.onChange();
  document.addEventListener("access-changed", refreshSave, { signal });
}

// ---------------------------------------------------------------- gate 2

function mdSection(text, title) {
  const lines = text.split("\n");
  const start = lines.findIndex((l) => l.trim() === `## ${title}`);
  if (start < 0) return null;
  let end = lines.findIndex((l, i) => i > start && l.startsWith("## "));
  if (end < 0) end = lines.length;
  return lines.slice(start + 1, end).join("\n").trim();
}

async function renderGate2(main, signal) {
  const s = stageOf("signoff") || {};
  const r = s.review || {};
  main.append(pageHead("Gate 2 · Sign-off", "The auditor signs off the planning pack once the QA reviewer reports READY FOR SIGN-OFF.", s.status), BANNER());
  const ready = r.verdict === "READY FOR SIGN-OFF";
  main.append(h("div", { class: "verdict " + (!r.exists ? "none" : ready ? "ok" : "bad") },
    !r.exists ? "No QA review yet: run the agent team" : `QA verdict: ${r.verdict || "missing"}`,
    r.pack_version ? h("span", { class: "small", style: "font-weight:500" }, `Pack ${r.pack_version}`) : null));

  const team = stageOf("team")?.outputs || [];
  const ver = (p) => team.find((o) => o.path === p);
  const load = async (p) => (ver(p)?.exists ? fetchText(p, ver(p).modified) : "");
  const [challenges, review] = await Promise.all([load("challenges.md"), load("review.md")]).catch(() => ["", ""]);
  const forAuditor = mdSection(challenges, "For the auditor");
  const qaPoints = mdSection(review, "QA points answered for the auditor");
  main.append(h("div", { class: "grid-2", style: "margin-top:16px" },
    h("div", { class: "card" }, h("h2", { class: "section", style: "margin-top:0" }, "Challenges marked for the auditor"),
      forAuditor ? markdown(forAuditor) : h("p", { class: "muted" }, "None.")),
    h("div", { class: "card" }, h("h2", { class: "section", style: "margin-top:0" }, "QA points answered for the auditor"),
      qaPoints ? markdown(qaPoints) : h("p", { class: "muted" }, "None."))));

  main.append(h("h2", { class: "section" }, "Auditor sign-off"));
  if (r.signed) {
    main.append(h("div", { class: "card" }, h("dl", { class: "kv" },
      h("dt", {}, "Decision"), h("dd", {}, pill(r.decision, r.decision === "Signed off" ? "ok" : "bad")),
      h("dt", {}, "Auditor"), h("dd", {}, r.auditor),
      h("dt", {}, "Date"), h("dd", {}, r.date)),
      h("p", { class: "muted small" }, "review.md is signed; a new team run writes a new review.")));
  } else {
    const auditor = h("input", { type: "text", id: "so-auditor", autocomplete: "name" });
    const decision = h("select", { id: "so-decision" }, h("option", {}, "Signed off"), h("option", {}, "Not signed off"));
    const ch = h("input", { type: "checkbox", id: "so-ch" });
    const qa = h("input", { type: "checkbox", id: "so-qa" });
    const comment = h("textarea", { id: "so-comment", maxlength: "600" });
    const btn = h("button", { class: "btn", type: "submit" }, "Record sign-off");
    const wrap = h("span", { class: "btn-wrap" }, btn);
    const reason = () => !r.exists ? "There is no QA review yet"
      : !ready ? `Sign-off needs the verdict READY FOR SIGN-OFF; it is ${r.verdict || "missing"}`
      : !canEdit() ? READ_ONLY_TIP
      : state.running ? `A ${state.running.stage} run is in progress` : "";
    const refresh = () => {
      const why = reason();
      for (const el of [auditor, decision, ch, qa, comment]) el.disabled = Boolean(why);
      btn.disabled = Boolean(why);
      if (why) wrap.title = why; else wrap.removeAttribute("title");
      note.textContent = why;
    };
    const note = h("span", { class: "muted small" });
    const form = h("form", { class: "card" },
      h("div", { class: "form-grid" },
        h("label", { for: "so-auditor" }, "Auditor"), auditor,
        h("label", { for: "so-decision" }, "Decision"), decision,
        h("label", { for: "so-ch" }, "Challenges for the auditor considered"), h("div", {}, ch),
        h("label", { for: "so-qa" }, "QA points for the auditor considered"), h("div", {}, qa),
        h("label", { for: "so-comment" }, "Comment"), comment),
      h("div", { class: "actions" }, wrap, note));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (/[|\n\r]/.test(auditor.value + comment.value)) { toast("The auditor name and comment may not contain | or a line break.", "bad"); return; }
      btn.disabled = true;
      try {
        await api("/api/signoff", { method: "POST", auth: true, body: {
          auditor: auditor.value.trim(), decision: decision.value,
          challenges_considered: ch.checked, qa_points_considered: qa.checked, comment: comment.value.trim(),
        } });
        toast("Sign-off recorded in review.md.", "ok");
        await refreshState();
        renderPage();
      } catch (err) {
        toast(`Not recorded: ${err.message}`, "bad");
        refresh();
      }
    });
    main.append(form);
    refresh();
    document.addEventListener("access-changed", refresh, { signal });
  }
  if (review) {
    main.append(h("details", { class: "card", style: "margin-top:16px" }, h("summary", {}, h("b", {}, "Full review.md")), markdown(review)));
  }
}

// ---------------------------------------------------------------- routing

function currentRoute() {
  const id = (location.hash.match(/^#\/([\w-]+)/) || [])[1];
  return PAGES.some((p) => p.id === id) ? id : "overview";
}

async function renderPage() {
  if (pageCtl) pageCtl.abort();
  pageCtl = new AbortController();
  const signal = pageCtl.signal;
  const main = $("#main");
  const scroll = window.scrollY;
  const sameRoute = renderPage.last === currentRoute();
  renderPage.last = currentRoute();
  try { await refreshState(); } catch { /* render from the last state we have */ }
  if (signal.aborted) return;
  main.replaceChildren();
  renderChrome();
  if (!state) { main.append(h("p", { class: "muted" }, "Loading…")); return; }
  const route = currentRoute();
  const page = PAGES.find((p) => p.id === route);
  document.title = `${page.label} · Procurement audit planner`;
  try {
    if (route === "overview") renderOverview(main);
    else if (page.stage) renderStage(main, page.stage, signal);
    else if (route === "gate1") await renderGate1(main, signal);
    else if (route === "gate2") await renderGate2(main, signal);
  } catch (err) {
    main.append(h("p", { class: "run-error" }, `This page failed to render: ${err.message}`));
    console.error(err);
  }
  if (sameRoute) window.scrollTo(0, scroll); else window.scrollTo(0, 0);
}

// Keep the chrome current; re-render the page when a run starts or finishes elsewhere.
async function poll() {
  for (;;) {
    await sleep(state?.running ? 3000 : 15000);
    try {
      const prev = await refreshState();
      const was = prev?.running?.id, now = state.running?.id;
      if (was !== now && currentRoute() === "overview") renderPage();
    } catch { /* the server may be restarting */ }
  }
}

async function main() {
  initAccess();
  window.addEventListener("hashchange", renderPage);
  renderChrome();
  try {
    await refreshState();
  } catch (err) {
    $("#main").replaceChildren(h("p", { class: "run-error" }, `Could not reach the server: ${err.message}`));
    return;
  }
  renderPage();
  poll();
}

main();
