"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftRight,
  Bot,
  HeartPulse,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  PieChart,
  Scale,
  ScrollText,
  ShieldCheck,
  TrendingUp,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { AuroraBackground } from "@/components/landing/AuroraBackground";
import { useAuth } from "@/lib/auth";
import { Wordmark } from "./Wordmark";

const groups: { heading: string; items: { href: string; label: string; icon: LucideIcon }[] }[] = [
  {
    heading: "Advice",
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboard },
      { href: "/app/advisor", label: "Advisor", icon: Bot },
      { href: "/app/allocation", label: "Allocation", icon: PieChart },
      { href: "/app/compare", label: "Compare funds", icon: Scale },
    ],
  },
  {
    heading: "Portfolio",
    items: [
      { href: "/app/trade", label: "Trade", icon: ArrowLeftRight },
      { href: "/app/health", label: "Health review", icon: HeartPulse },
      { href: "/app/markets", label: "Markets", icon: TrendingUp },
    ],
  },
  {
    heading: "Records",
    items: [
      { href: "/app/profile", label: "Risk profile", icon: UserRound },
      { href: "/app/audit", label: "Audit trail", icon: ScrollText },
      { href: "/app/compliance", label: "Compliance rules", icon: ShieldCheck },
    ],
  },
];

// Sidebar width in px (independent of the root font size); remembered per browser
const MIN_WIDTH = 200;
const MAX_WIDTH = 360;
const DEFAULT_WIDTH = 248;
const COLLAPSED_WIDTH = 72;
const STORAGE_KEY = "finfuture.sidebar";

function readStored(): { width: number; collapsed: boolean } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as { width?: unknown; collapsed?: unknown };
    const width = typeof v.width === "number" ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, v.width)) : DEFAULT_WIDTH;
    return { width, collapsed: v.collapsed === true };
  } catch {
    return null;
  }
}

function writeStored(width: number, collapsed: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ width, collapsed }));
  } catch {
    // storage unavailable (private mode); the sidebar still works for this visit
  }
}

function NavList({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const path = usePathname();
  const router = useRouter();

  return (
    <nav aria-label="Main" className="space-y-6">
      {groups.map((g) => (
        <div key={g.heading}>
          {collapsed ? (
            <div aria-hidden className="mx-auto mb-2 h-px w-8 bg-on-primary/20" />
          ) : (
            <p className="mb-1.5 px-3 text-[12px] font-semibold uppercase tracking-wider text-on-primary/60">{g.heading}</p>
          )}
          <ul className="space-y-0.5">
            {g.items.map((it) => {
              const active = it.href === "/app" ? path === "/app" : path.startsWith(it.href);
              const Icon = it.icon;
              return (
                <li key={it.href}>
                  <Link
                    href={it.href}
                    prefetch={true}
                    onPointerEnter={() => router.prefetch(it.href)}
                    onTouchStart={() => router.prefetch(it.href)}
                    onClick={onNavigate}
                    title={collapsed ? it.label : undefined}
                    aria-label={collapsed ? it.label : undefined}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-10 items-center gap-3 rounded-button text-[15px] select-none transition-all duration-140 ease-out active:scale-[0.98] ${
                      collapsed ? "justify-center px-0" : "px-3"
                    } ${
                      active
                        ? "bg-on-primary font-semibold text-primary shadow-[0_0_24px_color-mix(in_srgb,var(--on-primary)_35%,transparent)]"
                        : "text-on-primary/90 hover:bg-on-primary/10 hover:text-on-primary active:bg-on-primary/15"
                    }`}
                  >
                    <Icon aria-hidden className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
                    {collapsed ? null : <span className="truncate">{it.label}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function AccountBlock({ collapsed = false }: { collapsed?: boolean }) {
  const { user, logout } = useAuth();
  const initial = user?.email?.[0]?.toUpperCase() ?? "?";

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-2 border-t border-on-primary/20 pt-3">
        <span title={user?.email} className="grid h-9 w-9 place-items-center rounded-full bg-on-primary/15 text-[14px] font-semibold text-on-primary">
          {initial}
        </span>
        <button
          onClick={logout}
          title="Sign out"
          aria-label="Sign out"
          className="grid h-10 w-10 place-items-center rounded-button text-on-primary transition-all duration-140 ease-out hover:bg-on-primary/10 active:scale-95"
        >
          <LogOut aria-hidden className="h-[18px] w-[18px]" />
        </button>
      </div>
    );
  }

  return (
    <div className="border-t border-on-primary/20 pt-3">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-on-primary/15 text-[13px] font-semibold text-on-primary">
          {initial}
        </span>
        <p className="min-w-0 truncate text-[13px] text-on-primary/90" title={user?.email}>
          {user?.email}
        </p>
      </div>
      <button
        onClick={logout}
        className="mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-button border border-on-primary/50 text-[14px] font-medium text-on-primary transition-all duration-140 ease-out hover:bg-on-primary hover:text-primary active:scale-[0.98]"
      >
        <LogOut aria-hidden className="h-4 w-4" />
        Sign out
      </button>
    </div>
  );
}

export function Sidebar() {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [collapsed, setCollapsed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const startRef = useRef<{ x: number; width: number } | null>(null);

  useEffect(() => {
    const stored = readStored();
    if (stored) {
      setWidth(stored.width);
      setCollapsed(stored.collapsed);
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded && !dragging) writeStored(width, collapsed);
  }, [loaded, dragging, width, collapsed]);

  // Drag the right edge to resize; dragging far enough left collapses to icons
  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    startRef.current = { x: e.clientX, width: collapsed ? COLLAPSED_WIDTH : width };
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const start = startRef.current;
    if (!start) return;
    const next = start.width + (e.clientX - start.x);
    if (next < MIN_WIDTH - 60) {
      setCollapsed(true);
    } else {
      setCollapsed(false);
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, next)));
    }
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (!startRef.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    startRef.current = null;
    setDragging(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width + (e.key === "ArrowRight" ? 16 : -16)));
    setCollapsed(false);
    setWidth(next);
  }

  const shown = collapsed ? COLLAPSED_WIDTH : width;
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <aside
      style={{ width: shown }}
      className={`sticky top-0 isolate hidden h-screen shrink-0 flex-col bg-primary lg:flex ${
        dragging ? "" : "transition-[width] duration-200 ease-out"
      }`}
    >
      <AuroraBackground />

      <div className={`relative z-10 flex shrink-0 items-center pt-5 pb-6 ${collapsed ? "flex-col gap-3 px-2" : "justify-between gap-2 pl-5 pr-3"}`}>
        <Wordmark href="/app" inverted compact={collapsed} />
        <button
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="grid h-9 w-9 place-items-center rounded-button text-on-primary/80 transition-all duration-140 ease-out hover:bg-on-primary/10 hover:text-on-primary active:scale-95"
        >
          <ToggleIcon aria-hidden className="h-[18px] w-[18px]" />
        </button>
      </div>

      <div
        className="relative z-10 min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 pb-3 [scrollbar-color:color-mix(in_srgb,var(--on-primary)_30%,transparent)_transparent] [scrollbar-width:thin]"
      >
        <NavList collapsed={collapsed} />
      </div>

      <div className={`relative z-10 shrink-0 pb-4 ${collapsed ? "px-3" : "px-5"}`}>
        <AccountBlock collapsed={collapsed} />
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={shown}
        tabIndex={0}
        title="Drag to resize · double-click to reset"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => {
          setCollapsed(false);
          setWidth(DEFAULT_WIDTH);
        }}
        onKeyDown={onKeyDown}
        className="group absolute inset-y-0 -right-1.5 z-20 w-3 cursor-col-resize touch-none outline-none"
      >
        <span
          aria-hidden
          className={`absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors ${
            dragging ? "bg-primary" : "bg-transparent group-hover:bg-primary/50 group-focus-visible:bg-primary"
          }`}
        />
      </div>
    </aside>
  );
}

/** Top bar with a menu sheet for narrow screens. */
export function MobileBar() {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <div className="lg:hidden">
      <div className="relative isolate flex h-14 items-center justify-between overflow-hidden bg-primary px-4">
        <AuroraBackground />
        <span className="relative z-10">
          <Wordmark href="/app" inverted />
        </span>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          className="relative z-10 grid h-10 w-10 place-items-center rounded-button border border-on-primary/40 text-on-primary transition-all duration-140 ease-out active:scale-95"
        >
          {open ? <X aria-hidden className="h-5 w-5" /> : <Menu aria-hidden className="h-5 w-5" />}
        </button>
      </div>
      {open ? (
        <div id="mobile-nav" className="fixed inset-x-0 top-14 bottom-0 z-40 isolate overflow-y-auto bg-primary px-4 py-6 [scrollbar-color:color-mix(in_srgb,var(--on-primary)_30%,transparent)_transparent] [scrollbar-width:thin]">
          <AuroraBackground />
          <div className="relative z-10">
            <NavList onNavigate={() => setOpen(false)} />
            <div className="mt-8 px-3">
              <AccountBlock />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
