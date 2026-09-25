/**
 * 404.
 *
 * The catch-all route. It offers the four places worth going next rather than
 * a dead end, because a mistyped path is a navigation error, not a failure.
 */

import { Link } from "react-router-dom";
import { Search } from "lucide-react";

import { PageHeader, SectionCard } from "@/components/common";
import { Button } from "@/components/ui/button";

const DESTINATIONS = [
  { to: "/app/trace", label: "Trace console", detail: "Start a new investigation." },
  { to: "/app/investigations", label: "Investigations", detail: "Your saved cases." },
  { to: "/app/entities", label: "Entities", detail: "Addresses your traces attributed." },
  { to: "/app/network", label: "Network", detail: "Live provider status." },
];

export default function NotFound() {
  return (
    <div className="px-6 py-8">
      <PageHeader
        eyebrow="404"
        title="No such page"
        description="This address does not match a route in BlockTrace. The page may have been renamed, or the link may have a typo in it."
        actions={
          <Button render={<Link to="/app/trace" />}>
            <Search data-icon="inline-start" />
            Go to the trace console
          </Button>
        }
      />

      <SectionCard title="Where you might have meant">
        <div className="grid gap-3 sm:grid-cols-2">
          {DESTINATIONS.map((d) => (
            <Link
              key={d.to}
              to={d.to}
              className="rounded-lg border p-4 transition-colors hover:bg-muted/50"
            >
              <p className="text-sm font-medium">{d.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">{d.detail}</p>
            </Link>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
