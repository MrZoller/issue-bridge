#!/usr/bin/env python3
"""IssueBridge E2E API sandbox runner (opt-in, safe-by-default).

This extends the existing GitLab sandbox E2E by exercising the FastAPI HTTP
endpoints end-to-end (instances, project pairs, sync trigger/logs, repair
mappings, conflicts, dashboard stats).

Required env vars (minimum):
- ISSUEBRIDGE_E2E=1
- E2E_GITLAB_TOKEN=...                     # PAT with `api` scope
- E2E_NAMESPACE_ID=123  OR  E2E_NAMESPACE_PATH=group/subgroup

Optional env vars:
- E2E_GITLAB_URL=https://gitlab.com
- E2E_PREFIX=issuebridge-e2e
- E2E_KEEP=1
- E2E_DB_URL=sqlite:////tmp/issuebridge_e2e_api_<runid>.db

Run:
  ISSUEBRIDGE_E2E=1 E2E_GITLAB_TOKEN=... E2E_NAMESPACE_PATH=yourgroup \
    python3 scripts/e2e_api_sandbox.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import NoReturn, Optional

import gitlab

# Ensure the repository root is on sys.path so `import app.*` works when this file is
# executed as a script (e.g. `python scripts/e2e_api_sandbox.py` in CI).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _die(msg: str) -> NoReturn:
    print(f"[e2e-api] ERROR: {msg}", file=sys.stderr)
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
class _Config:
    prefix: str
    run_id: str
    keep: bool
    db_url: str
    gitlab_url: str
    token: str
    namespace_id: Optional[int]
    namespace_path: Optional[str]


def _normalize_url(url: str) -> str:
    return (url or "").rstrip("/")


def _make_db_url(run_id: str) -> str:
    return f"sqlite:////tmp/issuebridge_e2e_api_{run_id}.db"


def _parse_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _gitlab(url: str, token: str) -> gitlab.Gitlab:
    gl = gitlab.Gitlab(url, private_token=token)
    gl.auth()
    return gl


def _resolve_namespace_id(
    gl: gitlab.Gitlab, *, ns_id: Optional[int], ns_path: Optional[str]
) -> int:
    if ns_id is not None:
        return int(ns_id)
    if not ns_path:
        _die("Missing E2E_NAMESPACE_ID or E2E_NAMESPACE_PATH")

    try:
        grp = gl.groups.get(ns_path)
        gid = getattr(grp, "id", None)
        if gid is not None:
            return int(gid)
    except Exception:
        pass

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


def _create_project(gl: gitlab.Gitlab, *, name: str, namespace_id: int, description: str) -> object:
    return gl.projects.create(
        {
            "name": name,
            "path": name,
            "description": description,
            "visibility": "private",
            "initialize_with_readme": False,
            "namespace_id": int(namespace_id),
        }
    )


def _delete_project(project: object) -> None:
    try:
        project.delete()  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[e2e-api] WARN: failed to delete project: {e}", file=sys.stderr)


def _load_config() -> _Config:
    if not _truthy("ISSUEBRIDGE_E2E"):
        _die("Refusing to run: set ISSUEBRIDGE_E2E=1 to opt in.")

    gitlab_url = _normalize_url(
        _env("E2E_GITLAB_URL", "https://gitlab.com") or "https://gitlab.com"
    )
    token = _env("E2E_GITLAB_TOKEN")
    if not token:
        _die("Missing E2E_GITLAB_TOKEN")

    ns_id = _parse_int(_env("E2E_NAMESPACE_ID"))
    ns_path = _env("E2E_NAMESPACE_PATH")
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
        gitlab_url=gitlab_url,
        token=token,
        namespace_id=ns_id,
        namespace_path=ns_path,
    )


def main() -> int:
    cfg = _load_config()
    print(f"[e2e-api] run_id={cfg.run_id}")

    gl = _gitlab(cfg.gitlab_url, cfg.token)
    namespace_id = _resolve_namespace_id(gl, ns_id=cfg.namespace_id, ns_path=cfg.namespace_path)

    src_project = None
    tgt_project = None
    db_path_to_cleanup: Optional[str] = None

    try:
        src_name = f"{cfg.prefix}-api-src-{cfg.run_id}"
        tgt_name = f"{cfg.prefix}-api-tgt-{cfg.run_id}"
        desc = f"IssueBridge automated E2E API sandbox ({cfg.run_id}). Safe to delete."

        print("[e2e-api] creating GitLab projects…")
        src_project = _create_project(
            gl, name=src_name, namespace_id=namespace_id, description=desc
        )
        tgt_project = _create_project(
            gl, name=tgt_name, namespace_id=namespace_id, description=desc
        )

        src_project_id = int(getattr(src_project, "id"))
        tgt_project_id = int(getattr(tgt_project, "id"))

        print("[e2e-api] seeding source project…")
        label_bug = getattr(src_project, "labels").create({"name": "bug", "color": "#d73a4a"})  # type: ignore[attr-defined]
        label_feature = getattr(src_project, "labels").create(  # type: ignore[attr-defined]
            {"name": "feature", "color": "#0e8a16"}
        )
        milestone = getattr(src_project, "milestones").create({"title": f"E2E API {cfg.run_id}"})  # type: ignore[attr-defined]
        due = (date.today() + timedelta(days=7)).isoformat()
        issue1 = getattr(src_project, "issues").create(  # type: ignore[attr-defined]
            {
                "title": f"E2E API issue 1 ({cfg.run_id})",
                "description": "Seeded by IssueBridge E2E API sandbox runner.",
                "labels": f"{label_bug.name},{label_feature.name}",
                "milestone_id": milestone.id,
                "due_date": due,
                "weight": 2,
                "confidential": True,
            }
        )
        issue1.notes.create({"body": "api-first comment"})  # type: ignore[attr-defined]
        issue1.notes.create({"body": "api-second comment"})  # type: ignore[attr-defined]

        issue2 = getattr(src_project, "issues").create(  # type: ignore[attr-defined]
            {
                "title": f"E2E API closed issue ({cfg.run_id})",
                "description": "This issue should arrive closed on target.",
                "labels": label_bug.name,
            }
        )
        issue2.state_event = "close"
        issue2.save()

        # IMPORTANT: set env BEFORE importing app.* so Settings/DB engine bind to this DB.
        os.environ["DATABASE_URL"] = cfg.db_url
        # Enable optional fields for this E2E run to validate full supported field coverage.
        os.environ["SYNC_FIELDS"] = ",".join(
            [
                "title",
                "description",
                "state",
                "labels",
                "assignees",
                "milestone",
                "due_date",
                "weight",
                "time_estimate",
                "issue_type",
                "iteration",
                "epic",
                "comments",
                "confidential",
                "discussion_locked",
            ]
        )
        if cfg.db_url.startswith("sqlite:////"):
            db_path_to_cleanup = cfg.db_url.replace("sqlite:////", "/")

        from fastapi.testclient import TestClient

        from app.main import app
        from app.models import Conflict, SyncedIssue
        from app.models.base import SessionLocal

        print("[e2e-api] exercising FastAPI endpoints…")
        with TestClient(app) as client:
            # Basic health
            r = client.get("/health")
            if r.status_code != 200:
                _die(f"/health failed: {r.status_code} {r.text}")

            # Instances CRUD (create + list + get)
            inst_src = {
                "name": f"E2E API Source {cfg.run_id}",
                "url": cfg.gitlab_url,
                "access_token": cfg.token,
                "description": "E2E API sandbox",
            }
            inst_tgt = {
                "name": f"E2E API Target {cfg.run_id}",
                "url": cfg.gitlab_url,
                "access_token": cfg.token,
                "description": "E2E API sandbox",
            }
            r1 = client.post("/api/instances/", json=inst_src)
            if r1.status_code != 200:
                _die(f"create source instance failed: {r1.status_code} {r1.text}")
            r2 = client.post("/api/instances/", json=inst_tgt)
            if r2.status_code != 200:
                _die(f"create target instance failed: {r2.status_code} {r2.text}")
            src_inst_id = int(r1.json()["id"])
            tgt_inst_id = int(r2.json()["id"])

            r_list = client.get("/api/instances/")
            if r_list.status_code != 200:
                _die(f"list instances failed: {r_list.status_code} {r_list.text}")
            if not any(i.get("id") == src_inst_id for i in r_list.json()):
                _die("expected source instance to appear in list")

            r_get = client.get(f"/api/instances/{src_inst_id}")
            if r_get.status_code != 200:
                _die(f"get instance failed: {r_get.status_code} {r_get.text}")

            # User mappings CRUD (smoke)
            mapping = {
                "source_instance_id": src_inst_id,
                "source_username": "alice",
                "target_instance_id": tgt_inst_id,
                "target_username": "alice_target",
            }
            r_map = client.post("/api/user-mappings/", json=mapping)
            if r_map.status_code != 200:
                _die(f"create user mapping failed: {r_map.status_code} {r_map.text}")
            mapping_id = int(r_map.json()["id"])

            # Project pair create (name auto-generation)
            pair_payload = {
                "name": None,
                "source_instance_id": src_inst_id,
                "source_project_id": str(src_project_id),
                "target_instance_id": tgt_inst_id,
                "target_project_id": str(tgt_project_id),
                "bidirectional": False,
                "sync_enabled": True,
                "sync_interval_minutes": 1,
            }
            r_pair = client.post("/api/project-pairs/", json=pair_payload)
            if r_pair.status_code != 200:
                _die(f"create project pair failed: {r_pair.status_code} {r_pair.text}")
            pair = r_pair.json()
            pair_id = int(pair["id"])
            if "<->" not in (pair.get("name") or ""):
                _die("expected auto-generated project pair name to contain '<->'")

            # Trigger sync through API
            r_sync = client.post(f"/api/sync/{pair_id}/trigger")
            if r_sync.status_code != 200:
                _die(f"trigger sync failed: {r_sync.status_code} {r_sync.text}")
            if r_sync.json().get("status") != "success":
                _die(f"unexpected trigger sync response: {r_sync.json()}")

            # ---- Field-level sync assertions (production-critical) ----
            tgt_ref = gl.projects.get(tgt_project_id)
            tgt_issues = tgt_ref.issues.list(get_all=True, state="all")
            mirrored = next(
                (i for i in tgt_issues if f"E2E API issue 1 ({cfg.run_id})" in i.title), None
            )
            if mirrored is None:
                _die("could not find mirrored issue 1 on target by title")

            # labels should be created + assigned
            labels = set(getattr(mirrored, "labels", []) or [])
            if not {"bug", "feature"}.issubset(labels):
                _die(f"expected labels bug+feature on target issue; got {sorted(labels)}")

            # milestone should be created on target if missing + assigned
            mirrored_milestone = getattr(mirrored, "milestone", None)
            milestone_title = None
            if isinstance(mirrored_milestone, dict):
                milestone_title = mirrored_milestone.get("title")
            else:
                milestone_title = getattr(mirrored_milestone, "title", None)
            expected_ms = f"E2E API {cfg.run_id}"
            if milestone_title != expected_ms:
                _die(f"expected milestone '{expected_ms}' on target issue, got '{milestone_title}'")

            # due date + weight + confidential should sync
            if getattr(mirrored, "due_date", None) not in {due, None}:
                _die(
                    f"expected due_date '{due}' on target issue, got {getattr(mirrored, 'due_date', None)}"
                )
            if getattr(mirrored, "weight", None) not in {2, "2"}:
                _die(f"expected weight 2 on target issue, got {getattr(mirrored, 'weight', None)}")
            if getattr(mirrored, "confidential", None) is not True:
                _die("expected confidential=True on target issue")

            # comments should sync (at least two)
            notes = tgt_ref.issues.get(int(getattr(mirrored, "iid"))).notes.list(  # type: ignore[attr-defined]
                get_all=True, per_page=100, order_by="created_at", sort="asc"
            )
            if not any("api-first comment" in (getattr(n, "body", "") or "") for n in notes):
                _die("expected first comment to sync to target")
            if not any("api-second comment" in (getattr(n, "body", "") or "") for n in notes):
                _die("expected second comment to sync to target")

            # ensure target project now has the milestone/labels created
            tgt_milestones = tgt_ref.milestones.list(get_all=True, per_page=100)  # type: ignore[attr-defined]
            if not any(getattr(m, "title", None) == expected_ms for m in tgt_milestones):
                _die("expected milestone to be created in target project")
            tgt_labels = tgt_ref.labels.list(get_all=True, per_page=100)  # type: ignore[attr-defined]
            tgt_label_names = {getattr(label_obj, "name", None) for label_obj in tgt_labels}
            if not {"bug", "feature"}.issubset(tgt_label_names):
                _die("expected labels to be created in target project")

            # closed issue should remain closed on target
            mirrored_closed = next(
                (i for i in tgt_issues if f"E2E API closed issue ({cfg.run_id})" in i.title), None
            )
            if mirrored_closed is None:
                _die("could not find mirrored closed issue on target by title")
            if getattr(mirrored_closed, "state", None) != "closed":
                _die(
                    f"expected closed state on target, got {getattr(mirrored_closed, 'state', None)}"
                )

            # ---- Update test: milestone creation/update + due_date clear + label add + weight change ----
            milestone2 = getattr(src_project, "milestones").create(  # type: ignore[attr-defined]
                {"title": f"E2E API v2 {cfg.run_id}"}
            )
            label_urgent = getattr(src_project, "labels").create(  # type: ignore[attr-defined]
                {"name": "urgent", "color": "#b60205"}
            )
            issue1.milestone_id = milestone2.id
            issue1.due_date = ""  # clear
            issue1.weight = 5
            issue1.labels = f"{label_bug.name},{label_feature.name},{label_urgent.name}"
            issue1.save()

            time.sleep(1.0)
            r_sync_u = client.post(f"/api/sync/{pair_id}/trigger")
            if r_sync_u.status_code != 200 or r_sync_u.json().get("status") != "success":
                _die(f"update trigger sync failed: {r_sync_u.status_code} {r_sync_u.text}")

            tgt_issues_u = tgt_ref.issues.list(get_all=True, state="all")
            mirrored_u = next(
                (i for i in tgt_issues_u if f"E2E API issue 1 ({cfg.run_id})" in i.title), None
            )
            if mirrored_u is None:
                _die("could not re-find mirrored issue 1 on target after update")

            ms_u = getattr(mirrored_u, "milestone", None)
            ms_u_title = (
                ms_u.get("title") if isinstance(ms_u, dict) else getattr(ms_u, "title", None)
            )
            expected_ms2 = f"E2E API v2 {cfg.run_id}"
            if ms_u_title != expected_ms2:
                _die(f"expected updated milestone '{expected_ms2}', got '{ms_u_title}'")
            if getattr(mirrored_u, "due_date", None) not in {None, ""}:
                _die(
                    f"expected due_date cleared on target, got {getattr(mirrored_u, 'due_date', None)}"
                )
            if getattr(mirrored_u, "weight", None) not in {5, "5"}:
                _die(
                    f"expected updated weight 5 on target, got {getattr(mirrored_u, 'weight', None)}"
                )
            labels_u = set(getattr(mirrored_u, "labels", []) or [])
            if "urgent" not in labels_u:
                _die(f"expected new label 'urgent' on target issue; got {sorted(labels_u)}")

            # Synced issues + logs endpoints
            r_synced = client.get(f"/api/sync/synced-issues?project_pair_id={pair_id}")
            if r_synced.status_code != 200:
                _die(f"list synced issues failed: {r_synced.status_code} {r_synced.text}")
            if len(r_synced.json()) < 2:
                _die(f"expected >=2 synced issues, got {len(r_synced.json())}")

            r_logs = client.get(f"/api/sync/logs?project_pair_id={pair_id}&limit=50")
            if r_logs.status_code != 200:
                _die(f"list logs failed: {r_logs.status_code} {r_logs.text}")
            if not any(log_entry.get("status") == "success" for log_entry in r_logs.json()):
                _die("expected at least one success sync log")

            # Dashboard endpoints should reflect activity
            r_stats = client.get("/api/dashboard/stats")
            if r_stats.status_code != 200:
                _die(f"dashboard stats failed: {r_stats.status_code} {r_stats.text}")
            stats = r_stats.json()
            if stats.get("total_pairs", 0) < 1:
                _die("expected total_pairs >= 1")
            if stats.get("total_synced_issues", 0) < 2:
                _die("expected total_synced_issues >= 2")

            r_activity = client.get("/api/dashboard/activity?limit=20")
            if r_activity.status_code != 200:
                _die(f"dashboard activity failed: {r_activity.status_code} {r_activity.text}")
            if len(r_activity.json()) < 1:
                _die("expected at least one activity log")

            # Toggle endpoint (scheduler wiring smoke)
            r_toggle1 = client.post(f"/api/project-pairs/{pair_id}/toggle")
            if r_toggle1.status_code != 200:
                _die(f"toggle failed: {r_toggle1.status_code} {r_toggle1.text}")
            if r_toggle1.json().get("sync_enabled") is not False:
                _die("expected sync_enabled to toggle to False")
            r_toggle2 = client.post(f"/api/project-pairs/{pair_id}/toggle")
            if r_toggle2.status_code != 200:
                _die(f"toggle failed: {r_toggle2.status_code} {r_toggle2.text}")
            if r_toggle2.json().get("sync_enabled") is not True:
                _die("expected sync_enabled to toggle back to True")

            # Repair mappings end-to-end: delete mappings, then rebuild from markers.
            db = SessionLocal()
            try:
                deleted = (
                    db.query(SyncedIssue)
                    .filter(SyncedIssue.project_pair_id == pair_id)
                    .delete(synchronize_session=False)
                )
                db.commit()
                if deleted < 2:
                    _die(f"expected to delete >=2 synced mappings, deleted {deleted}")

                # Confirm endpoint reflects deletion
                r_synced0 = client.get(f"/api/sync/synced-issues?project_pair_id={pair_id}")
                if r_synced0.status_code != 200:
                    _die(f"list synced issues failed: {r_synced0.status_code} {r_synced0.text}")
                if len(r_synced0.json()) != 0:
                    _die("expected 0 synced issues after manual delete")

                r_repair = client.post(f"/api/sync/{pair_id}/repair-mappings")
                if r_repair.status_code != 200:
                    _die(f"repair mappings failed: {r_repair.status_code} {r_repair.text}")

                r_synced1 = client.get(f"/api/sync/synced-issues?project_pair_id={pair_id}")
                if r_synced1.status_code != 200:
                    _die(f"list synced issues failed: {r_synced1.status_code} {r_synced1.text}")
                if len(r_synced1.json()) < 2:
                    _die("expected repair-mappings to rebuild >=2 mappings")
            finally:
                db.close()

            # Conflict resolution endpoint (integration smoke): insert a conflict row then resolve via API.
            db2 = SessionLocal()
            try:
                conflict = Conflict(
                    project_pair_id=pair_id,
                    synced_issue_id=None,
                    source_issue_iid=int(getattr(issue1, "iid")),
                    target_issue_iid=None,
                    conflict_type="e2e_smoke",
                    description="E2E API conflict smoke test",
                    resolved=False,
                )
                db2.add(conflict)
                db2.commit()
                db2.refresh(conflict)
                conflict_id = int(conflict.id)
            finally:
                db2.close()

            r_resolve = client.post(
                f"/api/sync/conflicts/{conflict_id}/resolve",
                json={"resolution_notes": "resolved by e2e"},
            )
            if r_resolve.status_code != 200:
                _die(f"resolve conflict failed: {r_resolve.status_code} {r_resolve.text}")
            if r_resolve.json().get("resolved") is not True:
                _die("expected conflict to be marked resolved")

            # Cleanup a user mapping to ensure delete works
            r_del_map = client.delete(f"/api/user-mappings/{mapping_id}")
            if r_del_map.status_code != 200:
                _die(f"delete mapping failed: {r_del_map.status_code} {r_del_map.text}")

            # Final: ensure target got our issues via actual GitLab API.
            tgt_ref = gl.projects.get(tgt_project_id)
            tgt_issues = tgt_ref.issues.list(get_all=True, state="all")
            if len(tgt_issues) < 2:
                _die(f"expected >=2 issues on target GitLab project, found {len(tgt_issues)}")
            if not any(f"E2E API issue 1 ({cfg.run_id})" in i.title for i in tgt_issues):
                _die("expected seeded issue to be mirrored onto target")
            if not any(f"E2E API closed issue ({cfg.run_id})" in i.title for i in tgt_issues):
                _die("expected closed seeded issue to be mirrored onto target")

            # Small idempotency check through API trigger
            time.sleep(1.0)
            r_sync2 = client.post(f"/api/sync/{pair_id}/trigger")
            if r_sync2.status_code != 200 or r_sync2.json().get("status") != "success":
                _die(f"idempotency trigger failed: {r_sync2.status_code} {r_sync2.text}")

        print("[e2e-api] OK")
        return 0

    finally:
        if cfg.keep:
            print("[e2e-api] keeping sandbox resources (E2E_KEEP=1)")
            return 0

        print("[e2e-api] cleaning up…")
        if tgt_project is not None:
            _delete_project(tgt_project)
        if src_project is not None:
            _delete_project(src_project)

        if db_path_to_cleanup:
            try:
                if os.path.exists(db_path_to_cleanup):
                    os.remove(db_path_to_cleanup)
            except Exception as e:
                print(f"[e2e-api] WARN: failed to delete DB file: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
