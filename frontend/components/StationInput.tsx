"use client";
import { useState, useEffect, useRef, useId } from "react";
import { getStations } from "@/lib/api";

// Official GTFS line colours (same palette as the Line Status board / map).
const LINE_COLOR: Record<string, string> = {
  KJ: "#ef4444", AG: "#f97316", PH: "#ec4899",
  KGL: "#22c55e", PYL: "#eab308", MR: "#84cc16", BRT: "#10b981", SA: "#38bdf8",
};

export type StationOption = { name: string; lines: string[] };

// Load the GTFS station list once, cleaned + deduped, with the line(s) each
// station serves — shared by every page that needs station autocomplete.
export function useStationOptions(): StationOption[] {
  const [options, setOptions] = useState<StationOption[]>([]);
  useEffect(() => {
    getStations()
      .then((rows: { name: string; line: string }[]) => {
        const byName = new Map<string, Set<string>>();
        for (const r of rows) {
          const name = r.name.replace(/\s*-\s*.*$/, "").trim();  // drop sponsor/"REDONE" suffix
          if (!name) continue;
          const line = r.line === "MRT" ? "KGL" : r.line;         // GTFS uses MRT for Kajang
          if (!byName.has(name)) byName.set(name, new Set());
          byName.get(name)!.add(line);
        }
        setOptions(
          [...byName.entries()]
            .map(([name, lines]) => ({ name, lines: [...lines].sort() }))
            .sort((a, b) => a.name.localeCompare(b.name))
        );
      })
      .catch(() => setOptions([]));   // offline → plain text input, nothing breaks
  }, []);
  return options;
}

// Autocomplete input backed by the station list. Prevents typos and
// wrong-station surprises by letting users pick a real station. Keyboard-navigable.
export default function StationInput({
  label, value, onChange, placeholder, options, onEnter,
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder: string; options: StationOption[]; onEnter?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  // Stable ids so the label, the input and the highlighted option can point at
  // each other — without these a screen reader cannot tell that this input has
  // a popup, which option is current, or even what the field is called.
  const uid     = useId();
  const inputId = `${uid}-input`;
  const listId  = `${uid}-list`;
  const optId   = (i: number) => `${uid}-opt-${i}`;

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const q = value.trim().toUpperCase();
  const matches = q.length === 0 ? [] :
    options
      .filter(o => o.name.toUpperCase().includes(q))
      .sort((a, b) => {
        const as = a.name.toUpperCase().startsWith(q) ? 0 : 1;
        const bs = b.name.toUpperCase().startsWith(q) ? 0 : 1;
        return as - bs || a.name.localeCompare(b.name);
      })
      .slice(0, 8);

  const pick = (name: string) => { onChange(name); setOpen(false); };

  return (
    <div ref={boxRef} style={{ position: "relative", width: "100%" }}>
      <label htmlFor={inputId} style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</label>
      <input
        id={inputId}
        className="input"
        placeholder={placeholder}
        value={value}
        autoComplete="off"
        // ARIA combobox pattern. Without these the dropdown is invisible to a
        // screen reader: the highlight moves on screen but nothing is spoken,
        // so the field appears not to respond to the arrow keys at all.
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches.length > 0 ? optId(active) : undefined}
        onChange={e => { onChange(e.target.value.toUpperCase()); setOpen(true); setActive(0); }}
        onFocus={() => value.trim() && setOpen(true)}
        // Tab must leave a closed list behind, or the popup hangs over the
        // next field and the user cannot tell what has focus.
        onBlur={() => setOpen(false)}
        onKeyDown={e => {
          if (!open || matches.length === 0) { if (e.key === "Enter") onEnter?.(); return; }
          if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, matches.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); pick(matches[active].name); }
          else if (e.key === "Escape") setOpen(false);
          else if (e.key === "Tab") setOpen(false);
        }}
      />
      {/* Spoken only. Tells the user a list appeared and how big it is —
          otherwise typing produces silence and there is no cue to press ↓. */}
      <div className="sr-only" role="status" aria-live="polite">
        {open && matches.length > 0
          ? `${matches.length} station${matches.length > 1 ? "s" : ""} available. Use arrow keys to review, Enter to select.`
          : ""}
      </div>
      {open && matches.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} suggestions`}
          style={{
          position: "absolute", zIndex: 30, left: 0, right: 0, top: "calc(100% + 4px)",
          margin: 0, padding: 4, listStyle: "none", background: "#ffffff",
          border: "1px solid #cdcdcd", borderRadius: 10, boxShadow: "0 6px 20px rgba(0,0,0,0.10)",
          maxHeight: 260, overflowY: "auto",
        }}>
          {matches.map((o, i) => (
            <li
              key={o.name}
              id={optId(i)}
              role="option"
              aria-selected={i === active}
              // Screen readers read the option's text content. The line chips
              // render as bare codes ("KJ"), so spell out the whole thing.
              aria-label={`${o.name}, ${o.lines.join(" and ")} line${o.lines.length > 1 ? "s" : ""}`}
              onMouseDown={e => { e.preventDefault(); pick(o.name); }}
              onMouseEnter={() => setActive(i)}
              style={{
                padding: "8px 10px", borderRadius: 7, cursor: "pointer", fontSize: 13,
                background: i === active ? "#f0f0f0" : "transparent", color: "#000000",
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              <span style={{ flex: 1 }}>📍 {o.name}</span>
              {o.lines.map(ln => (
                <span key={ln} style={{
                  fontSize: 9, fontWeight: 700, color: LINE_COLOR[ln] ?? "#737373",
                  background: `${LINE_COLOR[ln] ?? "#737373"}18`,
                  border: `1px solid ${LINE_COLOR[ln] ?? "#737373"}40`,
                  padding: "1px 5px", borderRadius: 4,
                }}>{ln}</span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
