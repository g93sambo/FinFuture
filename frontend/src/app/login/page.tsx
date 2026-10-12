"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthFrame } from "@/components/shell/AuthFrame";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/app");
  }, [status, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace("/app");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame
      title="Sign in"
      lede="Use the email and password you registered with."
      aside={
        <div className="text-sm">
          <p className="font-semibold text-ink">After you sign in</p>
          <ul className="mt-3 divide-y divide-line border-y border-line text-muted">
            <li className="py-2.5">Your portfolio, health review and audit trail open on the Overview.</li>
            <li className="py-2.5">Pending trade proposals expire fifteen minutes after they are drafted.</li>
            <li className="py-2.5">If your profile is unfinished, the Advisor picks up the questions.</li>
          </ul>
        </div>
      }
    >
      <form onSubmit={submit} className="max-w-[400px] space-y-5" noValidate>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password">
          {(p) => (
            <Input {...p} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <div className="flex items-center gap-5 pt-2">
          <Button type="submit" pending={pending} disabled={!email || !password}>
            Sign in
          </Button>
          <Link href="/register" className="text-sm text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary">
            Create an account
          </Link>
        </div>
      </form>
    </AuthFrame>
  );
}
