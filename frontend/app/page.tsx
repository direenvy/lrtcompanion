import Link from "next/link";
import CommuteCard from "@/components/CommuteCard";
import VideoHero from "@/components/VideoHero";
import ScrollReveal from "@/components/ScrollReveal";
import ExplodedStack from "@/components/ExplodedStack";

const intents = [
  {
    href: "/reroute",
    title: "I need to get somewhere",
    desc: "Plan a trip — we'll route around any active disruptions.",
  },
  {
    href: "/detect",
    title: "Something's wrong",
    desc: "Report a delay, breakdown, or crowded train.",
  },
  {
    href: "/chat",
    title: "I have a question",
    desc: "Ask about fares, hours, station info — answers from official docs.",
  },
];

const stats = [
  { v: "187", l: "Stations" },
  { v: "1,903", l: "RAG chunks" },
  { v: "573", l: "Labelled posts" },
  { v: "5",   l: "AI agents" },
];

const features = [
  {
    num: "01", href: "/detect",
    title: "Report a Disruption",
    desc: "Saw a delay, breakdown, or crowded train? Describe what happened — we flag it and update the live status board for other commuters.",
  },
  {
    num: "02", href: "/reroute",
    title: "Help me plan a trip to escape disruptions",
    desc: "Tell us where you're going. We find the best route around any active disruption, with alternatives by bus, walk, or ride-hail.",
  },
  {
    num: "03", href: "/voice",
    title: "Voice Help",
    desc: "Hands full, or reading is hard? Say where you are and where you're going — spoken directions in English or Bahasa Malaysia.",
  },
  {
    num: "04", href: "/chat",
    title: "Ask Anything",
    desc: "Fares, station info, service hours — ask in plain language, answered from official Rapid KL documents.",
  },
  {
    num: "05", href: "/status",
    title: "Live Line Status",
    desc: "All 8 Rapid KL rail lines at a glance — updated live from commuter reports.",
  },
];

export default function Home() {
  return (
    <div className="anim-fade-up">

      {/* ── Full-bleed video hero — Sonos style, headline on footage ── */}
      <VideoHero />
      <ScrollReveal />

      {/* ── Editorial statement + smart commute card ── */}
      <div className="reveal-on-scroll" style={{ padding: "96px 0 0" }}>
        <p style={{ color: "#000000", fontSize: "clamp(21px, 2.5vw, 28px)", fontWeight: 400, lineHeight: 1.35, maxWidth: 800, marginBottom: "64px" }}>
          An agentic AI companion for Rapid KL — detecting disruptions from commuter
          reports, rerouting you intelligently, and answering questions grounded in
          official documents.
        </p>
        <CommuteCard />
      </div>

      {/* ── Intent — large white cards on concrete ── */}
      <div className="reveal-on-scroll" style={{ margin: "96px 0" }}>
        <h2 style={{ fontSize: "clamp(28px, 4vw, 40px)", fontWeight: 400, lineHeight: 1.2, color: "#000000", marginBottom: "40px" }}>
          What do you need?
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
          {intents.map((it, i) => (
            <Link key={it.href} href={it.href} style={{ textDecoration: "none" }}>
              <div className="card card-lift" style={{
                padding: "40px 32px",
                minHeight: 220,
                display: "flex", flexDirection: "column", justifyContent: "space-between",
                animationDelay: `${i * 80}ms`,
              }}>
                <div>
                  <div style={{ fontSize: 21, fontWeight: 500, lineHeight: 1.3, color: "#000000", marginBottom: 12 }}>
                    {it.title}
                  </div>
                  <p style={{ fontSize: 15, color: "#737373", lineHeight: 1.5, margin: 0 }}>
                    {it.desc}
                  </p>
                </div>
                <span style={{ color: "#000000", fontSize: 15, fontWeight: 500, marginTop: 24 }}>
                  Start →
                </span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* ── Dark stats section — surface rhythm: concrete → white → void ── */}
      <div className="reveal-on-scroll" style={{
        background: "#000000", borderRadius: 20,
        padding: "clamp(32px, 6vw, 64px) clamp(20px, 4vw, 48px)", margin: "96px 0",
      }}>
        <p style={{ fontSize: 13, color: "#bfbfbf", letterSpacing: "0.12em", textTransform: "uppercase", fontWeight: 500, marginBottom: 40 }}>
          The system
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 32 }}>
          {stats.map((s) => (
            <div key={s.l}>
              <div style={{ fontSize: "clamp(40px, 5vw, 64px)", fontWeight: 400, lineHeight: 1.0, color: "#ffffff", marginBottom: 8 }}>{s.v}</div>
              <div style={{ fontSize: 15, color: "#bfbfbf" }}>{s.l}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Exploded pipeline — scroll-scrubbed, Sonos exploded-view adaptation ── */}
      <ExplodedStack />

      {/* ── Split feature — editorial statement + visual (Sonos "Astonishingly clear") ── */}
      <div className="reveal-on-scroll" style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 48, alignItems: "center", margin: "96px 0",
      }}>
        <div>
          <h2 style={{
            fontSize: "clamp(32px, 5vw, 56px)", fontWeight: 400,
            lineHeight: 1.1, letterSpacing: "-0.01em",
            color: "#000000", marginBottom: 24,
          }}>
            Every line,<br />one clear picture
          </h2>
          <p style={{ fontSize: 17, color: "#5f5f5f", lineHeight: 1.55, maxWidth: 480, marginBottom: 32 }}>
            LRT Companion fuses the official GTFS rail network, crowd-sourced
            disruption reports, and retrieval-grounded AI into a single view
            of the Klang Valley system — so you always know the way through.
          </p>
          <div className="card" style={{
            display: "inline-flex", alignItems: "baseline", gap: 12,
            padding: "24px 32px", border: "1px solid #e0e0e0",
          }}>
            <span style={{ fontSize: 40, fontWeight: 400, lineHeight: 1, color: "#000000" }}>187</span>
            <span style={{ fontSize: 14, color: "#737373" }}>stations · 8 lines mapped</span>
          </div>
        </div>
        <div style={{
          backgroundImage: "url(/feature.jpg)",
          backgroundSize: "cover", backgroundPosition: "center",
          backgroundColor: "#e0e0e0",
          borderRadius: 20, aspectRatio: "4 / 5", minHeight: 380,
        }} />
      </div>

      {/* ── Feature list — numbered editorial rows ── */}
      <div className="reveal-on-scroll" style={{ margin: "96px 0 64px" }}>
        <h2 style={{ fontSize: "clamp(28px, 4vw, 40px)", fontWeight: 400, lineHeight: 1.2, color: "#000000", marginBottom: "40px" }}>
          Everything it does
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {features.map((f, i) => (
            <Link key={f.href} href={f.href} style={{ textDecoration: "none" }}>
              <div className="card card-lift" style={{
                display: "flex", alignItems: "flex-start", gap: "clamp(16px, 3vw, 32px)",
                padding: "clamp(20px, 3vw, 32px) clamp(20px, 3vw, 40px)",
                animationDelay: `${i * 70}ms`,
              }}>
                <span style={{ fontSize: 14, fontWeight: 500, color: "#bfbfbf", minWidth: 28, paddingTop: 4 }}>
                  {f.num}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 21, fontWeight: 500, color: "#000000", marginBottom: 8 }}>{f.title}</div>
                  <p style={{ fontSize: 15, color: "#737373", lineHeight: 1.5, maxWidth: 640 }}>{f.desc}</p>
                </div>
                <span style={{ color: "#000000", fontSize: 18, paddingTop: 4 }}>→</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* ── Closing video moment — Sonos "product image card" pattern ── */}
      <div className="reveal-on-scroll" style={{ position: "relative", borderRadius: 20, overflow: "hidden", margin: "96px 0 64px" }}>
        <video
          autoPlay muted loop playsInline preload="metadata"
          style={{ display: "block", width: "100%", aspectRatio: "16 / 8", objectFit: "cover" }}
        >
          <source src="/hero2.mp4" type="video/mp4" />
        </video>
        <div style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(180deg, rgba(0,0,0,0.05) 40%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }} />
        <div style={{ position: "absolute", left: 48, bottom: 40, right: 48 }}>
          <p style={{ fontSize: "clamp(28px, 4vw, 48px)", fontWeight: 400, lineHeight: 1.1, color: "#ffffff", marginBottom: 20 }}>
            See the whole network move.
          </p>
          <Link href="/status" className="hero-btn-ghost" style={{ padding: "12px 26px", fontSize: 15 }}>
            Open Line Status
          </Link>
        </div>
      </div>

    </div>
  );
}
