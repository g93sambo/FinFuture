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

export default function RegisterPage() {
  const { register, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/onboarding");
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
      router.replace("/onboarding");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame
      title="Open your account"
      lede="Tell us where you are today. It only takes a few minutes."
      pointsTitle="Have these handy"
      points={[
        "Your age, job and who depends on you",
        "Roughly what you earn, save, spend and owe",
        "How long you plan to invest, and why",
        "How you'd feel if your money dropped 20%",
        "Your investing experience so far",
      ]}
    >
      <form onSubmit={submit} className="max-w-[36rem] space-y-5" noValidate>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password" hint="8 to 72 characters." error={pwError}>
          {(p) => (
            <PasswordInput {...p} autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <Field label="Confirm password" error={confirmError}>
          {(p) => (
            <PasswordInput {...p} autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
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
