"use client";

import { FormEvent, useMemo, useState } from "react";

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
}: {
  activeView: View;
  onViewChange: (v: View) => void;
  isLoading: boolean;
  onRunResearch: () => void;
}) {
  const navItems: { view: View; icon: string; label: string }[] = [
    { view: "chat", icon: "chat_bubble", label: "Research Chat" },
    { view: "sources", icon: "fact_check", label: "Sources & Verify" },
    { view: "metrics", icon: "monitoring", label: "System Metrics" },
  ];

  return (
    <aside className="w-64 border-r border-border-dark bg-card-dark flex flex-col shrink-0">
      {/* Logo */}
      <div className="p-6 flex items-center gap-3">
        <div className="size-10 bg-primary rounded-lg flex items-center justify-center text-white shrink-0">
          <span className="material-symbols-outlined">auto_awesome</span>
        </div>
        <div>
          <h1 className="font-bold text-sm tracking-tight">Autonomous RAG</h1>
          <p className="text-[10px] text-slate-500 font-mono">v0.1.0</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-4 space-y-1">
        {navItems.map(({ view, icon, label }) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors ${
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

      {/* Run Research */}
      <div className="p-4 border-t border-border-dark">
        <button
          onClick={onRunResearch}
          disabled={isLoading}
          className="w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white rounded font-bold text-sm transition-all flex items-center justify-center gap-2"
        >
          <span className="material-symbols-outlined text-[18px]">
            {isLoading ? "hourglass_top" : "add_circle"}
          </span>
          {isLoading ? "Running…" : "Run Research"}
        </button>
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

  return (
    <aside className="w-72 border-l border-border-dark bg-card-dark/50 overflow-y-auto p-5 hidden xl:flex flex-col gap-6">
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
              className={`relative pl-8 ${status === "pending" ? "opacity-40" : ""}`}
            >
              {/* Dot */}
              <div
                className={`absolute left-0 top-0 size-6 rounded-full flex items-center justify-center z-10 ${
                  status === "done"
                    ? "bg-green-500/20 border-2 border-green-500"
                    : status === "active"
                    ? "bg-primary/20 border-2 border-primary"
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

              <div className="space-y-1">
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
              </div>
            </div>
          );
        })}
      </div>

      {/* Performance stats */}
      {metrics && (
        <div className="glass p-4 rounded-xl space-y-3 mt-auto">
          <span className="text-[10px] uppercase font-bold text-slate-500">Performance</span>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 bg-white/5 rounded-lg border border-white/5">
              <p className="text-[9px] text-slate-500 uppercase font-bold">Latency</p>
              <p className="text-sm font-bold">
                {(metrics.total_duration_ms / 1000).toFixed(1)}s
              </p>
            </div>
            <div className="p-2 bg-white/5 rounded-lg border border-white/5">
              <p className="text-[9px] text-slate-500 uppercase font-bold">Sources</p>
              <p className="text-sm font-bold">{metrics.evidence_count}</p>
            </div>
            <div className="p-2 bg-white/5 rounded-lg border border-white/5">
              <p className="text-[9px] text-slate-500 uppercase font-bold">Citations</p>
              <p className="text-sm font-bold">{metrics.citation_count}</p>
            </div>
            <div className="p-2 bg-white/5 rounded-lg border border-white/5">
              <p className="text-[9px] text-slate-500 uppercase font-bold">Claims</p>
              <p className="text-sm font-bold">{metrics.claim_count}</p>
            </div>
          </div>
        </div>
      )}
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
    <div className="flex-1 flex flex-col gap-3 overflow-hidden">
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
              className="grid grid-cols-12 border-b border-primary/5 hover:bg-primary/5 transition-colors"
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
                  className={`flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold border ${verdictStyle(v.verdict)}`}
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
    <div className="flex flex-col gap-3 overflow-y-auto pr-1">
      {citations.map((c, i) => (
        <div
          key={c.citation_id}
          className="glass rounded-xl p-4 hover:border-primary/40 transition-all cursor-pointer group"
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

function MetricsDashboard({
  metrics,
  finalResponse,
}: {
  metrics: QueryMetrics | null;
  finalResponse: QueryResponse | null;
}) {
  if (!metrics || !finalResponse) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        No metrics available. Run a query to see performance data.
      </div>
    );
  }

  const maxDuration = Math.max(...metrics.stages.map((s) => s.duration_ms), 1);

  const metricCards = [
    {
      icon: "verified_user",
      label: "Confidence",
      value: `${(finalResponse.confidence_score * 100).toFixed(0)}%`,
      sub: finalResponse.refusal ? "Refusal" : "Accepted",
    },
    {
      icon: "format_quote",
      label: "Citations",
      value: String(metrics.citation_count),
      sub: `${metrics.evidence_count} evidence chunks`,
    },
    {
      icon: "fact_check",
      label: "Claims Checked",
      value: String(metrics.claim_count),
      sub: "via Verifier",
    },
    {
      icon: "timer",
      label: "Total Latency",
      value: `${(metrics.total_duration_ms / 1000).toFixed(2)}s`,
      sub: `${metrics.stages.length} stages`,
    },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-black tracking-tight">Performance Overview</h2>
        <p className="text-slate-500 text-sm mt-1">
          Query: <span className="text-slate-300">{finalResponse.query}</span>
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {metricCards.map((card) => (
          <div
            key={card.label}
            className="bg-card-dark border border-border-dark p-5 rounded-xl hover:border-primary transition-colors"
          >
            <div className="flex justify-between items-start mb-3">
              <span className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg text-[20px]">
                {card.icon}
              </span>
            </div>
            <h3 className="text-slate-500 text-xs font-medium">{card.label}</h3>
            <p className="text-2xl font-bold mt-1">{card.value}</p>
            <p className="text-[11px] text-slate-400 mt-2">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Stage latency bar chart */}
      <div className="bg-card-dark border border-border-dark rounded-xl p-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h4 className="text-base font-bold">Latency by Stage</h4>
            <p className="text-slate-500 text-xs">Breakdown of processing time across the pipeline</p>
          </div>
          <div className="text-right">
            <span className="text-xl font-black text-primary">
              {(metrics.total_duration_ms / 1000).toFixed(2)}s
            </span>
            <span className="block text-[10px] text-slate-500 uppercase font-bold tracking-widest">
              Total
            </span>
          </div>
        </div>
        <div className="flex items-end justify-between h-40 gap-3 px-2">
          {metrics.stages.map((stage) => {
            const pct = Math.round((stage.duration_ms / maxDuration) * 100);
            return (
              <div key={stage.stage} className="flex flex-col items-center gap-2 flex-1">
                <span className="text-[10px] text-slate-400 font-mono">
                  {(stage.duration_ms / 1000).toFixed(2)}s
                </span>
                <div
                  className="w-full bg-primary/20 rounded-t-lg relative overflow-hidden"
                  style={{ height: `${Math.max(pct, 4)}%` }}
                >
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-primary to-primary/60 h-full" />
                </div>
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">
                  {stage.stage}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Trace ID */}
      <div className="glass rounded-xl p-4 flex items-center justify-between">
        <div className="flex gap-6">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-500">Trace ID</span>
            <p className="text-xs font-mono text-slate-300 mt-0.5">{finalResponse.trace_id}</p>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-500">Answer ID</span>
            <p className="text-xs font-mono text-slate-300 mt-0.5">{finalResponse.answer_id}</p>
          </div>
        </div>
        <span
          className={`px-3 py-1 rounded-full text-xs font-bold ${
            finalResponse.refusal
              ? "bg-rose-500/10 text-rose-500 border border-rose-500/20"
              : "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20"
          }`}
        >
          {finalResponse.refusal ? "Refused" : "Answered"}
        </span>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function Home() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [finalResponse, setFinalResponse] = useState<QueryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<View>("chat");

  const canSubmit = useMemo(() => query.trim().length > 0 && !isLoading, [query, isLoading]);

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
        headers: { "Content-Type": "application/json" },
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
      />

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 border-b border-border-dark flex items-center justify-between px-6 bg-bg-dark/80 backdrop-blur-md shrink-0">
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
          <div className="flex-1 flex overflow-hidden">
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
                  <div className="max-w-3xl mx-auto space-y-4">
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
                                className="px-2.5 py-1 rounded-lg border border-border-dark bg-card-dark text-[11px] text-slate-400 flex items-center gap-1.5"
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
                  <div className="max-w-3xl mx-auto flex flex-col items-center justify-center py-16 text-center space-y-4">
                    <div className="size-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
                      <span className="material-symbols-outlined text-primary text-[32px]">
                        manage_search
                      </span>
                    </div>
                    <h3 className="font-bold text-lg">Ask a research question</h3>
                    <p className="text-slate-500 text-sm max-w-sm">
                      Submit a query to receive an evidence-grounded answer with citations,
                      verification, and a full agent trace.
                    </p>
                  </div>
                )}
              </div>

              {/* Input area */}
              <div className="p-5 bg-gradient-to-t from-bg-dark to-transparent shrink-0">
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
          <div className="flex-1 flex gap-5 p-5 overflow-hidden">
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
          <MetricsDashboard metrics={metrics} finalResponse={finalResponse} />
        )}
      </main>
    </div>
  );
}
