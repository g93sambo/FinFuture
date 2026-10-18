import Link from "next/link";

/** Equify brand wordmark with rounded emblem. `compact` hides subtitle if needed. */
export function Wordmark({ href = "/", inverted = false }: { href?: string; inverted?: boolean; compact?: boolean }) {
  return (
    <Link href={href} className={`group inline-flex items-center gap-2.5 ${inverted ? "text-on-primary" : "text-ink"}`}>
      <span
        aria-hidden
        className={`grid h-7 w-7 place-items-center rounded-[8px] transition-transform duration-150 group-hover:scale-105 ${
          inverted ? "bg-on-primary text-primary" : "bg-primary text-on-primary"
        }`}
      >
        <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4">
          <path
            d="M4.5 13.5L8.5 9.5L11.5 12.5L15.5 6.5"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M12.5 6.5H15.5V9.5"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="text-[17px] font-bold tracking-tight">Equify</span>
    </Link>
  );
}

