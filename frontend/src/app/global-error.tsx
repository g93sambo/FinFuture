"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Global system error:", error);
  }, [error]);

  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-[#FFFFFF] p-6 font-sans text-[#0E1B16]">
        <div className="max-w-[50ch] rounded-2xl border border-[#E6ECE9] bg-[#FFFFFF] p-8 shadow-sm">
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-[#FEF5E7] px-3 py-1 text-xs font-semibold text-[#B86E00]">
            <span>System Notice</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0E1B16]">
            Application Temporarily Unavailable
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-[#76847D]">
            We encountered a temporary initialization error while rendering this page. Your financial data and credentials remain fully protected.
          </p>
          <div className="mt-6 flex gap-3">
            <button
              type="button"
              onClick={() => reset()}
              className="rounded-lg bg-[#0F2922] px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-[#163B31] transition-colors"
            >
              Reload View
            </button>
            <a
              href="/app"
              className="rounded-lg border border-[#E6ECE9] bg-[#F7F9F8] px-4 py-2 text-xs font-semibold text-[#0E1B16] hover:bg-[#EEF3F0] transition-colors"
            >
              Dashboard
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
