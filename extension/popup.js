const $ = (id) => document.getElementById(id);

function render(res) {
  const out = $("out");
  out.innerHTML = "";
  const box = document.createElement("div");
  box.className = `res ${res.risk_level}`;
  const head = document.createElement("div");
  head.innerHTML = `<b></b> <span></span>`;
  head.querySelector("b").textContent = `${res.risk_level} · ${Math.round(res.risk_score)}`;
  head.querySelector("span").textContent = res.category;
  const why = document.createElement("div");
  why.textContent = (res.reasons || [])[0] || "No strong indicators of account or card selling.";
  const link = document.createElement("a");
  link.href = `${res.base || $("api").value}/case/${res.id}`; link.target = "_blank"; link.textContent = "Open case in command center";
  box.append(head, why, link);
  out.append(box);
}

chrome.storage.sync.get({ api: "http://localhost:8000", key: "" }, ({ api, key }) => { $("api").value = api; $("key").value = key; });
$("key").addEventListener("change", () => chrome.storage.sync.set({ key: $("key").value.trim() }));
chrome.storage.local.get("last", ({ last }) => { if (last) render(last); });
$("api").addEventListener("change", () => chrome.storage.sync.set({ api: $("api").value.trim() }));

async function send(text, pageUrl, tabId) {
  $("out").textContent = "Checking…";
  chrome.runtime.sendMessage({ type: "analyze", tabId, payload: { text, pageUrl, title: "popup" } }, (r) => {
    if (r?.ok) render({ ...r.res, base: $("api").value });
    else $("out").textContent = "Couldn't reach MuleWatch: " + (r?.error || "unknown error");
  });
}

$("check").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if ($("text").value.trim()) send($("text").value, tab?.url || "", tab?.id);
});

$("page").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const [{ result } = {}] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => String(getSelection()) || document.title });
  $("text").value = result || "";
  if (result) send(result, tab.url, tab.id);
});
