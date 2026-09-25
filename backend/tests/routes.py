"""
Route inventory: what the API actually serves.

A router that fails to register produces a 404, which reads as "this feature
does not exist" rather than "this build is broken". So this asserts the surface
is really reachable.

NOTE ON HOW THIS INSPECTS: FastAPI 0.141 stores an included router in
`app.routes` as an `_IncludedRouter` wrapper rather than flattening its routes
into the top-level list. Walking `app.routes` directly therefore shows the
wrappers and finds nothing, which is how an earlier version of this test
"proved" 21 working endpoints were missing. The source of truth is the OpenAPI
schema, which is what a client actually receives — so this reads that instead.
"""

import sys

sys.path.insert(0, ".")

import main  # noqa: E402
from services.chain_registry import supported_chains  # noqa: E402


def main_check() -> int:
    # The contract a client sees.
    schema = main.app.openapi()
    paths = schema.get("paths", {})

    served = set()
    for path, operations in paths.items():
        for method in operations:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                served.add((method.upper(), path))

    print("Routes in the OpenAPI schema:")
    for method, path in sorted(served, key=lambda x: (x[1], x[0])):
        print(f"  {method:6} {path}")

    failures = []

    def expect(method, path):
        if (method, path) not in served:
            failures.append(f"missing {method} {path}")

    # -- the investigation journey, endpoint by endpoint ----------------
    expect("POST", "/trace/detect")
    expect("POST", "/trace/run")
    expect("GET", "/investigations")
    expect("GET", "/investigations/{investigation_id}")
    expect("POST", "/investigations")
    expect("DELETE", "/investigations/{investigation_id}")
    expect("GET", "/analytics/overview")
    expect("GET", "/analytics/risk-trend")
    expect("GET", "/entities")
    expect("GET", "/entities/types")
    expect("GET", "/entities/{chain_value}/{address}")
    expect("GET", "/network/chains")
    expect("GET", "/network/status")
    expect("GET", "/network/overview")
    expect("GET", "/reports")
    expect("GET", "/reports/{filename}")
    expect("POST", "/reports/{investigation_id}/regenerate")
    expect("GET", "/auth/status")
    expect("POST", "/auth/login")
    expect("POST", "/auth/signup")
    expect("POST", "/auth/logout")

    # -- the legacy endpoint must survive the refactor -------------------
    expect("POST", "/trace")
    expect("GET", "/")
    expect("GET", "/health")

    # -- the two /trace paths must both exist and be distinct ------------
    # `/trace` is the legacy TRON-only handler in main.py; `/trace/run` is the
    # multi-chain engine. If either is shadowed the other, one of them is dead
    # code that still looks alive.
    for required in ("/trace", "/trace/run", "/trace/detect"):
        if required not in paths:
            failures.append(f"legacy/new trace path {required} absent from schema")

    # -- the health response must not under-report the chains -------------
    health = main.health()
    declared = {c.value for c in supported_chains()}
    if set(health.chains) != declared:
        failures.append(
            f"health reports chains {sorted(health.chains)} but the registry "
            f"has {sorted(declared)}"
        )
    if not health.persistence:
        failures.append("health does not report which persistence backend is in use")
    if not health.auth:
        failures.append("health does not report the auth mode")

    # -- RULE 7: no secret may appear anywhere in the schema --------------
    # The OpenAPI document is fetched by the browser. A service-role key or a
    # real provider key showing up in it would be a leak in the one artefact
    # every client can read.
    import config  # noqa: E402
    import json

    blob = json.dumps(schema, default=str)
    for secret_name, secret in (
        ("SUPABASE_SERVICE_ROLE_KEY", config.SUPABASE_SERVICE_ROLE_KEY),
        ("SUPABASE_ANON_KEY", config.SUPABASE_ANON_KEY),
        ("ETHERSCAN_API_KEY", config.ETHERSCAN_API_KEY),
        ("TRONSCAN_API_KEY", config.TRONSCAN_API_KEY),
    ):
        if secret and len(secret) > 8 and secret in blob:
            failures.append(f"SECRET LEAK: {secret_name} appears in the OpenAPI schema")

    print()
    print(f"supported chains : {sorted(declared)}")
    print(f"persistence      : {health.persistence}")
    print(f"auth mode        : {health.auth}")
    print(f"served routes    : {len(served)}")

    if failures:
        print()
        for f in failures:
            print("FAIL:", f)
        return 1

    print()
    print("PASS  every expected route is served; legacy + multi-chain coexist;")
    print("      health is honest about chains/persistence/auth; no secrets in schema")
    return 0


if __name__ == "__main__":
    sys.exit(main_check())
