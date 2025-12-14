"""Seed a demo SQLite DB with sample IssueBridge data.

This is intended for docs/screenshots and local demos.
It does NOT contact GitLab.

Usage:
  python scripts/seed_demo_data.py --db ./data/demo_issuebridge.db --overwrite
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _sqlite_url_for_path(db_path: Path) -> str:
    # SQLAlchemy sqlite absolute path uses 4 slashes: sqlite:////abs/path
    p = db_path.expanduser().resolve()
    return f"sqlite:////{p}"


@dataclass(frozen=True)
class SeedResult:
    db_path: Path


def seed_demo_db(db_path: Path, overwrite: bool = False) -> SeedResult:
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if overwrite and db_path.exists():
        db_path.unlink()

    # IMPORTANT: DATABASE_URL must be set before importing app.* modules
    os.environ["DATABASE_URL"] = _sqlite_url_for_path(db_path)
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    from app.models.base import init_db, SessionLocal  # noqa: WPS433
    from app.models import GitLabInstance, ProjectPair, UserMapping, SyncLog, Conflict, SyncedIssue  # noqa: WPS433
    from app.models.sync_log import SyncStatus, SyncDirection  # noqa: WPS433

    init_db()

    now = datetime.utcnow()

    db = SessionLocal()
    try:
        # Instances
        prod = GitLabInstance(
            name="Production",
            url="https://gitlab.example.com",
            access_token="demo-token-not-a-real-token",
            description="Demo source GitLab (token is fake)",
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=1),
        )
        dev = GitLabInstance(
            name="Development",
            url="https://gitlab.dev.example.com",
            access_token="demo-token-not-a-real-token",
            description="Demo target GitLab (token is fake)",
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=2),
        )
        db.add_all([prod, dev])
        db.commit()
        db.refresh(prod)
        db.refresh(dev)

        # Project pairs
        pair_a = ProjectPair(
            name="Example: platform/api",
            source_instance_id=prod.id,
            source_project_id="platform/api",
            target_instance_id=dev.id,
            target_project_id="platform/api-mirror",
            bidirectional=True,
            sync_enabled=True,
            sync_interval_minutes=60,
            created_at=now - timedelta(days=9),
            updated_at=now - timedelta(hours=2),
            last_sync_at=now - timedelta(minutes=18),
        )
        pair_b = ProjectPair(
            name="Example: docs/site (one-way)",
            source_instance_id=prod.id,
            source_project_id="docs/site",
            target_instance_id=dev.id,
            target_project_id="docs/site-mirror",
            bidirectional=False,
            sync_enabled=False,
            sync_interval_minutes=120,
            created_at=now - timedelta(days=8),
            updated_at=now - timedelta(days=1),
            last_sync_at=None,
        )
        db.add_all([pair_a, pair_b])
        db.commit()
        db.refresh(pair_a)
        db.refresh(pair_b)

        # User mappings (a couple of examples)
        db.add_all(
            [
                UserMapping(
                    source_instance_id=prod.id,
                    source_username="alice",
                    target_instance_id=dev.id,
                    target_username="alice.dev",
                    created_at=now - timedelta(days=7),
                    updated_at=now - timedelta(days=7),
                ),
                UserMapping(
                    source_instance_id=prod.id,
                    source_username="bob",
                    target_instance_id=dev.id,
                    target_username="bobby",
                    created_at=now - timedelta(days=7),
                    updated_at=now - timedelta(days=3),
                ),
            ]
        )
        db.commit()

        # Synced issue mappings for pair_a
        synced_rows = []
        for i in range(1, 13):
            synced_rows.append(
                SyncedIssue(
                    project_pair_id=pair_a.id,
                    source_issue_iid=i,
                    source_issue_id=1000 + i,
                    source_updated_at=now - timedelta(days=1, minutes=i * 3),
                    target_issue_iid=500 + i,
                    target_issue_id=9000 + i,
                    target_updated_at=now - timedelta(days=1, minutes=i * 2),
                    last_synced_at=now - timedelta(minutes=20 - (i % 5)),
                    sync_hash=f"demo-hash-{i}",
                )
            )
        db.add_all(synced_rows)
        db.commit()

        # Sync logs (mix of statuses)
        db.add_all(
            [
                SyncLog(
                    project_pair_id=pair_a.id,
                    source_issue_iid=3,
                    target_issue_iid=503,
                    status=SyncStatus.SUCCESS,
                    direction=SyncDirection.SOURCE_TO_TARGET,
                    message="Updated title/labels and synced 2 new comments",
                    created_at=now - timedelta(minutes=18),
                ),
                SyncLog(
                    project_pair_id=pair_a.id,
                    source_issue_iid=7,
                    target_issue_iid=507,
                    status=SyncStatus.CONFLICT,
                    direction=SyncDirection.SOURCE_TO_TARGET,
                    message="Conflict detected: issue updated on both sides",
                    created_at=now - timedelta(hours=2, minutes=5),
                ),
                SyncLog(
                    project_pair_id=pair_a.id,
                    source_issue_iid=11,
                    target_issue_iid=None,
                    status=SyncStatus.FAILED,
                    direction=SyncDirection.SOURCE_TO_TARGET,
                    message="Failed to create target issue (permission denied)",
                    created_at=now - timedelta(hours=6),
                ),
            ]
        )
        db.commit()

        # Conflicts (one unresolved, one resolved)
        c1 = Conflict(
            project_pair_id=pair_a.id,
            synced_issue_id=None,
            source_issue_iid=7,
            target_issue_iid=507,
            conflict_type="concurrent_update",
            description="Source and target issue were updated within the same sync window.",
            resolved=False,
            created_at=now - timedelta(hours=2),
        )
        c2 = Conflict(
            project_pair_id=pair_a.id,
            synced_issue_id=None,
            source_issue_iid=11,
            target_issue_iid=None,
            conflict_type="target_permission_denied",
            description="Target token lacked permissions to create issues.",
            resolved=True,
            resolved_at=now - timedelta(hours=5, minutes=30),
            resolution_notes="Adjusted target token scopes and re-ran sync.",
            created_at=now - timedelta(hours=6),
        )
        db.add_all([c1, c2])
        db.commit()

    finally:
        db.close()

    return SeedResult(db_path=db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo IssueBridge SQLite DB")
    parser.add_argument(
        "--db",
        default="./data/demo_issuebridge.db",
        help="Path to SQLite DB file to create (default: ./data/demo_issuebridge.db)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete existing DB file first",
    )
    args = parser.parse_args()

    result = seed_demo_db(Path(args.db), overwrite=bool(args.overwrite))
    print(f"Seeded demo DB at: {result.db_path}")


if __name__ == "__main__":
    main()
