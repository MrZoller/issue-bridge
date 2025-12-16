#!/usr/bin/env python3
"""IssueBridge auth E2E sandbox runner.

This is a fast, hermetic integration test that validates:
- /health remains publicly accessible when auth is enabled
- all other routes return 401 without Authorization
- valid Authorization succeeds

It is intentionally executed in a separate process to ensure the app reads auth
configuration from environment variables before import-time initialization.

Run:
  python3 scripts/e2e_auth_sandbox.py
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Ensure repository root is importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _basic(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def main() -> int:
    # Force auth on
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["AUTH_USERNAME"] = "e2e"
    os.environ["AUTH_PASSWORD"] = "secret"

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        # /health is allowlisted
        r = client.get("/health")
        if r.status_code != 200:
            print(f"[e2e-auth] /health expected 200, got {r.status_code}: {r.text}")
            return 2

        # Root should be protected
        r0 = client.get("/")
        if r0.status_code != 401:
            print(f"[e2e-auth] / expected 401, got {r0.status_code}: {r0.text}")
            return 2

        # API should be protected
        r1 = client.get("/api/instances/")
        if r1.status_code != 401:
            print(f"[e2e-auth] /api/instances expected 401, got {r1.status_code}: {r1.text}")
            return 2

        # With valid auth, should succeed (200 + JSON)
        r2 = client.get("/api/instances/", headers={"Authorization": _basic("e2e", "secret")})
        if r2.status_code != 200:
            print(f"[e2e-auth] authed /api/instances expected 200, got {r2.status_code}: {r2.text}")
            return 2

        # Wrong password should still be 401
        r3 = client.get("/api/instances/", headers={"Authorization": _basic("e2e", "wrong")})
        if r3.status_code != 401:
            print(f"[e2e-auth] wrong password expected 401, got {r3.status_code}: {r3.text}")
            return 2

    print("[e2e-auth] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
