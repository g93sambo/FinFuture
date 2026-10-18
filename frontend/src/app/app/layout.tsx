"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { MobileBar, Sidebar } from "@/components/shell/Sidebar";
import { Loading, Notice } from "@/components/ui/Feedback";
import { useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { status, ensureSession, sessionError } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") {
      const target = pathname && pathname !== "/app" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${target}`);
    }
    if (status === "authenticated") void ensureSession();
  }, [status, router, ensureSession, pathname]);

  if (status !== "authenticated") {
    return (
      <div className="mx-auto max-w-5xl px-6">
        <Loading label="Checking your sign-in" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar />
      <MobileBar />
      <main id="main" className="min-w-0 flex-1 px-5 py-8 sm:px-8 lg:px-12 lg:py-10">
        <div className="mx-auto max-w-[110rem]">
          {sessionError ? (
            <Notice tone="danger" title="Could not open an advisory session" className="mb-6">
              {sessionError}
            </Notice>
          ) : null}
          {children}
        </div>
      </main>
    </div>
  );
}

