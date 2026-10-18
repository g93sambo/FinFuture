import { humanize } from "@/lib/format";
import { Tag } from "../ui/Feedback";

const names: Record<string, string> = {
  loss_aversion: "Loss aversion",
  recency_bias: "Recency bias",
  overconfidence: "Overconfidence",
  herd_mentality: "Following the crowd",
  disposition_effect: "Disposition effect",
};

/** A behavioural nudge. Amber, not red: it informs, it does not block. */
export function BiasAlert({
  biasType,
  severity,
  confidence,
  text,
  coolOff,
}: {
  biasType?: string;
  severity?: string;
  confidence?: number;
  text?: string;
  coolOff?: boolean;
}) {
  return (
    <div className="border border-warning/35 bg-warning-soft px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-warning">{names[biasType ?? ""] ?? humanize(biasType)}</p>
        {severity ? <Tag tone="warning">{humanize(severity)} signal</Tag> : null}
        {typeof confidence === "number" ? <span className="figures text-[0.9375rem] text-muted">confidence {Math.round(confidence * 100)}%</span> : null}
      </div>
      {text ? <p className="mt-1.5 max-w-[68ch] text-sm text-ink">{text}</p> : null}
      {coolOff ? <p className="mt-2 text-[0.9375rem] font-medium text-ink">Suggested: wait 24 hours before acting on this.</p> : null}
    </div>
  );
}
