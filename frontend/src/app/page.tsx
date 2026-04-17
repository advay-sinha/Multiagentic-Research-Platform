"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { useAuth } from "@/lib/auth";

gsap.registerPlugin(useGSAP);

// ─── Types ──────────────────────────────────────────────────────────────────

type Citation = {
  citation_id: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string;
  snippet: string;
  chunk_start: number;
  chunk_end: number;
  answer_span_start?: number;
  answer_span_end?: number;
};

type TraceEvent = {
  event_id: string;
  agent: string;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

type ClaimVerification = {
  claim_id: string;
  claim_text: string;
  verdict: string;
  evidence_chunk_ids: string[];
  confidence: number;
  notes: string;
};

type StageMetrics = {
  stage: string;
  duration_ms: number;
};

type QueryMetrics = {
  total_duration_ms: number;
  stages: StageMetrics[];
  evidence_count: number;
  citation_count: number;
  claim_count: number;
};

type QueryResponse = {
  answer_id: string;
  query: string;
  answer: string;
  citations: Citation[];
  claim_verifications: ClaimVerification[];
  confidence_score: number;
  refusal: boolean;
  trace_id: string;
  metrics: QueryMetrics;
};

type StreamEvent = {
  event?: string;
  data?: string;
};

type View = "chat" | "sources" | "metrics";

// ─── Constants ───────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const PIPELINE_STAGES = ["Planner", "Retriever", "Writer", "Critic", "Verifier"] as const;

// ─── Synthetic Fallback Data ─────────────────────────────────────────────────
// Used when LLM API requests fail or no query run yet. Keeps dashboard legible.

const SYNTHETIC_METRICS: QueryMetrics = {
  total_duration_ms: 8420,
  stages: [
    { stage: "Planner", duration_ms: 640 },
    { stage: "Retriever", duration_ms: 2180 },
    { stage: "Writer", duration_ms: 3150 },
    { stage: "Critic", duration_ms: 1280 },
    { stage: "Verifier", duration_ms: 1170 },
  ],
  evidence_count: 12,
  citation_count: 6,
  claim_count: 4,
};

const SYNTHETIC_RESPONSE: QueryResponse = {
  answer_id: "synthetic-answer-0001",
  query: "(demo) What are the latest advances in retrieval-augmented generation?",
  answer: "",
  citations: [],
  claim_verifications: [
    {
      claim_id: "c1",
      claim_text: "RAG systems reduce hallucination vs. closed-book LLMs.",
      verdict: "Supported",
      evidence_chunk_ids: ["e1", "e2"],
      confidence: 0.86,
      notes: "Demo: multiple sources attest to grounding benefits.",
    },
    {
      claim_id: "c2",
      claim_text: "Hybrid retrieval outperforms dense-only on long-tail queries.",
      verdict: "Partial",
      evidence_chunk_ids: ["e3"],
      confidence: 0.61,
      notes: "Demo: supported for some domains, mixed for others.",
    },
    {
      claim_id: "c3",
      claim_text: "Reranking is unnecessary with strong embeddings.",
      verdict: "Unsupported",
      evidence_chunk_ids: [],
      confidence: 0.22,
      notes: "Demo: evidence contradicts this claim.",
    },
    {
      claim_id: "c4",
      claim_text: "Claim-level verification improves end-user trust.",
      verdict: "Supported",
      evidence_chunk_ids: ["e4"],
      confidence: 0.78,
      notes: "Demo: UX studies report measurable gains.",
    },
  ],
  confidence_score: 0.74,
  refusal: false,
  trace_id: "synthetic-trace-0001",
  metrics: SYNTHETIC_METRICS,
};

// ─── SSE Parsing ─────────────────────────────────────────────────────────────

function parseSseChunk(buffer: string): { events: StreamEvent[]; rest: string } {
  const events: StreamEvent[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const part of parts) {
    const lines = part.split("\n");
    const event: StreamEvent = {};
    for (const line of lines) {
      if (line.startsWith("event:")) {
        event.event = line.replace("event:", "").trim();
      } else if (line.startsWith("data:")) {
        event.data = line.replace("data:", "").trim();
      }
    }
    events.push(event);
  }
  return { events, rest };
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

function Sidebar({
  activeView,
  onViewChange,
  isLoading,
  onRunResearch,
  onIngest,
}: {
  activeView: View;
  onViewChange: (v: View) => void;
  isLoading: boolean;
  onRunResearch: () => void;
  onIngest: () => void;
}) {
  const { user, logout } = useAuth();
  const navItems: { view: View; icon: string; label: string }[] = [
    { view: "chat", icon: "chat_bubble", label: "Research Chat" },
    { view: "sources", icon: "fact_check", label: "Sources & Verify" },
    { view: "metrics", icon: "monitoring", label: "System Metrics" },
  ];

  const sidebarRef = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out", clearProps: "transform,opacity" } });
      tl.fromTo(
        ".sidebar-logo",
        { x: -30, opacity: 0 },
        { x: 0, opacity: 1, duration: 0.6 }
      )
        .fromTo(
          ".sidebar-nav-btn",
          { x: -20, opacity: 0 },
          { x: 0, opacity: 1, duration: 0.45, stagger: 0.08 },
          "-=0.3"
        )
        .fromTo(
          ".sidebar-cta",
          { y: 20, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.45, stagger: 0.08 },
          "-=0.2"
        );

      gsap.to(".sidebar-logo-icon", {
        boxShadow: "0 0 24px rgba(131,89,248,0.55)",
        duration: 1.6,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
    },
    { scope: sidebarRef }
  );

  return (
    <aside
      ref={sidebarRef}
      className="w-64 border-r border-border-dark bg-card-dark flex flex-col shrink-0"
    >
      {/* Logo */}
      <div className="sidebar-logo p-6 flex items-center gap-3">
        <div className="sidebar-logo-icon size-10 bg-primary rounded-lg flex items-center justify-center text-white shrink-0">
          <span className="material-symbols-outlined">auto_awesome</span>
        </div>
        <div>
          <h1 className="font-bold text-sm tracking-tight">MARs</h1>
          <p className="text-[10px] text-slate-500 font-mono">v0.1.0</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-4 space-y-1">
        {navItems.map(({ view, icon, label }) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`sidebar-nav-btn w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors ${
              activeView === view
                ? "bg-primary/10 text-primary border border-primary/20"
                : "text-slate-400 hover:bg-white/5"
            }`}
          >
            <span className="material-symbols-outlined text-[20px]">{icon}</span>
            {label}
          </button>
        ))}
      </nav>

      {/* Ingest + Run Research */}
      <div className="p-4 border-t border-border-dark space-y-2">
        <button
          onClick={onIngest}
          className="sidebar-cta w-full py-3 bg-card-dark hover:bg-white/5 text-slate-200 rounded font-bold text-sm transition-all flex items-center justify-center gap-2 border border-border-dark hover:border-primary/40"
        >
          <span className="material-symbols-outlined text-[18px]">library_add</span>
          Ingest Sources
        </button>
        <button
          onClick={onRunResearch}
          disabled={isLoading}
          className="sidebar-cta w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white rounded font-bold text-sm transition-all flex items-center justify-center gap-2"
        >
          <span className="material-symbols-outlined text-[18px]">
            {isLoading ? "hourglass_top" : "add_circle"}
          </span>
          {isLoading ? "Running…" : "Run Research"}
        </button>
      </div>

      {/* Auth footer */}
      <div className="p-4 border-t border-border-dark">
        {user ? (
          <div className="flex items-center gap-2">
            <div className="size-8 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-xs shrink-0">
              {user.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold truncate">{user.name}</p>
              <p className="text-[10px] text-slate-500 truncate">{user.email}</p>
            </div>
            <button
              onClick={logout}
              title="Log out"
              className="size-8 rounded-lg text-slate-400 hover:bg-white/5 flex items-center justify-center"
            >
              <span className="material-symbols-outlined text-[16px]">logout</span>
            </button>
          </div>
        ) : (
          <div className="flex gap-2">
            <Link
              href="/login"
              className="flex-1 py-2 text-center bg-card-dark border border-border-dark hover:border-primary/40 rounded text-xs font-bold text-slate-200"
            >
              Log in
            </Link>
            <Link
              href="/signup"
              className="flex-1 py-2 text-center bg-primary/10 border border-primary/20 hover:bg-primary/20 rounded text-xs font-bold text-primary"
            >
              Sign up
            </Link>
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── Agent Trace Sidebar ──────────────────────────────────────────────────────

function AgentTraceSidebar({
  traceEvents,
  metrics,
  isLoading,
}: {
  traceEvents: TraceEvent[];
  metrics: QueryMetrics | null;
  isLoading: boolean;
}) {
  const completedAgents = new Set(traceEvents.map((e) => e.agent.toLowerCase()));

  function stageStatus(stage: string): "done" | "active" | "pending" {
    const key = stage.toLowerCase();
    if (completedAgents.has(key)) return "done";
    if (isLoading) {
      // first stage not yet completed
      for (const s of PIPELINE_STAGES) {
        if (!completedAgents.has(s.toLowerCase())) {
          return s.toLowerCase() === key ? "active" : "pending";
        }
      }
    }
    return "pending";
  }

  const stageNote: Record<string, string> = {
    Planner: "Decomposing query into sub-tasks.",
    Retriever: "Querying vector database for evidence.",
    Writer: "Synthesizing findings and citations.",
    Critic: "Evaluating draft for gaps.",
    Verifier: "Cross-checking claims against sources.",
  };

  const stageEventNote = (stage: string): string => {
    const ev = [...traceEvents].reverse().find(
      (e) => e.agent.toLowerCase() === stage.toLowerCase()
    );
    if (ev?.payload?.message && typeof ev.payload.message === "string") {
      return ev.payload.message;
    }
    return stageNote[stage] ?? "";
  };

  const traceRef = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      gsap.fromTo(
        ".trace-stage",
        { x: 24, opacity: 0 },
        {
          x: 0,
          opacity: 1,
          duration: 0.5,
          stagger: 0.08,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
      gsap.fromTo(
        ".trace-perf",
        { y: 20, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.5,
          delay: 0.4,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: traceRef }
  );

  useGSAP(
    () => {
      gsap.fromTo(
        ".trace-dot-active",
        { scale: 0.85 },
        {
          scale: 1.15,
          duration: 0.7,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
          transformOrigin: "50% 50%",
        }
      );
      gsap.fromTo(
        ".trace-dot-done",
        { scale: 0 },
        {
          scale: 1,
          duration: 0.4,
          ease: "back.out(2)",
          transformOrigin: "50% 50%",
          clearProps: "transform",
        }
      );
      gsap.fromTo(
        ".trace-progress-done",
        { scaleX: 0 },
        {
          scaleX: 1,
          duration: 0.7,
          ease: "power3.out",
          transformOrigin: "0% 50%",
          clearProps: "transform",
        }
      );
      gsap.to(".trace-progress-active", {
        xPercent: 200,
        duration: 1.2,
        repeat: -1,
        ease: "sine.inOut",
      });
    },
    { scope: traceRef, dependencies: [traceEvents.length, isLoading] }
  );

  return (
    <aside
      ref={traceRef}
      className="w-72 border-l border-border-dark bg-card-dark/50 overflow-y-auto p-5 hidden xl:flex flex-col gap-6"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-[10px] uppercase tracking-widest text-slate-500">
          Agent Trace
        </h3>
        <span className="material-symbols-outlined text-slate-500 text-[18px]">
          account_tree
        </span>
      </div>

      {/* Pipeline timeline */}
      <div className="relative space-y-6 before:content-[''] before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-px before:bg-border-dark">
        {PIPELINE_STAGES.map((stage) => {
          const status = stageStatus(stage);
          return (
            <div
              key={stage}
              className={`trace-stage relative pl-8 ${status === "pending" ? "opacity-40" : ""}`}
            >
              {/* Dot */}
              <div
                className={`absolute left-0 top-0 size-6 rounded-full flex items-center justify-center z-10 ${
                  status === "done"
                    ? "trace-dot-done bg-green-500/20 border-2 border-green-500"
                    : status === "active"
                    ? "trace-dot-active bg-primary/20 border-2 border-primary"
                    : "bg-slate-800 border-2 border-slate-700"
                }`}
              >
                {status === "done" ? (
                  <span className="material-symbols-outlined text-[13px] text-green-500">check</span>
                ) : status === "active" ? (
                  <div className="size-2 rounded-full bg-primary animate-ping" />
                ) : (
                  <div className="size-1.5 rounded-full bg-slate-600" />
                )}
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between items-center">
                  <h4
                    className={`text-sm font-semibold ${
                      status === "active" ? "text-primary" : ""
                    }`}
                  >
                    {stage}
                  </h4>
                  {status === "active" && (
                    <span className="text-[10px] text-primary font-mono">Active</span>
                  )}
                  {status === "done" && metrics && (
                    <span className="text-[10px] text-slate-500 font-mono">
                      {(
                        (metrics.stages.find((s) => s.stage.toLowerCase() === stage.toLowerCase())
                          ?.duration_ms ?? 0) / 1000
                      ).toFixed(1)}
                      s
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 leading-snug">{stageEventNote(stage)}</p>

                {/* Progress bar per agent */}
                <div className="relative h-1.5 w-full rounded-full bg-slate-800/60 overflow-hidden">
                  {status === "done" && (
                    <div className="trace-progress-done absolute inset-y-0 left-0 bg-gradient-to-r from-green-500/70 to-emerald-400 rounded-full w-full" />
                  )}
                  {status === "active" && (
                    <div className="trace-progress-active absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-primary/40 via-primary to-primary/40 rounded-full" />
                  )}
                  {status === "pending" && (
                    <div className="absolute inset-y-0 left-0 w-0 bg-slate-700 rounded-full" />
                  )}
                </div>
                <div className="flex justify-between text-[9px] font-mono text-slate-500">
                  <span>
                    {status === "done" ? "100%" : status === "active" ? "Running" : "Queued"}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Performance stats — synthetic fallback when metrics missing */}
      {(() => {
        const perf = metrics ?? SYNTHETIC_METRICS;
        const isSynthetic = !metrics;
        return (
          <div className="trace-perf glass p-4 rounded-xl space-y-3 mt-auto">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase font-bold text-slate-500">Performance</span>
              {isSynthetic && (
                <span className="text-[9px] uppercase font-bold text-amber-500/80 bg-amber-500/10 px-1.5 py-0.5 rounded">
                  Synthetic
                </span>
              )}
            </div>
            <div className={`grid grid-cols-2 gap-2 ${isSynthetic ? "opacity-60" : ""}`}>
              <div className="p-2 bg-white/5 rounded-lg border border-white/5">
                <p className="text-[9px] text-slate-500 uppercase font-bold">Latency</p>
                <p className="text-sm font-bold">
                  {(perf.total_duration_ms / 1000).toFixed(1)}s
                </p>
              </div>
              <div className="p-2 bg-white/5 rounded-lg border border-white/5">
                <p className="text-[9px] text-slate-500 uppercase font-bold">Sources</p>
                <p className="text-sm font-bold">{perf.evidence_count}</p>
              </div>
              <div className="p-2 bg-white/5 rounded-lg border border-white/5">
                <p className="text-[9px] text-slate-500 uppercase font-bold">Citations</p>
                <p className="text-sm font-bold">{perf.citation_count}</p>
              </div>
              <div className="p-2 bg-white/5 rounded-lg border border-white/5">
                <p className="text-[9px] text-slate-500 uppercase font-bold">Claims</p>
                <p className="text-sm font-bold">{perf.claim_count}</p>
              </div>
            </div>
          </div>
        );
      })()}
    </aside>
  );
}

// ─── Verification Table ───────────────────────────────────────────────────────

function VerificationTable({ verifications }: { verifications: ClaimVerification[] }) {
  function verdictStyle(verdict: string) {
    const v = verdict.toLowerCase();
    if (v.includes("support")) return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
    if (v.includes("unsupport") || v.includes("contradict") || v.includes("false"))
      return "bg-rose-500/10 text-rose-500 border-rose-500/20";
    if (v.includes("partial")) return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    return "bg-slate-700/40 text-slate-400 border-slate-700/40";
  }

  function verdictIcon(verdict: string) {
    const v = verdict.toLowerCase();
    if (v.includes("support")) return "check_circle";
    if (v.includes("unsupport") || v.includes("contradict") || v.includes("false"))
      return "cancel";
    if (v.includes("partial")) return "warning";
    return "help";
  }

  const tableRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (verifications.length === 0) return;
      gsap.fromTo(
        ".verify-row",
        { y: 14, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.4,
          stagger: 0.06,
          ease: "power2.out",
          clearProps: "transform,opacity",
        }
      );
      gsap.fromTo(
        ".verify-badge",
        { scale: 0.6, opacity: 0 },
        {
          scale: 1,
          opacity: 1,
          duration: 0.4,
          stagger: 0.05,
          ease: "back.out(2)",
          transformOrigin: "50% 50%",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: tableRef, dependencies: [verifications.length] }
  );

  if (verifications.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        No verification data yet. Run a query to see claim analysis.
      </div>
    );
  }

  const supported = verifications.filter((v) => v.verdict.toLowerCase().includes("support")).length;
  const unsupported = verifications.filter(
    (v) => v.verdict.toLowerCase().includes("unsupport") || v.verdict.toLowerCase().includes("contradict")
  ).length;
  const partial = verifications.filter((v) => v.verdict.toLowerCase().includes("partial")).length;

  return (
    <div ref={tableRef} className="flex-1 flex flex-col gap-3 overflow-hidden">
      {/* Summary badges */}
      <div className="flex items-center gap-3 px-1 shrink-0">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Verification Table
        </h2>
        <div className="flex gap-2">
          {supported > 0 && (
            <span className="flex items-center gap-1 bg-emerald-500/10 text-emerald-500 px-2 py-0.5 rounded text-[10px] font-bold">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              {supported} Supported
            </span>
          )}
          {unsupported > 0 && (
            <span className="flex items-center gap-1 bg-rose-500/10 text-rose-500 px-2 py-0.5 rounded text-[10px] font-bold">
              <span className="size-1.5 rounded-full bg-rose-500" />
              {unsupported} Unsupported
            </span>
          )}
          {partial > 0 && (
            <span className="flex items-center gap-1 bg-amber-500/10 text-amber-500 px-2 py-0.5 rounded text-[10px] font-bold">
              <span className="size-1.5 rounded-full bg-amber-500" />
              {partial} Partial
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-hidden glass rounded-xl border border-primary/20 flex flex-col">
        <div className="grid grid-cols-12 border-b border-primary/10 bg-slate-900/40 text-[11px] font-bold text-slate-400 uppercase tracking-tight shrink-0">
          <div className="col-span-4 p-3 border-r border-primary/10">Claim</div>
          <div className="col-span-5 p-3 border-r border-primary/10">Notes / Evidence</div>
          <div className="col-span-1 p-3 border-r border-primary/10 text-center">Conf</div>
          <div className="col-span-2 p-3">Status</div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {verifications.map((v) => (
            <div
              key={v.claim_id}
              className="verify-row grid grid-cols-12 border-b border-primary/5 hover:bg-primary/5 transition-colors"
            >
              <div className="col-span-4 p-3 border-r border-primary/10 text-xs leading-relaxed font-medium">
                {v.claim_text}
              </div>
              <div className="col-span-5 p-3 border-r border-primary/10 text-xs leading-relaxed italic text-slate-400 bg-slate-50/5">
                {v.notes || "—"}
              </div>
              <div className="col-span-1 p-3 border-r border-primary/10 flex items-center justify-center">
                <span className="font-mono text-[10px] text-slate-400">
                  {(v.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="col-span-2 p-3 flex items-center">
                <span
                  className={`verify-badge flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold border ${verdictStyle(v.verdict)}`}
                >
                  <span className="material-symbols-outlined text-[12px]">
                    {verdictIcon(v.verdict)}
                  </span>
                  {v.verdict}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Citations Panel ──────────────────────────────────────────────────────────

function CitationsPanel({ citations }: { citations: Citation[] }) {
  const citationsRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (citations.length === 0) return;
      gsap.fromTo(
        ".citation-card",
        { x: -20, opacity: 0 },
        {
          x: 0,
          opacity: 1,
          duration: 0.45,
          stagger: 0.08,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: citationsRef, dependencies: [citations.length] }
  );

  if (citations.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        No sources retrieved yet. Run a query first.
      </div>
    );
  }

  function scoreColor(idx: number) {
    if (idx === 0) return "text-emerald-500";
    if (idx === 1) return "text-emerald-500";
    if (idx <= 3) return "text-amber-500";
    return "text-slate-400";
  }

  return (
    <div ref={citationsRef} className="flex flex-col gap-3 overflow-y-auto pr-1">
      {citations.map((c, i) => (
        <div
          key={c.citation_id}
          className="citation-card glass rounded-xl p-4 hover:border-primary/40 hover:-translate-y-0.5 transition-all cursor-pointer group"
        >
          <div className="flex justify-between items-start mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-primary bg-primary/10 px-2 py-0.5 rounded">
                #{String(i + 1).padStart(2, "0")}
              </span>
            </div>
            <span className={`text-xs font-bold ${scoreColor(i)}`}>
              {c.source_id || "—"}
            </span>
          </div>
          <h3 className="font-bold text-sm mb-2 group-hover:text-primary transition-colors leading-snug">
            {c.title || c.url}
          </h3>
          {c.snippet && (
            <p className="text-xs text-slate-400 line-clamp-3 mb-3 leading-relaxed italic">
              &ldquo;{c.snippet}&rdquo;
            </p>
          )}
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            {c.published_at && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[12px]">calendar_today</span>
                {c.published_at}
              </span>
            )}
            {c.url && (
              <a
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 hover:text-primary transition-colors"
              >
                <span className="material-symbols-outlined text-[12px]">language</span>
                <span className="truncate max-w-[120px]">{c.url.replace(/^https?:\/\//, "")}</span>
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Metrics Dashboard ────────────────────────────────────────────────────────

type RecallPoint = {
  t: number;
  recall: number;
  latency_s: number;
};

const SYNTHETIC_RECALL: RecallPoint[] = [
  { t: 0, recall: 0.62, latency_s: 9.2 },
  { t: 1, recall: 0.71, latency_s: 8.4 },
  { t: 2, recall: 0.68, latency_s: 7.9 },
  { t: 3, recall: 0.77, latency_s: 8.1 },
  { t: 4, recall: 0.82, latency_s: 7.5 },
  { t: 5, recall: 0.79, latency_s: 7.8 },
];

function MetricsDashboard({
  metrics,
  finalResponse,
  recallHistory,
}: {
  metrics: QueryMetrics | null;
  finalResponse: QueryResponse | null;
  recallHistory: RecallPoint[];
}) {
  // Skeleton fallback: if LLM/API fails or no query run yet, render synthetic data
  // so dashboard is legible by default instead of an empty state.
  const isSynthetic = !metrics || !finalResponse;
  const activeMetrics: QueryMetrics = metrics ?? SYNTHETIC_METRICS;
  const activeResponse = finalResponse ?? SYNTHETIC_RESPONSE;
  const activeRecall = recallHistory.length >= 2 ? recallHistory : SYNTHETIC_RECALL;

  const totalClaims = activeResponse.claim_verifications.length;
  const supportedClaims = activeResponse.claim_verifications.filter((v) =>
    v.verdict.toLowerCase().includes("support") && !v.verdict.toLowerCase().includes("unsupport")
  ).length;
  const claimsWithEvidence = activeResponse.claim_verifications.filter(
    (v) => v.evidence_chunk_ids.length > 0
  ).length;

  // Agent hallucination rate: fraction of claims the agent produced that are
  // factually incorrect, fabricated, or not supported by retrieved evidence.
  // A claim counts as hallucinated when ANY of the following is true:
  //   1. verdict is explicitly unsupported / partial / contradicted / false / refuted
  //   2. verdict claims "supported" but no evidence_chunk_ids were attached
  //      (fabricated citation — agent asserted grounding that doesn't exist)
  //   3. confidence < 0.5 — agent's own verifier flagged low conviction
  const hallucinatedClaims = activeResponse.claim_verifications.filter((v) => {
    const t = v.verdict.toLowerCase();
    const badVerdict =
      t.includes("unsupport") ||
      t.includes("partial") ||
      t.includes("contradict") ||
      t.includes("refut") ||
      t.includes("false");
    const fabricated = t.includes("support") && !t.includes("unsupport") && v.evidence_chunk_ids.length === 0;
    const lowConfidence = typeof v.confidence === "number" && v.confidence < 0.5;
    return badVerdict || fabricated || lowConfidence;
  }).length;

  const faithfulnessPct = totalClaims > 0 ? (supportedClaims / totalClaims) * 100 : 0;
  const citationCoveragePct = totalClaims > 0 ? (claimsWithEvidence / totalClaims) * 100 : 0;
  const hallucinationPct = totalClaims > 0 ? (hallucinatedClaims / totalClaims) * 100 : 0;

  const dashRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const tl = gsap.timeline({
        defaults: { ease: "power3.out", clearProps: "transform,opacity" },
      });
      tl.fromTo(
        ".dash-header",
        { y: -16, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.5 }
      )
        .fromTo(
          ".dash-card",
          { y: 28, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.5, stagger: 0.08 },
          "-=0.25"
        )
        .fromTo(
          ".dash-bar-wrap",
          { y: 24, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.5 },
          "-=0.2"
        )
        .fromTo(
          ".dash-line-latency, .dash-line-recall",
          { strokeDasharray: 800, strokeDashoffset: 800, opacity: 0 },
          {
            strokeDashoffset: 0,
            opacity: 1,
            duration: 1,
            stagger: 0.15,
            ease: "power3.out",
          },
          "-=0.3"
        )
        .fromTo(
          ".dash-trace",
          { y: 20, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.4 },
          "-=0.3"
        );
    },
    { scope: dashRef }
  );

  const metricCards = [
    {
      icon: "verified_user",
      label: "Confidence",
      value: `${(activeResponse.confidence_score * 100).toFixed(0)}%`,
      sub: activeResponse.refusal ? "Refusal" : "Accepted",
      tone: "primary" as const,
    },
    {
      icon: "timer",
      label: "Total Latency",
      value: `${(activeMetrics.total_duration_ms / 1000).toFixed(2)}s`,
      sub: `${activeMetrics.stages.length} stages`,
      tone: "primary" as const,
    },
    {
      icon: "shield_person",
      label: "Faithfulness",
      value: `${faithfulnessPct.toFixed(0)}%`,
      sub: `${supportedClaims}/${totalClaims || "—"} supported`,
      tone: "emerald" as const,
    },
    {
      icon: "link",
      label: "Citation Coverage",
      value: `${citationCoveragePct.toFixed(0)}%`,
      sub: `${claimsWithEvidence}/${totalClaims || "—"} with evidence`,
      tone: "sky" as const,
    },
    {
      icon: "error",
      label: "Hallucination",
      value: `${hallucinationPct.toFixed(0)}%`,
      sub: `${hallucinatedClaims}/${totalClaims || "—"} fabricated or unsupported`,
      tone: "rose" as const,
    },
    {
      icon: "format_quote",
      label: "Citations",
      value: String(activeMetrics.citation_count),
      sub: `${activeMetrics.evidence_count} evidence chunks`,
      tone: "primary" as const,
    },
  ];

  const toneClass: Record<string, string> = {
    primary: "text-primary bg-primary/10",
    emerald: "text-emerald-400 bg-emerald-500/10",
    sky: "text-sky-400 bg-sky-500/10",
    rose: "text-rose-400 bg-rose-500/10",
  };

  // ── Line chart helpers ──
  const chartW = 520;
  const chartH = 180;
  const padL = 36;
  const padR = 12;
  const padT = 16;
  const padB = 28;
  const plotW = chartW - padL - padR;
  const plotH = chartH - padT - padB;

  // Latency points
  const latencyMax = Math.max(...activeMetrics.stages.map((s) => s.duration_ms), 1);
  const latencyPts = activeMetrics.stages.map((s, i, arr) => {
    const x = padL + (arr.length <= 1 ? 0 : (plotW * i) / (arr.length - 1));
    const y = padT + plotH - (s.duration_ms / latencyMax) * plotH;
    return { x, y, label: s.stage, value: s.duration_ms };
  });
  const latencyPath = latencyPts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const latencyArea =
    latencyPts.length > 0
      ? `${latencyPath} L${latencyPts[latencyPts.length - 1].x},${padT + plotH} L${latencyPts[0].x},${padT + plotH} Z`
      : "";

  // Recall points
  const recallMax = 1;
  const recallPts = activeRecall.map((r, i, arr) => {
    const x = padL + (arr.length <= 1 ? 0 : (plotW * i) / (arr.length - 1));
    const y = padT + plotH - (Math.min(r.recall, recallMax) / recallMax) * plotH;
    return { x, y, label: `#${r.t + 1}`, value: r.recall };
  });
  const recallPath = recallPts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const recallArea =
    recallPts.length > 0
      ? `${recallPath} L${recallPts[recallPts.length - 1].x},${padT + plotH} L${recallPts[0].x},${padT + plotH} Z`
      : "";

  const yTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div
      ref={dashRef}
      className={`flex-1 overflow-y-auto p-6 space-y-8 ${isSynthetic ? "opacity-90" : ""}`}
    >
      {/* Header */}
      <div className="dash-header">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-black tracking-tight">Performance Overview</h2>
          {isSynthetic && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border bg-amber-500/10 text-amber-500 border-amber-500/20">
              Synthetic / Demo
            </span>
          )}
        </div>
        <p className="text-slate-500 text-sm mt-1">
          {isSynthetic ? (
            <>Preview data shown. Run a query for live metrics.</>
          ) : (
            <>Query: <span className="text-slate-300">{activeResponse.query}</span></>
          )}
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {metricCards.map((card) => (
          <div
            key={card.label}
            className="dash-card bg-card-dark border border-border-dark p-5 rounded-xl hover:border-primary hover:-translate-y-1 transition-all"
          >
            <div className="flex justify-between items-start mb-3">
              <span
                className={`material-symbols-outlined p-2 rounded-lg text-[20px] ${
                  toneClass[card.tone]
                }`}
              >
                {card.icon}
              </span>
            </div>
            <h3 className="text-slate-500 text-xs font-medium">{card.label}</h3>
            <p className="text-2xl font-bold mt-1">{card.value}</p>
            <p className="text-[11px] text-slate-400 mt-2">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Dual line charts: Latency by Stage + Recall over Time */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Latency by Stage — line chart */}
        <div className="dash-bar-wrap bg-card-dark border border-border-dark rounded-xl p-6">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h4 className="text-base font-bold">Latency by Stage</h4>
              <p className="text-slate-500 text-xs">
                Processing time across the pipeline
              </p>
            </div>
            <div className="text-right">
              <span className="text-xl font-black text-primary">
                {(activeMetrics.total_duration_ms / 1000).toFixed(2)}s
              </span>
              <span className="block text-[10px] text-slate-500 uppercase font-bold tracking-widest">
                Total
              </span>
            </div>
          </div>
          <svg
            viewBox={`0 0 ${chartW} ${chartH}`}
            className="w-full h-52"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id="latFill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgb(131,89,248)" stopOpacity="0.45" />
                <stop offset="100%" stopColor="rgb(131,89,248)" stopOpacity="0" />
              </linearGradient>
            </defs>
            {/* grid */}
            {[0, 0.25, 0.5, 0.75, 1].map((t) => {
              const y = padT + plotH - t * plotH;
              return (
                <g key={t}>
                  <line
                    x1={padL}
                    x2={padL + plotW}
                    y1={y}
                    y2={y}
                    stroke="rgba(148,163,184,0.08)"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={padL - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize="9"
                    fill="#64748b"
                    fontFamily="monospace"
                  >
                    {((latencyMax * t) / 1000).toFixed(1)}s
                  </text>
                </g>
              );
            })}
            {/* area + line */}
            {latencyArea && <path d={latencyArea} fill="url(#latFill)" />}
            <path
              d={latencyPath}
              fill="none"
              stroke="rgb(131,89,248)"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="dash-line-latency"
            />
            {latencyPts.map((p) => (
              <g key={p.label}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r="4"
                  fill="rgb(20,18,35)"
                  stroke="rgb(131,89,248)"
                  strokeWidth="2"
                />
                <text
                  x={p.x}
                  y={chartH - 8}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#94a3b8"
                  fontFamily="monospace"
                >
                  {p.label}
                </text>
                <text
                  x={p.x}
                  y={p.y - 8}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#cbd5e1"
                  fontFamily="monospace"
                >
                  {(p.value / 1000).toFixed(2)}s
                </text>
              </g>
            ))}
          </svg>
        </div>

        {/* Recall over Time — line chart */}
        <div className="dash-bar-wrap bg-card-dark border border-border-dark rounded-xl p-6">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h4 className="text-base font-bold">Recall Over Time</h4>
              <p className="text-slate-500 text-xs">
                Per-query recall (supported-claim ratio)
              </p>
            </div>
            <div className="text-right">
              <span className="text-xl font-black text-emerald-400">
                {(
                  (activeRecall[activeRecall.length - 1]?.recall ?? 0) * 100
                ).toFixed(0)}
                %
              </span>
              <span className="block text-[10px] text-slate-500 uppercase font-bold tracking-widest">
                Latest
              </span>
            </div>
          </div>
          <svg
            viewBox={`0 0 ${chartW} ${chartH}`}
            className="w-full h-52"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id="recFill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgb(52,211,153)" stopOpacity="0.4" />
                <stop offset="100%" stopColor="rgb(52,211,153)" stopOpacity="0" />
              </linearGradient>
            </defs>
            {yTicks.map((t) => {
              const y = padT + plotH - t * plotH;
              return (
                <g key={t}>
                  <line
                    x1={padL}
                    x2={padL + plotW}
                    y1={y}
                    y2={y}
                    stroke="rgba(148,163,184,0.08)"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={padL - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize="9"
                    fill="#64748b"
                    fontFamily="monospace"
                  >
                    {(t * 100).toFixed(0)}%
                  </text>
                </g>
              );
            })}
            {recallArea && <path d={recallArea} fill="url(#recFill)" />}
            <path
              d={recallPath}
              fill="none"
              stroke="rgb(52,211,153)"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="dash-line-recall"
            />
            {recallPts.map((p) => (
              <g key={p.label}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r="4"
                  fill="rgb(20,18,35)"
                  stroke="rgb(52,211,153)"
                  strokeWidth="2"
                />
                <text
                  x={p.x}
                  y={chartH - 8}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#94a3b8"
                  fontFamily="monospace"
                >
                  {p.label}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </div>

      {/* Trace ID */}
      <div className="dash-trace glass rounded-xl p-4 flex items-center justify-between">
        <div className="flex gap-6">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-500">Trace ID</span>
            <p className="text-xs font-mono text-slate-300 mt-0.5">{activeResponse.trace_id}</p>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-500">Answer ID</span>
            <p className="text-xs font-mono text-slate-300 mt-0.5">{activeResponse.answer_id}</p>
          </div>
        </div>
        <span
          className={`px-3 py-1 rounded-full text-xs font-bold ${
            isSynthetic
              ? "bg-amber-500/10 text-amber-500 border border-amber-500/20"
              : activeResponse.refusal
              ? "bg-rose-500/10 text-rose-500 border border-rose-500/20"
              : "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20"
          }`}
        >
          {isSynthetic ? "Demo" : activeResponse.refusal ? "Refused" : "Answered"}
        </span>
      </div>
    </div>
  );
}

// ─── Ingest Modal ────────────────────────────────────────────────────────────

type IngestItem = {
  url: string;
  status: string;
  document_id?: string;
  title?: string;
  error?: string;
};

type DocUploadStatus = {
  filename: string;
  status: string;
  document_id?: string;
  error?: string;
};

function IngestModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { authHeaders } = useAuth();
  const [urlsText, setUrlsText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [urlResults, setUrlResults] = useState<IngestItem[]>([]);
  const [docResults, setDocResults] = useState<DocUploadStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const modalRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (!open) return;
      gsap.fromTo(
        ".ingest-backdrop",
        { opacity: 0 },
        { opacity: 1, duration: 0.25, ease: "power1.out", clearProps: "opacity" }
      );
      gsap.fromTo(
        ".ingest-panel",
        { opacity: 0, scale: 0.92, y: 16 },
        {
          opacity: 1,
          scale: 1,
          y: 0,
          duration: 0.4,
          ease: "back.out(1.6)",
          transformOrigin: "50% 50%",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: modalRef, dependencies: [open] }
  );

  if (!open) return null;

  async function handleSubmit() {
    setBusy(true);
    setError(null);
    setUrlResults([]);
    setDocResults([]);

    const urls = urlsText
      .split(/\r?\n/)
      .map((u) => u.trim())
      .filter(Boolean);

    try {
      // URL ingest
      if (urls.length > 0) {
        const res = await fetch(`${API_BASE}/v1/ingest/url`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ urls }),
        });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(`URL ingest failed (${res.status}): ${t.slice(0, 200)}`);
        }
        const data = (await res.json()) as { items: IngestItem[] };
        setUrlResults(data.items || []);
      }

      // File upload: one request per file (matches existing /v1/documents)
      const uploads: DocUploadStatus[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        try {
          const res = await fetch(`${API_BASE}/v1/documents`, {
            method: "POST",
            headers: { ...authHeaders() },
            body: form,
          });
          if (!res.ok) {
            uploads.push({
              filename: file.name,
              status: "failed",
              error: `HTTP ${res.status}`,
            });
            continue;
          }
          const data = (await res.json()) as { document_id: string; status: string };
          uploads.push({
            filename: file.name,
            status: data.status,
            document_id: data.document_id,
          });
        } catch (err) {
          uploads.push({
            filename: file.name,
            status: "failed",
            error: err instanceof Error ? err.message : "unknown",
          });
        }
      }
      setDocResults(uploads);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  function resultBadge(status: string) {
    const s = status.toLowerCase();
    if (s === "failed") return "bg-rose-500/10 text-rose-500 border-rose-500/20";
    if (s.includes("skipped")) return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
  }

  return (
    <div
      ref={modalRef}
      className="ingest-backdrop fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="ingest-panel bg-card-dark border border-border-dark rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border-dark">
          <div className="flex items-center gap-3">
            <div className="size-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
              <span className="material-symbols-outlined text-[20px]">library_add</span>
            </div>
            <div>
              <h3 className="font-bold text-base">Ingest Sources</h3>
              <p className="text-xs text-slate-500">
                Index URLs and documents into the vector store for retrieval + verification.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="size-8 rounded-lg hover:bg-white/5 flex items-center justify-center text-slate-400"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* URLs */}
          <div>
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2 block">
              URLs (one per line)
            </label>
            <textarea
              value={urlsText}
              onChange={(e) => setUrlsText(e.target.value)}
              rows={5}
              placeholder={"https://example.com/article-1\nhttps://example.com/paper.pdf"}
              className="w-full bg-bg-dark border border-border-dark rounded-lg p-3 text-sm font-mono placeholder:text-slate-600 focus:ring-1 focus:ring-primary focus:border-primary resize-none"
            />
          </div>

          {/* Files */}
          <div>
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2 block">
              Documents (text / markdown)
            </label>
            <input
              type="file"
              multiple
              accept=".txt,.md,.markdown,.json,.csv"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-bold file:text-xs file:cursor-pointer hover:file:bg-primary/20"
            />
            {files.length > 0 && (
              <p className="text-[11px] text-slate-500 mt-1.5">{files.length} file(s) selected</p>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="bg-rose-500/10 border border-rose-500/20 rounded-lg p-3 text-rose-400 text-xs">
              {error}
            </div>
          )}

          {/* Results */}
          {(urlResults.length > 0 || docResults.length > 0) && (
            <div className="space-y-2">
              <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Results
              </h4>
              <div className="space-y-1.5">
                {urlResults.map((r) => (
                  <div
                    key={r.url}
                    className="flex items-center justify-between gap-3 bg-bg-dark border border-border-dark rounded-lg px-3 py-2 text-xs"
                  >
                    <span className="truncate text-slate-300 font-mono">{r.url}</span>
                    <span
                      className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-bold border ${resultBadge(r.status)}`}
                    >
                      {r.status}
                    </span>
                  </div>
                ))}
                {docResults.map((r) => (
                  <div
                    key={r.filename}
                    className="flex items-center justify-between gap-3 bg-bg-dark border border-border-dark rounded-lg px-3 py-2 text-xs"
                  >
                    <span className="truncate text-slate-300">{r.filename}</span>
                    <span
                      className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-bold border ${resultBadge(r.status)}`}
                    >
                      {r.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border-dark flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm font-bold text-slate-300 hover:bg-white/5"
          >
            Close
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy || (urlsText.trim().length === 0 && files.length === 0)}
            className="px-4 py-2 rounded-lg text-sm font-bold bg-primary hover:bg-primary/90 disabled:opacity-50 text-white flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">
              {busy ? "hourglass_top" : "cloud_upload"}
            </span>
            {busy ? "Ingesting…" : "Ingest"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

type HistoryItem = {
  query: string;
  answer_id: string;
  trace_id: string;
  confidence_score: number;
  created_at: string;
  citation_count: number;
};

export default function Home() {
  const { user, authHeaders } = useAuth();
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [finalResponse, setFinalResponse] = useState<QueryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<View>("chat");
  const [ingestOpen, setIngestOpen] = useState(false);
  const [recallHistory, setRecallHistory] = useState<RecallPoint[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);

  // Fetch user query history whenever login state changes.
  useEffect(() => {
    if (!user) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/v1/auth/history?limit=15`, {
          headers: { ...authHeaders() },
        });
        if (!res.ok) return;
        const data = (await res.json()) as { items: HistoryItem[] };
        if (!cancelled) setHistory(data.items);
      } catch {
        // non-fatal
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, authHeaders]);

  const canSubmit = useMemo(() => query.trim().length > 0 && !isLoading, [query, isLoading]);

  const mainRef = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      gsap.fromTo(
        ".main-header",
        { y: -16, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.5,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
      gsap.fromTo(
        ".main-input",
        { y: 24, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.5,
          delay: 0.15,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: mainRef }
  );

  useGSAP(
    () => {
      gsap.fromTo(
        ".view-stage",
        { opacity: 0, y: 12 },
        {
          opacity: 1,
          y: 0,
          duration: 0.4,
          ease: "power2.out",
          clearProps: "transform,opacity",
        }
      );
    },
    { scope: mainRef, dependencies: [activeView] }
  );

  useGSAP(
    () => {
      if (answer || isLoading) return;
      gsap.fromTo(
        ".empty-state",
        { opacity: 0, y: 20 },
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: "power3.out",
          clearProps: "opacity",
        }
      );
      gsap.to(".empty-state-icon", {
        y: -6,
        duration: 1.6,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
    },
    { scope: mainRef, dependencies: [answer, isLoading] }
  );

  useGSAP(
    () => {
      gsap.fromTo(
        ".answer-block",
        { y: 18, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.5,
          ease: "power3.out",
          clearProps: "transform,opacity",
        }
      );
      gsap.fromTo(
        ".citation-chip",
        { y: 10, opacity: 0, scale: 0.9 },
        {
          y: 0,
          opacity: 1,
          scale: 1,
          duration: 0.35,
          stagger: 0.06,
          ease: "back.out(1.5)",
          transformOrigin: "50% 50%",
          clearProps: "transform,opacity",
        }
      );
    },
    {
      scope: mainRef,
      dependencies: [Boolean(finalResponse), citations.length],
    }
  );

  function focusChat() {
    setActiveView("chat");
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSubmit) return;

    setIsLoading(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    setTraceEvents([]);
    setFinalResponse(null);

    try {
      const response = await fetch(`${API_BASE}/v1/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ query }),
      });

      if (!response.ok || !response.body) {
        let detail = `Stream request failed (${response.status})`;
        try {
          const errJson = await response.clone().json();
          if (errJson?.detail) detail = String(errJson.detail);
          else if (errJson?.error?.message) detail = String(errJson.error.message);
        } catch {
          // non-JSON error body — keep generic message
        }
        throw new Error(detail);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;
        for (const eventItem of parsed.events) {
          if (!eventItem.event || !eventItem.data) continue;
          if (eventItem.event === "answer_delta") {
            const data = JSON.parse(eventItem.data) as { text: string };
            setAnswer((prev) => prev + data.text);
          }
          if (eventItem.event === "citation") {
            const citation = JSON.parse(eventItem.data) as Citation;
            setCitations((prev) => {
              if (prev.find((item) => item.citation_id === citation.citation_id)) return prev;
              return [...prev, citation];
            });
          }
          if (eventItem.event === "trace_event") {
            const trace = JSON.parse(eventItem.data) as TraceEvent;
            setTraceEvents((prev) => [...prev, trace]);
          }
          if (eventItem.event === "final") {
            const finalPayload = JSON.parse(eventItem.data) as QueryResponse;
            setFinalResponse(finalPayload);
            if (finalPayload.answer) {
              setAnswer(finalPayload.answer);
            }
            // Append recall point (supported-claim ratio) for trend chart.
            const claims = finalPayload.claim_verifications;
            const supported = claims.filter(
              (v) =>
                v.verdict.toLowerCase().includes("support") &&
                !v.verdict.toLowerCase().includes("unsupport")
            ).length;
            const recall = claims.length > 0 ? supported / claims.length : finalPayload.confidence_score;
            setRecallHistory((prev) => {
              const next = [
                ...prev,
                {
                  t: prev.length,
                  recall,
                  latency_s: finalPayload.metrics.total_duration_ms / 1000,
                },
              ];
              return next.slice(-20);
            });

            // Refresh the sidebar history list if the user is logged in so the
            // new query shows up as a reusable cached chip.
            if (user) {
              fetch(`${API_BASE}/v1/auth/history?limit=15`, {
                headers: { ...authHeaders() },
              })
                .then((r) => (r.ok ? r.json() : null))
                .then((data: { items: HistoryItem[] } | null) => {
                  if (data) setHistory(data.items);
                })
                .catch(() => {
                  /* non-fatal */
                });
            }
          }
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }

  const metrics = finalResponse?.metrics ?? null;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-bg-dark text-slate-100 font-display">
      {/* ── Sidebar ── */}
      <Sidebar
        activeView={activeView}
        onViewChange={setActiveView}
        isLoading={isLoading}
        onRunResearch={focusChat}
        onIngest={() => setIngestOpen(true)}
      />

      <IngestModal open={ingestOpen} onClose={() => setIngestOpen(false)} />

      {/* ── Main ── */}
      <main ref={mainRef} className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="main-header h-14 border-b border-border-dark flex items-center justify-between px-6 bg-bg-dark/80 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="font-bold text-base tracking-tight">
              {activeView === "chat"
                ? "Research Chat"
                : activeView === "sources"
                ? "Sources & Verification"
                : "System Metrics"}
            </h2>
            <div className="flex items-center gap-2 px-3 py-1 bg-border-dark/50 rounded-full border border-border-dark">
              <div
                className={`size-2 rounded-full ${
                  isLoading ? "bg-primary animate-pulse" : "bg-green-500"
                }`}
              />
              <span className="text-xs font-medium text-slate-300">
                {isLoading ? "Processing" : "Ready"}
              </span>
            </div>
          </div>
          <span className="text-xs text-slate-500 font-mono hidden sm:block">{API_BASE}</span>
        </header>

        {/* ── Chat View ── */}
        {activeView === "chat" && (
          <div className="view-stage flex-1 flex overflow-hidden">
            {/* Chat window */}
            <section className="flex-1 flex flex-col bg-bg-dark/30">
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {error && (
                  <div className="max-w-3xl mx-auto">
                    <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-rose-400 text-sm">
                      <span className="material-symbols-outlined text-[16px] mr-2 align-text-bottom">
                        error
                      </span>
                      {error}
                    </div>
                  </div>
                )}

                {(answer || isLoading) && (
                  <div className="answer-block max-w-3xl mx-auto space-y-4">
                    <div className="flex items-start gap-3">
                      <div className="size-8 rounded-lg bg-primary/20 text-primary flex items-center justify-center shrink-0 mt-0.5">
                        <span className="material-symbols-outlined text-[18px]">smart_toy</span>
                      </div>
                      <div className="flex-1 space-y-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm">RAG Assistant</span>
                          {finalResponse && (
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
                                finalResponse.confidence_score >= 0.7
                                  ? "bg-green-500/10 text-green-500 border-green-500/20"
                                  : finalResponse.confidence_score >= 0.4
                                  ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                                  : "bg-rose-500/10 text-rose-500 border-rose-500/20"
                              }`}
                            >
                              {(finalResponse.confidence_score * 100).toFixed(0)}% Confidence
                            </span>
                          )}
                        </div>

                        <div className="glass p-5 rounded-xl text-slate-200 leading-relaxed text-sm">
                          {answer ? (
                            <p className="whitespace-pre-wrap">{answer}</p>
                          ) : (
                            <div className="flex items-center gap-2 text-slate-400">
                              <div className="size-1.5 rounded-full bg-primary animate-bounce" />
                              <div
                                className="size-1.5 rounded-full bg-primary animate-bounce"
                                style={{ animationDelay: "0.15s" }}
                              />
                              <div
                                className="size-1.5 rounded-full bg-primary animate-bounce"
                                style={{ animationDelay: "0.3s" }}
                              />
                            </div>
                          )}
                        </div>

                        {/* Citation chips */}
                        {citations.length > 0 && (
                          <div className="flex flex-wrap gap-2">
                            {citations.map((c, i) => (
                              <div
                                key={c.citation_id}
                                className="citation-chip px-2.5 py-1 rounded-lg border border-border-dark bg-card-dark text-[11px] text-slate-400 flex items-center gap-1.5"
                              >
                                <span className="material-symbols-outlined text-[12px]">
                                  description
                                </span>
                                [{i + 1}] {c.title || c.url}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {!answer && !isLoading && (
                  <div className="empty-state max-w-3xl mx-auto flex flex-col items-center justify-center py-16 text-center space-y-4">
                    <div className="empty-state-icon size-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
                      <span className="material-symbols-outlined text-primary text-[32px]">
                        manage_search
                      </span>
                    </div>
                    <h3 className="font-bold text-lg">Ask a research question</h3>
                    <p className="text-slate-500 text-sm max-w-sm">
                      Submit a query to receive an evidence-grounded answer with citations,
                      verification, and a full agent trace.
                    </p>

                    {user && history.length > 0 && (
                      <div className="w-full max-w-2xl pt-6 space-y-2">
                        <p className="text-[10px] uppercase tracking-widest font-bold text-slate-500">
                          Your recent queries (cached)
                        </p>
                        <div className="flex flex-wrap gap-2 justify-center">
                          {history.slice(0, 8).map((h) => (
                            <button
                              key={h.answer_id}
                              onClick={() => setQuery(h.query)}
                              className="px-3 py-1.5 rounded-full border border-border-dark hover:border-primary/40 bg-card-dark text-xs text-slate-300 hover:text-primary flex items-center gap-1.5 max-w-xs"
                              title={`${h.citation_count} citations · confidence ${(h.confidence_score * 100).toFixed(0)}%`}
                            >
                              <span className="material-symbols-outlined text-[12px]">
                                history
                              </span>
                              <span className="truncate">{h.query}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Input area */}
              <div className="main-input p-5 bg-gradient-to-t from-bg-dark to-transparent shrink-0">
                <form
                  onSubmit={handleSubmit}
                  className="max-w-3xl mx-auto relative"
                >
                  <textarea
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        if (canSubmit) {
                          e.currentTarget.form?.requestSubmit();
                        }
                      }
                    }}
                    placeholder="Ask a research question… (Enter to submit, Shift+Enter for newline)"
                    rows={2}
                    className="w-full bg-card-dark border border-border-dark rounded-xl py-3.5 pl-4 pr-14 text-sm focus:ring-1 focus:ring-primary focus:border-primary resize-none transition-all placeholder:text-slate-600 shadow-2xl"
                  />
                  <button
                    type="submit"
                    disabled={!canSubmit}
                    className="absolute right-2 bottom-2 size-10 bg-primary disabled:opacity-50 text-white rounded-lg flex items-center justify-center hover:scale-105 disabled:hover:scale-100 transition-transform"
                  >
                    <span className="material-symbols-outlined text-[20px]">send</span>
                  </button>
                </form>
              </div>
            </section>

            {/* Agent trace sidebar */}
            <AgentTraceSidebar
              traceEvents={traceEvents}
              metrics={metrics}
              isLoading={isLoading}
            />
          </div>
        )}

        {/* ── Sources & Verification View ── */}
        {activeView === "sources" && (
          <div className="view-stage flex-1 flex gap-5 p-5 overflow-hidden">
            {/* Left: Sources */}
            <div className="w-80 shrink-0 flex flex-col gap-3 overflow-hidden">
              <div className="flex items-center justify-between px-1 shrink-0">
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  Retrieved Sources ({citations.length})
                </h2>
              </div>
              <CitationsPanel citations={citations} />
            </div>

            {/* Right: Verification Table */}
            <VerificationTable
              verifications={finalResponse?.claim_verifications ?? []}
            />
          </div>
        )}

        {/* ── Metrics View ── */}
        {activeView === "metrics" && (
          <div className="view-stage flex-1 flex flex-col overflow-hidden">
            <MetricsDashboard
              metrics={metrics}
              finalResponse={finalResponse}
              recallHistory={recallHistory}
            />
          </div>
        )}
      </main>
    </div>
  );
}
