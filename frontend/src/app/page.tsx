"use client";

import { FormEvent, useMemo, useState } from "react";
import styles from "./page.module.css";

type Citation = {
  citation_id: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string;
  snippet: string;
  chunk_start: number;
  chunk_end: number;
};

type TraceEvent = {
  event_id: string;
  agent: string;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

type QueryResponse = {
  answer_id: string;
  query: string;
  answer: string;
  citations: Citation[];
  claim_verifications: {
    claim_id: string;
    claim_text: string;
    verdict: string;
    evidence_chunk_ids: string[];
    confidence: number;
    notes: string;
  }[];
  confidence_score: number;
  refusal: boolean;
  trace_id: string;
};

type StreamEvent = {
  event?: string;
  data?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

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

export default function Home() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [finalResponse, setFinalResponse] = useState<QueryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(() => query.trim().length > 0 && !isLoading, [query, isLoading]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
        throw new Error(`Stream request failed (${response.status})`);
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
            if (!finalPayload.answer) {
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

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Autonomous Agentic Research Platform</p>
            <h1>Research, traced and grounded.</h1>
            <p className={styles.subhead}>
              Submit a query to receive a grounded answer with citations and a trace of agent actions.
            </p>
          </div>
          <div className={styles.status}>
            <span className={styles.badge}>{isLoading ? "Running" : "Idle"}</span>
            <span className={styles.apiBase}>API: {API_BASE}</span>
          </div>
        </header>

        <form className={styles.form} onSubmit={handleSubmit}>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask a research question..."
            rows={3}
          />
          <button type="submit" disabled={!canSubmit}>
            {isLoading ? "Working..." : "Run query"}
          </button>
        </form>

        {error && <div className={styles.error}>Error: {error}</div>}

        <section className={styles.results}>
          <div className={styles.answerCard}>
            <h2>Answer</h2>
            <p className={styles.answer}>{answer || "Answer will appear here."}</p>
            {finalResponse && (
              <div className={styles.metaRow}>
                <span>Confidence: {finalResponse.confidence_score}</span>
                <span>Refusal: {finalResponse.refusal ? "true" : "false"}</span>
                <span>Trace: {finalResponse.trace_id}</span>
              </div>
            )}
          </div>

          <div className={styles.panelGrid}>
            <div className={styles.panel}>
              <h3>Citations</h3>
              <ul>
                {citations.length === 0 && <li className={styles.empty}>No citations yet.</li>}
                {citations.map((citation) => (
                  <li key={citation.citation_id}>
                    <div className={styles.citationTitle}>{citation.title || citation.url}</div>
                    <div className={styles.citationMeta}>{citation.url}</div>
                    <div className={styles.citationSnippet}>{citation.snippet}</div>
                  </li>
                ))}
              </ul>
            </div>
            <div className={styles.panel}>
              <h3>Trace events</h3>
              <ul>
                {traceEvents.length === 0 && <li className={styles.empty}>No trace events yet.</li>}
                {traceEvents.map((eventItem) => (
                  <li key={eventItem.event_id}>
                    <div className={styles.traceHeader}>
                      <span>{eventItem.agent}</span>
                      <span>{eventItem.event_type}</span>
                    </div>
                    <div className={styles.traceMeta}>{eventItem.timestamp}</div>
                    <pre className={styles.tracePayload}>
                      {JSON.stringify(eventItem.payload, null, 2)}
                    </pre>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
