"use client";
/**
 * BackToTop — circular monochrome button, appears after scrolling past
 * the first viewport, smooth-scrolls back to the top. Sonos scroll-
 * indicator styling: white pill circle, hairline border, black icon.
 */
import { useEffect, useState } from "react";

export default function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        setVisible(window.scrollY > 600);
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      aria-label="Back to top"
      style={{
        position: "fixed", right: 24, bottom: 24, zIndex: 40,
        width: 44, height: 44, borderRadius: "50%",
        background: "#ffffff", border: "1px solid #cdcdcd",
        color: "#000000", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
        transform: visible ? "none" : "translateY(8px)",
        transition: "opacity 0.25s ease, transform 0.25s ease",
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="18 15 12 9 6 15" />
      </svg>
    </button>
  );
}
