/**
 * Sign-in.
 *
 * This page does three jobs that are worth keeping separate, because they are
 * different states rather than different screens:
 *
 *   live   a real credential exchange against Supabase
 *   demo   no credential exists, and the page says why rather than showing a
 *          form that cannot work
 *   broken the API did not answer — a retry, not a password field
 *
 * The failure this page is most careful about: in a demo deployment there is no
 * account and no password, so showing a sign-in form would invite an operator
 * to type a real credential into a system that has nowhere to put it. In demo
 * mode the form is replaced by an explanation.
 *
 * The other one: `POST /auth/signup` returns **no token**. It answers
 * `{user_id, email, session, confirmation_required}` where `session` is a
 * *boolean*. A successful registration therefore does not sign anyone in, and
 * this page never pretends otherwise — it asks the operator to sign in
 * separately, which is the truth about the flow.
 */

import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowRight, Info, KeyRound, Radar, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorPanel, LoadingBlock } from "@/components/common";
import { useAuth } from "@/hooks/use-auth";

/** The two mutually exclusive forms, kept as a mode rather than two components. */
const MODES = { signIn: "sign-in", signUp: "sign-up" };

/** Email shape, checked before a request is spent on it. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function Field({ id, label, type, value, onChange, autoComplete, placeholder, disabled, hint }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={value ? !EMAIL_RE.test(value) && id === "email" : undefined}
        required
      />
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { status, loading, login, signUp, refreshStatus } = useAuth();

  const [mode, setMode] = useState(MODES.signIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // A bookmarked investigation survives the round trip through this page.
  const destination = location.state?.from || "/app";

  // The capability answer is authoritative about whether a form is even
  // meaningful, so the form follows it rather than the other way round.
  useEffect(() => {
    if (!status) return;
    setError(null);
    if (status.mode === "demo") setMode(MODES.signIn);
    else if (!status.signup_enabled && mode === MODES.signUp) setMode(MODES.signIn);
  }, [status, mode]);

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setNotice(null);

    // Checked here so an obviously malformed address is reported without a
    // round trip. The server checks it again — this is a courtesy, not the
    // validation.
    if (!EMAIL_RE.test(email)) {
      setError({ kind: "invalid_input", detail: "Enter an email address in the form name@example.org." });
      return;
    }
    if (password.length < 8) {
      setError({
        kind: "invalid_input",
        detail: "Passwords are at least 8 characters. Nothing has been sent to the server.",
      });
      return;
    }

    setBusy(true);
    try {
      if (mode === MODES.signUp) {
        const result = await signUp(email, password);
        // `session` here is a boolean, not a session object. There is no token
        // to store, so the operator signs in on the next screen.
        if (result?.confirmation_required) {
          setNotice(
            `Account created for ${result.email}. Confirm the address from the email ` +
              "the backend sent, then sign in here.",
          );
          setMode(MODES.signIn);
          setPassword("");
          toast.success("Account created — confirm your email, then sign in.");
        } else {
          setNotice(
            `Account created for ${result.email}. Registration does not sign you in; ` +
              "use the form above to sign in.",
          );
          setMode(MODES.signIn);
          setPassword("");
          toast.success("Account created. Sign in to continue.");
        }
        return;
      }

      await login(email, password);
      toast.success("Signed in.");
      navigate(destination, { replace: true });
    } catch (err) {
      // 401 and 503 arrive from the same endpoint with the same shape, so the
      // `kind` is what tells the operator whether to retype or to call an
      // administrator. Both are preserved.
      setError({ kind: err.kind, detail: err.message, status: err.status });
      toast.error(
        err.kind === "unavailable"
          ? "The authentication service is not available."
          : "Sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading && !status) {
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <div className="w-full max-w-md">
          <LoadingBlock label="Checking this deployment's access mode" />
        </div>
      </div>
    );
  }

  // Reachable, but the capability check failed. The guard normally catches
  // this first; reaching here means the backend went away while the page was
  // open, and the honest response is a retry rather than a form.
  if (!status) {
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <CardTitle>The BlockTrace API is not responding</CardTitle>
            <CardDescription>
              No credential has been checked. BlockTrace cannot tell whether this
              deployment requires sign-in, so it will not ask for one.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ErrorPanel
              error={{
                kind: "unavailable",
                detail: "No response from the API. Start the backend, then try again.",
              }}
            />
            <Button onClick={() => refreshStatus()}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // -- demo ---------------------------------------------------------------
  // Deliberately not a form. There is no credential to ask for, and asking for
  // one here would collect a real password for a system that cannot check it.
  if (status.demo_mode) {
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <div className="mb-1 flex items-center gap-2">
              <Radar className="size-5 text-primary" aria-hidden="true" />
              <CardTitle>BlockTrace is running in demo mode</CardTitle>
            </div>
            <CardDescription className="leading-6">
              There is no account to sign in to, and there is nothing to sign in
              *with*.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <div>
                  <p className="font-medium">Cases are not isolated here.</p>
                  <p className="mt-1">
                    Every operator of this deployment sees the same investigations,
                    and they are stored in a {status.supabase_configured ? "shared" : "local"} store rather
                    than per account. Treat anything you type as visible to others.
                  </p>
                </div>
              </div>
            </div>

            <dl className="space-y-2 text-sm">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">Supabase</dt>
                <dd>
                  <Badge variant={status.supabase_configured ? "secondary" : "outline"}>
                    {status.supabase_configured ? "configured" : "not configured"}
                  </Badge>
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">Registration</dt>
                <dd>
                  <Badge variant="outline">disabled</Badge>
                </dd>
              </div>
            </dl>

            <p className="text-xs leading-5 text-muted-foreground">{status.note}</p>
          </CardContent>
          <CardFooter>
            <Button className="w-full" render={<Link to="/app" />}>
              Open the console
              <ArrowRight data-icon="inline-end" />
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // -- live ---------------------------------------------------------------
  const isSignUp = mode === MODES.signUp;

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-5 py-12">
        <Link to="/" className="mb-8 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <Radar className="size-4" aria-hidden="true" />
          BlockTrace
        </Link>

        <Card>
          <CardHeader>
            <CardTitle>{isSignUp ? "Create an account" : "Sign in"}</CardTitle>
            <CardDescription>
              {isSignUp
                ? "Registration is enabled on this deployment. Your password is sent to the backend and stored by Supabase — it is never held in this browser."
                : "Case data on this deployment is isolated per account."}
            </CardDescription>
          </CardHeader>

          <CardContent>
            {notice ? (
              <div className="mb-4 flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs leading-5 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
                <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span>{notice}</span>
              </div>
            ) : null}

            {error ? (
              <div className="mb-4">
                <ErrorPanel error={error} />
              </div>
            ) : null}

            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <Field
                id="email"
                label="Email"
                type="email"
                autoComplete="username"
                placeholder="name@example.org"
                value={email}
                onChange={setEmail}
                disabled={busy}
              />
              <Field
                id="password"
                label="Password"
                type="password"
                autoComplete={isSignUp ? "new-password" : "current-password"}
                placeholder="At least 8 characters"
                value={password}
                onChange={setPassword}
                disabled={busy}
                hint={isSignUp ? "Eight characters minimum. There is no reset flow in this build." : undefined}
              />

              <Button type="submit" className="w-full" size="lg" disabled={busy}>
                {busy ? (
                  "Working…"
                ) : isSignUp ? (
                  <>
                    <KeyRound data-icon="inline-start" />
                    Create account
                  </>
                ) : (
                  "Sign in"
                )}
              </Button>
            </form>
          </CardContent>

          <CardFooter className="flex-col items-stretch gap-3">
            {status.signup_enabled ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => {
                  setMode(isSignUp ? MODES.signIn : MODES.signUp);
                  setError(null);
                  setNotice(null);
                }}
              >
                {isSignUp ? "I already have an account" : "Create an account"}
              </Button>
            ) : null}

            <p className="flex items-start gap-1.5 text-[11px] leading-4 text-muted-foreground">
              <ShieldCheck className="mt-px size-3 shrink-0" aria-hidden="true" />
              <span>
                This browser holds only your own session token, in{" "}
                <span className="font-mono">localStorage</span>. No API key, and
                no database service-role key, is ever sent to the client.
              </span>
            </p>
          </CardFooter>
        </Card>

        {status.note ? (
          <p className="mt-4 text-center text-[11px] leading-5 text-muted-foreground">
            {status.note}
          </p>
        ) : null}
      </div>
    </div>
  );
}
