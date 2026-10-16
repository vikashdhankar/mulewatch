import { tr } from "./i18n";

async function req(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (r.status === 401 && !path.startsWith("/api/auth/login")) {
    window.dispatchEvent(new Event("mw:signed-out"));
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const d = await r.json(); msg = d.detail || msg; } catch { /* not json */ }
    const e = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    e.status = r.status;
    throw e;
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}

const json = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const qs = (params = {}) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null && v !== false));

/** POST that returns a file: downloads it with the server's file name. */
async function download(path, body) {
  const r = await fetch(path, { credentials: "same-origin", ...(body ? json("POST", body) : {}) });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch { /* binary */ }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") || "")?.[1] || "download";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return { name, sha: r.headers.get("x-pack-sha256") };
}

export const api = {
  // auth & users
  me: () => req("/api/auth/me"),
  login: (username, password) => req("/api/auth/login", json("POST", { username, password })),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  changePassword: (old, nw) => req("/api/auth/password", json("POST", { old, new: nw })),
  telegramCode: () => req("/api/auth/telegram-code", { method: "POST" }),
  telegramUnlink: () => req("/api/auth/telegram", { method: "DELETE" }),
  users: () => req("/api/users"),
  createUser: (u) => req("/api/users", json("POST", u)),
  updateUser: (id, data) => req(`/api/users/${id}`, json("PATCH", data)),
  resetPassword: (id, password) => req(`/api/users/${id}/reset-password`, json("POST", { password })),

  // cases
  stats: () => req("/api/stats"),
  posts: (params = {}) => req("/api/posts?" + qs(params)),
  post: (id) => req(`/api/posts/${id}`),
  police: (id) => req(`/api/posts/${id}/police`),
  updateCase: (id, data) => req(`/api/posts/${id}/case`, json("PATCH", data)),
  feedback: (id, label) => req(`/api/posts/${id}/feedback`, json("POST", { label })),
  takedown: (id) => req(`/api/posts/${id}/takedown`, { method: "POST" }),
  draft: (id, kind, lang, bank) => req(`/api/posts/${id}/drafts/${kind}?` + qs({ lang, bank })),
  exportDraft: (id, kind, body) => download(`/api/posts/${id}/drafts/${kind}/export`, body),
  evidencePack: (id) => download(`/api/posts/${id}/evidence-pack.zip`),
  evidenceFile: (id, fid) => download(`/api/posts/${id}/evidence/${fid}`),
  clocks: () => req("/api/clocks"),
  analyze: (form) => req("/api/analyze", { method: "POST", body: form }),
  analyzeUrl: (url, save) => req("/api/analyze/url", json("POST", { url, save })),
  graph: (params = {}) => req("/api/graph?" + qs(params)),
  alerts: () => req("/api/alerts"),
  alertsSeen: () => req("/api/alerts/seen", { method: "POST" }),

  // complaints, map, audit, brief
  complaints: () => req("/api/complaints"),
  uploadComplaints: (file) => { const f = new FormData(); f.append("file", file); return req("/api/complaints/upload", { method: "POST", body: f }); },
  importComplaints: (token, mapping, label) => req("/api/complaints/import", json("POST", { token, mapping, label })),
  deleteImport: (id) => req(`/api/complaints/imports/${id}`, { method: "DELETE" }),
  districts: () => req("/api/districts"),
  briefUrl: (lang, hours, district) => "/api/brief.pdf?" + qs({ lang, hours, district }),
  audit: (params = {}) => req("/api/audit?" + qs(params)),
  auditVerify: () => req("/api/audit/verify"),
  briefSchedule: () => req("/api/brief/schedule"),
  briefSend: (lang) => req("/api/brief/send", json("POST", { lang })),

  // bulk link checks
  bulkJobs: () => req("/api/bulk"),
  bulkJob: (id) => req(`/api/bulk/${id}`),
  bulkCreate: (text, label) => req("/api/bulk", json("POST", { text, label })),
  bulkUpload: (file, label) => { const f = new FormData(); f.append("file", file); f.append("label", label || ""); return req("/api/bulk/upload", { method: "POST", body: f }); },
  bulkCancel: (id) => req(`/api/bulk/${id}/cancel`, { method: "POST" }),

  // monitoring
  watchlist: () => req("/api/watchlist"),
  addWatch: (kind, value, note = "") => req("/api/watchlist", json("POST", { kind, value, note })),
  delWatch: (id) => req(`/api/watchlist/${id}`, { method: "DELETE" }),
  sources: () => req("/api/sources"),
  addSource: (kind, url, name) => req("/api/sources", json("POST", { kind, url, name })),
  toggleSource: (id, enabled) => req(`/api/sources/${id}`, json("PATCH", { enabled })),
  crawl: () => req("/api/crawl", { method: "POST" }),
  bot: () => req("/api/bot"),
  unlinkAlerts: () => req("/api/bot/alerts", { method: "DELETE" }),
};

export const LEVELS = ["Critical", "High", "Medium", "Low"];
export const ROLE_LABEL = { ANALYST: "Analyst", IO: "Investigating Officer", SUPERVISOR: "Supervisor" };
export const STATUS = {
  NEW: "New", VERIFIED: "Verified", NOTICE_DRAFTED: "Notice drafted", NOTICE_SENT: "Notice sent",
  CONTENT_REMOVED: "Content removed", FIR_LINKED: "Linked to FIR", CLOSED_NO_ACTION: "Closed – no action",
};
export const RANK = { ANALYST: 0, IO: 1, SUPERVISOR: 2 };
export const can = (me, role) => !!me && RANK[me.role] >= RANK[role];

export function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime()) / 1000);
  if (s < 45) return tr("just now");
  if (s < 3600) return tr("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400) return tr("{n} h ago", { n: Math.round(s / 3600) });
  return tr("{n} d ago", { n: Math.round(s / 86400) });
}

export function istTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function inr(n) {
  return "₹" + Math.round(n || 0).toLocaleString("en-IN");
}

export const caseId = (id) => `MW-${String(id).padStart(5, "0")}`;
