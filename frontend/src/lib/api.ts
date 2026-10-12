import type {
  AgentEvent,
  AnchorResult,
  AuditEntry,
  ClientProfile,
  CompareResponse,
  ComplianceRule,
  Execution,
  HealthReport,
  MacroResponse,
  Portfolio,
  Proposal,
  Quote,
  SessionStart,
  Trade,
  User,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");

const TOKEN_KEY = "finfuture.token";

export const tokenStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      window.localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: token lives for this page only */
    }
  },
  clear() {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(ApiError.describe(status, detail));
    this.status = status;
    this.detail = detail;
  }
  static describe(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors
      return detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc ?? []).slice(1).join(".")} ${d.msg ?? ""}`.trim()).join("; ");
    }
    if (detail && typeof detail === "object" && "reason" in detail) return String((detail as { reason: unknown }).reason);
    if (status === 0) return "The advisory service could not be reached. Check that the backend is running.";
    return `Request failed (${status})`;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

async function request<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  const { auth = true, headers, ...rest } = init;
  const h = new Headers(headers);
  if (auth) {
    const token = tokenStore.get();
    if (token) h.set("Authorization", `Bearer ${token}`);
  }
  if (rest.body && typeof rest.body === "string" && !h.has("Content-Type")) h.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...rest, headers: h });
  } catch {
    throw new ApiError(0, null);
  }
  if (res.status === 401 && auth) {
    onUnauthorized?.();
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // auth
  register: (email: string, password: string) =>
    request<User>("/api/v1/auth/register", { method: "POST", body: json({ email, password }), auth: false }),
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/api/v1/auth/login", {
      method: "POST",
      auth: false,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password }).toString(),
    }),
  me: () => request<User>("/api/v1/auth/me"),

  // session & chat
  startSession: () => request<SessionStart>("/api/v1/session/start", { method: "POST" }),
  sendMessage: (session_id: string, message: string) =>
    request<{ text: string; agent: string; type: string; events: AgentEvent[] }>("/api/v1/chat/message", {
      method: "POST",
      body: json({ session_id, message }),
    }),

  // profile & portfolio
  profile: (clientId: string) => request<ClientProfile>(`/api/v1/profile/${encodeURIComponent(clientId)}`),
  portfolio: (clientId: string) => request<Portfolio>(`/api/v1/portfolio/${encodeURIComponent(clientId)}`),
  healthReport: (clientId: string) =>
    request<HealthReport>("/api/v1/portfolio/health-report", { method: "POST", body: json({ client_id: clientId }) }),
  recommendAllocation: (clientId: string) =>
    request<{ client_id: string; events: AgentEvent[] }>("/api/v1/allocation/recommend", {
      method: "POST",
      body: json({ client_id: clientId }),
    }),

  // comparison
  compare: (kind: "etfs" | "bonds", clientId: string, symbols: string[]) =>
    request<CompareResponse>(`/api/v1/compare/${kind}`, { method: "POST", body: json({ client_id: clientId, symbols }) }),

  // trading
  proposeTrade: (clientId: string, symbol: string, side: "BUY" | "SELL", qty: number) =>
    request<{ proposal: Proposal; requires_user_approval: boolean }>("/api/v1/trade/propose", {
      method: "POST",
      body: json({ client_id: clientId, symbol, side, qty }),
    }),
  executeProposal: (clientId: string, proposalId: string, approved: boolean) =>
    request<{ status: string; execution: Execution | null; events: AgentEvent[] }>("/api/v1/trade/execute", {
      method: "POST",
      body: json({ client_id: clientId, proposal_id: proposalId, user_approved: approved }),
    }),
  trades: (clientId: string, limit = 100) =>
    request<{ client_id: string; trades: Trade[] }>(`/api/v1/trades/${encodeURIComponent(clientId)}?limit=${limit}`),

  // audit & compliance
  audit: (clientId: string, limit = 500) =>
    request<{ client_id: string; entries: AuditEntry[] }>(`/api/v1/audit/${encodeURIComponent(clientId)}?limit=${limit}`),
  verifyAudit: (clientId: string) =>
    request<{ client_id: string; valid: boolean; first_invalid_entry: string | null }>(
      `/api/v1/audit/${encodeURIComponent(clientId)}/verify`,
    ),
  anchorAudit: (clientId: string) =>
    request<AnchorResult>(`/api/v1/audit/${encodeURIComponent(clientId)}/anchor`, { method: "POST" }),
  rules: () => request<{ rules: ComplianceRule[] }>("/api/v1/compliance/rules"),

  // market data
  quote: (symbol: string) => request<Quote>(`/api/v1/market/quote/${encodeURIComponent(symbol)}`),
  history: (symbol: string, period = "6mo") =>
    request<import("./types").PriceHistoryResponse>(`/api/v1/market/history/${encodeURIComponent(symbol)}?period=${encodeURIComponent(period)}`),
  macro: () => request<MacroResponse>("/api/v1/market/macro"),
};
