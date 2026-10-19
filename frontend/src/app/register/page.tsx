"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthFrame } from "@/components/shell/AuthFrame";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { useAuth } from "@/lib/auth";

/** Mirrors password_problem() in backend/api/routes/auth.py; the server also rejects common passwords. */
function passwordProblem(password: string, email: string): string | null {
  if (password.length < 10) return "Use at least 10 characters.";
  if (password.length > 72) return "Use 72 characters or fewer.";
  if (!/[a-z]/i.test(password) || !/\d/.test(password)) return "Include at least one letter and one number.";
  if (new Set(password.toLowerCase()).size < 4) return "Use a less repetitive password.";
  const name = email.split("@")[0]?.toLowerCase() ?? "";
  if (name.length >= 4 && password.toLowerCase().includes(name)) return "Don't include your email name in the password.";
  return null;
}

function RegisterForm() {
  const { register, status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams?.get("next");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/onboarding");
  }, [status, router]);

  const pwError = password ? passwordProblem(password, email) : null;
  const confirmError = confirm && confirm !== password ? "The two passwords do not match." : null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pwError || confirmError) return;
    setPending(true);
    setError(null);
    try {
      if (fullName.trim() && typeof window !== "undefined") {
        localStorage.setItem("finfuture.user_name", fullName.trim());
      }
      await register(email.trim(), password);
      router.replace("/onboarding");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-[36rem] space-y-5" noValidate>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <Field label="Your Name (Optional)" hint="How your AI wealth advisor should address you.">
        {(p) => <Input {...p} type="text" placeholder="e.g. Hillary" value={fullName} onChange={(e) => setFullName(e.target.value)} />}
      </Field>
      <Field label="Email">
        {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
      </Field>
      <Field label="Password" hint="At least 10 characters, with a letter and a number. Avoid common passwords." error={pwError}>
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
        <Link
          href={nextParam ? `/login?next=${encodeURIComponent(nextParam)}` : "/login"}
          className="text-sm text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary"
        >
          Sign in instead
        </Link>
      </div>
    </form>
  );
}

export default function RegisterPage() {
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
      <Suspense fallback={<div className="h-48 flex items-center justify-center text-muted text-sm">Loading...</div>}>
        <RegisterForm />
      </Suspense>
    </AuthFrame>
  );
}
