"use client";
/**
 * Mic button that fills a text field by speech.
 *
 * Transcription goes through the backend's LOCAL Whisper model, the same one
 * the Voice Help page uses — so a station or fare question is recognised with
 * the station-name vocabulary hint rather than competing against English
 * priors ("Kerinchi" -> "Corinthian"). If the model is unavailable it falls
 * back to the browser recogniser, and if that is missing too the button simply
 * does not render: typing always works.
 *
 * Deliberately simpler than the Voice Help page, which runs both engines at
 * once to keep a live transcript on screen while the user speaks. Here the
 * user is filling a text box they can already see and edit, so a single
 * accurate result after they stop is the better trade.
 */
import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { apiBase } from "@/lib/api";

const SILENCE_MS = 4000;   // matches Voice Help — these users pause mid-sentence

export default function VoiceInput({
  onResult,
  lang = "en",
  title = "Ask by voice",
}: {
  onResult: (text: string) => void;
  lang?: "en" | "ms";
  title?: string;
}) {
  const [listening, setListening] = useState(false);
  const [busy, setBusy]     = useState(false);
  const [local, setLocal]   = useState<boolean | null>(null);
  const [error, setError]   = useState("");
  const mediaRec = useRef<MediaRecorder | null>(null);
  const chunks   = useRef<Blob[]>([]);
  const recRef   = useRef<any>(null);

  // Ask before recording, not after: discovering the transcription path is
  // unavailable once the user has already spoken means losing the utterance.
  useEffect(() => {
    let alive = true;
    axios.get(`${apiBase()}/api/voice/stt-status`)
      .then(({ data }) => { if (alive) setLocal(!!data.available); })
      .catch(() => { if (alive) setLocal(false); });
    return () => { alive = false; };
  }, []);

  const SR = typeof window !== "undefined"
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : null;

  // Nothing can transcribe — render nothing rather than a button that fails.
  if (local === false && !SR) return null;

  const stop = () => {
    recRef.current?.stop?.();
    mediaRec.current?.stop?.();
    setListening(false);
  };

  const startLocal = async () => {
    setError("");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        // Same constraints as Voice Help: conference-call noise suppression
        // gates the soft speech this feature exists to serve.
        audio: { noiseSuppression: false, echoCancellation: false, autoGainControl: true },
      });
    } catch {
      setError("Microphone blocked — allow it in the address bar, or type instead.");
      return;
    }
    chunks.current = [];
    const mr = new MediaRecorder(stream);
    mediaRec.current = mr;
    let silence: ReturnType<typeof setTimeout> | null = null;

    mr.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data); };
    mr.onstop = async () => {
      if (silence) clearTimeout(silence);
      stream.getTracks().forEach(t => t.stop());
      setListening(false);
      const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
      if (blob.size < 2000) return;               // too short to be speech
      setBusy(true);
      try {
        const form = new FormData();
        form.append("audio", blob, "speech.webm");
        const { data } = await axios.post(
          `${apiBase()}/api/voice/transcribe?lang=${lang}`, form, { timeout: 20000 });
        const text = (data?.text ?? "").trim();
        if (text) onResult(text);
        else setError("I didn't catch that — try again, or type it.");
      } catch {
        setError("Could not transcribe — please type your question.");
      } finally {
        setBusy(false);
      }
    };
    mr.start();
    setListening(true);
    // No streaming transcript to end on, so stop on a fixed window; the user
    // can also tap again to submit immediately.
    silence = setTimeout(() => mr.state !== "inactive" && mr.stop(), 12000);
  };

  const startBrowser = () => {
    setError("");
    const rec = new SR();
    recRef.current = rec;
    rec.lang = lang === "ms" ? "ms-MY" : "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    let finalText = "";
    let silence: ReturnType<typeof setTimeout> | null = null;
    const arm = () => {
      if (silence) clearTimeout(silence);
      silence = setTimeout(() => rec.stop(), SILENCE_MS);
    };
    rec.onresult = (e: any) => {
      finalText = "";
      for (let i = 0; i < e.results.length; i++)
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript + " ";
      arm();
    };
    rec.onerror = () => { setListening(false); setError("Speech input failed — please type instead."); };
    rec.onend = () => {
      if (silence) clearTimeout(silence);
      setListening(false);
      if (finalText.trim()) onResult(finalText.trim());
    };
    rec.start();
    setListening(true);
  };

  const toggle = () => {
    if (busy) return;
    if (listening) { stop(); return; }
    if (local) startLocal(); else startBrowser();
  };

  return (
    <>
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        title={title}
        aria-label={listening ? "Stop recording" : title}
        aria-pressed={listening}
        style={{
          flexShrink: 0,
          width: 40, height: 40, borderRadius: "50%",
          border: `1px solid ${listening ? "rgba(239,68,68,0.5)" : "rgba(0,0,0,0.12)"}`,
          background: listening ? "rgba(239,68,68,0.08)" : "transparent",
          cursor: busy ? "default" : "pointer",
          fontSize: 16, lineHeight: 1,
          transition: "all 0.15s",
        }}
      >
        {busy ? "…" : listening ? "◼" : "🎤"}
      </button>
      {/* Spoken status — without it a screen-reader user gets no signal that
          recording started, finished, or failed. */}
      <div className="sr-only" role="status" aria-live="polite">
        {busy ? "Transcribing, please wait."
          : listening ? "Listening. Speak your question."
          : error || ""}
      </div>
      {error && (
        <span style={{ position: "absolute", bottom: -18, left: 12, fontSize: 10.5, color: "#b91c1c" }}>
          {error}
        </span>
      )}
    </>
  );
}
