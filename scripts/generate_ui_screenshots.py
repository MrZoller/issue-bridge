"""Generate UI screenshots with seeded demo data.

This script:
- seeds a demo SQLite DB (fake tokens)
- starts the FastAPI app briefly on localhost
- drives the UI with Playwright (headless)
- captures screenshots of key tabs

Usage:
  python scripts/generate_ui_screenshots.py \
    --db ./data/demo_issuebridge.db \
    --out ./docs/screenshots \
    --overwrite

Notes:
- You may need: pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _sqlite_url_for_path(db_path: Path) -> str:
    p = db_path.expanduser().resolve()
    return f"sqlite:////{p}"


def _wait_http_ready(url: str, timeout_s: float = 15.0) -> None:
    import urllib.request

    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= resp.status < 500:
                    return
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.2)
    raise RuntimeError(f"Server not ready at {url}: {last_err}")


def _ensure_out_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)


def _seed_demo_db(db_path: Path, overwrite: bool) -> None:
    cmd = [sys.executable, "scripts/seed_demo_data.py", "--db", str(db_path)]
    if overwrite:
        cmd.append("--overwrite")
    subprocess.run(cmd, check=True)


def _run() -> None:
    parser = argparse.ArgumentParser(description="Generate IssueBridge UI screenshots")
    parser.add_argument("--db", default="./data/demo_issuebridge.db")
    parser.add_argument("--out", default="./docs/screenshots")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)

    _ensure_out_dir(out_dir)
    _seed_demo_db(db_path=db_path, overwrite=bool(args.overwrite))

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["DATABASE_URL"] = _sqlite_url_for_path(db_path)
    env.setdefault("LOG_LEVEL", "WARNING")
    env.setdefault("DEFAULT_SYNC_INTERVAL_MINUTES", "60")

    # Start server
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_http_ready(f"{base_url}/health", timeout_s=20.0)

        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})

            def snap(name: str) -> None:
                page.wait_for_timeout(150)
                page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True)

            # Dashboard
            page.goto(base_url, wait_until="networkidle")
            page.wait_for_selector("#pairs-status-tbody tr")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#pairs-status-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("dashboard")

            # Instances
            page.click('button[data-tab="instances-tab"]')
            page.wait_for_selector("#instances-tbody tr")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#instances-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("instances")

            # Project pairs
            page.click('button[data-tab="pairs-tab"]')
            page.wait_for_selector("#pairs-tbody tr")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#pairs-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("project-pairs")

            # User mappings
            page.click('button[data-tab="mappings-tab"]')
            page.wait_for_selector("#mappings-tbody tr")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#mappings-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("user-mappings")

            # Sync logs
            page.click('button[data-tab="logs-tab"]')
            page.wait_for_selector("#logs-tbody tr")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#logs-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("sync-logs")

            # Conflicts
            page.click('button[data-tab="conflicts-tab"]')
            page.wait_for_selector("#conflicts-tbody")
            page.wait_for_function(
                """() => {
                    const tb = document.querySelector('#conflicts-tbody');
                    return tb && !tb.innerText.includes('Loading');
                }"""
            )
            snap("conflicts")

            browser.close()

        print(f"Wrote screenshots to: {out_dir.resolve()}")

    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except Exception:  # noqa: BLE001
                server.kill()

        # If the server errored, surface logs to help diagnose
        rc = server.poll()
        if rc not in (0, None):
            try:
                out = (server.stdout.read() if server.stdout else "")
                err = (server.stderr.read() if server.stderr else "")
            except Exception:  # noqa: BLE001
                out, err = "", ""
            if out.strip() or err.strip():
                print("--- uvicorn output ---")
                print(out)
                print(err)


if __name__ == "__main__":
    _run()
