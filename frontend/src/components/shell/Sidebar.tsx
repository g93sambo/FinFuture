"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Wordmark } from "./Wordmark";

const groups: { heading: string; items: { href: string; label: string }[] }[] = [
  {
    heading: "Advice",
    items: [
      { href: "/app", label: "Overview" },
      { href: "/app/advisor", label: "Advisor" },
      { href: "/app/allocation", label: "Allocation" },
      { href: "/app/compare", label: "Compare funds" },
    ],
  },
  {
    heading: "Portfolio",
    items: [
      { href: "/app/trade", label: "Trade" },
      { href: "/app/health", label: "Health review" },
      { href: "/app/markets", label: "Markets" },
    ],
  },
  {
    heading: "Records",
    items: [
      { href: "/app/profile", label: "Risk profile" },
      { href: "/app/audit", label: "Audit trail" },
      { href: "/app/compliance", label: "Compliance rules" },
    ],
  },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="space-y-7">
      {groups.map((g) => (
        <div key={g.heading}>
          <p className="mb-2 px-3 text-[12.5px] text-on-primary/70">{g.heading}</p>
          <ul className="space-y-px">
            {g.items.map((it) => {
              const active = it.href === "/app" ? path === "/app" : path.startsWith(it.href);
              return (
                <li key={it.href}>
                  <Link
                    href={it.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-9 items-center px-3 text-[14.5px] transition-colors ${
                      active ? "bg-on-primary font-semibold text-primary" : "text-on-primary hover:bg-on-primary/10"
                    }`}
                  >
                    {it.label}
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

function AccountBlock() {
  const { user, logout } = useAuth();
  return (
    <div className="border-t border-on-primary/20 pt-4 text-[13px]">
      <p className="text-on-primary/70">Signed in as</p>
      <p className="truncate text-on-primary" title={user?.email}>
        {user?.email}
      </p>
      <button onClick={logout} className="mt-3 text-on-primary underline decoration-on-primary/40 underline-offset-4 hover:decoration-on-primary">
        Sign out
      </button>
      <p className="mt-5 border border-on-primary/30 px-2 py-1.5 text-on-primary/85">
        Paper trading account. No real money moves.
      </p>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between overflow-y-auto bg-primary px-4 py-6 lg:flex">
      <div>
        <div className="mb-9 px-3">
          <Wordmark href="/app" inverted />
        </div>
        <NavList />
      </div>
      <div className="px-3">
        <AccountBlock />
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
      <div className="flex h-14 items-center justify-between bg-primary px-4">
        <Wordmark href="/app" inverted />
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          className="h-9 border border-on-primary/40 px-3 text-sm text-on-primary"
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>
      {open ? (
        <div id="mobile-nav" className="fixed inset-x-0 top-14 bottom-0 z-40 overflow-y-auto bg-primary px-4 py-6">
          <NavList onNavigate={() => setOpen(false)} />
          <div className="mt-8 px-3">
            <AccountBlock />
          </div>
        </div>
      ) : null}
    </div>
  );
}
