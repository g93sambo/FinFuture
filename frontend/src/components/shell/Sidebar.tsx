"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Wordmark } from "./Wordmark";

const navItems: { href: string; label: string; group: string }[] = [
  { href: "/app", label: "Dashboard", group: "Core" },
  { href: "/app/advisor", label: "Advisor", group: "Advice" },
  { href: "/app/allocation", label: "Allocation", group: "Advice" },
  { href: "/app/compare", label: "Compare", group: "Advice" },
  { href: "/app/trade", label: "Finance & Trade", group: "Portfolio" },
  { href: "/app/markets", label: "Markets", group: "Portfolio" },
  { href: "/app/health", label: "Reports & Health", group: "Reports" },
  { href: "/app/profile", label: "Profile", group: "Account" },
];

export function TopNav() {
  const path = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setNotifOpen(false);
        setSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  const filteredNav = navItems.filter((it) =>
    it.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
    it.group.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "EQ";

  return (
    <header className="sticky top-0 z-30 border-b border-line/80 bg-background/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1380px] items-center justify-between gap-4 px-5 sm:px-8">
        {/* Left: Brand Wordmark */}
        <div className="flex items-center gap-3 shrink-0">
          <Wordmark href="/app" />
        </div>

        {/* Center: Horizontal Pill Navigation matching Equify screenshot */}
        <nav aria-label="Main Navigation" className="hidden lg:flex items-center gap-1 overflow-x-auto py-1">
          {navItems.map((it) => {
            const active = it.href === "/app" ? path === "/app" : path.startsWith(it.href);
            return (
              <Link
                key={it.href}
                href={it.href}
                prefetch={true}
                onPointerEnter={() => router.prefetch(it.href)}
                aria-current={active ? "page" : undefined}
                className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium whitespace-nowrap transition-all duration-150 select-none ${
                  active
                    ? "bg-primary text-on-primary shadow-xs"
                    : "text-muted hover:text-ink hover:bg-surface"
                }`}
              >
                {it.label}
              </Link>
            );
          })}
        </nav>

        {/* Right: Search, Bell, and User Avatar */}
        <div ref={menuRef} className="relative flex items-center gap-2.5 shrink-0">
          {/* Quick Search Button */}
          <button
            type="button"
            onClick={() => {
              setSearchOpen((v) => !v);
              setNotifOpen(false);
              setMenuOpen(false);
            }}
            aria-label="Quick navigation search"
            className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
          >
            <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4">
              <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M13.2 13.2L16.5 16.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>

          {/* Notification Bell Button */}
          <button
            type="button"
            onClick={() => {
              setNotifOpen((v) => !v);
              setSearchOpen(false);
              setMenuOpen(false);
            }}
            aria-label="Account notifications"
            className="relative grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface hover:text-ink transition-colors"
          >
            <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4">
              <path
                d="M10 3.5C7.5 3.5 5.5 5.5 5.5 8V11.5L4 13.5V14.5H16V13.5L14.5 11.5V8C14.5 5.5 12.5 3.5 10 3.5Z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
              <path d="M8.5 15C8.5 15.8 9.2 16.5 10 16.5C10.8 16.5 11.5 15.8 11.5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span className="absolute top-1.5 right-2 h-1.5 w-1.5 rounded-full bg-accent" />
          </button>

          {/* Profile Avatar Button */}
          <button
            type="button"
            onClick={() => {
              setMenuOpen((v) => !v);
              setSearchOpen(false);
              setNotifOpen(false);
            }}
            className="flex items-center gap-2 rounded-full border border-line bg-surface p-0.5 pr-2.5 text-xs font-medium text-ink hover:border-primary/40 transition-colors"
          >
            <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-[11px] font-bold text-on-primary">
              {initials}
            </span>
            <span className="hidden sm:inline max-w-[120px] truncate text-ink">
              {user?.email?.split("@")[0] ?? "Investor"}
            </span>
          </button>

          {/* Search Popover */}
          {searchOpen ? (
            <div className="absolute top-11 right-0 z-50 w-72 rounded-card border border-line bg-background p-3 shadow-lg">
              <input
                type="text"
                autoFocus
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Jump to page or tool…"
                className="w-full rounded-control border border-line bg-surface px-3 py-1.5 text-xs text-ink focus:border-accent focus:outline-none"
              />
              <ul className="mt-2 max-h-56 overflow-y-auto divide-y divide-line/60 text-xs">
                {filteredNav.map((it) => (
                  <li key={it.href}>
                    <Link
                      href={it.href}
                      onClick={() => {
                        setSearchOpen(false);
                        setSearchQuery("");
                      }}
                      className="flex items-center justify-between px-2 py-2 rounded-md text-ink hover:bg-surface"
                    >
                      <span className="font-medium">{it.label}</span>
                      <span className="text-[11px] text-muted">{it.group}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* Notifications Popover */}
          {notifOpen ? (
            <div className="absolute top-11 right-0 z-50 w-80 rounded-card border border-line bg-background p-4 shadow-lg text-xs">
              <div className="flex items-center justify-between border-b border-line pb-2.5">
                <span className="font-semibold text-ink">Account Protection</span>
                <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">Active</span>
              </div>
              <ul className="mt-2.5 space-y-2.5 text-muted">
                <li className="flex items-start gap-2">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  <span>Pre-trade suitability and concentration checks run automatically on every order.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span>Paper trading mode enabled. No real funds are at risk.</span>
                </li>
              </ul>
            </div>
          ) : null}

          {/* User Account Menu Popover */}
          {menuOpen ? (
            <div className="absolute top-11 right-0 z-50 w-64 rounded-card border border-line bg-background p-4 shadow-lg text-xs">
              <p className="text-muted">Signed in as</p>
              <p className="mt-0.5 truncate font-semibold text-ink" title={user?.email}>
                {user?.email}
              </p>
              <div className="mt-3 border-t border-line pt-2.5 space-y-1">
                <Link
                  href="/app/profile"
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-md px-2.5 py-1.5 text-ink hover:bg-surface"
                >
                  Risk Profile & Suitability
                </Link>
                <Link
                  href="/onboarding"
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-md px-2.5 py-1.5 text-ink hover:bg-surface"
                >
                  Update Onboarding Questionnaire
                </Link>
                <Link
                  href="/app/compliance"
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-md px-2.5 py-1.5 text-ink hover:bg-surface"
                >
                  Fiduciary Safeguards & Rules
                </Link>
                <Link
                  href="/app/audit"
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-md px-2.5 py-1.5 text-ink hover:bg-surface"
                >
                  Account Activity Log
                </Link>
              </div>
              <div className="mt-3 border-t border-line pt-2.5">
                <button
                  type="button"
                  onClick={logout}
                  className="w-full rounded-md bg-primary px-3 py-1.5 text-center font-medium text-on-primary hover:bg-primary-hover transition-colors"
                >
                  Sign out
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

export function Sidebar() {
  return <TopNav />;
}

/** Mobile navigation bar for smaller viewports */
export function MobileBar() {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  const { user, logout } = useAuth();

  useEffect(() => setOpen(false), [path]);

  return (
    <div className="lg:hidden border-b border-line bg-background px-5 py-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted">
          Section: <strong className="text-ink">{navItems.find((i) => (i.href === "/app" ? path === "/app" : path.startsWith(i.href)))?.label ?? "Dashboard"}</strong>
        </span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink"
        >
          {open ? "Close Menu" : "All Pages ▾"}
        </button>
      </div>
      {open ? (
        <nav className="mt-3 grid grid-cols-2 gap-1.5 border-t border-line pt-3 pb-2">
          {navItems.map((it) => {
            const active = it.href === "/app" ? path === "/app" : path.startsWith(it.href);
            return (
              <Link
                key={it.href}
                href={it.href}
                onClick={() => setOpen(false)}
                className={`rounded-lg px-3 py-2 text-xs font-medium ${
                  active ? "bg-primary text-on-primary" : "bg-surface text-ink hover:bg-surface-muted"
                }`}
              >
                {it.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={logout}
            className="col-span-2 mt-1 rounded-lg border border-line py-2 text-xs font-medium text-muted hover:text-ink"
          >
            Sign out ({user?.email})
          </button>
        </nav>
      ) : null}
    </div>
  );
}

