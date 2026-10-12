"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL, api, tokenStore } from "./api";
import { useAuth } from "./auth";
import type { AgentEvent } from "./types";

export type Connection = "connecting" | "live" | "fallback" | "closed";
export type ProposalState = "open" | "approving" | "rejecting" | "done" | "cancelled" | "blocked";

export interface TranscriptItem {
  id: string;
  /** "you" for messages typed here, otherwise the raw event. */
  from: "you" | "agent";
  text?: string;
  event?: AgentEvent;
  at: string;
}

let seq = 0;
const nextId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`;

/**
 * Drives the Advisor conversation. Prefers the WebSocket (/ws/chat/{session});
 * if it cannot connect, falls back to the REST chat endpoint so the
 * conversation still works.
 */
export function useAdvisor() {
  const { session, clientId, setClientId } = useAuth();
  const [items, setItems] = useState<TranscriptItem[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [waiting, setWaiting] = useState(false);
  const [stage, setStage] = useState<string>("PROFILING");
  const [proposals, setProposals] = useState<Record<string, ProposalState>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const lastApproved = useRef<string | null>(null);
  const seeded = useRef(false);

  const push = useCallback((item: Omit<TranscriptItem, "id" | "at"> & { at?: string }) => {
    setItems((xs) => [...xs, { id: nextId(), at: item.at ?? new Date().toISOString(), ...item }]);
  }, []);

  const ingest = useCallback(
    (events: AgentEvent[]) => {
      for (const ev of events) {
        if (ev.event === "user_message") continue; // we already show what the user typed
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
        push({ from: "agent", event: ev, text: ev.text, at: ev.timestamp });
      }
      if (events.length) setWaiting(false);
    },
    [push, setClientId],
  );

  // Seed with the greeting returned by /session/start.
  useEffect(() => {
    if (!session || seeded.current) return;
    seeded.current = true;
    setStage(session.stage);
    push({ from: "agent", event: { event: "agent_response", agent: "Orchestrator", text: session.message }, text: session.message });
  }, [session, push]);

  // Open the socket for this session.
  useEffect(() => {
    if (!session) return;
    const token = tokenStore.get();
    if (!token) return;
    let opened = false;
    let disposed = false;
    const ws = new WebSocket(`${WS_URL}/ws/chat/${encodeURIComponent(session.session_id)}?token=${encodeURIComponent(token)}`);
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
        /* ignore non-JSON frames */
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
  }, [session, ingest]);

  const socketOpen = () => wsRef.current?.readyState === WebSocket.OPEN;

  const restSend = useCallback(
    async (text: string) => {
      if (!session) return;
      try {
        const res = await api.sendMessage(session.session_id, text);
        ingest(res.events);
      } catch (e) {
        setWaiting(false);
        push({ from: "agent", event: { event: "error", agent: "Orchestrator", text: (e as Error).message }, text: (e as Error).message });
      }
    },
    [session, ingest, push],
  );

  const send = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t || !session) return;
      push({ from: "you", text: t });
      setWaiting(true);
      if (socketOpen()) wsRef.current!.send(JSON.stringify({ type: "message", text: t }));
      else void restSend(t);
    },
    [session, push, restSend],
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

  return { items, connection, waiting, stage, proposals, send, approve, reject, ready: Boolean(session) };
}
