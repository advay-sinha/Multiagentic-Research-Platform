"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export type AuthUser = {
  user_id: string;
  email: string;
  name: string;
};

type AuthState = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  authHeaders: () => Record<string, string>;
};

const AuthContext = createContext<AuthState | null>(null);

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const STORAGE_KEY = "mars.auth.v1";

type StoredAuth = { token: string; user: AuthUser };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Hydrate from localStorage on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as StoredAuth;
        setToken(parsed.token);
        setUser(parsed.user);
      }
    } catch {
      // ignore corrupt blob
    } finally {
      setLoading(false);
    }
  }, []);

  const persist = useCallback((t: string, u: AuthUser) => {
    setToken(t);
    setUser(u);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: t, user: u }));
    } catch {
      // storage full / unavailable — keep in memory only
    }
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch(`${API_BASE}/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(extractErr(body) || `Login failed (${res.status})`);
      }
      const data = (await res.json()) as { access_token: string; user: AuthUser };
      persist(data.access_token, data.user);
    },
    [persist]
  );

  const signup = useCallback(
    async (email: string, password: string, name?: string) => {
      const res = await fetch(`${API_BASE}/v1/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, name }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(extractErr(body) || `Signup failed (${res.status})`);
      }
      const data = (await res.json()) as { access_token: string; user: AuthUser };
      persist(data.access_token, data.user);
    },
    [persist]
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }, []);

  const authHeaders = useCallback((): Record<string, string> => {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [token]);

  return (
    <AuthContext.Provider
      value={{ user, token, loading, login, signup, logout, authHeaders }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

function extractErr(body: string): string | null {
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed?.detail === "string") return parsed.detail;
    if (typeof parsed?.error?.message === "string") return parsed.error.message;
  } catch {
    // not JSON
  }
  return null;
}
