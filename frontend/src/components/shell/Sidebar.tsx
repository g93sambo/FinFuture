"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuroraBackground } from "@/components/landing/AuroraBackground";
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
  const router = useRouter();

  return (
    <nav aria-label="Main" className="space-y-7">
      {groups.map((g) => (
        <div key={g.heading}>
          <p className="mb-2 px-3 text-[0.875rem] font-medium text-on-primary/75">{g.heading}</p>
          <ul className="space-y-1">
            {g.items.map((it) => {
              const active = it.href === "/app" ? path === "/app" : path.startsWith(it.href);
              return (
                <li key={it.href}>
                  <Link
                    href={it.href}
                    prefetch={true}
                    onPointerEnter={() => router.prefetch(it.href)}
                    onTouchStart={() => router.prefetch(it.href)}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-11 items-center px-3 text-[1.125rem] select-none rounded-button transition-all duration-140 ease-out active:scale-[0.98] ${
                      active ? "bg-on-primary font-semibold text-primary shadow-[0_0_24px_color-mix(in_srgb,var(--on-primary)_35%,transparent)]" : "text-on-primary hover:bg-on-primary/10 active:bg-on-primary/15"
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
    <div className="border-t border-on-primary/20 pt-3 text-[1rem]">
      <p className="truncate text-on-primary" title={user?.email}>
        {user?.email}
      </p>
      <button onClick={logout} className="mt-3 flex h-11 w-full items-center justify-center rounded-button border border-on-primary/60 text-[1rem] font-medium text-on-primary transition-all duration-140 ease-out hover:bg-on-primary hover:text-primary active:scale-[0.98]">
        Sign out
      </button>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 isolate hidden h-screen w-72 shrink-0 flex-col overflow-hidden bg-primary lg:flex">
      <AuroraBackground />
      <div className="relative z-10 shrink-0 px-7 pt-6 pb-7">
        <Wordmark href="/app" inverted />
      </div>
      <div className="relative z-10 min-h-0 flex-1 overflow-y-auto px-4 pb-3 [scrollbar-color:color-mix(in_srgb,var(--on-primary)_30%,transparent)_transparent] [scrollbar-width:thin]">
        <NavList />
      </div>
      <div className="relative z-10 shrink-0 px-7 pb-4">
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
      <div className="relative isolate flex h-16 items-center justify-between overflow-hidden bg-primary px-4">
        <AuroraBackground />
        <span className="relative z-10">
          <Wordmark href="/app" inverted />
        </span>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          className="relative z-10 h-11 rounded-button border border-on-primary/40 px-4 text-[1rem] text-on-primary transition-all duration-140 ease-out active:scale-95"
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>
      {open ? (
        <div id="mobile-nav" className="fixed inset-x-0 top-16 bottom-0 z-40 isolate overflow-y-auto bg-primary px-4 py-6 [scrollbar-color:color-mix(in_srgb,var(--on-primary)_30%,transparent)_transparent] [scrollbar-width:thin]">
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
