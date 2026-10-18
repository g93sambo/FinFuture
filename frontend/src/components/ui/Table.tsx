import type { ComponentProps, ReactNode } from "react";

/** Horizontally scrollable, ruled table. Header row sits on a hairline, no zebra stripes. */
export function Table({ children, caption, className = "" }: { children: ReactNode; caption?: string; className?: string }) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full border-collapse text-left text-[1rem]">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function Th({ numeric, className = "", ...rest }: ComponentProps<"th"> & { numeric?: boolean }) {
  return (
    <th
      scope="col"
      className={`border-b border-ink/70 px-4 py-3 text-[0.9375rem] font-medium whitespace-nowrap text-muted first:pl-5 last:pr-5 ${numeric ? "text-right" : ""} ${className}`}
      {...rest}
    />
  );
}

export function Td({ numeric, className = "", ...rest }: ComponentProps<"td"> & { numeric?: boolean }) {
  return (
    <td
      className={`border-b border-line px-4 py-3 align-top text-ink first:pl-5 last:pr-5 ${numeric ? "figures text-right whitespace-nowrap" : ""} ${className}`}
      {...rest}
    />
  );
}

export function Tr({ className = "", ...rest }: ComponentProps<"tr">) {
  return <tr className={`hover:bg-surface ${className}`} {...rest} />;
}
