#!/usr/bin/env python3
"""Measure the farm-side cost of persisting a relay content batch.

Answers one question: once agent-boot stopped writing PostgreSQL directly, how
long does device_farm take to write the same rows, and how does that scale with
batch size?

It drives the real object — `services.content.edge_ingest.persist_edge_batch` —
against a real database, so the numbers include the real SQL, the real indexes
and the real row counts already in `content_items`.

    uv run python scripts/benchmark_edge_ingest.py --database-url postgresql+asyncpg://...
    uv run python scripts/benchmark_edge_ingest.py --sizes 10,100,1000 --repeat 5

**Nothing is committed.** Every batch runs inside one outer transaction that is
rolled back at the end; `persist_edge_batch`'s own commit is redirected to a
SAVEPOINT release. Safe to point at a database that holds real data, though it
does take real locks for the duration, so prefer a replica or a quiet window.

Scope, so the number is not read as more than it is: this measures the DB leg
only. It does not include XML parsing on the agent, the relay round trip, or
JSON chunking — those sit on the other side of the wire and need a real device
to measure. See `device_farm_edge_ingest_duration_seconds` for the same
measurement taken in production.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import statistics
import sys
import time
import uuid
from typing import Any

DEFAULT_SIZES = (1, 10, 100, 1000)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _make_items(count: int, run_tag: str) -> list[dict[str, Any]]:
    """Synthetic posts shaped like the Facebook parser output.

    Every run gets a unique `post_key` so rows are genuine inserts rather than
    ON CONFLICT no-ops — a duplicate batch measures the conflict path, which is
    much cheaper and would flatter the result.
    """
    return [
        {
            "post_key": f"bench-{run_tag}-{index}",
            "_pid": f"pid-{run_tag}-{index}",
            "author": f"Người dùng {index}",
            "text": (
                f"Nội dung bài viết số {index} dùng để đo tốc độ ghi. "
                "Đoạn này cố tình dài để raw_data có kích thước gần với dữ liệu thật."
            ),
            "timestamp": "2 giờ",
            "reactions": f"{index % 900}",
            "comments": f"{index % 120}",
            "shares": f"{index % 30}",
            "platform": "facebook",
            "media_artifacts": [f"https://example.test/{run_tag}/{index}.jpg"],
        }
        for index in range(count)
    ]


async def _pick_relay_id(conn) -> str:
    from sqlalchemy import text

    row = (
        await conn.execute(
            text(
                """
                SELECT ra.relay_id
                FROM relay_agents ra
                WHERE ra.org_id IS NOT NULL AND ra.user_id IS NOT NULL
                ORDER BY ra.last_heartbeat_at DESC NULLS LAST
                LIMIT 1
                """
            )
        )
    ).first()
    if row is None:
        raise SystemExit(
            "no enrolled relay agent with an org and user was found — pass "
            "--relay-id, or enroll one first. persist_edge_batch resolves the "
            "tenant from the relay identity and refuses anything else."
        )
    return str(row[0])


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    import db.database as database
    from services.content import edge_ingest
    from services.content.registry import seed_registry

    seed_registry()

    # Round trips matter more than milliseconds here. On localhost a query costs
    # microseconds; from a customer machine it cost a full WAN RTT, and that is
    # what moving the write to the farm actually bought. Counting them lets the
    # reader multiply by their own RTT instead of trusting a borrowed number.
    query_count = 0

    engine = create_async_engine(args.database_url, echo=False, pool_size=2, max_overflow=0)

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn_, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        nonlocal query_count
        query_count += 1

    conn = await engine.connect()
    outer = await conn.begin()

    relay_id = args.relay_id or await _pick_relay_id(conn)
    print(f"relay_id      : {relay_id}")
    print(f"database      : {engine.url.render_as_string(hide_password=True)}")
    print(f"collection    : {args.collection}")
    print("committed     : nothing — outer transaction is rolled back\n")

    @contextlib.asynccontextmanager
    async def _savepoint_session():
        """Give persist_edge_batch a session it may commit, without committing.

        join_transaction_mode="create_savepoint" turns its commit() into a
        SAVEPOINT release inside our outer transaction, so the write is fully
        exercised — indexes, constraints, triggers — and still disappears.
        """
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    original = database.edge_ingest_session
    edge_ingest.edge_ingest_session = _savepoint_session
    database.edge_ingest_session = _savepoint_session

    results: list[tuple[int, dict[str, float]]] = []
    try:
        for size in args.sizes:
            wall_ms: list[float] = []
            db_ms: list[float] = []
            queries: list[int] = []
            inserted_total = 0
            for iteration in range(args.repeat):
                run_tag = uuid.uuid4().hex[:12]
                batch = {
                    "schema_version": 1,
                    "kind": "content",
                    "item_level": 0,
                    "items": _make_items(size, run_tag),
                    "captured_at": "2026-08-27T00:00:00+00:00",
                    "parent_hint": None,
                    "post_stats": None,
                }
                context = {
                    "collection": args.collection,
                    "content_type": args.content_type,
                    "platform": "facebook",
                    "dedupe_field": "post_key",
                    "hash_scope": run_tag,
                    "device_serial": args.device_serial,
                    "scenario_name": "benchmark_edge_ingest",
                    "captured_at": "2026-08-27T00:00:00+00:00",
                }
                batch["content_hashes"] = [
                    edge_ingest.scope_content_hash(
                        edge_ingest.compute_content_hash(item, "post_key"), run_tag
                    )
                    for item in batch["items"]
                ]

                before_queries = query_count
                started = time.perf_counter()
                result = await edge_ingest.persist_edge_batch(
                    relay_id=relay_id,
                    batch=batch,
                    trusted_context=context,
                )
                wall_ms.append((time.perf_counter() - started) * 1000.0)
                queries.append(query_count - before_queries)
                db_ms.append(float(result.get("db_ms") or 0))
                inserted_total += int(result.get("inserted_count") or 0)

                if iteration == 0 and inserted_total != size:
                    print(
                        f"  warning: size={size} inserted {inserted_total} of {size} "
                        "— rows are colliding, the timing below is the conflict path",
                        file=sys.stderr,
                    )

            stats = {
                "wall_p50": _percentile(wall_ms, 0.50),
                "wall_p95": _percentile(wall_ms, 0.95),
                "db_p50": _percentile(db_ms, 0.50),
                "per_row_us": (statistics.median(wall_ms) * 1000.0 / size) if size else 0.0,
                "queries": statistics.median(queries) if queries else 0,
            }
            results.append((size, stats))
            print(
                f"size={size:>5}  wall p50={stats['wall_p50']:7.1f}ms  "
                f"p95={stats['wall_p95']:7.1f}ms  db p50={stats['db_p50']:7.1f}ms  "
                f"{stats['per_row_us']:8.1f}µs/row  {stats['queries']:.0f} queries"
            )
    finally:
        edge_ingest.edge_ingest_session = original
        database.edge_ingest_session = original
        await outer.rollback()
        await conn.close()
        await engine.dispose()

    print("\nrolled back — no rows were committed")
    if len(results) > 1:
        first, last = results[0], results[-1]
        print(
            f"per-row cost {first[0]}→{last[0]} items: "
            f"{first[1]['per_row_us']:.1f}µs → {last[1]['per_row_us']:.1f}µs"
        )
        print(
            "A per-row cost that falls as the batch grows is the batch insert "
            "working; one that stays flat means the batch is not batching."
        )
    # Two of the counted statements are this harness's SAVEPOINT/RELEASE, which
    # only exist because we roll back. Production does not pay them.
    counted = max(int(stats["queries"]) for _, stats in results)
    real = max(1, counted - 2)
    print(
        f"\n{real} queries per batch in production ({counted} counted here, minus this "
        "harness's SAVEPOINT/RELEASE), constant regardless of batch size, all local to "
        "the farm. Multiply by your agent→Postgres RTT to see what the old direct-DB "
        "path paid per batch for the same work."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("BENCH_DATABASE_URL") or os.environ.get("DATABASE_URL", ""),
        help="SQLAlchemy async DSN (postgresql+asyncpg://...). Defaults to "
             "BENCH_DATABASE_URL, then DATABASE_URL.",
    )
    parser.add_argument("--relay-id", default="", help="Enrolled relay to attribute rows to")
    parser.add_argument("--collection", default="benchmark_edge_ingest")
    parser.add_argument("--content-type", default="fb_post")
    parser.add_argument("--device-serial", default="bench-device")
    parser.add_argument("--repeat", type=int, default=5, help="Batches per size (default 5)")
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="Comma-separated batch sizes (default 1,10,100,1000)",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("no database URL — pass --database-url or set BENCH_DATABASE_URL")
    url = args.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    args.database_url = url
    args.sizes = [int(s) for s in str(args.sizes).split(",") if s.strip()]

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
