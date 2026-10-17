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
      action={<ButtonLink href="/onboarding">Complete risk questionnaire</ButtonLink>}
    >
      Recommendations, trades and health reports are all tailored to your investor profile. Complete the interactive
      onboarding questionnaire to configure your financial parameters, risk tolerance, and investment goals. It takes under two minutes.
    </Empty>
  );
}
