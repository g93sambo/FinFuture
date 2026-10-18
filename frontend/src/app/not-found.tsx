import { ButtonLink } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[110rem] px-5 py-10 sm:px-8">
      <Wordmark />
      <div className="mt-24 max-w-[48ch] rounded-card border border-line bg-background p-8 shadow-xs">
        <h1 className="text-[2.125rem] font-semibold tracking-tight text-ink">There is no page at this address</h1>
        <p className="mt-2 text-muted">The link may be out of date. Your account and portfolio are unaffected.</p>
        <div className="mt-8 flex gap-5">
          <ButtonLink href="/app">Go to your overview</ButtonLink>
          <ButtonLink href="/" variant="quiet">
            Home page
          </ButtonLink>
        </div>
      </div>
    </div>
  );
}

