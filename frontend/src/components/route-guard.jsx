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

import { Navigate, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorPanel, LoadingBlock } from "@/components/common";
import { useAuth } from "@/hooks/use-auth";

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
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>The BlockTrace API is not responding</CardTitle>
          <CardDescription>
            BlockTrace could not determine whether this deployment requires sign-in,
            because the backend did not answer. That is a statement about this
            browser&apos;s connection to the server, not about your access.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ErrorPanel
            error={{
              kind: "unavailable",
              detail:
                "No response from the API. Start the backend, then check that " +
                "VITE_API_URL points at it.",
            }}
          />
          <Button onClick={() => window.location.reload()}>Retry</Button>
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
