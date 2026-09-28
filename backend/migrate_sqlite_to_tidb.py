"""
Migrate the local SQLite database (backend/Shongkho_test.db) into TiDB Cloud.

Reads TIDB_DATABASE_URL from backend/.env (must be the mysql+pymysql:// URL),
reflects both schemas, disables FK checks for the load, copies every table,
and verifies row counts. Safe to re-run: target tables are cleared first.

Usage:  python migrate_sqlite_to_tidb.py [--sqlite PATH]
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, inspect, text

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SQLITE_PATH = BASE_DIR / "Shongkho_test.db"
if "--sqlite" in sys.argv:
    SQLITE_PATH = Path(sys.argv[sys.argv.index("--sqlite") + 1])

CHUNK = 500


def main():
    import database  # loads .env, applies MySQL connect_args (TLS/utf8mb4)

    src = create_engine(f"sqlite:///{SQLITE_PATH.as_posix()}")
    dst = database.get_engine()

    src_meta, dst_meta = MetaData(), MetaData()
    src_meta.reflect(bind=src)
    dst_meta.reflect(bind=dst)

    tables = [t for t in src_meta.sorted_tables if t.name in dst_meta.tables]
    skipped = [t.name for t in src_meta.sorted_tables if t.name not in dst_meta.tables]
    if skipped:
        print(f"[warn] tables with no TiDB counterpart (skipped): {skipped}")

    total_copied = 0
    with dst.connect() as dconn:
        dconn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in tables:
            dtable = dst_meta.tables[table.name]
            dconn.execute(dtable.delete())  # idempotent re-runs
            dconn.commit()

            with src.connect() as sconn:
                rows = [dict(r._mapping) for r in sconn.execute(table.select())]

            copied = 0
            for i in range(0, len(rows), CHUNK):
                batch = []
                for row in rows[i : i + CHUNK]:
                    batch.append({k: v for k, v in row.items() if k in dtable.columns})
                if batch:
                    dconn.execute(dtable.insert(), batch)
                    copied += len(batch)
            dconn.commit()
            total_copied += copied
            print(f"  {table.name:<22} {len(rows):>6} rows -> TiDB")

        dconn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        dconn.commit()

    print(f"\nDone. {total_copied} rows copied across {len(tables)} tables.")

    # ---- verification: source vs target counts ----
    print("\nVerification (sqlite -> tidb):")
    ok = True
    with src.connect() as sconn, dst.connect() as dconn:
        for table in tables:
            n_src = sconn.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar()
            n_dst = dconn.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar()
            mark = "OK " if n_src == n_dst else "MISMATCH"
            if n_src != n_dst:
                ok = False
            print(f"  [{mark}] {table.name:<22} {n_src:>6} -> {n_dst:>6}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
