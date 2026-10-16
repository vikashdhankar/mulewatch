import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [me, setMe] = useState(undefined);      // undefined = checking, null = signed out
  const refresh = useCallback(() => api.me().then(setMe).catch(() => setMe(null)), []);

  useEffect(() => {
    refresh();
    const out = () => setMe(null);
    window.addEventListener("mw:signed-out", out);
    return () => window.removeEventListener("mw:signed-out", out);
  }, [refresh]);

  const login = async (u, p) => { await api.login(u, p); await refresh(); };
  const logout = async () => { try { await api.logout(); } finally { setMe(null); } };

  return <AuthCtx.Provider value={{ me, login, logout, refresh }}>{children}</AuthCtx.Provider>;
}
