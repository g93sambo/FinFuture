"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "./api";
import type { SessionStart, User } from "./types";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthState {
  status: Status;
  user: User | null;
  /** Advisory session started for this visit (holds the chat stage). */
  session: SessionStart | null;
  sessionError: string | null;
  /** The client profile this user acts on. Null until risk profiling is complete. */
  clientId: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  ensureSession: () => Promise<SessionStart | null>;
  refreshSession: () => Promise<SessionStart | null>;
  setClientId: (id: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<SessionStart | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [clientId, setClientIdState] = useState<string | null>(null);
  const sessionPromise = useRef<Promise<SessionStart | null> | null>(null);

  const reset = useCallback(() => {
    tokenStore.clear();
    // Forget everything tied to this account (name, open chat, saved results) so the next
    // person on this browser starts clean; only the layout preference survives.
    try {
      const keys = Object.keys(window.localStorage).filter((k) => k.startsWith("finfuture.") && k !== "finfuture.sidebar");
      keys.forEach((k) => window.localStorage.removeItem(k));
    } catch {
      // Storage unavailable: nothing to clear
    }
    sessionPromise.current = null;
    setUser(null);
    setSession(null);
    setClientIdState(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(reset);
    const token = tokenStore.get();
    if (!token) {
      setStatus("anonymous");
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        setStatus("authenticated");
      })
      .catch(() => reset());
    return () => setUnauthorizedHandler(null);
  }, [reset]);

  const ensureSession = useCallback(async () => {
    if (!sessionPromise.current) {
      sessionPromise.current = api
        .startSession()
        .then((s) => {
          setSession(s);
          setSessionError(null);
          if (s.client_id) setClientIdState(s.client_id);
          return s;
        })
        .catch((e: Error) => {
          sessionPromise.current = null;
          setSessionError(e.message);
          return null;
        });
    }
    return sessionPromise.current;
  }, []);

  const refreshSession = useCallback(async () => {
    sessionPromise.current = null;
    return ensureSession();
  }, [ensureSession]);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password);
    tokenStore.set(access_token);
    const u = await api.me();
    sessionPromise.current = null;
    setUser(u);
    setStatus("authenticated");
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      await api.register(email, password);
      await login(email, password);
    },
    [login],
  );

  const value = useMemo<AuthState>(
    () => ({
      status,
      user,
      session,
      sessionError,
      clientId,
      login,
      register,
      logout: reset,
      ensureSession,
      refreshSession,
      setClientId: setClientIdState,
    }),
    [status, user, session, sessionError, clientId, login, register, reset, ensureSession, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
