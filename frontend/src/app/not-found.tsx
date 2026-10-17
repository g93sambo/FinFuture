import { ButtonLink } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1280px] px-5 py-10 sm:px-8">
      <Wordmark />
      <div className="mt-20 max-w-[48ch] rounded-card border border-line bg-background p-8 shadow-xs">
        <h1 className="text-[26px] font-bold tracking-tight text-ink">There is no page at this address</h1>
        <p className="mt-2 text-sm text-muted">The link may be out of date. Your account and portfolio are unaffected.</p>
        <div className="mt-7 flex gap-5">
          <ButtonLink href="/app">Go to your dashboard</ButtonLink>
          <ButtonLink href="/" variant="quiet">
            Home page
          </ButtonLink>
        </div>
      </div>
    </div>
  );
}

