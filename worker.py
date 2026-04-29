from __future__ import annotations

import asyncio
import logging
from typing import Any

import config
from feeds import poll_rest, run_ws, state
from persistence import run_persistence


logger = logging.getLogger(__name__)


class PostgresWorkerLock:
    """Postgres advisory lock held for the lifetime of one ingestion worker."""

    def __init__(self, database_url: str, lock_id: int) -> None:
        self.database_url = database_url
        self.lock_id = lock_id
        self.conn: Any = None

    async def acquire(self) -> None:
        """Wait until the singleton ingestion lock is available."""
        while True:
            acquired = await asyncio.to_thread(self._try_acquire)
            if acquired:
                logger.info("Acquired worker advisory lock %s.", self.lock_id)
                return
            logger.warning(
                "Worker advisory lock %s is held elsewhere; retrying in %.1fs.",
                self.lock_id,
                config.WORKER_LOCK_RETRY_SEC,
            )
            await asyncio.sleep(config.WORKER_LOCK_RETRY_SEC)

    async def release(self) -> None:
        """Release the advisory lock and close its connection."""
        await asyncio.to_thread(self._release)

    def _try_acquire(self) -> bool:
        if self.conn is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("psycopg is required for postgres locks") from exc
            self.conn = psycopg.connect(self.database_url)

        with self.conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (self.lock_id,))
            return bool(cur.fetchone()[0])

    def _release(self) -> None:
        if self.conn is None:
            return
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
            self.conn.commit()
        finally:
            self.conn.close()
            self.conn = None


async def _maybe_acquire_lock() -> PostgresWorkerLock | None:
    if config.DATABASE_BACKEND != "postgres":
        return None
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for postgres worker mode")
    lock = PostgresWorkerLock(config.DATABASE_URL, config.POSTGRES_WORKER_LOCK_ID)
    await lock.acquire()
    return lock


async def main() -> None:
    """Run market ingestion, REST polling, and persistence without UI rendering."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    lock = await _maybe_acquire_lock()
    try:
        await asyncio.gather(run_ws(), poll_rest(), run_persistence(state))
    finally:
        if lock is not None:
            await lock.release()


if __name__ == "__main__":
    asyncio.run(main())
