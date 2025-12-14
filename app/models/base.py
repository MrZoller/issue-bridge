"""Database base configuration"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_conflicts_make_target_issue_iid_nullable():
    """
    SQLite-only schema upgrade:
    Historically `conflicts.target_issue_iid` was created as NOT NULL, but the
    app can log conflicts without a target issue (NULL target_issue_iid).
    SQLite can't ALTER COLUMN, so we rebuild the table when needed.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        # If table doesn't exist, nothing to migrate.
        tables = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "conflicts" not in tables:
            return

        info_rows = conn.exec_driver_sql("PRAGMA table_info(conflicts)").fetchall()
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        target_col = next((r for r in info_rows if r[1] == "target_issue_iid"), None)
        if target_col is None:
            return

        notnull = int(target_col[3] or 0)
        if notnull == 0:
            return  # already nullable

        # Rebuild conflicts table using current SQLAlchemy metadata.
        conn.exec_driver_sql("ALTER TABLE conflicts RENAME TO conflicts_old")

        # Ensure models are imported so metadata contains the current schema.
        from app.models import Base as ModelsBase  # noqa: WPS433 (runtime import)

        ModelsBase.metadata.tables["conflicts"].create(bind=conn)

        cols = (
            "id, project_pair_id, synced_issue_id, source_issue_iid, target_issue_iid, "
            "conflict_type, description, source_data, target_data, resolved, resolved_at, "
            "resolution_notes, created_at"
        )
        conn.exec_driver_sql(
            f"INSERT INTO conflicts ({cols}) SELECT {cols} FROM conflicts_old"
        )
        conn.exec_driver_sql("DROP TABLE conflicts_old")


def init_db():
    """Initialize database"""
    # Ensure all models are imported so SQLAlchemy metadata is populated.
    # (Without this, create_all() may create no tables in some import orders.)
    import app.models  # noqa: F401  (import for side-effects)

    Base.metadata.create_all(bind=engine)
    _sqlite_conflicts_make_target_issue_iid_nullable()
