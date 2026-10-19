"use client";

import { useEffect } from "react";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log unexpected client error to monitoring telemetry
    console.error("Application error caught by boundary:", error);
  }, [error]);

  const friendlyMessage = error?.message?.includes("fetch") || error?.message?.includes("network")
    ? "Our advisory engine took longer than expected to respond. The system may be warming up after a period of inactivity."
    : "We encountered an unexpected display issue. Your account balances, active orders, and cryptographic audit records remain safe and unaffected.";

  return (
    <div className="mx-auto flex min-h-screen max-w-[110rem] flex-col justify-between px-5 py-10 sm:px-8">
      <div>
        <Wordmark />
        <div className="mt-20 max-w-[54ch] rounded-card border border-line bg-background p-8 shadow-xs">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-warning-soft px-3 py-1 text-xs font-semibold text-warning">
            <span>Notice</span>
            <span>&bull;</span>
            <span>Temporary Glitch</span>
          </div>
          <h1 className="text-[2rem] font-bold tracking-tight text-ink sm:text-[2.25rem]">
            Something didn&apos;t load as expected
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted sm:text-base">
            {friendlyMessage}
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button onClick={() => reset()}>
              Try Again
            </Button>
            <ButtonLink href="/app" variant="secondary">
              Go to Dashboard
            </ButtonLink>
            <ButtonLink href="/" variant="quiet">
              Home
            </ButtonLink>
          </div>
        </div>
      </div>

      <footer className="mt-12 border-t border-line pt-6 text-xs text-muted">
        FinFuture &bull; Every action is recorded in a signed, append-only audit trail.
      </footer>
    </div>
  );
}
