"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { TranscriptRow } from "@/components/domain/AgentMessage";
import { ButtonLink } from "@/components/ui/Button";
import { Loading, Tag, type Tone } from "@/components/ui/Feedback";
import { useAuth } from "@/lib/auth";
import type { ChatMessageAttachment, ChatSessionItem } from "@/lib/types";
import { useAdvisor, type Connection } from "@/lib/useAdvisor";

const dagPipeline: {
  id: string;
  agent: string;
  role: string;
  tier: "GREEN" | "YELLOW" | "RED";
  tierTone: Tone;
  activeIn: string[];
}[] = [
  {
    id: "intent",
    agent: "Orchestrator",
    role: "Intent & Multimodal Guard (RULE-09)",
    tier: "GREEN",
    tierTone: "success",
    activeIn: ["PROFILING", "ADVICE_GENERATION", "PROPOSAL_REVIEW", "EXECUTION", "HEALTH_MONITORING"],
  },
  {
    id: "profiler",
    agent: "RiskProfiler",
    role: "Stated + Behavioral Calibration",
    tier: "GREEN",
    tierTone: "success",
    activeIn: ["PROFILING", "ADVICE_GENERATION"],
  },
  {
    id: "quant",
    agent: "AllocationEngine",
    role: "CVaR / Student-t Monte Carlo / Tax",
    tier: "GREEN",
    tierTone: "success",
    activeIn: ["ADVICE_GENERATION", "HEALTH_MONITORING"],
  },
  {
    id: "compliance",
    agent: "ComplianceGuard",
    role: "12-Rule Deterministic Firewall",
    tier: "GREEN",
    tierTone: "success",
    activeIn: ["ADVICE_GENERATION", "PROPOSAL_REVIEW", "EXECUTION"],
  },
  {
    id: "execution",
    agent: "ExecutionAgent",
    role: "Human-in-the-Loop + Step-Up MFA Gate",
    tier: "RED",
    tierTone: "danger",
    activeIn: ["PROPOSAL_REVIEW", "EXECUTION"],
  },
];

const starterPrompts = [
  "What is the current mortgage rate trend and 10Y yield spread?",
  "Simulate $10M to $100M wealth plan over 10 years with $500k withdrawals",
  "Compare SPY, VTI, and QQQ factor exposures",
  "Optimize my cross-border tax strategy for least legal tax",
  "Analyze Dangote Refinery valuation, debt, and IPO prospectus",
  "Review my portfolio health and diagnose drift",
];

const connectionText: Record<Connection, string> = {
  connecting: "Connecting…",
  live: "Live connection active",
  fallback: "Standard requests",
  closed: "Connection closed",
};

/** Categorizes chat sessions chronologically */
function groupSessions(sessions: ChatSessionItem[]) {
  const now = new Date();
  const today: ChatSessionItem[] = [];
  const yesterday: ChatSessionItem[] = [];
  const fiveDays: ChatSessionItem[] = [];
  const older: ChatSessionItem[] = [];

  for (const s of sessions) {
    const d = new Date(s.updated_at || s.created_at);
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 3600 * 24));
    if (diffDays === 0) today.push(s);
    else if (diffDays === 1) yesterday.push(s);
    else if (diffDays <= 7) fiveDays.push(s);
    else older.push(s);
  }

  return { today, yesterday, fiveDays, older };
}

function getTimeOfDayGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good Morning";
  if (hour < 17) return "Good Afternoon";
  return "Good Evening";
}

/** Glowing emerald spiral portal orb styled for the original clean color scheme */
function GlowingSpiralOrb() {
  const gradientId = useId();
  return (
    <div className="relative mx-auto my-5 flex h-20 w-20 items-center justify-center">
      <div className="absolute inset-0 rounded-full bg-accent/15 blur-xl animate-pulse" />
      <svg
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="relative h-16 w-16 animate-[spin_12s_linear_infinite]"
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="1" />
            <stop offset="60%" stopColor="#269966" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#0F2922" stopOpacity="0.25" />
          </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="42" stroke={`url(#${gradientId})`} strokeWidth="3.5" strokeDasharray="14 8 20 6" strokeLinecap="round" opacity="0.9" />
        <circle cx="50" cy="50" r="33" stroke={`url(#${gradientId})`} strokeWidth="4" strokeDasharray="10 12 18 8" strokeLinecap="round" className="animate-[spin_8s_linear_infinite_reverse]" style={{ transformOrigin: "center" }} />
        <circle cx="50" cy="50" r="23" stroke="var(--accent)" strokeWidth="3.5" strokeDasharray="8 6 14 4" strokeLinecap="round" opacity="0.85" />
        <circle cx="50" cy="50" r="14" stroke="var(--accent)" strokeWidth="3" strokeDasharray="6 4" strokeLinecap="round" opacity="0.95" />
        <circle cx="50" cy="50" r="6" fill="var(--accent)" className="animate-ping" style={{ transformOrigin: "center", animationDuration: "3s" }} />
        <circle cx="50" cy="50" r="4.5" fill="var(--primary)" />
      </svg>
    </div>
  );
}

export default function AdvisorPage() {
  const { user, clientId } = useAuth();
  const {
    items,
    connection,
    waiting,
    stage,
    proposals,
    send,
    approve,
    reject,
    ready,
    activeSessionId,
    activeTitle,
    sessions,
    loadSession,
    createNewSession,
    deleteSession,
    loadingHistory,
  } = useAdvisor();

  const [draft, setDraft] = useState("");
  const [stagedAttachments, setStagedAttachments] = useState<ChatMessageAttachment[]>([]);
  const [reasoningActive, setReasoningActive] = useState(true);
  const [deepResearchActive, setDeepResearchActive] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [showDagDrawer, setShowDagDrawer] = useState(false);
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionDropdownRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<{
    start: () => void;
    stop: () => void;
  } | null>(null);

  const userName = user?.email ? user.email.split("@")[0] : "Investor";
  const capitalizedUserName = userName.charAt(0).toUpperCase() + userName.slice(1);
  const greeting = `${getTimeOfDayGreeting()}, ${capitalizedUserName}! How can I assist you?`;

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [items.length, waiting]);

  // Click outside to close dropdowns
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (sessionDropdownRef.current && !sessionDropdownRef.current.contains(e.target as Node)) {
        setSessionDropdownOpen(false);
      }
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Browser speech recognition
  useEffect(() => {
    if (typeof window !== "undefined") {
      const win = window as unknown as {
        SpeechRecognition?: new () => {
          continuous: boolean;
          interimResults: boolean;
          lang: string;
          onresult: (e: { results: Array<Array<{ transcript: string }>> }) => void;
          onerror: () => void;
          onend: () => void;
          start: () => void;
          stop: () => void;
        };
        webkitSpeechRecognition?: new () => {
          continuous: boolean;
          interimResults: boolean;
          lang: string;
          onresult: (e: { results: Array<Array<{ transcript: string }>> }) => void;
          onerror: () => void;
          onend: () => void;
          start: () => void;
          stop: () => void;
        };
      };

      const SpeechRecognitionCtor = win.SpeechRecognition || win.webkitSpeechRecognition;
      if (SpeechRecognitionCtor) {
        const recognition = new SpeechRecognitionCtor();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = "en-US";
        recognition.onresult = (event) => {
          const transcript = event.results[0]?.[0]?.transcript || "";
          setDraft((prev) => (prev ? `${prev} ${transcript}` : transcript));
          setIsListening(false);
        };
        recognition.onerror = () => setIsListening(false);
        recognition.onend = () => setIsListening(false);
        recognitionRef.current = recognition;
      }
    }
  }, []);

  function toggleSpeech() {
    if (!recognitionRef.current) {
      alert("Voice input is not supported in this browser. Please use Chrome or Edge.");
      return;
    }
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      setIsListening(true);
      recognitionRef.current.start();
    }
  }

  function handleFiles(files: FileList | File[]) {
    const list = Array.from(files);
    list.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const result = e.target?.result as string;
        const isImage = file.type.startsWith("image/");
        setStagedAttachments((prev) => [
          ...prev,
          {
            type: isImage ? "image" : "document",
            name: file.name,
            size: file.size,
            mime_type: file.type || "application/octet-stream",
            data: result,
          },
        ]);
      };
      reader.readAsDataURL(file);
    });
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length > 0) {
      const files = Array.from(e.clipboardData.files);
      const hasMedia = files.some((f) => f.type.startsWith("image/") || f.type.includes("pdf"));
      if (hasMedia) {
        e.preventDefault();
        handleFiles(files);
      }
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer && e.dataTransfer.files) {
      handleFiles(e.dataTransfer.files);
    }
  }

  function removeAttachment(idx: number) {
    setStagedAttachments((prev) => prev.filter((_, i) => i !== idx));
  }

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const textToSend = draft.trim();
    if ((!textToSend && stagedAttachments.length === 0) || waiting) return;

    let enrichedPrompt = textToSend;
    if (deepResearchActive) {
      enrichedPrompt = `[Deep SEC & Web Research Mode] ${enrichedPrompt}`;
    }

    send(enrichedPrompt, stagedAttachments);
    setDraft("");
    setStagedAttachments([]);
    inputRef.current?.focus();
  }

  const filteredSessions = useMemo(() => {
    if (!sessionSearch.trim()) return sessions;
    const q = sessionSearch.toLowerCase();
    return sessions.filter((s) => (s.title || "").toLowerCase().includes(q));
  }, [sessions, sessionSearch]);

  const grouped = useMemo(() => groupSessions(filteredSessions), [filteredSessions]);
  const hasMessages = items.length > 1 || (items.length === 1 && items[0].from === "you");
  const profiling = stage === "PROFILING" && !clientId;

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className="relative w-full"
    >
      {/* Hidden File Input for Multimodal attachments */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.pdf,.csv,.json,.txt"
        multiple
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Drag & Drop Overlay */}
      {dragOver && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center rounded-3xl bg-surface/95 backdrop-blur-sm border-2 border-dashed border-accent">
          <div className="grid h-14 w-14 place-items-center rounded-full bg-accent-soft text-accent shadow-xs">
            <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </div>
          <p className="mt-3 text-base font-semibold text-ink">Drop charts, images, or documents here</p>
          <p className="text-xs text-muted">Orion will perform multimodal vision inspection</p>
        </div>
      )}

      {/* Optional Collapsible Multi-Agent Strategy Compiler DAG */}
      {showDagDrawer && (
        <div className="mb-5 rounded-2xl border border-line bg-surface/90 p-4 shadow-xs animate-fade-in">
          <div className="flex items-center justify-between border-b border-line pb-2.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold tracking-wider text-ink uppercase">
                Multi-Agent Compiler DAG & Permission Matrix
              </span>
              <Tag tone="success">Stage: {stage}</Tag>
            </div>
            <button
              type="button"
              onClick={() => setShowDagDrawer(false)}
              className="text-xs font-medium text-muted hover:text-ink"
            >
              ✕ Close
            </button>
          </div>
          <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
            {dagPipeline.map((node, idx) => (
              <div
                key={node.id}
                className={`rounded-xl border p-3 transition-all ${
                  node.activeIn.includes(stage)
                    ? "border-accent bg-background shadow-xs ring-1 ring-accent/20"
                    : "border-line bg-surface opacity-75"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="figures text-[10px] font-semibold text-muted">0{idx + 1}</span>
                  <Tag tone={node.tierTone}>{node.tier}</Tag>
                </div>
                <p className="mt-1 text-xs font-semibold text-ink">{node.agent}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-muted">{node.role}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2-Column Layout: Main Chat Card on Left/Center, "History Chat" Sidebar on Right */}
      <div className="grid gap-5 lg:grid-cols-[1fr_275px] xl:grid-cols-[1fr_310px] items-start">
        {/* 1. Main Advisory Conversation Window (Dribbble Layout) */}
        <section
          aria-label="AI Advisory Conversation"
          className="flex min-h-[82vh] flex-col overflow-hidden rounded-3xl border border-line bg-background shadow-[0_2px_20px_rgba(15,41,34,0.04)]"
        >
          {/* Header Bar matching Image 2: "New AI chat ▾" + "Private" on left, action icons on right */}
          <div className="flex items-center justify-between border-b border-line bg-surface/50 px-4 py-3 sm:px-6">
            {/* Left: Session Dropdown + Private Pill */}
            <div ref={sessionDropdownRef} className="relative flex items-center gap-2 sm:gap-2.5">
              <button
                type="button"
                onClick={() => setSessionDropdownOpen((v) => !v)}
                className="flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-sm font-semibold text-ink hover:bg-surface transition-colors"
              >
                <span className="max-w-[180px] truncate sm:max-w-[280px]">
                  {activeTitle || "New AI chat"}
                </span>
                <span className="text-xs text-muted">▾</span>
              </button>

              <span className="inline-flex items-center gap-1 rounded-full border border-line bg-background px-2.5 py-0.5 text-[11px] font-medium text-muted shadow-2xs">
                <span className="text-accent text-[11px]">🔒</span>
                <span>Private</span>
              </span>

              {/* Status Indicator */}
              <span className="hidden md:inline-flex items-center gap-1 text-[11px] text-muted">
                <span className={`h-1.5 w-1.5 rounded-full ${connection === "live" ? "bg-accent animate-pulse" : "bg-amber-500"}`} />
                <span>{connectionText[connection]}</span>
              </span>

              {/* Session Dropdown Popover */}
              {sessionDropdownOpen && (
                <div className="absolute left-0 top-10 z-40 w-72 rounded-2xl border border-line bg-background p-2.5 shadow-xl animate-fade-in">
                  <div className="flex items-center justify-between border-b border-line pb-2 mb-2">
                    <span className="text-xs font-bold text-ink">Conversations</span>
                    <button
                      type="button"
                      onClick={() => {
                        setSessionDropdownOpen(false);
                        void createNewSession();
                      }}
                      className="rounded-full bg-primary px-2.5 py-0.5 text-[11px] font-semibold text-on-primary hover:bg-primary-hover"
                      style={{ color: "#ffffff" }}
                    >
                      + New
                    </button>
                  </div>

                  <input
                    type="text"
                    value={sessionSearch}
                    onChange={(e) => setSessionSearch(e.target.value)}
                    placeholder="Filter chats…"
                    className="mb-2 w-full rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink placeholder:text-muted focus:border-accent focus:outline-hidden"
                  />

                  <div className="max-h-60 overflow-y-auto space-y-1">
                    {filteredSessions.length === 0 ? (
                      <p className="py-3 text-center text-xs text-muted">No chats found</p>
                    ) : (
                      filteredSessions.map((s) => (
                        <div
                          key={s.session_id}
                          onClick={() => {
                            void loadSession(s.session_id);
                            setSessionDropdownOpen(false);
                          }}
                          className={`flex items-center justify-between rounded-lg px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                            s.session_id === activeSessionId
                              ? "bg-accent-soft text-accent font-semibold"
                              : "text-ink hover:bg-surface"
                          }`}
                        >
                          <span className="truncate pr-2">{s.title || "Advisory Session"}</span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (confirm("Delete this conversation?")) void deleteSession(s.session_id);
                            }}
                            className="text-muted hover:text-danger p-0.5"
                          >
                            ✕
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Right: Actions */}
            <div ref={menuRef} className="relative flex items-center gap-1.5 sm:gap-2">
              {/* New Chat Button */}
              <button
                type="button"
                onClick={() => void createNewSession()}
                title="Start New Chat"
                className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
                aria-label="New Chat"
              >
                <svg className="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </button>

              {/* Multi-Agent DAG toggle */}
              <button
                type="button"
                onClick={() => setShowDagDrawer((v) => !v)}
                className="hidden sm:flex items-center gap-1.5 rounded-full border border-line bg-background px-2.5 py-1 text-xs font-medium text-muted hover:text-ink hover:bg-surface transition-colors shadow-2xs"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                <span>DAG</span>
              </button>

              {/* Share Button */}
              <button
                type="button"
                onClick={() => {
                  if (typeof window !== "undefined") {
                    navigator.clipboard.writeText(window.location.href);
                    alert("Advisory link copied to clipboard!");
                  }
                }}
                title="Share Conversation"
                className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
                aria-label="Share"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                </svg>
              </button>

              {/* Three-Dot Menu */}
              <button
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
                aria-label="Options"
              >
                <svg className="h-4.5 w-4.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" />
                </svg>
              </button>

              {menuOpen && (
                <div className="absolute right-0 top-10 z-30 w-52 rounded-2xl border border-line bg-background p-1.5 shadow-lg animate-fade-in">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      void createNewSession();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-ink hover:bg-surface transition-colors"
                  >
                    <span className="text-accent">+</span>
                    <span>New conversation</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      setShowDagDrawer((v) => !v);
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-ink hover:bg-surface transition-colors"
                  >
                    <span className="text-accent">⚙</span>
                    <span>Inspect Multi-Agent DAG</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      fileInputRef.current?.click();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-ink hover:bg-surface transition-colors"
                  >
                    <span className="text-accent">📎</span>
                    <span>Upload chart / document</span>
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Profiling Setup Banner if not finished */}
          {profiling && (
            <div className="flex flex-col items-start justify-between gap-3 border-b border-line bg-accent-soft/70 px-4 py-3 sm:flex-row sm:items-center sm:px-6">
              <div>
                <p className="text-xs font-semibold text-ink">Prefer a guided setup?</p>
                <p className="text-[11px] text-muted">Complete your risk profile via interactive options & sliders.</p>
              </div>
              <ButtonLink href="/onboarding" variant="primary" size="sm" className="shrink-0">
                Take Onboarding Questionnaire →
              </ButtonLink>
            </div>
          )}

          {/* Chat Messages Area */}
          <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
            {!ready || loadingHistory ? (
              <div className="grid h-full min-h-[300px] place-items-center">
                <Loading label="Opening advisory stream…" />
              </div>
            ) : !hasMessages ? (
              /* Hero Empty State */
              <div className="flex h-full min-h-[420px] flex-col items-center justify-center text-center">
                <GlowingSpiralOrb />

                <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">
                  {greeting}
                </h1>
                <p className="mt-2 max-w-md text-sm text-muted">
                  Ask for an institutional allocation, paste financial filings, upload charts, or evaluate mortgage rate trends.
                </p>

                {/* Suggestion Chips */}
                <div className="mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
                  {starterPrompts.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => send(p)}
                      disabled={waiting}
                      className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-xs font-medium text-ink hover:border-accent hover:bg-accent-soft hover:text-accent transition-all shadow-2xs"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              /* Active Transcript Stream with Bubble Layout matching Image 2 */
              <ol className="space-y-1" aria-live="polite">
                {items.map((it) => (
                  <TranscriptRow
                    key={it.id}
                    item={it}
                    proposals={proposals}
                    onApprove={approve}
                    onReject={reject}
                    onSelectOption={(opt) => send(opt)}
                  />
                ))}

                {waiting && (
                  <li className="flex items-center gap-2.5 my-4 animate-fade-in pl-1">
                    <span className="h-2 w-2 rounded-full bg-accent animate-ping" />
                    <span className="text-xs font-medium text-muted">Generating project workflow & quantitative models…</span>
                  </li>
                )}
              </ol>
            )}
            <div ref={endRef} />
          </div>

          {/* Bottom Elevated Composer matching Image 2 */}
          <div className="border-t border-line bg-surface/30 p-4">
            <form
              onSubmit={submit}
              className="rounded-2xl border border-line bg-background p-3 shadow-xs transition-all focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/20"
            >
              {/* Staged Multimodal Attachments / Context Chips */}
              {stagedAttachments.length > 0 && (
                <div className="mb-2.5 flex flex-wrap gap-2 border-b border-line pb-2">
                  {stagedAttachments.map((att, idx) => (
                    <div
                      key={idx}
                      className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-2.5 py-1 text-xs text-ink shadow-2xs"
                    >
                      {att.type === "image" && att.data ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={att.data} alt={att.name || "Upload"} className="h-5 w-5 rounded object-cover" />
                      ) : (
                        <span className="text-accent text-[11px]">📎</span>
                      )}
                      <span className="max-w-[150px] truncate font-medium">{att.name || "Attachment"}</span>
                      <button
                        type="button"
                        onClick={() => removeAttachment(idx)}
                        className="text-muted hover:text-ink font-semibold ml-1"
                        aria-label="Remove"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Textarea Input with "Ask AI anything" placeholder */}
              <textarea
                ref={inputRef}
                rows={2}
                value={draft}
                onPaste={handlePaste}
                placeholder={
                  profiling
                    ? "For example: I'm 34, looking to simulate high-growth wealth accumulation..."
                    : "Ask AI anything"
                }
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                disabled={!ready}
                maxLength={10000}
                className="w-full resize-none bg-transparent px-1 pt-0.5 text-sm text-ink placeholder:text-muted focus:outline-hidden"
              />

              {/* Bottom Controls Strip matching Image 2 */}
              <div className="mt-2 flex items-center justify-between border-t border-line/60 pt-2">
                {/* Left tools */}
                <div className="flex items-center gap-1.5 sm:gap-2">
                  {/* + Attachment button */}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    title="Attach files or images"
                    className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
                  >
                    <span className="text-base font-bold leading-none">+</span>
                  </button>

                  {/* Model Selector Pill */}
                  <div className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11px] font-medium text-ink shadow-2xs">
                    <span className="text-accent text-[11px]">✦</span>
                    <span>Orion gpt-4o</span>
                    <span className="text-[9px] text-muted">▾</span>
                  </div>

                  {/* Reasoning toggle button */}
                  <button
                    type="button"
                    onClick={() => setReasoningActive((v) => !v)}
                    title="Toggle Reasoning Mode"
                    className={`grid h-7 w-7 place-items-center rounded-full transition-colors ${
                      reasoningActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface hover:text-ink"
                    }`}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                  </button>

                  {/* Deep Research toggle button */}
                  <button
                    type="button"
                    onClick={() => setDeepResearchActive((v) => !v)}
                    title="Toggle Deep Web & SEC Research"
                    className={`grid h-7 w-7 place-items-center rounded-full transition-colors ${
                      deepResearchActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface hover:text-ink"
                    }`}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                  </button>
                </div>

                {/* Right tools */}
                <div className="flex items-center gap-2">
                  {/* Microphone voice button */}
                  <button
                    type="button"
                    onClick={toggleSpeech}
                    title={isListening ? "Listening... click to stop" : "Voice input"}
                    className={`grid h-7 w-7 place-items-center rounded-full transition-all ${
                      isListening ? "bg-danger-soft text-danger animate-pulse" : "text-muted hover:bg-surface hover:text-ink"
                    }`}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                  </button>

                  {/* Circular Upward Arrow Send Button matching Image 2 */}
                  <button
                    type="submit"
                    disabled={!ready || (!draft.trim() && stagedAttachments.length === 0) || waiting}
                    className="grid h-8 w-8 place-items-center rounded-full bg-primary text-on-primary shadow-xs hover:bg-primary-hover disabled:opacity-35 disabled:hover:bg-primary transition-all"
                    style={{ color: "#ffffff" }}
                    aria-label="Send message"
                  >
                    <span className="text-sm font-bold leading-none" style={{ color: "#ffffff" }}>↑</span>
                  </button>
                </div>
              </div>
            </form>

            {/* Disclaimer underneath (matching Image 2) */}
            <p className="mt-2 text-center text-[11px] text-muted">
              Actions may contain mistakes. Please use with discretion.
            </p>
          </div>
        </section>

        {/* 2. Right "History Chat" Sidebar (added back as requested) */}
        <aside
          aria-label="Chat History"
          className="flex min-h-[82vh] flex-col overflow-hidden rounded-3xl border border-line bg-background shadow-[0_2px_20px_rgba(15,41,34,0.04)]"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-line bg-surface/50 px-4 py-3.5">
            <h2 className="text-sm font-semibold tracking-tight text-ink">History Chat</h2>
            <button
              type="button"
              onClick={() => void createNewSession()}
              className="flex items-center gap-1 rounded-full border border-line bg-background px-3 py-1 text-xs font-semibold text-ink shadow-2xs hover:border-accent hover:text-accent hover:bg-accent-soft transition-all"
            >
              <span>+</span>
              <span>New Chat</span>
            </button>
          </div>

          {/* Search Box */}
          <div className="p-3 border-b border-line/60 bg-surface/30">
            <input
              type="text"
              value={sessionSearch}
              onChange={(e) => setSessionSearch(e.target.value)}
              placeholder="Search history…"
              className="w-full rounded-xl border border-line bg-surface px-3 py-1.5 text-xs text-ink placeholder:text-muted focus:border-accent focus:outline-hidden"
            />
          </div>

          {/* Grouped Chronological List */}
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {filteredSessions.length === 0 ? (
              <div className="grid h-40 place-items-center text-center">
                <p className="text-xs text-muted">No conversations found.</p>
                <button
                  type="button"
                  onClick={() => void createNewSession()}
                  className="mt-2 text-xs font-semibold text-accent hover:underline"
                >
                  Start first chat
                </button>
              </div>
            ) : null}

            {/* Today */}
            {grouped.today.length > 0 && (
              <div>
                <p className="px-2 text-[10px] font-bold tracking-wider text-muted uppercase">Today</p>
                <div className="mt-1.5 space-y-1">
                  {grouped.today.map((s) => {
                    const active = s.session_id === activeSessionId;
                    return (
                      <div
                        key={s.session_id}
                        onClick={() => void loadSession(s.session_id)}
                        className={`group relative flex items-center justify-between rounded-xl px-2.5 py-2 text-left text-xs cursor-pointer transition-all ${
                          active
                            ? "bg-accent-soft text-accent font-semibold border border-accent/30 shadow-2xs"
                            : "text-ink hover:bg-surface border border-transparent"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 pr-2">
                          <svg className="h-3.5 w-3.5 shrink-0 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                          </svg>
                          <span className="truncate">{s.title || "Advisory Session"}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm("Delete this conversation?")) {
                              void deleteSession(s.session_id);
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 text-muted hover:text-danger p-0.5 rounded transition-opacity"
                          title="Delete session"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Yesterday */}
            {grouped.yesterday.length > 0 && (
              <div>
                <p className="px-2 text-[10px] font-bold tracking-wider text-muted uppercase">Yesterday</p>
                <div className="mt-1.5 space-y-1">
                  {grouped.yesterday.map((s) => {
                    const active = s.session_id === activeSessionId;
                    return (
                      <div
                        key={s.session_id}
                        onClick={() => void loadSession(s.session_id)}
                        className={`group relative flex items-center justify-between rounded-xl px-2.5 py-2 text-left text-xs cursor-pointer transition-all ${
                          active
                            ? "bg-accent-soft text-accent font-semibold border border-accent/30 shadow-2xs"
                            : "text-ink hover:bg-surface border border-transparent"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 pr-2">
                          <svg className="h-3.5 w-3.5 shrink-0 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                          </svg>
                          <span className="truncate">{s.title || "Advisory Session"}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm("Delete this conversation?")) {
                              void deleteSession(s.session_id);
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 text-muted hover:text-danger p-0.5 rounded transition-opacity"
                          title="Delete session"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Previous 7 Days */}
            {grouped.fiveDays.length > 0 && (
              <div>
                <p className="px-2 text-[10px] font-bold tracking-wider text-muted uppercase">Previous 7 Days</p>
                <div className="mt-1.5 space-y-1">
                  {grouped.fiveDays.map((s) => {
                    const active = s.session_id === activeSessionId;
                    return (
                      <div
                        key={s.session_id}
                        onClick={() => void loadSession(s.session_id)}
                        className={`group relative flex items-center justify-between rounded-xl px-2.5 py-2 text-left text-xs cursor-pointer transition-all ${
                          active
                            ? "bg-accent-soft text-accent font-semibold border border-accent/30 shadow-2xs"
                            : "text-ink hover:bg-surface border border-transparent"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 pr-2">
                          <svg className="h-3.5 w-3.5 shrink-0 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                          </svg>
                          <span className="truncate">{s.title || "Advisory Session"}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm("Delete this conversation?")) {
                              void deleteSession(s.session_id);
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 text-muted hover:text-danger p-0.5 rounded transition-opacity"
                          title="Delete session"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Older */}
            {grouped.older.length > 0 && (
              <div>
                <p className="px-2 text-[10px] font-bold tracking-wider text-muted uppercase">Older</p>
                <div className="mt-1.5 space-y-1">
                  {grouped.older.map((s) => {
                    const active = s.session_id === activeSessionId;
                    return (
                      <div
                        key={s.session_id}
                        onClick={() => void loadSession(s.session_id)}
                        className={`group relative flex items-center justify-between rounded-xl px-2.5 py-2 text-left text-xs cursor-pointer transition-all ${
                          active
                            ? "bg-accent-soft text-accent font-semibold border border-accent/30 shadow-2xs"
                            : "text-ink hover:bg-surface border border-transparent"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 pr-2">
                          <svg className="h-3.5 w-3.5 shrink-0 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                          </svg>
                          <span className="truncate">{s.title || "Advisory Session"}</span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm("Delete this conversation?")) {
                              void deleteSession(s.session_id);
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 text-muted hover:text-danger p-0.5 rounded transition-opacity"
                          title="Delete session"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
