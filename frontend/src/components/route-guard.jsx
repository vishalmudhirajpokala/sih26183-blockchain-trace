/**
 * Route guard.
 *
 * The backend distinguishes three states and this guard preserves all three,
 * because collapsing any pair of them produces a screen that lies:
 *
 *   still checking   show a loading state
 *   locked           send the operator to sign in
 *   unreachable      say the API is unreachable and offer a retry
 *
 * The failure this exists to prevent: a deployment whose backend is down must
 * not redirect to the sign-in page. That page says "your credentials were
 * rejected", when in fact no credentials were ever checked. The operator then
 * retypes a password into a system that is not running, and concludes the
 * account is broken.
 */

import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorPanel, LoadingBlock } from "@/components/common";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";

/** Shown while `/auth/status` has not answered yet. */
function CheckingState() {
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-md">
        <LoadingBlock label="Checking this deployment's access mode" />
      </div>
    </div>
  );
}

/**
 * The backend could not be reached at all.
 *
 * This is deliberately not a sign-in screen. There is no session to establish
 * and no credential to correct, so the only useful action is a retry.
 */
function UnreachableState() {
  const { refreshStatus } = useAuth();
  const [elapsed, setElapsed] = useState(0);
  const [givenUp, setGivenUp] = useState(false);

  /*
   * Wait before declaring the service down.
   *
   * A free-tier backend idles out after fifteen minutes and takes about a
   * minute to come back. A visitor who arrives inside that window was told
   * "the API is not responding", which reads as a broken deployment rather
   * than a sleeping one -- and on a demo day that is the difference between a
   * pause and a bad impression.
   *
   * So the two cases that look identical from the browser are separated: a host
   * that is waking up, and a host that has gone. It polls for longer than the
   * documented spin-up before saying the second one.
   *
   * The wording carries as much weight as the polling. "Waking up, about a
   * minute" is something somebody waits for. "Not responding" is something they
   * report.
   */
  const BUDGET_MS = 100000;
  const POLL_MS = 4000;

  useEffect(() => {
    const started = Date.now();
    const tick = setInterval(() => {
      const passed = Date.now() - started;
      setElapsed(passed);
      if (passed >= BUDGET_MS) {
        clearInterval(tick);
        setGivenUp(true);
      }
    }, 500);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    if (givenUp) return undefined;
    let cancelled = false;
    const poll = setInterval(async () => {
      if (cancelled) return;
      /*
       * The probe is deliberately NOT `refreshStatus()`. That call sets the
       * shared `loading` flag, and the guard above turns `loading && !status`
       * into its generic "Checking this deployment's access mode" screen -- so
       * polling with it would replace this explanation with a vaguer one every
       * few seconds, which is the opposite of helpful.
       *
       * Instead the endpoint is asked directly, and the shared status is only
       * refreshed once the probe has succeeded. A failure is then already known
       * not to happen, so that call cannot bounce the screen.
       */
      try {
        const next = await api.authStatus();
        if (cancelled) return;
        if (next) {
          clearInterval(poll);
          setGivenUp(false);
          refreshStatus();
        }
      } catch {
        // Still asleep. The next tick tries again; nothing to report yet.
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(poll);
    };
  }, [givenUp, refreshStatus]);

  const seconds = Math.ceil(elapsed / 1000);

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>
            {givenUp
              ? "The BlockTrace API is not responding"
              : "The BlockTrace backend is waking up"}
          </CardTitle>
          <CardDescription>
            {givenUp ? (
              <>
                BlockTrace waited {seconds}s and the backend still did not
                answer. That is a statement about this browser&apos;s connection
                to the server, not about your access.
              </>
            ) : (
              <>
                This deployment&apos;s backend sleeps when nobody is using it and
                takes about a minute to start again. BlockTrace is waiting for it
                and will continue on its own — there is no need to reload.{" "}
                {seconds}s elapsed.
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {givenUp ? (
            <ErrorPanel
              error={{
                kind: "unavailable",
                detail:
                  "No response from the API after waiting. Start the backend, " +
                  "then check that VITE_API_URL points at it.",
              }}
            />
          ) : (
            <LoadingBlock label="Waiting for the backend to accept requests" />
          )}
          <Button
            onClick={() => {
              setGivenUp(false);
              setElapsed(0);
              refreshStatus();
            }}
          >
            {givenUp ? "Retry" : "Check now"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Wrap an element that requires a readable data source.
 *
 * Demo mode counts as accessible — it is deliberately open — so `canAccess`
 * rather than `isAuthenticated` is the test. What the guard must never do is
 * make a demo look private, so the pages themselves still read `isDemo` and
 * label it.
 */
export function RequireAccess({ children }) {
  const { loading, status, canAccess } = useAuth();
  const location = useLocation();

  if (loading && !status) return <CheckingState />;

  // `status === null` means the capability check failed. `loading` is already
  // false here, so this is a settled failure rather than a pending one.
  if (!status) return <UnreachableState />;

  if (!canAccess) {
    // `state.from` lets the sign-in page send the operator back where they were
    // headed, so a bookmarked investigation link survives the round trip.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  return children;
}

/**
 * The inverse: a page that is meaningless without a session, such as the
 * sign-in form itself. Sending a signed-in operator to the sign-in page would
 * let them type a password into a form that cannot do anything with it.
 *
 * In demo mode there is no real session, so the demo is allowed in — the page
 * then explains what demo mode is instead of pretending to be signed in.
 */
export function RedirectIfSignedIn({ children }) {
  const { loading, status, isAuthenticated, isDemo } = useAuth();
  const location = useLocation();

  if (loading && !status) return <CheckingState />;
  if (!status) return <UnreachableState />;
  if (isAuthenticated || isDemo) {
    return <Navigate to={location.state?.from || "/app"} replace />;
  }

  return children;
}
