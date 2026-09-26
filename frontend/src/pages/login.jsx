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
import {
  AlertTriangle,
  ArrowRight,
  Info,
  KeyRound,
  Loader2,
  Radar,
  ShieldCheck,
} from "lucide-react";
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

/**
 * Google's four-colour mark, drawn inline.
 *
 * Inline rather than an image or an icon package: it is the only third-party
 * brand in the product, it is four paths, and adding a dependency or an asset
 * for it would be a worse trade than twenty lines of SVG. The colours are
 * Google's own, and unlike the rest of this interface they cannot come from
 * the theme, because a brand mark that changes colour with the theme stops
 * being that brand's mark.
 */
function GoogleMark() {
  return (
    <svg
      className="size-4 shrink-0"
      viewBox="0 0 24 24"
      role="img"
      aria-label="Google"
    >
      <path
        fill="#4285F4"
        d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.54 5.54 0 0 1-2.4 3.63v3.02h3.86c2.26-2.09 3.56-5.17 3.56-8.89Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3.02c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.28v3.13A11.99 11.99 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.27A7.2 7.2 0 0 1 4.9 12c0-.79.14-1.55.37-2.27V6.6H1.28A11.99 11.99 0 0 0 0 12c0 1.94.47 3.77 1.28 5.4l3.99-3.13Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.77c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0A11.99 11.99 0 0 0 1.28 6.6l3.99 3.13C6.22 6.88 8.87 4.77 12 4.77Z"
      />
    </svg>
  );
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { status, loading, login, signUp, signInWithGoogle, refreshStatus } = useAuth();

  const [mode, setMode] = useState(MODES.signIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  /*
   * Where a successful sign-in lands.
   *
   * The trace console, not the dashboard. Someone who just authenticated has
   * not come to read a dashboard -- they came to do the thing they needed an
   * account to do, which is trace a wallet. The dashboard is a place to end up,
   * not a place to be sent.
   *
   * A bookmarked investigation still wins: `location.state.from` is set by the
   * route guard, so being bounced off a deep link and signing in returns you to
   * the case you were reading rather than discarding it.
   */
  const destination = location.state?.from || "/app/trace";

  /**
   * Google sign-in.
   *
   * Google is the faster path for an investigator who already has an account,
   * and it is the only path that does not ask this system to handle a password
   * at all. Each failure gets its own message, because they are not the same
   * problem: "not configured" is an operator's to fix, "cancelled" is the user's
   * own doing and needs no error styling at all.
   */
  async function onGoogle() {
    if (googleBusy) return;
    setGoogleBusy(true);
    setError(null);
    try {
      const result = await signInWithGoogle();
      if (result.ok) return; // the page is navigating away
      if (result.reason === "cancelled") {
        setGoogleBusy(false);
        return;
      }
      if (result.reason === "not_configured") {
        setError({
          kind: "unavailable",
          detail:
            "Google sign-in is not configured on this deployment. It needs " +
            "VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY, and a Google provider " +
            "enabled on that Supabase project. Use the form below, or open the app " +
            "directly if it is running in demo mode.",
        });
      } else {
        setError({ kind: "unavailable", detail: result.detail });
      }
    } catch (exc) {
      setError({
        kind: "unavailable",
        detail: exc?.message || "Google sign-in could not be started.",
      });
    } finally {
      setGoogleBusy(false);
    }
  }

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
          {/* The mark, swapped by theme. See app-sidebar.jsx for why there are
              two files rather than one filtered. */}
          <img
            src="/brand/blocktrace-mark.png"
            alt=""
            width={18}
            height={18}
            className="size-[18px] shrink-0 dark:hidden"
          />
          <img
            src="/brand/blocktrace-mark-on-dark.png"
            alt=""
            width={18}
            height={18}
            className="hidden size-[18px] shrink-0 dark:block"
          />
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
            {/*
              Google first, because it is the shorter path and the only one that
              never puts a password in this system. Styled from the same tokens
              as every other control on this page, so it reads as part of the
              product rather than a third-party widget; only the mark is Google's.

              Above the form, not below it, because a user who already has a
              Google account should never have to scroll to find the button.
            */}
            <Button
              type="button"
              variant="outline"
              className="h-9 w-full gap-2"
              onClick={onGoogle}
              disabled={googleBusy || busy}
            >
              {googleBusy ? (
                <Loader2
                  className="size-4 animate-spin"
                  data-icon="inline-start"
                  aria-hidden="true"
                />
              ) : (
                <GoogleMark />
              )}
              {googleBusy ? "Opening Google…" : "Continue with Google"}
            </Button>

            <div className="my-4 flex items-center gap-3">
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
              <span className="text-xs text-muted-foreground">or use email</span>
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
            </div>
          </CardContent>

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
