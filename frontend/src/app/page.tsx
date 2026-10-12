import Link from "next/link";
import { ButtonLink } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";

const steps = [
  {
    title: "Profile",
    body: "A short conversation records your age, finances, time horizon, tolerance for loss and experience. It produces a suitability tier, an emotional risk score and a KYC result.",
  },
  {
    title: "Compare",
    body: "Funds you name are scored on cost, tracking error, liquidity, size, one-year return and manager. Anything above your risk tier is set aside with the reason stated.",
  },
  {
    title: "Allocate",
    body: "A CVaR optimiser builds the portfolio within limits set by your profile, then explains which holdings carry the risk and why.",
  },
  {
    title: "Check",
    body: "The recommendation is tested against suitability, concentration and disclosure rules. A failed rule stops it from reaching you.",
  },
  {
    title: "Approve",
    body: "A trade is only a proposal until you approve it. Approvals expire after fifteen minutes and a second submission within thirty seconds is refused.",
  },
  {
    title: "Record",
    body: "Every decision is written to a hash-chained, signed audit log that you can verify yourself and anchor to a public test network.",
  },
];

const rules = [
  ["SUIT-001", "Recommended risk may not exceed your tolerance by more than one point."],
  ["SUIT-002", "Horizons under three years cap equities at 40% and bond duration at seven years."],
  ["SUIT-003", "Low capacity for loss caps risk at moderate and equities at half the portfolio."],
  ["CONC-001", "No single stock above 15% of the portfolio."],
  ["CONC-002", "No single sector above 30%."],
  ["CONC-003", "At least two asset classes above 5%. A warning, not a block."],
  ["REG-001", "No promise or suggestion of guaranteed returns."],
  ["REG-002", "Every recommendation carries a risk disclosure."],
  ["REG-003", "No order without your explicit approval."],
  ["REG-004", "Approvals older than fifteen minutes are void."],
  ["AML-001", "Orders above $100,000 need enhanced checks."],
  ["AML-002", "More than five orders in ten minutes are blocked."],
];

function ExampleTicket() {
  const checks = [
    ["REG-003", "Your approval recorded"],
    ["REG-004", "Approval 42 seconds old"],
    ["CONC-001", "BND would be 0.7% of portfolio"],
    ["AML-001", "Notional under $100,000"],
  ];
  return (
    <figure className="border border-ink bg-background">
      <figcaption className="flex items-baseline justify-between border-b border-ink px-5 py-3">
        <span className="text-sm font-semibold">Trade proposal</span>
        <span className="text-[13px] text-muted">Example</span>
      </figcaption>
      <dl className="divide-y divide-line px-5">
        {[
          ["Instruction", "Buy 10 BND"],
          ["Estimated price", "$72.40"],
          ["Notional", "$724.00"],
          ["Expires", "in 14 min"],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between py-2.5 text-sm">
            <dt className="text-muted">{k}</dt>
            <dd className="figures">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="border-t border-line bg-surface px-5 py-4">
        <p className="mb-2 text-[13px] font-medium text-muted">Pre-trade checks</p>
        <ul className="space-y-1.5 text-sm">
          {checks.map(([id, text]) => (
            <li key={id} className="grid grid-cols-[5.5rem_1fr_auto] gap-2">
              <span className="figures text-muted">{id}</span>
              <span>{text}</span>
              <span className="font-medium text-success">Pass</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex gap-3 border-t border-line px-5 py-4" aria-hidden>
        <span className="inline-flex h-9 items-center bg-primary px-4 text-sm font-medium text-on-primary">Approve</span>
        <span className="inline-flex h-9 items-center border border-ink/25 px-4 text-sm font-medium">Cancel</span>
      </div>
    </figure>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between px-5 sm:px-8">
          <Wordmark />
          <nav className="flex items-center gap-6 text-sm">
            <a href="#process" className="hidden text-ink hover:text-primary sm:inline">
              How it works
            </a>
            <a href="#safeguards" className="hidden text-ink hover:text-primary sm:inline">
              Safeguards
            </a>
            <Link href="/login" className="text-ink hover:text-primary">
              Sign in
            </Link>
            <ButtonLink href="/register" size="sm">
              Open an account
            </ButtonLink>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-[1180px] gap-12 px-5 py-16 sm:px-8 lg:grid-cols-12 lg:py-24">
          <div className="lg:col-span-7 lg:pr-8">
            <h1 className="max-w-[18ch] text-[34px] leading-[1.15] font-semibold text-ink sm:text-[42px]">
              Investment advice that shows its working and waits for your approval.
            </h1>
            <p className="mt-6 max-w-[56ch] text-[17px] text-muted">
              FinFuture profiles you through conversation, compares real funds against your profile, builds an allocation
              and explains it. When you want to act, it drafts the order, checks it against twelve written rules, and
              places it in a paper-trading account only after you say yes.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-5">
              <ButtonLink href="/register">Start your risk profile</ButtonLink>
              <ButtonLink href="/login" variant="quiet">
                I already have an account
              </ButtonLink>
            </div>
            <dl className="mt-14 grid max-w-[560px] grid-cols-1 border-t border-ink text-sm sm:grid-cols-3">
              {[
                ["Account type", "Paper trading"],
                ["Rules applied", "Before every output"],
                ["Audit log", "Hash chained, signed"],
              ].map(([k, v], i) => (
                <div key={k} className={`py-3 ${i > 0 ? "sm:border-l sm:border-line sm:pl-4" : ""}`}>
                  <dt className="text-muted">{k}</dt>
                  <dd className="mt-0.5 font-medium text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="lg:col-span-5 lg:pt-3">
            <ExampleTicket />
          </div>
        </section>

        <section id="process" className="border-t border-line bg-surface">
          <div className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <div className="grid gap-10 lg:grid-cols-12">
              <div className="lg:col-span-4">
                <h2 className="text-[26px] leading-tight font-semibold text-ink">How a recommendation reaches your account</h2>
                <p className="mt-4 max-w-[40ch] text-muted">
                  Six stages, in this order. Each one can stop the process and tell you why.
                </p>
              </div>
              <ol className="border-t border-ink lg:col-span-8">
                {steps.map((s, i) => (
                  <li key={s.title} className="grid grid-cols-[2.5rem_1fr] gap-x-4 border-b border-line py-5 sm:grid-cols-[2.5rem_9rem_1fr]">
                    <span className="figures text-sm text-muted">{String(i + 1).padStart(2, "0")}</span>
                    <h3 className="font-semibold text-ink">{s.title}</h3>
                    <p className="col-start-2 mt-1 max-w-[60ch] text-[15px] text-muted sm:col-start-3 sm:mt-0">{s.body}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        <section id="safeguards" className="mx-auto max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
          <div className="grid gap-10 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <h2 className="text-[26px] leading-tight font-semibold text-ink">The rules it works within</h2>
              <p className="mt-4 max-w-[40ch] text-muted">
                These run on every recommendation and every order. The full catalogue, with thresholds, is visible inside
                the app.
              </p>
              <div className="mt-8 border-l-2 border-primary pl-4 text-sm text-ink">
                <p className="font-semibold">What it will not do</p>
                <ul className="mt-2 space-y-1 text-muted">
                  <li>Trade without your approval.</li>
                  <li>Touch real money. This is a paper account.</li>
                  <li>Promise a return.</li>
                </ul>
              </div>
            </div>
            <div className="lg:col-span-8">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">Compliance rules</caption>
                <thead>
                  <tr>
                    <th scope="col" className="w-28 border-b border-ink py-2.5 text-left font-medium text-muted">
                      Rule
                    </th>
                    <th scope="col" className="border-b border-ink py-2.5 text-left font-medium text-muted">
                      Requirement
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map(([id, text]) => (
                    <tr key={id}>
                      <td className="figures border-b border-line py-3 align-top text-primary">{id}</td>
                      <td className="border-b border-line py-3 text-ink">{text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="bg-primary">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-6 px-5 py-12 sm:px-8">
            <p className="max-w-[44ch] text-[20px] leading-snug text-on-primary">
              Profiling takes about three minutes. You can stop at any point and nothing is traded until you approve it.
            </p>
            <Link
              href="/register"
              className="inline-flex h-10 items-center bg-on-primary px-5 text-sm font-medium text-primary hover:bg-on-primary/90"
            >
              Open an account
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto grid max-w-[1180px] gap-6 px-5 py-10 text-[13px] text-muted sm:px-8 md:grid-cols-[1fr_2fr]">
          <p>FinFuture Advisory. Built for the PBCSF Financial Participant track.</p>
          <p className="max-w-[80ch]">
            Investing involves risk, including possible loss of principal. Past performance is no guarantee of future
            results. Orders are placed in a simulated paper-trading account and do not involve real funds. Nothing on this
            site is an offer to buy or sell a security.
          </p>
        </div>
      </footer>
    </div>
  );
}
