import axios from "axios";

export function friendlyError(e: unknown): string {
  const err = e as { code?: string; response?: { status?: number; data?: { detail?: string } } };
  if (err?.response?.status === 429) return "Too many requests — wait a few seconds and try again.";
  if (err?.response?.status && err.response.status >= 500)
    return "The server hit a problem processing this. Try again in a moment.";
  if (err?.response?.data?.detail) return String(err.response.data.detail);
  if (err?.code === "ERR_NETWORK" || !err?.response)
    return "Can't connect right now. Please check your connection and try again.";
  return "Something went wrong. Please try again.";
}

export function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";   // SSR fallback; real calls run client-side
}

const API = axios.create();
API.interceptors.request.use((config) => {
  config.baseURL = apiBase();
  return config;
});

export const detectDisruption = (text: string) =>
  API.post("/api/nlp/detect", { text }).then((r) => r.data);

export interface RoutePreferences {
  priority:            "fastest" | "fewest_stops" | "fewest_transfers";
  prefer_shelter:      boolean;
  avoid_lines:         string[];
  require_wheelchair:  boolean;
  prefer_less_walking: boolean;
  require_tactile:     boolean;
  prefer_quiet:        boolean;
  max_walk_minutes:    number;   // 0 = no limit; else 5 / 10 / 15
  prefer_safer_walk:   boolean;  // warn on low-scoring station walk approaches
}

export const DEFAULT_PREFS: RoutePreferences = {
  priority:            "fastest",
  prefer_shelter:      false,
  avoid_lines:         [],
  require_wheelchair:  false,
  prefer_less_walking: false,
  require_tactile:     false,
  prefer_quiet:        false,
  max_walk_minutes:    0,
  prefer_safer_walk:   false,
};

export const findRoute = (
  origin: string,
  destination: string,
  disrupted_stops: string[] = [],
  preferences: RoutePreferences = DEFAULT_PREFS
) =>
  API.post("/api/reroute/find", { origin, destination, disrupted_stops, preferences }).then(
    (r) => r.data
  );

export const getStations = () =>
  API.get("/api/reroute/stations").then((r) => r.data.stations);

export const getNetworkMap = () =>
  API.get("/api/reroute/network").then((r) => r.data);

export const chatWithRAG = (
  question: string,
  history: { role: string; text: string }[] = []
) =>
  API.post("/api/rag/chat", { question, history }).then((r) => r.data);

export const submitFeedback = (question: string, answer: string, rating: 1 | -1) =>
  API.post("/api/rag/feedback", { question, answer, rating }).then((r) => r.data);

export const getDashboardStats = () =>
  API.get("/api/dashboard/stats").then((r) => r.data);

export const getLineStatus = () =>
  API.get("/api/dashboard/line-status").then((r) => r.data);

export const getIncidents = (hours = 168) =>
  API.get("/api/dashboard/incidents", { params: { hours } }).then((r) => r.data);

export const runOrchestrator = (
  text: string,
  origin: string,
  destination: string,
  disrupted_stops: string[] = []
) =>
  API.post("/api/orchestrator/disruption", {
    text, origin, destination, disrupted_stops,
  }).then((r) => r.data);
