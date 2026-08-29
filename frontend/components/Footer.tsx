import Link from "next/link";

const columns = [
  {
    heading: "Use",
    links: [
      { href: "/reroute",     label: "Plan Trip" },
      { href: "/detect",      label: "Report Disruption" },
      { href: "/voice",       label: "Voice Help" },
      { href: "/chat",        label: "Fares & FAQ" },
    ],
  },
  {
    heading: "Monitor",
    links: [
      { href: "/status",      label: "Line Status" },
      { href: "/dashboard",   label: "Dashboard" },
      { href: "/orchestrate", label: "Agent Pipeline" },
      { href: "/settings",    label: "Settings" },
    ],
  },
];

export default function Footer() {
  return (
    <footer style={{ background: "#000000", marginTop: 96 }}>
      <div style={{ maxWidth: 1040, margin: "0 auto", padding: "64px 1.5rem 40px" }}>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 64, marginBottom: 64 }}>
          <div style={{ flex: "1 1 260px" }}>
            <span style={{ color: "#ffffff", fontWeight: 700, fontSize: 14, letterSpacing: "0.12em" }}>
              LRT COMPANION
            </span>
            <p style={{ color: "#737373", fontSize: 14, lineHeight: 1.5, maxWidth: 300, marginTop: 16 }}>
              An agentic AI decision-support system for Klang Valley rail commuters.
            </p>
          </div>

          {columns.map((col) => (
            <div key={col.heading}>
              <p style={{ color: "#737373", fontSize: 13, fontWeight: 500, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 16 }}>
                {col.heading}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {col.links.map((l) => (
                  <Link key={l.href} href={l.href} style={{ color: "#bfbfbf", fontSize: 14, textDecoration: "none" }}>
                    {l.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{ borderTop: "1px solid #2e2e2e", paddingTop: 24, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
          <span style={{ color: "#737373", fontSize: 13 }}>
            © 2026 LRT Companion — Final Year Project
          </span>
          <span style={{ marginLeft: "auto", color: "#5f5f5f", fontSize: 12 }}>
            Crowd-sourced disruption data · GTFS via data.gov.my · Not affiliated with Rapid KL or Prasarana
          </span>
        </div>

      </div>
    </footer>
  );
}
