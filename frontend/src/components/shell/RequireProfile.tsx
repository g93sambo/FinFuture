"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { ButtonLink } from "../ui/Button";
import { Empty, Loading } from "../ui/Feedback";

/**
 * Most screens act on a client profile. Until the risk profiling conversation
 * is finished there is none, so these screens point the user to the Advisor.
 */
export function RequireProfile({ children }: { children: (clientId: string) => ReactNode }) {
  const { clientId, session, sessionError } = useAuth();
  if (clientId) return <>{children(clientId)}</>;
  if (!session && !sessionError) return <Loading label="Opening your advisory session" />;
  return (
    <Empty
      title="Your risk profile is not finished yet"
      action={<ButtonLink href="/app/advisor">Answer the profiling questions</ButtonLink>}
    >
      Recommendations, trades and reports are all tailored to your profile. The Advisor asks five short sets of questions
      about you, your finances, your time horizon, your attitude to risk and your experience. It takes about three minutes.
    </Empty>
  );
}
