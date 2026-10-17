import type { ReactNode } from "react";
import { Wordmark } from "./Wordmark";

/** Shared frame for sign-in and registration. Form on the left, context on the right. */
export function AuthFrame({ title, lede, children, aside }: { title: string; lede: ReactNode; children: ReactNode; aside: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-surface/40">
      <header className="border-b border-line bg-background">
        <div className="mx-auto flex h-16 max-w-[1280px] items-center px-5 sm:px-8">
          <Wordmark />
        </div>
      </header>
      <main className="mx-auto grid w-full max-w-[1280px] flex-1 items-start gap-12 px-5 py-12 sm:px-8 lg:grid-cols-12 lg:py-16">
        <div className="rounded-card border border-line bg-background p-7 shadow-[0_4px_20px_rgba(15,41,34,0.04)] lg:col-span-6">
          <h1 className="text-[26px] leading-tight font-bold tracking-tight text-ink">{title}</h1>
          <p className="mt-1.5 text-sm text-muted">{lede}</p>
          <div className="mt-7">{children}</div>
        </div>
        <aside className="rounded-card border border-line bg-background p-6 shadow-[0_2px_12px_rgba(15,41,34,0.03)] lg:col-span-5 lg:col-start-8">
          {aside}
        </aside>
      </main>
    </div>
  );
}

