"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL, api, tokenStore } from "./api";
import { useAuth } from "./auth";
import type { AgentEvent, ChatMessageAttachment, ChatSessionItem } from "./types";

export type Connection = "connecting" | "live" | "fallback" | "closed";
export type ProposalState = "open" | "approving" | "rejecting" | "done" | "cancelled" | "blocked";

export interface TranscriptItem {
  id: string;
  from: "you" | "agent";
  text?: string;
  event?: AgentEvent;
  attachments?: ChatMessageAttachment[];
  at: string;
}

let seq = 0;
const nextId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`;

export function useAdvisor() {
  const { session: initialSession, clientId, setClientId } = useAuth();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeTitle, setActiveTitle] = useState<string>("Orion Advisory");
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const [items, setItems] = useState<TranscriptItem[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [waiting, setWaiting] = useState(false);
  const [stage, setStage] = useState<string>("PROFILING");
  const [proposals, setProposals] = useState<Record<string, ProposalState>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const lastApproved = useRef<string | null>(null);
  const seeded = useRef<string | null>(null);

  // Initialize activeSessionId from auth session
  useEffect(() => {
    if (initialSession && !activeSessionId) {
      setActiveSessionId(initialSession.session_id);
      setStage(initialSession.stage || "PROFILING");
    }
  }, [initialSession, activeSessionId]);

  // Fetch user's session list
  const refreshSessions = useCallback(async () => {
    try {
      const list = await api.getChatSessions();
      setSessions(list);
    } catch {
      // offline / quiet fallback
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions, activeSessionId]);

  const push = useCallback((item: Omit<TranscriptItem, "id" | "at"> & { at?: string }) => {
    setItems((xs) => [...xs, { id: nextId(), at: item.at ?? new Date().toISOString(), ...item }]);
  }, []);

  const ingest = useCallback(
    (events: AgentEvent[]) => {
      for (const ev of events) {
        if (ev.event === "user_message") continue;
        if (ev.structured_event === "session_started") {
          if (ev.stage) setStage(ev.stage);
          continue;
        }
        if (ev.client_id) setClientId(ev.client_id);
        if (ev.profile_complete) setStage("ADVICE_GENERATION");
        if (ev.event === "trade_proposal" && ev.proposal) {
          const pid = ev.proposal.proposal_id;
          setStage("PROPOSAL_REVIEW");
          setProposals((p) => ({ ...p, [pid]: p[pid] ?? "open" }));
        }
        if (ev.event === "trade_filled" && ev.execution) {
          const pid = ev.execution.proposal_id;
          setStage("ADVICE_GENERATION");
          setProposals((p) => ({ ...p, [pid]: "done" }));
        }
        if (ev.event === "error" && lastApproved.current) {
          const pid = lastApproved.current;
          setProposals((p) => ({ ...p, [pid]: "blocked" }));
          lastApproved.current = null;
        }
        if (ev.event === "agent_response" && /cancelled/i.test(ev.text ?? "")) {
          setStage("ADVICE_GENERATION");
          setProposals((p) => {
            const next = { ...p };
            for (const k of Object.keys(next)) if (next[k] === "open" || next[k] === "rejecting") next[k] = "cancelled";
            return next;
          });
        }
        push({ from: "agent", event: ev, text: ev.text, attachments: ev.attachments, at: ev.timestamp });
      }
      if (events.length) setWaiting(false);
    },
    [push, setClientId],
  );

  // Seed initial greeting if active session is new
  useEffect(() => {
    if (!initialSession || !activeSessionId || seeded.current === activeSessionId) return;
    if (activeSessionId === initialSession.session_id) {
      seeded.current = activeSessionId;
      setStage(initialSession.stage);
      push({
        from: "agent",
        event: { event: "agent_response", agent: "Orchestrator", text: initialSession.message },
        text: initialSession.message,
      });
    }
  }, [initialSession, activeSessionId, push]);

  // Connect WebSocket to currently active session
  useEffect(() => {
    if (!activeSessionId) return;
    const token = tokenStore.get();
    if (!token) return;

    let opened = false;
    let disposed = false;
    const ws = new WebSocket(`${WS_URL}/ws/chat/${encodeURIComponent(activeSessionId)}?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;
    setConnection("connecting");

    const fallbackTimer = setTimeout(() => {
      if (!opened && !disposed) setConnection("fallback");
    }, 4000);

    ws.onopen = () => {
      opened = true;
      setConnection("live");
    };

    ws.onmessage = (m) => {
      try {
        ingest([JSON.parse(m.data) as AgentEvent]);
      } catch {
        /* ignore */
      }
    };

    ws.onerror = () => {
      if (!disposed) setConnection("fallback");
    };

    ws.onclose = () => {
      if (disposed) return;
      setConnection(opened ? "closed" : "fallback");
    };

    return () => {
      disposed = true;
      clearTimeout(fallbackTimer);
      ws.close();
      wsRef.current = null;
    };
  }, [activeSessionId, ingest]);

  const socketOpen = () => wsRef.current?.readyState === WebSocket.OPEN;

  // Load a historical chat session
  const loadSession = useCallback(
    async (sessionId: string) => {
      if (sessionId === activeSessionId) return;
      setLoadingHistory(true);
      try {
        const detail = await api.getChatSession(sessionId);
        setActiveSessionId(detail.session_id);
        setActiveTitle(detail.title || "Advisory Conversation");
        setStage(detail.stage || "ADVICE_GENERATION");
        seeded.current = detail.session_id;

        const converted: TranscriptItem[] = [];
        const nextProposals: Record<string, ProposalState> = {};

        for (const m of detail.messages) {
          const from = m.sender === "user" ? ("you" as const) : ("agent" as const);
          const ev = m.events && m.events.length > 0 ? m.events[0] : undefined;

          if (ev?.event === "trade_proposal" && ev.proposal) {
            nextProposals[ev.proposal.proposal_id] = "open";
          }
          if (ev?.event === "trade_filled" && ev.execution) {
            nextProposals[ev.execution.proposal_id] = "done";
          }

          converted.push({
            id: m.id || nextId(),
            from,
            text: m.text || "",
            event: ev,
            attachments: m.attachments,
            at: m.created_at,
          });
        }

        setItems(converted);
        setProposals(nextProposals);
      } catch (e) {
        console.error("Failed to load session:", e);
      } finally {
        setLoadingHistory(false);
      }
    },
    [activeSessionId],
  );

  // Create a brand new chat session
  const createNewSession = useCallback(
    async (title = "New Advisory Conversation") => {
      try {
        setWaiting(true);
        const res = await api.createChatSession(title);
        setActiveSessionId(res.session_id);
        setActiveTitle(res.title || title);
        setStage(res.stage || "ADVICE_GENERATION");
        seeded.current = res.session_id;

        setItems([
          {
            id: nextId(),
            from: "agent",
            text: res.message,
            event: { event: "agent_response", agent: "WealthAdvisor", text: res.message },
            at: new Date().toISOString(),
          },
        ]);
        setProposals({});
        await refreshSessions();
      } catch (e) {
        console.error("Failed to create new session:", e);
      } finally {
        setWaiting(false);
      }
    },
    [refreshSessions],
  );

  // Delete a session
  const deleteSession = useCallback(
    async (sessionId: string) => {
      try {
        await api.deleteChatSession(sessionId);
        await refreshSessions();
        if (sessionId === activeSessionId) {
          // Switch to another session or create new
          const remaining = sessions.filter((s) => s.session_id !== sessionId);
          if (remaining.length > 0) {
            void loadSession(remaining[0].session_id);
          } else {
            void createNewSession("New Advisory Conversation");
          }
        }
      } catch (e) {
        console.error("Failed to delete session:", e);
      }
    },
    [activeSessionId, sessions, refreshSessions, loadSession, createNewSession],
  );

  const restSend = useCallback(
    async (text: string, attachments?: ChatMessageAttachment[]) => {
      if (!activeSessionId) return;
      try {
        const res = await api.sendMessage(activeSessionId, text, attachments);
        ingest(res.events);
        void refreshSessions();
      } catch (e) {
        setWaiting(false);
        push({ from: "agent", event: { event: "error", agent: "Orchestrator", text: (e as Error).message }, text: (e as Error).message });
      }
    },
    [activeSessionId, ingest, push, refreshSessions],
  );

  const send = useCallback(
    (text: string, attachments?: ChatMessageAttachment[]) => {
      const t = text.trim();
      if ((!t && (!attachments || attachments.length === 0)) || !activeSessionId) return;
      push({ from: "you", text: t, attachments });
      setWaiting(true);
      if (socketOpen()) {
        wsRef.current!.send(JSON.stringify({ type: "message", text: t, attachments: attachments || [] }));
        void refreshSessions();
      } else {
        void restSend(t, attachments);
      }
    },
    [activeSessionId, push, restSend, refreshSessions],
  );

  const approve = useCallback(
    async (proposalId: string) => {
      setProposals((p) => ({ ...p, [proposalId]: "approving" }));
      lastApproved.current = proposalId;
      setWaiting(true);
      if (socketOpen()) {
        wsRef.current!.send(JSON.stringify({ type: "approve", proposal_id: proposalId }));
        return;
      }
      if (!clientId) return;
      try {
        const res = await api.executeProposal(clientId, proposalId, true);
        ingest(res.events);
      } catch (e) {
        setProposals((p) => ({ ...p, [proposalId]: "blocked" }));
        setWaiting(false);
        push({ from: "agent", event: { event: "error", agent: "ExecutionModule", text: (e as Error).message }, text: (e as Error).message });
      }
    },
    [clientId, ingest, push],
  );

  const reject = useCallback(
    (proposalId: string) => {
      setProposals((p) => ({ ...p, [proposalId]: "rejecting" }));
      setWaiting(true);
      if (socketOpen()) wsRef.current!.send(JSON.stringify({ type: "reject", proposal_id: proposalId }));
      else void restSend("cancel");
    },
    [restSend],
  );

  return {
    items,
    connection,
    waiting,
    stage,
    proposals,
    send,
    approve,
    reject,
    ready: Boolean(activeSessionId),
    activeSessionId,
    activeTitle,
    sessions,
    loadSession,
    createNewSession,
    deleteSession,
    refreshSessions,
    loadingHistory,
  };
}
