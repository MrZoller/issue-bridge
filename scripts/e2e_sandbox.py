#!/usr/bin/env python3
"""
IssueBridge E2E sandbox runner (opt-in, safe-by-default).

What it does (high level):
- Creates two temporary GitLab projects (source + target) in a namespace you control
- Seeds source with a small set of issues, labels, milestones, and comments
- Creates a temporary IssueBridge DB, configures instances + a project pair
- Runs sync and asserts core expectations (creation, updates, comment dedupe/idempotency)
- Cleans up (deletes the temporary projects + local DB) unless KEEP is enabled

This script is intentionally environment-driven to avoid committing secrets.

Required env vars (minimum):
- ISSUEBRIDGE_E2E=1                        # explicit opt-in guard
- E2E_GITLAB_TOKEN=...                     # PAT with `api` scope
- E2E_NAMESPACE_ID=123  OR  E2E_NAMESPACE_PATH=group/subgroup

Optional env vars:
- E2E_GITLAB_URL=https://gitlab.com        # defaults to https://gitlab.com
- E2E_SOURCE_TOKEN / E2E_TARGET_TOKEN      # override per side (defaults to E2E_GITLAB_TOKEN)
- E2E_SOURCE_URL / E2E_TARGET_URL          # override per side (defaults to E2E_GITLAB_URL)
- E2E_TARGET_NAMESPACE_ID / _PATH          # target namespace override (defaults to source namespace)
- E2E_PREFIX=issuebridge-e2e               # project name prefix
- E2E_KEEP=1                               # keep GitLab projects + DB for inspection
- E2E_DB_URL=sqlite:////tmp/issuebridge_e2e_<runid>.db  # override DB location

Run:
  ISSUEBRIDGE_E2E=1 E2E_GITLAB_TOKEN=... E2E_NAMESPACE_PATH=yourgroup \
    python3 scripts/e2e_sandbox.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NoReturn, Optional
from urllib.parse import quote

import gitlab


def _die(msg: str) -> NoReturn:
    print(f"[e2e] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return default
    v = str(v).strip()
    return v if v != "" else default


def _truthy(name: str, default: bool = False) -> bool:
    v = _env(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class _Side:
    url: str
    token: str
    namespace_id: Optional[int]
    namespace_path: Optional[str]


@dataclass(frozen=True)
class _Config:
    prefix: str
    run_id: str
    keep: bool
    db_url: str
    source: _Side
    target: _Side


def _normalize_url(url: str) -> str:
    return (url or "").rstrip("/")


def _make_db_url(run_id: str) -> str:
    return f"sqlite:////tmp/issuebridge_e2e_{run_id}.db"


def _parse_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _resolve_namespace_id(
    gl: gitlab.Gitlab, *, ns_id: Optional[int], ns_path: Optional[str]
) -> Optional[int]:
    if ns_id is not None:
        return int(ns_id)
    if not ns_path:
        return None

    # Prefer group full_path lookup (works for group/subgroup paths).
    try:
        grp = gl.groups.get(ns_path)
        gid = getattr(grp, "id", None)
        if gid is not None:
            return int(gid)
    except Exception:
        pass

    # Fallback: namespace search + exact full_path match.
    try:
        for ns in gl.namespaces.list(search=ns_path, get_all=True):  # type: ignore[attr-defined]
            full_path = getattr(ns, "full_path", None) or getattr(ns, "path", None)
            if full_path and str(full_path).strip("/") == str(ns_path).strip("/"):
                nid = getattr(ns, "id", None)
                if nid is not None:
                    return int(nid)
    except Exception:
        pass

    _die(
        "Unable to resolve namespace id. Provide E2E_NAMESPACE_ID or a valid E2E_NAMESPACE_PATH "
        "(group/subgroup)."
    )


def _gitlab(url: str, token: str) -> gitlab.Gitlab:
    gl = gitlab.Gitlab(url, private_token=token)
    gl.auth()
    return gl


def _create_project(
    gl: gitlab.Gitlab,
    *,
    name: str,
    namespace_id: Optional[int],
    description: str,
) -> object:
    payload = {
        "name": name,
        "path": name,  # keep deterministic + easy to match for cleanup
        "description": description,
        "visibility": "private",
        "initialize_with_readme": False,
    }
    if namespace_id is not None:
        payload["namespace_id"] = int(namespace_id)
    return gl.projects.create(payload)


def _delete_project(project: object) -> None:
    try:
        # python-gitlab project resource supports delete()
        project.delete()  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[e2e] WARN: failed to delete project: {e}", file=sys.stderr)


def _http_post(gl: gitlab.Gitlab, path: str, *, post_data: dict) -> None:
    gl.http_post(path, post_data=post_data)


def _set_time_estimate(gl: gitlab.Gitlab, *, project_id: int, issue_iid: int, seconds: int) -> None:
    pid = quote(str(int(project_id)), safe="")
    iid = quote(str(int(issue_iid)), safe="")
    _http_post(
        gl,
        f"/projects/{pid}/issues/{iid}/time_estimate",
        post_data={"duration": f"{int(seconds)}s"},
    )


def _load_config() -> _Config:
    if not _truthy("ISSUEBRIDGE_E2E"):
        _die("Refusing to run: set ISSUEBRIDGE_E2E=1 to opt in.")

    url = _normalize_url(_env("E2E_GITLAB_URL", "https://gitlab.com") or "https://gitlab.com")
    token = _env("E2E_GITLAB_TOKEN")
    if not token:
        _die("Missing E2E_GITLAB_TOKEN")

    source_url = _normalize_url(_env("E2E_SOURCE_URL", url) or url)
    target_url = _normalize_url(_env("E2E_TARGET_URL", url) or url)
    source_token = _env("E2E_SOURCE_TOKEN", token) or token
    target_token = _env("E2E_TARGET_TOKEN", token) or token

    ns_id = _parse_int(_env("E2E_NAMESPACE_ID"))
    ns_path = _env("E2E_NAMESPACE_PATH")
    tgt_ns_id = _parse_int(_env("E2E_TARGET_NAMESPACE_ID")) or ns_id
    tgt_ns_path = _env("E2E_TARGET_NAMESPACE_PATH") or ns_path

    if ns_id is None and not ns_path:
        _die("Missing namespace: set E2E_NAMESPACE_ID or E2E_NAMESPACE_PATH.")

    prefix = _env("E2E_PREFIX", "issuebridge-e2e") or "issuebridge-e2e"
    run_id = uuid.uuid4().hex[:10]
    keep = _truthy("E2E_KEEP", default=False)
    db_url = _env("E2E_DB_URL") or _make_db_url(run_id)

    return _Config(
        prefix=prefix,
        run_id=run_id,
        keep=keep,
        db_url=db_url,
        source=_Side(source_url, source_token, ns_id, ns_path),
        target=_Side(target_url, target_token, tgt_ns_id, tgt_ns_path),
    )


def main() -> int:
    cfg = _load_config()
    print(f"[e2e] run_id={cfg.run_id}")

    src_gl = _gitlab(cfg.source.url, cfg.source.token)
    tgt_gl = _gitlab(cfg.target.url, cfg.target.token)

    src_ns_id = _resolve_namespace_id(
        src_gl, ns_id=cfg.source.namespace_id, ns_path=cfg.source.namespace_path
    )
    tgt_ns_id = _resolve_namespace_id(
        tgt_gl, ns_id=cfg.target.namespace_id, ns_path=cfg.target.namespace_path
    )

    src_project = None
    tgt_project = None
    db_path_to_cleanup = None

    try:
        src_name = f"{cfg.prefix}-src-{cfg.run_id}"
        tgt_name = f"{cfg.prefix}-tgt-{cfg.run_id}"
        desc = f"IssueBridge automated E2E sandbox ({cfg.run_id}). Safe to delete."

        print("[e2e] creating GitLab projects…")
        src_project = _create_project(
            src_gl, name=src_name, namespace_id=src_ns_id, description=desc
        )
        tgt_project = _create_project(
            tgt_gl, name=tgt_name, namespace_id=tgt_ns_id, description=desc
        )

        src_project_id = int(getattr(src_project, "id"))
        tgt_project_id = int(getattr(tgt_project, "id"))

        # Seed source project
        print("[e2e] seeding source project…")
        label_bug = getattr(src_project, "labels").create({"name": "bug", "color": "#d73a4a"})  # type: ignore[attr-defined]
        label_feature = getattr(src_project, "labels").create(
            {"name": "feature", "color": "#0e8a16"}
        )  # type: ignore[attr-defined]
        milestone = getattr(src_project, "milestones").create({"title": f"E2E {cfg.run_id}"})  # type: ignore[attr-defined]

        due = (date.today() + timedelta(days=7)).isoformat()
        issue1 = getattr(src_project, "issues").create(  # type: ignore[attr-defined]
            {
                "title": f"E2E issue 1 ({cfg.run_id})",
                "description": "Seeded by IssueBridge E2E sandbox runner.",
                "labels": f"{label_bug.name},{label_feature.name}",
                "milestone_id": milestone.id,
                "due_date": due,
                "weight": 3,
            }
        )
        issue2 = getattr(src_project, "issues").create(  # type: ignore[attr-defined]
            {
                "title": f"E2E closed issue ({cfg.run_id})",
                "description": "This issue should arrive closed on target.",
                "labels": label_bug.name,
            }
        )
        issue2.state_event = "close"
        issue2.save()

        note1 = getattr(issue1, "notes").create({"body": "first comment"})  # type: ignore[attr-defined]
        note2 = getattr(issue1, "notes").create({"body": "second comment"})  # type: ignore[attr-defined]

        # Best-effort time estimate (not all GitLab plans enable time tracking).
        try:
            _set_time_estimate(
                src_gl, project_id=src_project_id, issue_iid=int(issue1.iid), seconds=3600
            )
        except Exception as e:
            print(f"[e2e] WARN: could not set time estimate (best-effort): {e}", file=sys.stderr)

        # Configure IssueBridge DB in-process (ensure env is set BEFORE importing app.*)
        os.environ["DATABASE_URL"] = cfg.db_url
        if cfg.db_url.startswith("sqlite:////"):
            db_path_to_cleanup = cfg.db_url.replace("sqlite:////", "/")

        from app.models.base import SessionLocal, init_db  # noqa: WPS433 (runtime import)
        from app.models.instance import GitLabInstance  # noqa: WPS433 (runtime import)
        from app.models.project_pair import ProjectPair  # noqa: WPS433 (runtime import)
        from app.services.sync_service import SyncService  # noqa: WPS433 (runtime import)

        print(f"[e2e] initializing IssueBridge DB at {cfg.db_url}…")
        init_db()
        db = SessionLocal()
        try:
            src_inst = GitLabInstance(
                name=f"E2E Source {cfg.run_id}",
                url=cfg.source.url,
                access_token=cfg.source.token,
                description="E2E sandbox",
            )
            tgt_inst = GitLabInstance(
                name=f"E2E Target {cfg.run_id}",
                url=cfg.target.url,
                access_token=cfg.target.token,
                description="E2E sandbox",
            )
            db.add(src_inst)
            db.add(tgt_inst)
            db.commit()
            db.refresh(src_inst)
            db.refresh(tgt_inst)

            pair = ProjectPair(
                name=f"E2E Pair {cfg.run_id}",
                source_instance_id=src_inst.id,
                source_project_id=str(src_project_id),
                target_instance_id=tgt_inst.id,
                target_project_id=str(tgt_project_id),
                sync_enabled=True,
                bidirectional=False,  # start unidirectional for deterministic asserts
                sync_interval_minutes=1,
            )
            db.add(pair)
            db.commit()
            db.refresh(pair)

            svc = SyncService(db)

            print("[e2e] running initial sync…")
            out1 = svc.sync_project_pair(pair.id)
            if out1.get("status") not in {"success"}:
                _die(f"initial sync failed: {out1}")

            # Verify target has issues + markers
            tgt_project_ref = tgt_gl.projects.get(tgt_project_id)
            tgt_issues = tgt_project_ref.issues.list(
                get_all=True, state="all", order_by="iid", sort="asc"
            )
            if len(tgt_issues) < 2:
                _die(f"expected >=2 issues on target, found {len(tgt_issues)}")

            # Find the mirrored issue by title
            mirrored = next(
                (i for i in tgt_issues if f"E2E issue 1 ({cfg.run_id})" in i.title), None
            )
            if mirrored is None:
                _die("could not find mirrored issue 1 on target by title")

            # Basic field assertions
            if getattr(mirrored, "due_date", None) not in {due, None}:
                _die(f"unexpected due_date on target: {getattr(mirrored, 'due_date', None)}")
            labels = set(getattr(mirrored, "labels", []) or [])
            if not {"bug", "feature"}.issubset(labels):
                _die(f"expected labels bug+feature on target; got {sorted(labels)}")
            desc = getattr(mirrored, "description", "") or ""
            if "*Synced from:" not in desc or "gl-issue-sync:" not in desc:
                _die("expected sync reference + marker in target description")

            # Closed issue should be closed
            mirrored_closed = next(
                (i for i in tgt_issues if f"E2E closed issue ({cfg.run_id})" in i.title), None
            )
            if mirrored_closed is None:
                _die("could not find mirrored closed issue on target by title")
            if getattr(mirrored_closed, "state", None) != "closed":
                _die(
                    f"expected closed state on target, got {getattr(mirrored_closed, 'state', None)}"
                )

            # Notes should exist and have markers
            notes = tgt_project_ref.issues.get(int(mirrored.iid)).notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if len(notes) < 2:
                _die(f"expected >=2 synced notes on target, found {len(notes)}")
            if not any("gl-issue-sync-note:" in (getattr(n, "body", "") or "") for n in notes):
                _die("expected at least one synced note marker on target")

            # Re-run sync to assert idempotency (no duped notes/issues)
            print("[e2e] running idempotency sync…")
            out2 = svc.sync_project_pair(pair.id)
            if out2.get("status") not in {"success"}:
                _die(f"idempotency sync failed: {out2}")

            tgt_issues2 = tgt_project_ref.issues.list(get_all=True, state="all")
            if len(tgt_issues2) != len(tgt_issues):
                _die(
                    f"expected stable issue count on target; {len(tgt_issues)} -> {len(tgt_issues2)}"
                )

            notes2 = tgt_project_ref.issues.get(int(mirrored.iid)).notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if len(notes2) != len(notes):
                _die(
                    f"expected stable note count on idempotency run; {len(notes)} -> {len(notes2)}"
                )

            # Update source issue + add a new comment; ensure target updates and doesn't duplicate old notes
            print("[e2e] applying source update + new comment…")
            issue1.title = f"[UPDATED] {issue1.title}"
            issue1.save()
            note3 = getattr(issue1, "notes").create({"body": "third comment"})  # type: ignore[attr-defined]

            # Ensure updated_at has moved enough for incremental filter overlap; tiny sleep to avoid edge cases.
            time.sleep(1.0)
            out3 = svc.sync_project_pair(pair.id)
            if out3.get("status") not in {"success"}:
                _die(f"update sync failed: {out3}")

            refreshed = tgt_project_ref.issues.get(int(mirrored.iid))
            if "[UPDATED]" not in getattr(refreshed, "title", ""):
                _die("expected updated title to propagate to target")

            notes3 = tgt_project_ref.issues.get(int(mirrored.iid)).notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if len(notes3) != len(notes2) + 1:
                _die(f"expected exactly one new synced note; {len(notes2)} -> {len(notes3)}")
            if not any("third comment" in (getattr(n, "body", "") or "") for n in notes3):
                _die("expected new comment to sync to target")

            # Final idempotency check after update
            print("[e2e] running post-update idempotency sync…")
            out4 = svc.sync_project_pair(pair.id)
            if out4.get("status") not in {"success"}:
                _die(f"post-update idempotency sync failed: {out4}")
            notes4 = tgt_project_ref.issues.get(int(mirrored.iid)).notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if len(notes4) != len(notes3):
                _die(f"expected stable note count post-update; {len(notes3)} -> {len(notes4)}")

            # --- Bidirectional phase ---
            print("[e2e] enabling bidirectional sync…")
            pair.bidirectional = True
            db.commit()

            tgt_created = tgt_project_ref.issues.create(  # type: ignore[attr-defined]
                {
                    "title": f"E2E created on target ({cfg.run_id})",
                    "description": "Originated on target in E2E bidirectional phase.",
                    "labels": "target-created",
                }
            )
            tgt_created_iid = int(getattr(tgt_created, "iid"))

            # Small delay to avoid edge-case timestamp equality around updated_after overlap.
            time.sleep(1.0)
            print("[e2e] running bidirectional sync (should copy target -> source)…")
            out5 = svc.sync_project_pair(pair.id)
            if out5.get("status") not in {"success"}:
                _die(f"bidirectional sync failed: {out5}")

            src_project_ref = src_gl.projects.get(src_project_id)
            src_issues = src_project_ref.issues.list(get_all=True, state="all")
            mirrored_on_source = next(
                (i for i in src_issues if f"E2E created on target ({cfg.run_id})" in i.title), None
            )
            if mirrored_on_source is None:
                _die(
                    "expected target-created issue to be mirrored onto source in bidirectional mode"
                )

            src_desc = getattr(mirrored_on_source, "description", "") or ""
            if "*Synced from:" not in src_desc or "gl-issue-sync:" not in src_desc:
                _die(
                    "expected sync reference + marker in source description for target-created issue"
                )

            # Create a comment on the target-created issue; ensure it syncs to source once and doesn't ping-pong back.
            tgt_created_issue = tgt_project_ref.issues.get(tgt_created_iid)  # type: ignore[attr-defined]
            tgt_created_issue.notes.create({"body": "note from target (bidirectional)"})  # type: ignore[attr-defined]

            time.sleep(1.0)
            print("[e2e] syncing target comment to source (no ping-pong)…")
            out6 = svc.sync_project_pair(pair.id)
            if out6.get("status") not in {"success"}:
                _die(f"bidirectional comment sync failed: {out6}")

            src_issue_full = src_project_ref.issues.get(int(getattr(mirrored_on_source, "iid")))  # type: ignore[attr-defined]
            src_notes = src_issue_full.notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if not any(
                "note from target (bidirectional)" in (getattr(n, "body", "") or "")
                for n in src_notes
            ):
                _die("expected target note to sync to source in bidirectional mode")

            tgt_notes_after = tgt_created_issue.notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if any(
                "note from target (bidirectional)" in (getattr(n, "body", "") or "")
                and "gl-issue-sync-note:" in (getattr(n, "body", "") or "")
                for n in tgt_notes_after
            ):
                _die("unexpected ping-pong: target appears to contain a synced-back note marker")

            # Final idempotency check across both projects.
            print("[e2e] running final bidirectional idempotency sync…")
            out7 = svc.sync_project_pair(pair.id)
            if out7.get("status") not in {"success"}:
                _die(f"final bidirectional idempotency sync failed: {out7}")

            src_issues2 = src_project_ref.issues.list(get_all=True, state="all")
            tgt_issues3 = tgt_project_ref.issues.list(get_all=True, state="all")
            if len(src_issues2) != len(src_issues):
                _die(
                    f"expected stable issue count on source; {len(src_issues)} -> {len(src_issues2)}"
                )
            if len(tgt_issues3) != len(tgt_issues2):
                _die(
                    f"expected stable issue count on target; {len(tgt_issues2)} -> {len(tgt_issues3)}"
                )

            # Keep references in locals so linters don't complain about "unused"
            _ = (note1, note2, note3)
        finally:
            try:
                db.close()  # type: ignore[name-defined]
            except Exception:
                pass

        print("[e2e] OK")
        return 0
    finally:
        if cfg.keep:
            print("[e2e] keeping sandbox resources (E2E_KEEP=1)")
            return 0

        # Best-effort cleanup (only projects we created).
        print("[e2e] cleaning up…")
        if tgt_project is not None:
            _delete_project(tgt_project)
        if src_project is not None:
            _delete_project(src_project)

        if db_path_to_cleanup:
            try:
                if os.path.exists(db_path_to_cleanup):
                    os.remove(db_path_to_cleanup)
            except Exception as e:
                print(f"[e2e] WARN: failed to delete DB file: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
