"use client";
/**
 * Voice Help — hands-free assistant for elderly / low-literacy riders.
 * Speak where you are stuck; the assistant reports it, finds a route around
 * live disruptions, and reads the directions aloud.
 *
 * Speech-to-text: browser Web Speech API (SpeechRecognition) — no external
 * services. A typed fallback box covers unsupported browsers.
 */
import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { friendlyError, apiBase } from "@/lib/api";
import LiveRegion from "@/components/LiveRegion";

interface Turn {
  who: "user" | "assistant";
  text: string;
  lang?: "en-US" | "ms-MY";   // language this turn was spoken/answered in
}

// Quiet gap after which the utterance is considered finished. 2.5 s cut people
// off mid-sentence while they recalled a station name — the target users here
// (elderly, low-literacy) pause more, not less, so this errs long. Tapping ⏹
// submits immediately for anyone who wants to move faster.
const SILENCE_MS = 4000;

export default function VoicePage() {
  const [turns, setTurns]         = useState<Turn[]>([]);
  const [listening, setListening] = useState(false);
  const [busy, setBusy]           = useState(false);
  const [lang, setLang]           = useState<"en-US" | "ms-MY">("en-US");
  const [typed, setTyped]         = useState("");
  const [error, setError]         = useState("");
  const [heard, setHeard]         = useState("");   // live interim transcript
  const [checking, setChecking]   = useState(false); // mic self-test running
  const [level, setLevel]         = useState(0);    // raw mic input level 0-100
  const originHint = useRef<string | null>(null);
  // Station offered by the last "did you mean X?" — a bare "yes" is meaningless
  // without it, so it has to survive to the next turn.
  const pendingStation = useRef<string | null>(null);
  const recRef     = useRef<any>(null);
  const meterStop  = useRef<(() => void) | null>(null);
  // Local-Whisper capture. Runs ALONGSIDE the browser recogniser rather than
  // replacing it: Whisper is batch (record, then transcribe), so without Web
  // Speech there would be no live "Heard:" text while the user is talking —
  // and that feedback is what tells an elderly or blind user it is working.
  // Web Speech drives the display; Whisper produces the transcript we act on.
  const mediaRec   = useRef<MediaRecorder | null>(null);
  const chunks     = useRef<Blob[]>([]);
  const [sttLocal, setSttLocal] = useState<boolean | null>(null);   // null = unknown
  const [sttBackend, setSttBackend] = useState<string | null>(null); // "groq" | "local" | null

  // Ask once, before any recording. Choosing the capture path AFTER the user
  // has spoken would mean discarding what they said.
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const { data } = await axios.get(`${apiBase()}/api/voice/stt-status`);
        if (!alive) return;
        setSttLocal(!!data.available);
        setSttBackend(data.backend ?? null);
        // Weights load on a background thread at boot; keep checking until up.
        if (!data.available && !data.error) setTimeout(poll, 4000);
      } catch { if (alive) setSttLocal(false); }
    };
    poll();
    return () => { alive = false; };
  }, []);

  // Raw mic level meter — independent of Google's speech service, so a flat
  // bar while speaking means the OS/device delivers no audio at all.
  //
  // NOT run while the recogniser is listening: Web Speech opens its own
  // capture of the same device, and two concurrent streams on Windows make the
  // gain controls fight each other, which quietly degrades the audio actually
  // sent for recognition. The meter is a diagnostic, so it defers to the thing
  // it is diagnosing — see checkMic(), which runs it on demand instead.
  const startMeter = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Noise suppression is tuned for conference calls and treats soft or
          // distant speech as background — exactly the voices this page is for.
          noiseSuppression: false,
          echoCancellation: false,
          autoGainControl:  true,   // keep: lifts quiet speakers
        },
      });
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      let raf = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(100, Math.round((peak / 128) * 300)));
        raf = requestAnimationFrame(tick);
      };
      tick();
      meterStop.current = () => {
        cancelAnimationFrame(raf);
        stream.getTracks().forEach(t => t.stop());
        ctx.close();
        setLevel(0);
        meterStop.current = null;
      };
    } catch (e: any) {
      const names: Record<string, string> = {
        NotAllowedError:  "Microphone permission is blocked — click the mic/lock icon in the address bar and allow it.",
        NotFoundError:    "No microphone device was found on this computer.",
        NotReadableError: "Another app is holding the microphone (Discord, Teams, OBS, Zoom…) — close it and retry.",
      };
      setError(names[e?.name] ?? `Microphone error: ${e?.name || e}`);
    }
  };

  // Feature-detect only after mount — SSR has no `window`, and branching on
  // it during render makes server and client HTML disagree (hydration error)
  const [ready, setReady] = useState(false);
  useEffect(() => { setReady(true); }, []);
  const SR = ready
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : null;
  const canListen = !!SR;
  const canSpeak  = ready && "speechSynthesis" in window;

  useEffect(() => () => {
    recRef.current?.abort?.();
    meterStop.current?.();
    if (canSpeak) window.speechSynthesis.cancel();
  }, [canSpeak]);

  // Chrome loads its voice list asynchronously — warm it so the first speak()
  // after page load can already pick the right reader
  useEffect(() => {
    if (!canSpeak) return;
    window.speechSynthesis.getVoices();
    const warm = () => window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener?.("voiceschanged", warm);
    return () => window.speechSynthesis.removeEventListener?.("voiceschanged", warm);
  }, [canSpeak]);

  // Each language gets its own reader — an English voice must never read
  // Malay text or vice versa, including when replaying old bubbles.
  // Malay preference order: real Malay voice (ms) → Indonesian (id, reads
  // Malay near-natively; Chrome ships "Google Bahasa Indonesia" built in)
  // → browser's best guess for u.lang.
  const speak = (text: string, speakLang: "en-US" | "ms-MY") => {
    if (!canSpeak) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.92;
    u.lang = speakLang;
    const voices = window.speechSynthesis.getVoices();
    const prefixes = speakLang === "ms-MY" ? ["ms", "id"] : ["en"];
    for (const p of prefixes) {
      const voice = voices.find(v => v.lang.toLowerCase().startsWith(p));
      if (voice) { u.voice = voice; break; }
    }
    window.speechSynthesis.speak(u);
  };

  // Mic self-test: runs the level meter for a few seconds while the recogniser
  // is NOT listening, so the two never contend for the device. Gives the user
  // the same "is my microphone working?" answer without the interference.
  const checkMic = async () => {
    if (listening || checking) return;
    setChecking(true);
    await startMeter();
    setTimeout(() => { meterStop.current?.(); setChecking(false); }, 5000);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { noiseSuppression: false, echoCancellation: false, autoGainControl: true },
      });
      chunks.current = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data); };
      mr.onstop = () => stream.getTracks().forEach(t => t.stop());
      mr.start();
      mediaRec.current = mr;
    } catch {
      mediaRec.current = null;   // fall through to the browser transcript
    }
  };

  // Stop the recorder and hand the audio to the local model. Returns null on
  // any failure so the caller keeps the browser transcript.
  const transcribeLocally = async (): Promise<string | null> => {
    const mr = mediaRec.current;
    mediaRec.current = null;
    if (!mr || mr.state === "inactive") return null;
    const blob: Blob = await new Promise(resolve => {
      mr.addEventListener("stop", () =>
        resolve(new Blob(chunks.current, { type: mr.mimeType || "audio/webm" })),
        { once: true });
      mr.stop();
    });
    if (blob.size < 2000) return null;         // too short to be speech
    try {
      const form = new FormData();
      form.append("audio", blob, "speech.webm");
      const { data } = await axios.post(
        `${apiBase()}/api/voice/transcribe?lang=${lang === "ms-MY" ? "ms" : "en"}`,
        form, { timeout: 20000 },
      );
      const text = (data?.text ?? "").trim();
      return data?.available && text ? text : null;
    } catch {
      return null;
    }
  };

  const submit = async (text: string, alternatives: string[] = []) => {
    const clean = text.trim();
    if (!clean || busy) return;
    const turnLang = lang;   // pin the language of THIS exchange
    setError("");
    setTurns(t => [...t, { who: "user", text: clean, lang: turnLang }]);
    setBusy(true);
    try {
      const { data } = await axios.post(`${apiBase()}/api/voice/assist`, {
        text: clean,
        // Lower-ranked readings from the recogniser. The backend tries each and
        // keeps whichever actually resolves to stations — the top-ranked guess
        // is often an English soundalike for a Malaysian place name.
        alternatives,
        origin_hint: originHint.current,
        pending_station: pendingStation.current,
        lang: turnLang === "ms-MY" ? "ms" : "en",
      });
      originHint.current = data.need_destination ? data.origin : null;
      pendingStation.current = data.pending_station ?? null;
      setTurns(t => [...t, { who: "assistant", text: data.reply, lang: turnLang }]);
      speak(data.reply, turnLang);
    } catch (e) {
      const msg = friendlyError(e);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const listen = () => {
    if (!canListen || busy) return;
    if (listening) { recRef.current?.stop?.(); return; }
    if (canSpeak) window.speechSynthesis.cancel();
    const rec = new SR();
    recRef.current = rec;
    rec.lang = lang;
    rec.continuous = true;       // keep listening through natural pauses
    rec.interimResults = true;   // stream partial words so the user SEES it hearing them
    // Ask for several readings, not one. Chrome ranks by acoustic likelihood,
    // which mis-serves Malaysian place names — "Kerinchi" commonly comes back
    // as ["Corinthian", "Kerinchi", …]. The backend picks whichever resolves.
    rec.maxAlternatives = 5;
    setHeard("");
    let concluded = false;   // some browsers end without result OR error — never fail silently
    let finalText = "";
    let finalAlts: string[] = [];   // lower-ranked readings of the final result
    let silence: ReturnType<typeof setTimeout> | null = null;
    // Submit after SILENCE_MS of quiet. 2.5 s cut people off mid-sentence when
    // they paused to recall a station name — which reads as "it did not hear
    // me" even though the audio was fine. Tapping ⏹ submits immediately.
    const armSilence = () => {
      if (silence) clearTimeout(silence);
      silence = setTimeout(() => rec.stop(), SILENCE_MS);
    };
    rec.onresult = (e: any) => {
      let interim = "";
      finalText = "";
      const alts: string[][] = [];
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i];
        const t = r[0].transcript;
        if (r.isFinal) {
          finalText += t + " ";
          // r is a SpeechRecognitionResult: an array-like of ranked readings.
          const ranked: string[] = [];
          for (let k = 1; k < r.length; k++) ranked.push(r[k].transcript);
          alts.push(ranked);
        } else interim += t;
      }
      // One sentence can arrive as several final results; stitch each rank
      // across them so alternative #1 is a whole sentence, not a fragment.
      const depth = Math.max(0, ...alts.map(a => a.length));
      finalAlts = Array.from({ length: depth }, (_, k) =>
        alts.map((a, j) => a[k] ?? (e.results[j]?.[0]?.transcript ?? "")).join(" ").trim()
      ).filter(Boolean);
      if (finalText) concluded = true;
      setHeard((finalText + interim).trim());
      armSilence();
    };
    rec.onerror = (e: any) => {
      setListening(false);
      const reasons: Record<string, string> = {
        "not-allowed":    "Microphone access was blocked — click the mic icon in the address bar and allow it, then try again.",
        "service-not-allowed": "This browser blocks the speech service (Brave does by default) — use Chrome or Edge, or type below.",
        "audio-capture":  "No microphone was found — check it's plugged in and allowed in Windows privacy settings.",
        "no-speech":      "I didn't hear anything — tap the mic and speak straight away.",
        "network":        "The speech service couldn't be reached — Chrome's voice input needs internet. Check your connection, or type below.",
        "aborted":        "Listening was cancelled.",
      };
      concluded = true;
      setError(reasons[e.error] ?? `Speech input failed (${e.error}) — please try again, or type below.`);
    };
    rec.onend = () => {
      if (silence) clearTimeout(silence);
      setListening(false);
      meterStop.current?.();
      if (finalText.trim() || mediaRec.current) {
        // Prefer the local model; keep the browser reading as a fallback AND as
        // an extra hypothesis, since either can be the one that resolves.
        const browserText = finalText.trim();
        setBusy(true);
        transcribeLocally().then(whisper => {
          const chosen = whisper || browserText;
          if (!chosen) {
            setBusy(false);
            setError("Listening ended without hearing anything — tap the mic and speak straight away, or type below.");
            return;
          }
          setBusy(false);
          const alts = whisper && browserText
            ? [browserText, ...finalAlts]   // browser reading becomes an alternative
            : finalAlts;
          submit(chosen, alts);
        });
      } else if (!concluded) {
        setError("Listening ended without hearing anything — tap the mic and speak straight away, or type below.");
      }
    };
    rec.start();
    // Capture the raw audio in parallel for Whisper. Failure here is not fatal:
    // Web Speech is already running, so the turn still completes on its
    // transcript — just without the accuracy gain.
    if (sttLocal) startRecording();
    setListening(true);
  };

  // Spoken status for screen readers. The assistant's reply is the important
  // one: without it a blind user hears silence after speaking and cannot tell
  // whether the request worked.
  const lastAssistant = [...turns].reverse().find(t => t.who === "assistant");
  const announcement =
      busy      ? "Finding your route, please wait."
    : listening ? "Listening. Say where you are and where you want to go."
    : lastAssistant ? lastAssistant.text
    : "";

  return (
    <div className="anim-fade-up" style={{ maxWidth: 580 }}>
      <LiveRegion message={announcement} />
      <LiveRegion message={error} politeness="assertive" />

      <p className="section-label" style={{ marginBottom: 8 }}>
        Voice Assistant · Speech in · Speech out
      </p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Voice-Guided Journey Assistant
      </h1>
      <p style={{ color: "#737373", fontSize: 14, lineHeight: 1.65, marginBottom: "1.5rem" }}>
        Stuck somewhere? Press the button and <strong>say where you are and where
        you want to go</strong> — for example: <em>&ldquo;I&rsquo;m stuck at Kampung Baru,
        I want to go to Masjid Jamek.&rdquo;</em> The assistant reports the problem,
        finds a way around it, and reads the directions out loud. You can also
        ask service questions — <em>&ldquo;how much is the My50 pass?&rdquo;</em>
      </p>

      {/* Big talk button */}
      <div className="card" style={{ padding: "2rem 1.5rem", marginBottom: 12, textAlign: "center" }}>
        {canListen ? (
          <>
            <button
              onClick={listen}
              disabled={busy}
              aria-label={listening ? "Stop listening" : "Press and speak"}
              style={{
                width: 120, height: 120, borderRadius: "50%",
                border: listening ? "3px solid #ef4444" : "3px solid rgba(0,0,0,0.15)",
                background: listening ? "rgba(239,68,68,0.08)" : "#000000",
                color: listening ? "#ef4444" : "#ffffff",
                fontSize: 44, cursor: "pointer",
                boxShadow: listening ? "0 0 0 10px rgba(239,68,68,0.08)" : "none",
                transition: "all 0.2s",
              }}
            >
              {busy ? "…" : listening ? "◼" : "🎤"}
            </button>
            <p style={{ fontSize: 14, color: "#5f5f5f", marginTop: 14 }}>
              {busy ? "Finding your route…"
                : listening ? (heard ? <>Heard: <em>&ldquo;{heard}&rdquo;</em></> : "Listening — take your time; pause when you're done")
                : "Tap the microphone, then speak"}
            </p>
            {/* Which engine is transcribing. Worth surfacing: accuracy differs
                markedly between them, so a tester reporting a mis-heard station
                needs to know which one produced it. */}
            {sttLocal !== null && (
              <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 8 }}>
                {!sttLocal
                  ? "☁️ Browser speech recognition — needs internet"
                  : sttBackend === "groq"
                  ? "☁️ Cloud speech recognition (Groq Whisper) — needs internet"
                  : sttBackend === "local"
                  ? "🎯 On-device speech recognition (Whisper) — works offline"
                  : "🎯 Speech recognition ready"}
              </p>
            )}

            {/* The level meter cannot run during recognition (two captures of
                one device fight each other), so it is offered on demand — the
                "is my mic even working?" question still gets an answer. */}
            {!listening && !busy && !checking && (
              <button
                onClick={checkMic}
                style={{
                  background: "none", border: "1px solid rgba(0,0,0,0.12)",
                  color: "#737373", fontSize: 11, padding: "5px 12px",
                  borderRadius: 99, cursor: "pointer", marginTop: 10,
                }}
              >
                Test my microphone
              </button>
            )}
            {checking && (
              <div style={{ maxWidth: 220, margin: "10px auto 0" }}>
                <div style={{ height: 6, borderRadius: 99, background: "rgba(0,0,0,0.07)", overflow: "hidden" }}>
                  <div style={{
                    height: "100%", width: `${level}%`, borderRadius: 99,
                    background: level > 4 ? "#22c55e" : "#ef4444",
                    transition: "width 0.08s linear",
                  }} />
                </div>
                <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 4 }}>
                  Mic level — {level > 4 ? "receiving audio ✓" : "no audio detected"}
                </p>
              </div>
            )}
            <div style={{ display: "inline-flex", gap: 6, marginTop: 10 }}>
              {([["en-US", "English"], ["ms-MY", "Bahasa Melayu"]] as const).map(([code, label]) => (
                <button key={code} onClick={() => setLang(code)} style={{
                  fontSize: 11, padding: "5px 12px", borderRadius: 99, cursor: "pointer",
                  border: `1px solid ${lang === code ? "#000000" : "rgba(0,0,0,0.12)"}`,
                  background: lang === code ? "#000000" : "transparent",
                  color: lang === code ? "#ffffff" : "#737373",
                }}>{label}</button>
              ))}
            </div>
          </>
        ) : ready ? (
          <p style={{ fontSize: 13, color: "#b45309" }}>
            This browser doesn&rsquo;t support voice input — use the box below;
            answers are still read aloud.
          </p>
        ) : (
          <p style={{ fontSize: 13, color: "#8f8f8f" }}>Loading…</p>
        )}
      </div>

      {/* Typed fallback (also the reliable path for demos) */}
      <div className="card" style={{ padding: "1rem 1.25rem", marginBottom: 12, display: "flex", gap: 8 }}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder='Or type it: "stuck at Kampung Baru, going to Masjid Jamek"'
          value={typed}
          onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { submit(typed); setTyped(""); } }}
        />
        <button className="pill-btn" style={{ fontSize: 13 }}
          onClick={() => { submit(typed); setTyped(""); }}>
          Send
        </button>
      </div>

      {error && (
        <p style={{ fontSize: 12, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
          ⚠ {error}
        </p>
      )}

      {/* Conversation */}
      <div role="log" aria-label="Conversation" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {turns.map((t, i) => (
          <div key={i} aria-label={t.who === "user" ? "You said" : "Assistant replied"} style={{
            alignSelf: t.who === "user" ? "flex-end" : "flex-start",
            maxWidth: "85%",
            background: t.who === "user" ? "#000000" : "rgba(0,0,0,0.04)",
            color:      t.who === "user" ? "#ffffff" : "#2e2e2e",
            border: "1px solid rgba(0,0,0,0.08)",
            borderRadius: 14, padding: "10px 14px",
            fontSize: 15, lineHeight: 1.6,
          }}>
            {t.who === "assistant" && canSpeak && (
              <button onClick={() => speak(t.text, t.lang ?? "en-US")} aria-label="Read this reply aloud"
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 14, padding: 0, marginRight: 8 }}>
                🔊
              </button>
            )}
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
