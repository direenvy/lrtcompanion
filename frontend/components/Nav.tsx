"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import NavUser from "@/components/NavUser";

// Nav labels stay short so they scan in a glance and survive mobile widths;
// each page carries the full descriptive title as its own heading.
// "/orchestrate" (the multi-agent pipeline) is deliberately NOT here — it is a
// demonstration of the NLP -> Rerouting -> RAG chain rather than a commuter
// task, so it lives under Dashboard instead of competing with Plan Trip.
// Nav labels stay SHORT so eight of them fit on one line before the hamburger
// takes over. Each page carries its full descriptive title as its own <h1>, so
// nothing is lost by trimming here — "Plan Trip" opens "Journey Recovery
// Planner", "Agent Pipeline" opens "Advanced Recovery Planner", and so on.
const navLinks = [
  { href: "/detect",      label: "Report Disruption" },
  { href: "/reroute",     label: "Plan Trip" },
  { href: "/orchestrate", label: "Agent Pipeline" },
  { href: "/voice",       label: "Voice Command" },
  { href: "/chat",        label: "Fares & FAQ" },
  { href: "/status",      label: "Line Status" },
  { href: "/dashboard",   label: "Dashboard" },
  { href: "/settings",    label: "Settings" },
];

export default function Nav() {
  const [open, setOpen] = useState(false);
  // Sonos-style hide-on-scroll-down, reveal-on-scroll-up. Nav always shows
  // near the top of the page and while any mobile drawer is open.
  const [hidden, setHidden] = useState(false);
  const pathname = usePathname();

  // Close drawer whenever route changes
  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    let lastY = window.scrollY;
    let ticking = false;
    const THRESHOLD = 8;   // ignore jitter smaller than this
    const REVEAL_AT = 80;  // always show when within this many px of the top

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        const y = window.scrollY;
        const dy = y - lastY;
        if (Math.abs(dy) < THRESHOLD) return;
        if (y < REVEAL_AT)      setHidden(false);      // top of page → show
        else if (dy > 0)        setHidden(true);       // scrolling down → hide
        else                    setHidden(false);      // scrolling up   → show
        lastY = y;
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Keep the bar visible whenever the mobile drawer is open, otherwise the
  // drawer would float detached with no visible parent.
  const isHidden = hidden && !open;

  return (
    <>
      {/* Spacer holding the 52px the fixed bar would otherwise take out of the
          flow. The bar itself is `fixed` (not `sticky`) because a sticky bar
          that also carries a transform and a backdrop-filter is unreliable in
          Chromium — it can refuse to repaint mid-slide. */}
      <div aria-hidden style={{ height: 52 }} />

      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 50,
        borderBottom: "1px solid rgba(0,0,0,0.07)",
        background: "rgba(255,255,255,0.88)",
        backdropFilter: "blur(16px)",
        padding: "0 1rem",
        display: "flex", alignItems: "center", height: 52,
        gap: 16,
        transform: isHidden ? "translateY(-100%)" : "translateY(0)",
        transition: "transform 320ms cubic-bezier(0.4, 0, 0.2, 1)",
        willChange: "transform",
      }}>
        {/* Hamburger (mobile only) */}
        <button
          onClick={() => setOpen(p => !p)}
          aria-label="Toggle menu"
          className="nav-burger"
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "#000000", padding: 8, marginLeft: -8,
            display: "none",  // shown via CSS media query
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            {open
              ? <><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></>
              : <><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></>}
          </svg>
        </button>

        {/* Wordmark — Sonos style: plain, bold, letter-spaced */}
        <Link href="/" style={{ textDecoration: "none", flexShrink: 0 }}>
          <span style={{
            color: "#000000", fontWeight: 700,
            fontSize: 12.5, letterSpacing: "0.09em",
            whiteSpace: "nowrap",
          }}>LRT COMPANION</span>
        </Link>

        {/* Desktop links */}
        {/* flex: 1 = "grow to fill the space between wordmark and account chip"
            min-width: 0  = "and shrink below your content when needed"; without
            this a flex child refuses to shrink past its own content width,
            which is exactly what caused the overlap. justify-content:center
            keeps the row visually centred while it fits. */}
        <div className="nav-links-desktop" style={{
          display: "flex", gap: 2,
          flex: "1 1 0",
          minWidth: 0,
          justifyContent: "center",
        }}>
          {navLinks.map(({ href, label }) => (
            <Link key={href} href={href} className="nav-link">{label}</Link>
          ))}
        </div>

        {/* Right side */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span className="nav-beta" style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: 11, fontFamily: "var(--font-sans)",
            color: "#5f5f5f",
            background: "rgba(0,0,0,0.04)",
            border: "1px solid #cdcdcd",
            padding: "3px 10px", borderRadius: 99,
          }}>
            <span className="pulse-green" style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#000000", display: "inline-block",
            }} />
            BETA
          </span>
          <NavUser />
        </div>
      </nav>

      {/* Mobile drawer */}
      {open && (
        <div className="nav-drawer" style={{
          position: "fixed", top: 52, left: 0, right: 0, zIndex: 49,
          background: "rgba(255,255,255,0.97)",
          backdropFilter: "blur(16px)",
          borderBottom: "1px solid rgba(0,0,0,0.07)",
          padding: "0.5rem 1rem 1rem",
          display: "flex", flexDirection: "column", gap: 2,
        }}>
          {navLinks.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              style={{
                color: pathname === href ? "#000000" : "#5f5f5f",
                textDecoration: "none",
                padding: "14px 12px",
                fontSize: 15,
                borderRadius: 8,
                background: pathname === href ? "rgba(0,0,0,0.05)" : "transparent",
                fontWeight: pathname === href ? 600 : 500,
              }}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
