import Link from "next/link";
import { ButtonLink } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";
import { AuroraBackground } from "@/components/landing/AuroraBackground";
import { FeatureCloud } from "@/components/landing/FeatureCloud";
import { RuleWall } from "@/components/landing/RuleWall";
import { RevealOnScroll } from "@/components/landing/Reveal";

const steps = [
  {
    title: "Profile",
    body: "Tell us about your goals, money and comfort with risk in a quick chat.",
  },
  {
    title: "Compare",
    body: "We compare real funds on cost and track record and drop any that are too risky for you.",
  },
  {
    title: "Allocate",
    body: "We build a mix of investments that suits you and explain why in plain words.",
  },
  {
    title: "Check",
    body: "Every suggestion passes our safety rules first. If it fails, you never see it.",
  },
  {
    title: "Approve",
    body: "Nothing is bought or sold until you say yes.",
  },
  {
    title: "Record",
    body: "Every decision is saved for good, so you can always check what happened.",
  },
];


export default function Landing() {
  return (
    <div className="min-h-screen">
      <RevealOnScroll />
      <header data-reveal="down" className="relative isolate overflow-hidden bg-primary text-on-primary">
        <AuroraBackground />
        <div className="relative z-10 mx-auto flex h-20 max-w-[110rem] items-center justify-between gap-4 px-5 sm:px-10 lg:px-16">
          <Wordmark compact inverted />
          <nav className="flex shrink-0 items-center gap-3 text-[1.0625rem] font-medium whitespace-nowrap sm:gap-7">
            <a href="#process" className="hidden text-on-primary/85 transition-colors hover:text-on-primary lg:inline">
              How it works
            </a>
            <a href="#safeguards" className="hidden text-on-primary/85 transition-colors hover:text-on-primary lg:inline">
              Safeguards
            </a>
            <Link href="/login" className="text-on-primary/85 transition-colors hover:text-on-primary">
              Sign in
            </Link>
            <Link
              href="/register"
              className="inline-flex h-10 items-center rounded-button bg-on-primary px-4 font-semibold text-primary shadow-[0_0_24px_color-mix(in_srgb,var(--on-primary)_30%,transparent)] transition-all duration-140 ease-out hover:bg-on-primary/90 active:scale-[0.97]"
            >
              <span className="sm:hidden">Open account</span>
              <span className="hidden sm:inline">Open an account</span>
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-[110rem] gap-12 px-6 py-10 sm:px-10 lg:grid-cols-12 lg:px-16 lg:py-14">
          <div className="lg:col-span-6 lg:pr-6">
            <h1 className="max-w-[13ch] text-[3.25rem] leading-[1.05] font-medium text-ink sm:text-[4.25rem] lg:text-[4.75rem]">
              {["Build", "Wealth", "With"].map((w, i) => (
                <span key={w} data-reveal="tilt" className="mr-[0.25em] inline-block" style={{ "--d": i + 1 } as React.CSSProperties}>
                  {w}
                </span>
              ))}
              <strong data-reveal="pop" className="inline-block font-bold" style={{ "--d": 4.5 } as React.CSSProperties}>
                Precision.
              </strong>
            </h1>
            <p data-reveal="up" style={{ "--d": 6 } as React.CSSProperties} className="mt-6 max-w-[60ch] text-[1.25rem] text-muted">
              FinFuture profiles you through conversation, compares real funds against your profile, builds an allocation
              and explains it. When you want to act, it drafts the order, checks it against twelve written rules, and
              places it in a paper-trading account only after you say yes.
            </p>
            <div data-reveal="up" style={{ "--d": 7 } as React.CSSProperties} className="mt-9 flex flex-wrap items-center gap-5">
              <ButtonLink href="/register">Start your risk profile</ButtonLink>
              <ButtonLink href="/login" variant="quiet">
                I already have an account
              </ButtonLink>
            </div>
          </div>
          <div data-reveal="zoom" style={{ "--d": 3 } as React.CSSProperties} className="lg:col-span-6 lg:pt-3">
            <FeatureCloud />
          </div>
          <dl className="-mx-6 flex snap-x snap-mandatory gap-5 overflow-x-auto scroll-px-6 px-6 py-4 [scrollbar-width:none] sm:-mx-10 sm:scroll-px-10 sm:px-10 lg:col-span-12 lg:mx-0 lg:grid lg:grid-cols-3 lg:gap-6 lg:overflow-visible lg:p-0">
            {[
              ["Understands you", "Learns your goals, income and comfort with risk."],
              ["Uses real facts", "Suggests investments from live market data, not hype."],
              ["You stay in control", "Nothing is bought or sold until you say yes."],
            ].map(([k, v], i) => (
              <div key={k} tabIndex={0} data-reveal="up" style={{ "--d": i } as React.CSSProperties} className="feature-bubble flex aspect-square w-[15rem] shrink-0 snap-start flex-col justify-center rounded-feature p-7 outline-none lg:block lg:aspect-auto lg:w-auto">
                <dt className="text-[1.1875rem] font-semibold whitespace-nowrap text-primary">{k}</dt>
                <dd className="mt-2 text-[1rem] leading-snug text-ink/80">{v}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* Full-width slogan strip: the SVG stretches the line to fill the strip edge to edge at any screen size. */}
        <section className="border-y border-line bg-primary-soft px-4 py-5 text-primary sm:px-6 lg:py-7">
          <h2 className="sr-only">Smart money moves around you.</h2>
          <svg data-reveal="sweep" viewBox="0 0 1000 80" className="block h-auto w-full" aria-hidden focusable="false">
            <text x="0" y="66" fontSize="80" textLength="1000" lengthAdjust="spacingAndGlyphs" fill="currentColor" fontWeight="500">
              Smart Money Moves Around <tspan fontWeight="700">You</tspan>.
            </text>
          </svg>
        </section>

        <section id="process" className="relative isolate overflow-hidden bg-primary text-on-primary">
          <AuroraBackground />
          <div className="relative z-10 mx-auto max-w-[110rem] px-6 py-14 sm:px-10 lg:px-16 lg:py-20">
            <div className="grid gap-10 xl:grid-cols-12">
              <div data-reveal="left" className="xl:col-span-4">
                <h2 className="text-[2.25rem] leading-tight font-semibold text-on-primary xl:text-[1.75rem] 2xl:text-[2.25rem]">How a recommendation reaches your account</h2>
                <p className="mt-4 max-w-[40ch] text-[1.125rem] text-on-primary/85">
                  Six simple steps. Any one of them can stop a bad idea before it reaches you.
                </p>
              </div>
              <ol className="border-t border-on-primary/60 xl:col-span-8">
                {steps.map((s, i) => (
                  <li key={s.title} data-reveal="right" style={{ "--d": i } as React.CSSProperties} className="grid grid-cols-[5.5rem_1fr] items-center gap-x-5 border-b border-on-primary/20 py-6 sm:grid-cols-[6.5rem_9rem_1fr]">
                    <span
                      aria-hidden
                      data-reveal="spin"
                      className="row-span-2 inline-block justify-self-center text-[3.5rem] leading-none font-bold text-on-primary sm:row-span-1 sm:text-[4.375rem]"
                      style={{ rotate: `${i % 2 === 0 ? 30 : -30}deg`, "--d": i + 2 } as React.CSSProperties}
                    >
                      {i + 1}
                    </span>
                    <h3 className="text-[1.25rem] font-semibold text-on-primary">{s.title}</h3>
                    <p className="col-start-2 mt-1 max-w-[60ch] text-[1.0625rem] text-on-primary/85 sm:col-start-3 sm:mt-0">{s.body}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        <section id="safeguards" className="overflow-hidden py-14 lg:py-20">
          <div className="mx-auto max-w-[110rem] px-6 sm:px-10 lg:px-16">
            <h2 data-reveal="up" className="text-[2.75rem] leading-[1.05] font-bold text-ink sm:text-[3.5rem]">
              Rules we <span data-reveal="pop" style={{ "--d": 3 } as React.CSSProperties} className="inline-block -rotate-3 bg-primary px-3 text-on-primary">never</span> break.
            </h2>
            <p data-reveal="up" style={{ "--d": 1 } as React.CSSProperties} className="mt-4 max-w-[44ch] text-[1.25rem] text-muted">Checked on every suggestion and every order. No exceptions.</p>
          </div>
          <div className="mt-12">
            <RuleWall />
          </div>
        </section>

        <section className="bg-primary">
          <div className="mx-auto flex max-w-[110rem] flex-wrap items-center justify-between gap-6 px-5 py-12 sm:px-8">
            <p data-reveal="left" className="max-w-[44ch] text-[1.375rem] leading-snug text-on-primary">
              Tell us where you are today, and we&apos;ll show you where your money could go. It only takes a few minutes.
            </p>
            <Link
              href="/register"
              data-reveal="pop"
              style={{ "--d": 2 } as React.CSSProperties}
              className="inline-flex h-12 items-center rounded-button bg-on-primary px-6 text-[1.0625rem] font-medium text-primary hover:bg-on-primary/90"
            >
              Start my profile
            </Link>
          </div>
        </section>
      </main>

      <footer data-reveal="up" className="border-t border-line">
        <div className="mx-auto grid max-w-[110rem] gap-6 px-5 py-10 text-[0.9375rem] text-muted sm:px-8 md:grid-cols-[1fr_2fr]">
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
