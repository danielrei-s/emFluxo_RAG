"""Worker de jobs (F7-T07): reserva em ``system_tx`` e executa o handler em ``tenant_tx``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass

from psycopg import Cursor
from psycopg.rows import DictRow
from rag_core.errors import RagError
from rag_core.logging import get_logger

from rag_central import jobs
from rag_central.db import Database


@dataclass(frozen=True)
class JobContext:
    """O que um handler recebe: o acesso à BD já preso ao tenant do job."""

    db: Database
    job: jobs.Job

    def tx(self, user_id: str | None = None) -> AbstractContextManager[Cursor[DictRow]]:
        return self.db.tenant_tx(self.job.tenant_id, user_id)


Handler = Callable[[jobs.Job, JobContext], None]


class Worker:
    def __init__(self, db: Database, handlers: dict[str, Handler], worker_id: str) -> None:
        self._db = db
        self._handlers = dict(handlers)
        self._worker_id = worker_id

    def run_once(self) -> bool:
        """Processa no máximo um job; devolve ``False`` quando não havia nenhum pronto."""
        with self._db.system_tx("job_claim") as cur:
            job = jobs.claim(cur, self._worker_id, sorted(self._handlers))
        if job is None:
            return False
        log = get_logger("worker")
        try:
            self._handlers[job.kind](job, JobContext(self._db, job))
        except Exception as exc:  # o texto da exceção nunca é guardado nem registado (INV-03)
            code = exc.code if isinstance(exc, RagError) else "handler_error"
            with self._db.system_tx("job_claim") as cur:
                status = jobs.fail(cur, job.id, code)
            log.warning("job_failed", job_id=job.id, error_code=code, status=status)
        else:
            with self._db.system_tx("job_claim") as cur:
                jobs.complete(cur, job.id)
            log.info("job_done", job_id=job.id)
        return True

    def drain(self, limit: int = 1000) -> Iterator[None]:
        """Corre até a fila ficar vazia (ou ``limit`` jobs); útil em testes e em lotes."""
        for _ in range(limit):
            if not self.run_once():
                return
            yield
