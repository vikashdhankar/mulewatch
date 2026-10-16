// MuleWatch Field Check — sends selected text / images from any page to the command center.
const DEFAULT_API = "http://localhost:8000";
const api = async () => (await chrome.storage.sync.get({ api: DEFAULT_API })).api.replace(/\/$/, "");
// the command center needs a sign-in; the extension authenticates with the shared ingest key instead
const keyHeader = async () => ({ "X-MW-Key": (await chrome.storage.sync.get({ key: "" })).key });

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "mw-text", title: "Check selected text with MuleWatch", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "mw-image", title: "Check this image with MuleWatch", contexts: ["image"] });
  chrome.contextMenus.create({ id: "mw-link", title: "Check this link with MuleWatch", contexts: ["link"] });
  chrome.contextMenus.create({ id: "mw-page", title: "Check this page with MuleWatch", contexts: ["page"] });
});

async function analyze({ text = "", imageUrl = "", pageUrl = "", title = "" }) {
  const base = await api();
  const form = new FormData();
  form.append("text", text);
  form.append("url", pageUrl);
  form.append("platform", title ? `Browser: ${new URL(pageUrl).hostname}` : "Browser extension");
  form.append("source", "extension");
  form.append("save", "true");
  if (imageUrl) {
    try {
      const blob = await (await fetch(imageUrl)).blob();
      form.append("image", blob, "capture." + (blob.type.split("/")[1] || "png"));
    } catch (e) { /* cross-origin image we can't read: fall back to text only */ }
  }
  const r = await fetch(base + "/api/analyze", { method: "POST", body: form, headers: await keyHeader() });
  if (r.status === 401) throw new Error("set the extension key (MW_INGEST_KEY) in the popup");
  if (!r.ok) throw new Error(`MuleWatch returned ${r.status}`);
  return r.json();
}

// Server fetches the link itself (public pages)
async function analyzeLink(url) {
  const r = await fetch((await api()) + "/api/analyze/url", {
    method: "POST", headers: { "Content-Type": "application/json", ...(await keyHeader()) }, body: JSON.stringify({ url, save: true }),
  });
  if (r.status === 401) throw new Error("set the extension key (MW_INGEST_KEY) in the popup");
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || `MuleWatch returned ${r.status}`);
  return d;
}

// Read the page as the investigator sees it (works on pages that need a login)
async function pageText(tabId) {
  const [{ result } = {}] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const sel = String(getSelection());
      if (sel.trim().length > 20) return sel;
      const meta = (n) => document.querySelector(`meta[property="${n}"],meta[name="${n}"]`)?.content || "";
      const main = document.querySelector("article, [role=article], main") || document.body;
      return [meta("og:title") || document.title, meta("og:description"), main.innerText].filter(Boolean).join("\n").slice(0, 5000);
    },
  });
  return result || "";
}

async function showResult(tabId, res) {
  const base = await api();
  await chrome.storage.local.set({ last: { ...res, base } });
  chrome.notifications.create(String(res.id), {
    type: "basic", iconUrl: "icon128.png",
    title: `${res.risk_level} risk · score ${Math.round(res.risk_score)}`,
    message: `${res.category}. ${(res.reasons || [])[0] || "No strong indicators."}`.slice(0, 250),
    priority: res.risk_level === "Critical" ? 2 : 0,
  });
  if (tabId) {
    chrome.scripting.executeScript({
      target: { tabId },
      args: [res.risk_level, Math.round(res.risk_score), res.category, `${base}/case/${res.id}`],
      func: (level, score, cat, link) => {
        const colors = { Critical: "#d7263d", High: "#ea7317", Medium: "#b88a00", Low: "#3f8f6b" };
        const el = document.createElement("a");
        el.href = link; el.target = "_blank";
        el.textContent = `MuleWatch: ${level} (${score}) — ${cat}. Open case`;
        Object.assign(el.style, { position: "fixed", right: "16px", bottom: "16px", zIndex: 2147483647, background: colors[level] || "#333",
          color: "#fff", padding: "10px 14px", borderRadius: "10px", font: "600 14px system-ui, sans-serif", textDecoration: "none",
          boxShadow: "0 8px 24px rgba(0,0,0,.25)" });
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 9000);
      },
    }).catch(() => {});
  }
}

chrome.notifications.onClicked.addListener(async (id) => {
  chrome.tabs.create({ url: `${await api()}/case/${id}` });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    let res;
    if (info.menuItemId === "mw-link") {
      res = await analyzeLink(info.linkUrl);
    } else if (info.menuItemId === "mw-page") {
      res = await analyze({ text: await pageText(tab.id), pageUrl: info.pageUrl || tab.url, title: tab.title || "" });
    } else {
      res = await analyze({
        text: info.menuItemId === "mw-text" ? info.selectionText : "",
        imageUrl: info.menuItemId === "mw-image" ? info.srcUrl : "",
        pageUrl: info.pageUrl || tab?.url || "", title: tab?.title || "",
      });
    }
    showResult(tab?.id, res);
  } catch (e) {
    chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title: "MuleWatch couldn't check this",
      message: `${e.message}${e.message.includes("fetch") ? ` Is the command center running at ${await api()}?` : ""}` });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "analyze") {
    analyze(msg.payload).then((res) => { showResult(msg.tabId, res); reply({ ok: true, res }); })
      .catch((e) => reply({ ok: false, error: e.message }));
    return true;
  }
});
