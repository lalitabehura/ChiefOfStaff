import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken, setSessionLostHandler, type TokenOut, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, extra?: { mfa_code?: string; recovery_code?: string }) => Promise<void>;
  register: (email: string, password: string, full_name: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setSessionLostHandler(() => setUser(null));
    refreshSession()
      .then((d) => setUser(d?.user ?? null))
      .finally(() => setLoading(false));
  }, []);

  const accept = (d: TokenOut) => {
    setAccessToken(d.access_token);
    setUser(d.user);
  };

  const login = useCallback<AuthState["login"]>(async (email, password, extra = {}) => {
    accept(await api<TokenOut>("/auth/login", { method: "POST", body: { email, password, ...extra }, retry: false }));
  }, []);

  const register = useCallback<AuthState["register"]>(async (email, password, full_name) => {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    accept(await api<TokenOut>("/auth/register", { method: "POST", body: { email, password, full_name, timezone } }));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", retry: false });
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, setUser }}>{children}</AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
