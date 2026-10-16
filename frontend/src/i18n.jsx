import { createContext, useCallback, useContext, useEffect, useState } from "react";
import HI from "./hi.json";

/* English text is the key: t("Cases") returns the Hindi when Hindi is on, else the English.
   Placeholders: t("{n} cases", { n: 4 }). Missing translations fall back to English; the build check
   (scripts/check-i18n.mjs) lists any t("…") string without a Hindi entry. */

const LangCtx = createContext({ lang: "en", setLang: () => {}, t: (s) => s });
const KEY = "mw_lang";
const current = { lang: "en" };

function fill(s, vars) {
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`)) : s;
}

/** Translate outside a component (helpers such as timeAgo). Components should use useT(). */
export function tr(s, vars) {
  return fill(current.lang === "hi" ? (HI[s] ?? s) : s, vars);
}

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem(KEY) || "en"; } catch { return "en"; }
  });
  current.lang = lang;
  useEffect(() => { document.documentElement.lang = lang === "hi" ? "hi" : "en"; }, [lang]);
  const setLang = useCallback((l) => {
    setLangState(l);
    try { localStorage.setItem(KEY, l); } catch { /* private window */ }
  }, []);
  const t = useCallback((s, vars) => fill(lang === "hi" ? (HI[s] ?? s) : s, vars), [lang]);
  return <LangCtx.Provider value={{ lang, setLang, t }}>{children}</LangCtx.Provider>;
}

export const useT = () => useContext(LangCtx);

export function LangSwitch() {
  const { lang, setLang } = useT();
  return (
    <div className="seg lang-switch" role="group" aria-label="Language / भाषा">
      <button className={`seg-btn${lang === "en" ? " on-indigo" : ""}`} onClick={() => setLang("en")} aria-pressed={lang === "en"}>EN</button>
      <button className={`seg-btn${lang === "hi" ? " on-indigo" : ""}`} onClick={() => setLang("hi")} aria-pressed={lang === "hi"} lang="hi">हिं</button>
    </div>
  );
}

/** A translated sentence with React elements inside it:
    <T k="Use {link} to change it." link={<Link to="/x">{t("My account")}</Link>} /> */
export function T({ k, ...parts }) {
  const { t } = useT();
  const s = t(k);
  const out = [];
  let last = 0;
  s.replace(/\{(\w+)\}/g, (m, name, at) => {
    out.push(s.slice(last, at));
    out.push(parts[name] !== undefined ? <span key={at}>{parts[name]}</span> : m);
    last = at + m.length;
    return m;
  });
  out.push(s.slice(last));
  return <>{out}</>;
}
