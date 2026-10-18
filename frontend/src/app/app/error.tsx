"use client";

import { useEffect } from "react";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Layout";

export default function DashboardErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard route error:", error);
  }, [error]);

  const isNetworkIssue =
    error?.message?.toLowerCase().includes("failed to fetch") ||
    error?.message?.toLowerCase().includes("network") ||
    error?.message?.toLowerCase().includes("connect");

  return (
    <div className="space-y-6 max-w-3xl">
      <Panel title="Dashboard View Notice">
        <div className="space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full bg-warning-soft px-3 py-1 text-xs font-semibold text-warning">
            <span>Notice</span>
            <span>&bull;</span>
            <span>{isNetworkIssue ? "Connection Warming Up" : "Data Render Issue"}</span>
          </div>

          <h2 className="text-xl font-bold text-ink">
            {isNetworkIssue
              ? "Unable to reach the advisory intelligence engine"
              : "We could not display this section"}
          </h2>

          <p className="text-sm leading-relaxed text-muted">
            {isNetworkIssue
              ? "The wealth engine may be waking up after idle standby. Your holdings, orders, and cryptographic audit records remain safe and untouched."
              : "An unexpected error occurred while processing this view. Your account and portfolio remain secure."}
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button onClick={() => reset()}>
              Retry Loading
            </Button>
            <ButtonLink href="/app" variant="secondary">
              Return to Overview
            </ButtonLink>
            <ButtonLink href="/app/advisor" variant="quiet">
              Ask Advisor
            </ButtonLink>
          </div>
        </div>
      </Panel>
    </div>
  );
}
