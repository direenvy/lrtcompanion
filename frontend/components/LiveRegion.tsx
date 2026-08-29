"use client";
/**
 * Screen-reader announcer.
 *
 * A live region must already be in the DOM when its text changes — screen
 * readers watch a mounted node for mutations. Conditionally rendering the
 * region together with the content it describes is the usual mistake: the
 * region and the text arrive in the same paint, and the announcement is
 * missed. So this stays mounted and empty, and only its text changes.
 *
 * politeness:
 *   "polite"    — waits for a pause. Results, status, counts.
 *   "assertive" — interrupts. Errors, and only errors.
 */
import { useEffect, useRef, useState } from "react";

export function LiveRegion({
  message,
  politeness = "polite",
}: {
  message: string;
  politeness?: "polite" | "assertive";
}) {
  // Re-announce an identical consecutive message (e.g. running the same search
  // twice): screen readers ignore a mutation that leaves the text unchanged,
  // so alternate a trailing zero-width space to force a real change.
  const [text, setText] = useState("");
  const flip = useRef(false);

  // Settle before announcing. A result usually lands over two or three renders
  // (data arrives, then the loading flag clears), and every intermediate write
  // CANCELS whatever the screen reader is currently speaking — the symptom is
  // an announcement that cuts off after a few words. Waiting for the message
  // to stop changing means the reader speaks once, from the top.
  useEffect(() => {
    if (!message) { setText(""); return; }
    const t = setTimeout(() => {
      flip.current = !flip.current;
      setText(flip.current ? message : message + "​");
    }, 350);
    return () => clearTimeout(t);
  }, [message]);

  return (
    <div
      className="sr-only"
      role={politeness === "assertive" ? "alert" : "status"}
      aria-live={politeness}
      aria-atomic="true"
    >
      {text}
    </div>
  );
}

export default LiveRegion;
