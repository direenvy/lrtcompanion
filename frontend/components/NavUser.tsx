"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function NavUser() {
  const { user, signOut, loading } = useAuth();

  if (loading) return null;

  if (!user) {
    return (
      <Link
        href="/login"
        style={{
          fontSize: 11, fontFamily: "var(--font-sans)", fontWeight: 600,
          color: "#000000",
          background: "rgba(0,0,0,0.06)",
          border: "1px solid rgba(0,0,0,0.12)",
          padding: "4px 12px", borderRadius: 7,
          textDecoration: "none",
          transition: "all 0.15s",
        }}
      >
        Sign In
      </Link>
    );
  }

  const initials = user.email?.slice(0, 2).toUpperCase() ?? "??";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Link
        href="/settings"
        title="Profile & Preferences"
        style={{
          display: "flex", alignItems: "center", gap: 7,
          textDecoration: "none",
          background: "rgba(0,0,0,0.04)",
          border: "1px solid #cdcdcd",
          borderRadius: 7, padding: "4px 10px",
          transition: "all 0.15s",
        }}
      >
        <span style={{
          width: 20, height: 20, borderRadius: "50%",
          background: "#000000", color: "#fff",
          fontFamily: "var(--font-sans)", fontWeight: 900,
          fontSize: 9, display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}>
          {initials}
        </span>
        <span style={{ fontSize: 11, color: "#5f5f5f", maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {user.email}
        </span>
      </Link>
      <button
        onClick={() => signOut()}
        style={{
          background: "none", border: "1px solid rgba(0,0,0,0.08)",
          color: "#737373", fontSize: 10, padding: "4px 9px",
          borderRadius: 6, cursor: "pointer", fontFamily: "var(--font-sans)",
        }}
      >
        Out
      </button>
    </div>
  );
}
