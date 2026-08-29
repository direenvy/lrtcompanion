"use client";
/**
 * ExplodedStack — Sonos-style scroll-scrubbed exploded view, adapted:
 * the agent pipeline starts as a collapsed deck and spreads apart as the
 * user scrolls through the section. Transform-only + rAF = no jank.
 */
import { useEffect, useRef } from "react";

const LAYERS = [
  { label: "You",              sub: "Report an issue or ask for a route",            bg: "#ffffff", color: "#000000", border: "1px solid #e0e0e0" },
  { label: "NLP Agent",        sub: "Classifies sentiment and issue type",           bg: "#e0e0e0", color: "#000000", border: "none" },
  { label: "Rerouting Agent",  sub: "Finds the way around disruptions on the GTFS network", bg: "#bfbfbf", color: "#000000", border: "none" },
  { label: "RAG Agent",        sub: "Advice grounded in official Rapid KL documents", bg: "#2e2e2e", color: "#ffffff", border: "none" },
  { label: "One clear answer", sub: "Route, alternatives, and what to do next",      bg: "#000000", color: "#ffffff", border: "none" },
];

// Smoother S-curve easing (easeInOutCubic) — gentle start, gentle finish.
const easeOut = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

export default function ExplodedStack() {
  const wrapRef  = useRef<HTMLDivElement>(null);
  const headRef  = useRef<HTMLDivElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const mid = (LAYERS.length - 1) / 2;

    // The open gap is derived from the viewport so the topmost card can never
    // ride up into the heading on a short laptop screen. Half the viewport is
    // the space above centre; subtract the heading block and a breathing gap,
    // then split what remains between the two cards above the middle one.
    // Centre-to-centre distance must EXCEED a card's own height or the cards
    // simply touch and the deck reads as one solid block. Measure the real
    // card height and add a deliberate visual gap on top of it.
    const VISUAL_GAP = 18;

    const apply = (p: number) => {
      const e = easeOut(p);
      const group = groupRef.current;
      const first = cardRefs.current[0];
      if (!group || !first) return;

      const cardH = first.offsetHeight || 88;
      const openGap = cardH + VISUAL_GAP;
      const gap = 10 + (openGap - 10) * e;

      cardRefs.current.forEach((el, i) => {
        if (!el) return;
        const d = i - mid;
        // A deeper shadow the further a card travels from the centre, so the
        // pieces read as separating in space rather than as a list that grew.
        el.style.transform = `translateY(${d * gap}px)`;
        el.style.boxShadow =
          `0 ${(2 + e * 16).toFixed(1)}px ${(6 + e * 34).toFixed(1)}px ` +
          `rgba(0,0,0,${(0.04 + e * 0.11).toFixed(3)})`;
      });

      // Lay the open deck out inside the band left between the heading and the
      // bottom of the screen. Sizing against that whole band — rather than only
      // the space above the deck's centre — is what keeps short screens from
      // being scaled down far more than they need to be.
      const h = window.innerHeight;
      const headEl = headRef.current;
      const headBottom = headEl
        ? headEl.offsetTop + headEl.offsetHeight
        : h * 0.14 + 107;

      const PAD = 24;
      const band  = h - headBottom - PAD * 2;
      const deckH = 4 * openGap + cardH;                  // fully-open height
      const fit   = Math.min(1, band / Math.max(deckH, 1));

      // Centre the deck in that band, but never let the gap under the heading
      // grow past 90px — on a tall screen the slack belongs at the bottom,
      // not as a void between the text and the deck.
      const topGap = Math.min(90, (band - deckH * fit) / 2);
      const centre = headBottom + PAD + topGap + (deckH * fit) / 2;

      group.style.top = `${centre.toFixed(1)}px`;
      group.style.transform = `translateX(-50%) scale(${fit.toFixed(3)})`;
    };

    if (reduce) { apply(1); return; }

    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        const wrap = wrapRef.current;
        if (!wrap) return;
        const rect = wrap.getBoundingClientRect();
        // Drive the spread off the section's APPROACH, not off the scrolling
        // that happens once it is already pinned. Opening begins when the
        // section's top edge is 60% of the way down the viewport and finishes
        // exactly when it reaches the top and the panel pins — so the deck is
        // already fully open the instant the section settles in the middle of
        // the screen, and it stays open for the whole pinned stretch.
        const start = window.innerHeight * 0.6;
        const p = Math.min(1, Math.max(0, (start - rect.top) / start));
        apply(p);
      });
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return (
    <div ref={wrapRef} style={{ height: "135vh", margin: "48px 0 0" }}>
      {/*
        Heading and stack are positioned independently rather than stacked in a
        flex column. Flex centred the *collapsed* deck, so the gap between the
        heading and the cards changed as the cards spread — and once the cards
        were free to overflow their box they rode up over the heading. Pinning
        the heading near the top and anchoring the stack to the exact vertical
        centre keeps both fixed while only the spread animates.
      */}
      <div style={{ position: "sticky", top: 0, height: "100vh", overflow: "hidden" }}>
        {/* Title plus one supporting line, the way the Sonos section carries a
            short paragraph beside its exploded product. It also fills what was
            an awkward void between the heading and the collapsed deck. */}
        <div ref={headRef} style={{
          position: "absolute", top: "14vh", left: 0, right: 0,
          textAlign: "center", zIndex: 10, padding: "0 24px",
        }}>
          <h2 style={{
            margin: 0,
            fontSize: "clamp(28px, 4vw, 40px)", fontWeight: 400,
            lineHeight: 1.2, color: "#000000",
          }}>
            Five agents, one answer
          </h2>
          <p style={{
            margin: "14px auto 0", maxWidth: 460,
            fontSize: 15, lineHeight: 1.5, color: "#5f5f5f",
          }}>
            One request is passed down a chain of specialists, each doing a
            single job, and comes back as a single answer you can act on.
          </p>
        </div>

        {/* Zero-height anchor sitting exactly on the vertical centre; every
            card is offset from it, so the deck stays centred at any height. */}
        <div ref={groupRef} style={{
          position: "absolute", top: "54%", left: "50%",
          transform: "translateX(-50%)",
          transformOrigin: "center center",
          /* `top` is overwritten in px by the scroll handler — the 54% is only
             the pre-hydration position so nothing jumps on first paint. */
          width: "min(560px, 88vw)", height: 0,
        }}>
          {LAYERS.map((l, i) => (
            <div
              key={l.label}
              ref={(el) => { cardRefs.current[i] = el; }}
              style={{
                position: "absolute", left: 0, right: 0,
                top: -45,                       // half a card, so it straddles centre
                background: l.bg, color: l.color,
                border: l.border,
                borderRadius: 16,
                padding: "20px 28px",
                zIndex: LAYERS.length - i,
                willChange: "transform",
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 2 }}>{l.label}</div>
              <div style={{ fontSize: 13, opacity: 0.7 }}>{l.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
