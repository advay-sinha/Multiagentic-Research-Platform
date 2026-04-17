"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-bg-dark">
      <div className="w-full max-w-md glass rounded-2xl border border-primary/20 p-8 space-y-6">
        <div className="text-center space-y-2">
          <div className="mx-auto size-12 rounded-xl bg-primary text-white flex items-center justify-center">
            <span className="material-symbols-outlined">auto_awesome</span>
          </div>
          <h1 className="text-2xl font-black tracking-tight">Welcome back</h1>
          <p className="text-sm text-slate-500">
            Log in to access your query history and per-user evidence cache.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Email
            </label>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-card-dark border border-border-dark rounded-lg p-3 text-sm focus:ring-1 focus:ring-primary focus:border-primary"
              placeholder="you@example.com"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-card-dark border border-border-dark rounded-lg p-3 text-sm focus:ring-1 focus:ring-primary focus:border-primary"
            />
          </div>

          {error && (
            <div className="bg-rose-500/10 border border-rose-500/20 rounded-lg p-3 text-rose-400 text-xs">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-lg font-bold text-sm flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">
              {busy ? "hourglass_top" : "login"}
            </span>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="text-center text-xs text-slate-500">
          New here?{" "}
          <Link href="/signup" className="text-primary hover:underline font-semibold">
            Create an account
          </Link>
          {"  ·  "}
          <Link href="/" className="text-slate-400 hover:text-slate-200">
            Continue as guest
          </Link>
        </div>
      </div>
    </div>
  );
}
