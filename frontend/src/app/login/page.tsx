"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthFrame } from "@/components/shell/AuthFrame";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";
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
      title="Welcome back"
      lede="Sign in to see how your money is doing."
      pointsTitle="After you sign in"
      points={[
        "Your portfolio and progress are waiting for you.",
        "Any trade you haven't approved yet expires after 15 minutes.",
        "Didn't finish your profile? We'll pick up where you left off.",
      ]}
    >
      <form onSubmit={submit} className="max-w-[36rem] space-y-5" noValidate>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password">
          {(p) => (
            <PasswordInput {...p} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
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
