"use client";
/**
 * ScrollReveal — reveals any element with .reveal-on-scroll as it enters
 * the viewport. IntersectionObserver + CSS transitions only (compositor-
 * friendly, no per-frame JS). Mount once per page.
 */
import { useEffect } from "react";

export default function ScrollReveal() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>(".reveal-on-scroll");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("reveal-in");
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.12 },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return null;
}
