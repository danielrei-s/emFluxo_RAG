"""Registo de consumo (F6-T03): só metadados, nunca conteúdo (INV-03)."""

from __future__ import annotations

from rag_core.interfaces import Clock, UsageEvent


class InMemoryUsageRecorder:
    """Guarda os eventos em memória; o total mensal é o do mês civil (UTC) do relógio."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> None:
        self.events.append(event)

    def tokens_used_this_month(self, tenant_id: str) -> int:
        now = self._clock.now()
        return sum(
            e.tokens_in + e.tokens_out
            for e in self.events
            if e.tenant_id == tenant_id
            and e.status == "ok"
            and (e.at.year, e.at.month) == (now.year, now.month)
        )
