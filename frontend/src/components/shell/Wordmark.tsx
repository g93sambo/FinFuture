import Link from "next/link";

/** Text wordmark. A square glyph built from two rules, no illustration. */
export function Wordmark({ href = "/", inverted = false }: { href?: string; inverted?: boolean }) {
  return (
    <Link href={href} className={`group inline-flex items-center gap-2.5 ${inverted ? "text-on-primary" : "text-primary"}`}>
      <span aria-hidden className={`grid h-6 w-6 place-items-center border-2 ${inverted ? "border-on-primary" : "border-primary"}`}>
        <span className={`block h-2.5 w-0.5 ${inverted ? "bg-on-primary" : "bg-primary"}`} />
      </span>
      <span className="text-[17px] font-semibold tracking-normal">
        FinFuture<span className={`font-normal ${inverted ? "text-on-primary/75" : "text-muted"}`}> Advisory</span>
      </span>
    </Link>
  );
}
