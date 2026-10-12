import type { ReactNode } from "react";
import { Wordmark } from "./Wordmark";

/** Shared frame for sign-in and registration. Form on the left, context on the right. */
export function AuthFrame({ title, lede, children, aside }: { title: string; lede: ReactNode; children: ReactNode; aside: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center px-5 sm:px-8">
          <Wordmark />
        </div>
      </header>
      <main className="mx-auto grid w-full max-w-[1180px] flex-1 gap-12 px-5 py-14 sm:px-8 lg:grid-cols-12 lg:py-20">
        <div className="lg:col-span-5">
          <h1 className="text-[28px] leading-tight font-semibold text-ink">{title}</h1>
          <p className="mt-2 text-muted">{lede}</p>
          <div className="mt-8">{children}</div>
        </div>
        <aside className="border-t border-ink pt-6 lg:col-span-5 lg:col-start-8 lg:mt-1">{aside}</aside>
      </main>
    </div>
  );
}
