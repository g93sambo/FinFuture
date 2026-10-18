import Link from "next/link";

/** Text wordmark. `compact` hides "Advisory" below tablet width. */
export function Wordmark({ href = "/", inverted = false, compact = false }: { href?: string; inverted?: boolean; compact?: boolean }) {
  return (
    <Link href={href} className={`inline-flex shrink-0 items-center whitespace-nowrap ${inverted ? "text-on-primary" : "text-primary"}`}>
      <span className="text-[1.3125rem] font-semibold tracking-normal">
        FinFuture<span className={`font-normal ${compact ? "hidden sm:inline" : ""} ${inverted ? "text-on-primary/75" : "text-muted"}`}> Advisory</span>
      </span>
    </Link>
  );
}
