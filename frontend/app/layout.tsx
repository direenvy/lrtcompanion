import type { Metadata, Viewport } from "next";
import { Geist_Mono, Geist } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "./providers";
import Nav from "@/components/Nav";
import Footer from "@/components/Footer";
import BackToTop from "@/components/BackToTop";

const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });
const sans = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "LRT Companion — Agentic AI for Disruption Management",
  description: "Real-time disruption alerts, smart rerouting, and AI assistance for Rapid KL.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f5f5f5",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body style={{ fontFamily: "var(--font-sans), sans-serif" }} suppressHydrationWarning>
      <AuthProvider>
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <div style={{
          position: "fixed", top: 0, left: "50%", transform: "translateX(-50%)",
          width: "min(700px, 90vw)", height: 260, borderRadius: "50%",
          background: "radial-gradient(ellipse, rgba(0,0,0,0.03) 0%, transparent 70%)",
          pointerEvents: "none", zIndex: 0,
        }} />
        <Nav />
        <main id="main-content" tabIndex={-1} className="page-main" style={{
          position: "relative", zIndex: 10,
          maxWidth: 1040, margin: "0 auto",
          padding: "3rem 1.5rem 5rem",
        }}>
          {children}
        </main>
        <Footer />
        <BackToTop />
      </AuthProvider>
      </body>
    </html>
  );
}
