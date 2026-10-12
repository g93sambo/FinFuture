"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthFrame } from "@/components/shell/AuthFrame";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/app/advisor");
  }, [status, router]);

  const pwError = password && password.length < 8 ? "Use at least 8 characters." : password.length > 72 ? "Use 72 characters or fewer." : null;
  const confirmError = confirm && confirm !== password ? "The two passwords do not match." : null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pwError || confirmError) return;
    setPending(true);
    setError(null);
    try {
      await register(email.trim(), password);
      router.replace("/app/advisor");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame
      title="Open an account"
      lede="A paper-trading account with $100,000 of simulated cash."
      aside={
        <div className="text-sm">
          <p className="font-semibold text-ink">Have these to hand for profiling</p>
          <ol className="mt-3 divide-y divide-line border-y border-line text-muted">
            {[
              "Age, employment status and number of dependents",
              "Approximate annual income, savings, monthly costs and debts",
              "How many years you plan to invest for, and why",
              "A risk rating from 1 to 10, and what you would do after a 20% fall",
              "Your investing experience and where the money comes from",
            ].map((t, i) => (
              <li key={t} className="grid grid-cols-[1.75rem_1fr] py-2.5">
                <span className="figures">{i + 1}</span>
                <span>{t}</span>
              </li>
            ))}
          </ol>
        </div>
      }
    >
      <form onSubmit={submit} className="max-w-[400px] space-y-5" noValidate>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password" hint="8 to 72 characters." error={pwError}>
          {(p) => (
            <Input {...p} type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <Field label="Confirm password" error={confirmError}>
          {(p) => (
            <Input {...p} type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          )}
        </Field>
        <div className="flex items-center gap-5 pt-2">
          <Button type="submit" pending={pending} disabled={!email || !password || !confirm || !!pwError || !!confirmError}>
            Create account
          </Button>
          <Link href="/login" className="text-sm text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary">
            Sign in instead
          </Link>
        </div>
      </form>
    </AuthFrame>
  );
}
