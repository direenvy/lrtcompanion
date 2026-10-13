"use client";
import { useState, useRef, useEffect } from "react";
import { chatWithRAG, submitFeedback } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import LiveRegion from "@/components/LiveRegion";
import VoiceInput from "@/components/VoiceInput";

interface Msg {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  mode?: string;
  grounding?: { verdict?: string; checked_by?: string | null };
  feedback?: 1 | -1 | null;  // thumbs up/down state
}

/* How the answer was produced, in the user's words rather than the pipeline's.
   The backend already decides this and logs it; showing it is what turns
   "every decision is traceable" from a claim into something visible. The two
   deterministic modes are labelled as such on purpose — an exact fare or an
   accessibility flag involves no model, and that is the more trustworthy
   answer, not a lesser one. */
function provenance(mode?: string, grounding?: Msg["grounding"]) {
  if (!mode) return null;
  if (mode === "fare_lookup")
    return { label: "Exact fare table", tone: "solid",
             title: "Answered from the validated fare matrix. No retrieval and no language model, so the number cannot drift." };
  if (mode === "network_facts")
    return { label: "Network data", tone: "solid",
             title: "Answered from the GTFS feed and the accessibility overlay. No retrieval and no language model." };
  if (mode.endsWith("_refused_on_verify"))
    return { label: "Refused — unsupported", tone: "warn",
             title: "A draft answer was generated, then checked against the retrieved documents and found not to follow from them. It was replaced with a refusal rather than served." };
  if (mode.includes("extractive"))
    return { label: "Document extract", tone: "soft",
             title: "Generation was unavailable, so the official document text is shown directly instead of a summary." };
  if (mode === "keyword")
    return { label: "Keyword retrieval", tone: "soft",
             title: "Semantic search was unavailable; this fell back to keyword matching over the same documents." };
  if (mode.startsWith("semantic")) {
    const v = grounding?.verdict;
    if (v === "supported")
      return { label: `Retrieved · verified${grounding?.checked_by ? ` (${grounding.checked_by})` : ""}`, tone: "solid",
               title: "Retrieved from the official documents, then checked a second time against those same documents and found to be supported by them." };
    return { label: "Retrieved · unverified", tone: "soft",
             title: "Retrieved from the official documents. The second-pass grounding check could not run, so the answer is served unverified rather than withheld." };
  }
  return null;
}

const TONES: Record<string, { bg: string; fg: string; bd: string }> = {
  solid: { bg: "rgba(16,185,129,0.10)",  fg: "#047857", bd: "rgba(16,185,129,0.30)" },
  soft:  { bg: "rgba(0,0,0,0.04)",       fg: "#737373", bd: "rgba(0,0,0,0.08)" },
  warn:  { bg: "rgba(245,158,11,0.12)",  fg: "#92400e", bd: "rgba(245,158,11,0.32)" },
};

const SUGGESTIONS = [
  "What is the My50 monthly pass?",
  "What to do during an LRT disruption?",
  "Can I bring a bicycle on the LRT?",
  "What are the LRT operating hours?",
];

export default function ChatPage() {
  const [msgs, setMsgs]    = useState<Msg[]>([{
    role: "assistant",
    text: "Hi! I'm your LRT AI assistant. I'm grounded in 41 official Rapid KL documents — ask me anything about fares, services, disruptions, or passenger rules.",
  }]);
  const [input, setInput]  = useState("");
  const [loading, setLoad] = useState(false);
  const listRef            = useRef<HTMLDivElement>(null);

  // Scroll only the message panel to its bottom — scrollIntoView would
  // also scroll the whole page, yanking the viewport down on every send.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [msgs, loading]);

  // Never let speech keep playing after the user navigates away
  useEffect(() => () => {
    if (typeof window !== "undefined" && "speechSynthesis" in window)
      window.speechSynthesis.cancel();
  }, []);

  // Read an answer aloud. Voice input alone only solves half the problem: a
  // user who cannot read the reply is no better served for being able to ask
  // by speech. Markdown is stripped first so asterisks are not spoken.
  const speak = (text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(
      text.replace(/[*_`#>]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1"));
    u.rate = 0.92;
    window.speechSynthesis.speak(u);
  };

  const send = async (override?: string) => {
    const q = (override ?? input).trim();
    if (!q || loading) return;
    setInput("");

    const newMsgs: Msg[] = [...msgs, { role: "user", text: q }];
    setMsgs(newMsgs);
    setLoad(true);

    try {
      // Send the last 10 turns as history for context
      const history = newMsgs.slice(-10).map(m => ({ role: m.role, text: m.text }));
      const d = await chatWithRAG(q, history);
      setMsgs(p => [...p, { role: "assistant", text: d.answer, sources: d.sources,
                            mode: d.mode, grounding: d.grounding, feedback: null }]);
    } catch {
      setMsgs(p => [...p, { role: "assistant", text: "Sorry — I can\u2019t reach the server right now. Please try again in a moment.", feedback: null }]);
    } finally { setLoad(false); }
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const giveFeedback = async (msgIdx: number, rating: 1 | -1) => {
    const msg = msgs[msgIdx];
    if (!msg || msg.role !== "assistant" || msg.feedback !== null && msg.feedback !== undefined) return;

    // Find the preceding user question
    const question = msgs[msgIdx - 1]?.text ?? "";

    // Update state immediately for instant UI response
    setMsgs(p => p.map((m, i) => i === msgIdx ? { ...m, feedback: rating } : m));

    try {
      await submitFeedback(question, msg.text, rating);
    } catch {
      // Feedback logging failing silently is acceptable
    }
  };

  // Announce the assistant's answer — it renders below the fold with no
  // visual cue a screen reader can pick up.
  const lastBot = [...msgs].reverse().find(m => m.role !== "user");
  const announcement = loading
    ? "Searching official documents, please wait."
    : (lastBot?.text ?? "");

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>
      <LiveRegion message={announcement} />

      <p className="section-label" style={{ marginBottom: 8 }}>RAG Chatbot · gemini-flash-lite · 1,903 chunks</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>RapidKL Fares, Passes & General Enquiries</h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "1.5rem" }}>
        Answers grounded in 41 official Rapid KL documents. Multi-turn conversation with retrieval-augmented generation.
      </p>

      {/* Suggestions */}
      {msgs.length === 1 && (
        <div className="anim-fade-in" style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: "1.25rem" }}>
          {SUGGESTIONS.map(s => (
            <button key={s} onClick={() => send(s)} className="pill-btn" style={{ fontSize: 11, padding: "5px 12px", borderRadius: 8 }}>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Chat window */}
      <div className="card" style={{ display: "flex", flexDirection: "column", height: 520 }}>

        {/* Messages */}
        <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: "1rem", display: "flex", flexDirection: "column", gap: 12 }}>
          {msgs.map((m, i) => (
            <div key={i} className="anim-fade-up" style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", alignItems: "flex-start", gap: 8 }}>
              {m.role === "assistant" && (
                <div style={{
                  width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
                  background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.25)",
                  display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, marginTop: 2,
                }}>🤖</div>
              )}
              <div style={{ maxWidth: "min(78%, 620px)", display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{
                  padding: "10px 14px", borderRadius: 14, fontSize: 13, lineHeight: 1.65,
                  ...(m.role === "user"
                    ? { background: "#fff", color: "#000", borderBottomRightRadius: 4 }
                    : { background: "#ffffff", border: "1px solid rgba(0,0,0,0.07)", color: "#2e2e2e", borderBottomLeftRadius: 4 }
                  ),
                }}>
                  {m.role === "assistant" ? (
                    <div className="md-body">
                      <ReactMarkdown>{m.text}</ReactMarkdown>
                    </div>
                  ) : (
                    <p style={{ whiteSpace: "pre-wrap" }}>{m.text}</p>
                  )}

                  {(() => {
                    const p = provenance(m.mode, m.grounding);
                    if (!p) return null;
                    const t = TONES[p.tone];
                    return (
                      <div style={{ marginTop: 8 }}>
                        <span title={p.title} style={{
                          fontSize: 9, letterSpacing: 0.3, color: t.fg, background: t.bg,
                          border: `1px solid ${t.bd}`, padding: "2px 7px", borderRadius: 5,
                          cursor: "help",
                        }}>
                          {p.label}
                        </span>
                      </div>
                    );
                  })()}

                  {m.sources && m.sources.length > 0 && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid rgba(0,0,0,0.08)", display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {m.sources.slice(0, 3).map(src => (
                        <span key={src} style={{ fontSize: 9, color: "#737373", background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.07)", padding: "2px 7px", borderRadius: 5 }}>
                          {src.replace(/\.pdf|\.txt/gi, "").slice(0, 38)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Feedback buttons — only on assistant messages after the greeting */}
                {m.role === "assistant" && i > 0 && (
                  <div style={{ display: "flex", gap: 4, paddingLeft: 2 }}>
                    <button
                      onClick={() => speak(m.text)}
                      aria-label="Read this answer aloud"
                      title="Read aloud"
                      style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, padding: "2px 4px" }}
                    >
                      🔊
                    </button>
                    <button
                      onClick={() => giveFeedback(i, 1)}
                      style={{
                        fontSize: 12, padding: "2px 8px", borderRadius: 6, cursor: m.feedback != null ? "default" : "pointer",
                        background: m.feedback === 1 ? "rgba(34,197,94,0.15)" : "transparent",
                        border: m.feedback === 1 ? "1px solid rgba(34,197,94,0.3)" : "1px solid transparent",
                        color: m.feedback === 1 ? "#22c55e" : "#8f8f8f",
                        transition: "all 0.15s",
                      }}
                      disabled={m.feedback != null}
                      title="Helpful"
                    >👍</button>
                    <button
                      onClick={() => giveFeedback(i, -1)}
                      style={{
                        fontSize: 12, padding: "2px 8px", borderRadius: 6, cursor: m.feedback != null ? "default" : "pointer",
                        background: m.feedback === -1 ? "rgba(239,68,68,0.15)" : "transparent",
                        border: m.feedback === -1 ? "1px solid rgba(239,68,68,0.3)" : "1px solid transparent",
                        color: m.feedback === -1 ? "#ef4444" : "#8f8f8f",
                        transition: "all 0.15s",
                      }}
                      disabled={m.feedback != null}
                      title="Not helpful"
                    >👎</button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="anim-fade-in" style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <div style={{ width: 26, height: 26, borderRadius: "50%", flexShrink: 0, background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.25)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11 }}>🤖</div>
              <div style={{ background: "#ffffff", border: "1px solid rgba(0,0,0,0.07)", borderRadius: 14, borderBottomLeftRadius: 4, padding: "12px 16px", display: "flex", gap: 5, alignItems: "center" }}>
                {[0, 150, 300].map(d => (
                  <span key={d} className="bounce-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: "#8f8f8f", display: "inline-block", animationDelay: `${d}ms` }} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Input row */}
        <div style={{ position: "relative", borderTop: "1px solid rgba(0,0,0,0.07)", padding: "0.75rem", display: "flex", alignItems: "center", gap: 8 }}>
          {/* Speaking a question must be as available as typing one — a
              low-literacy or blind user could ask about routes by voice but
              had to type to ask about fares. Transcribed text lands in the box
              rather than sending straight away, so it can be corrected. */}
          <VoiceInput
            onResult={text => setInput(prev => (prev ? prev + " " : "") + text)}
            title="Ask by voice"
          />
          <input
            className="input"
            style={{ flex: 1 }}
            placeholder="Ask about LRT fares, disruptions, rules… (Enter to send)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
          />
          <button className="btn-primary" onClick={() => send()} disabled={loading || !input.trim()}>Send</button>
        </div>
      </div>

      {/* Meta */}
      <div className="card" style={{ marginTop: 12, padding: "0.7rem 1.1rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {[["Model","gemini-flash-lite"],["Embedding","gemini-embedding-2"],["Chunks","1,903"],["Docs","41 official"]].map(([k,v]) => (
          <span key={k} style={{ fontSize: 10 }}>
            <span style={{ color: "#8f8f8f" }}>{k}: </span>
            <span style={{ color: "#737373" }}>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
