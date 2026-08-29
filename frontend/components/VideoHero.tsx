"use client";
/**
 * VideoHero — Sonos-style full-bleed video hero.
 * Edge-to-edge footage directly under the nav, centered display headline
 * and pill CTAs overlaid, small circular pause/play control bottom-right.
 * No scrim — the footage provides contrast (DESIGN.md).
 */
import { useRef, useState } from "react";
import Link from "next/link";

export default function VideoHero() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); }
    else          { v.pause(); setPlaying(false); }
  };

  return (
    <div className="full-bleed-hero" style={{ position: "relative", overflow: "hidden" }}>
      <video
        ref={videoRef}
        autoPlay muted loop playsInline
        preload="auto"
        style={{
          display: "block", width: "100%",
          height: "min(calc(100vh - 52px), 900px)", objectFit: "cover",
        }}
      >
        <source src="/hero.mp4" type="video/mp4" />
      </video>

      {/* Contrast veil — cinematic gradient, darker toward the base */}
      <div style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(180deg, rgba(0,0,0,0.25) 0%, rgba(0,0,0,0.30) 55%, rgba(0,0,0,0.50) 100%)",
        pointerEvents: "none",
      }} />

      {/* Centered overlay — headline + pill CTAs */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        textAlign: "center", padding: "0 24px",
      }}>
        <h1 className="anim-fade-up" style={{
          fontSize: "clamp(2.5rem, 7vw, 5.75rem)",
          fontWeight: 400, lineHeight: 1.05,
          letterSpacing: "-0.025em",
          color: "#ffffff",
          textShadow: "0 2px 20px rgba(0,0,0,0.6), 0 6px 60px rgba(0,0,0,0.45)",
          marginBottom: "40px",
          maxWidth: "16ch",
        }}>
          <span style={{ opacity: 0.9 }}>From disruption<br />to destination</span><br />
          {/* Non-breaking space keeps "thinks ahead" together: without it the
              line wraps to a stranded "ahead" on its own line at most widths. */}
          <span style={{ fontWeight: 650 }}>with AI that thinks&nbsp;ahead</span>
        </h1>
        <div className="anim-fade-up" style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center", animationDelay: "150ms" }}>
          <Link href="/reroute" className="hero-btn-solid">Plan trips to exit disruptions</Link>
          <Link href="/status" className="hero-btn-ghost">Check Line Status</Link>
        </div>
      </div>

      {/* Pause / play — Sonos scroll-indicator style */}
      <button
        onClick={toggle}
        aria-label={playing ? "Pause video" : "Play video"}
        className="hero-pause"
      >
        {playing ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="6,4 20,12 6,20" />
          </svg>
        )}
      </button>
    </div>
  );
}
