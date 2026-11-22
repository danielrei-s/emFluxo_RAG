"""Escolha de modelo, fallback e disjuntor por fornecedor (F6-T04)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from rag_core.errors import AccessDenied, UpstreamError
from rag_core.interfaces import Clock, LLMProvider, TenantPolicy
from rag_core.types import ChatMessage, GenerationParams, LLMResult

FAILURE_THRESHOLD = 3
OPEN_SECONDS = 30.0


class CircuitBreaker:
    """Abre após ``threshold`` falhas seguidas e só deixa passar de novo ao fim de ``open_s``."""

    def __init__(
        self, clock: Clock, threshold: int = FAILURE_THRESHOLD, open_s: float = OPEN_SECONDS
    ):
        self._clock = clock
        self._threshold = threshold
        self._open_s = open_s
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock.now().timestamp() - self._opened_at >= self._open_s:
            self._opened_at = None  # meio aberto: deixa passar um pedido de teste
            self._failures = self._threshold - 1  # uma nova falha volta a abrir
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock.now().timestamp()


@dataclass(frozen=True)
class RoutedResult:
    result: LLMResult
    alias: str
    skipped: tuple[str, ...] = field(
        default=()
    )  # aliases que falharam ou estavam com o disjuntor aberto


class ModelRouter:
    """Escolhe o alias segundo a política e cai para o seguinte quando um fornecedor falha."""

    def __init__(self, providers: Mapping[str, LLMProvider], clock: Clock) -> None:
        self._providers = dict(providers)
        self._breakers = {alias: CircuitBreaker(clock) for alias in providers}

    def order(self, requested: str | None, policy: TenantPolicy) -> list[str]:
        """Pedido primeiro (se houver), depois os restantes permitidos pela ordem da política."""
        allowed = list(policy.allowed_models)
        if requested is not None and requested not in allowed:
            raise AccessDenied("model_not_allowed")
        if requested is None:
            return allowed
        return [requested, *(a for a in allowed if a != requested)]

    def _candidates(self, order: Sequence[str]) -> Iterator[tuple[str, LLMProvider, list[str]]]:
        skipped: list[str] = []
        for alias in order:
            provider = self._providers.get(alias)
            breaker = self._breakers.get(alias)
            if provider is None or breaker is None or not breaker.allow():
                skipped.append(alias)
                continue
            yield alias, provider, skipped

    def generate(
        self,
        requested: str | None,
        policy: TenantPolicy,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
    ) -> RoutedResult:
        failed: list[str] = []
        for alias, provider, skipped in self._candidates(self.order(requested, policy)):
            try:
                result = provider.generate(messages, params=params)
            except UpstreamError:
                self._breakers[alias].record_failure()
                failed.append(alias)
                continue
            self._breakers[alias].record_success()
            return RoutedResult(result, alias, tuple([*skipped, *failed]))
        raise UpstreamError("all_models_failed")

    def stream(
        self,
        requested: str | None,
        policy: TenantPolicy,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
    ) -> Iterator[tuple[str, str]]:
        """Pares ``(alias, pedaço)``. Só há fallback antes do primeiro pedaço de texto."""
        for alias, provider, _ in self._candidates(self.order(requested, policy)):
            tokens = provider.stream(messages, params=params)
            try:
                first = next(tokens, None)
            except UpstreamError:
                self._breakers[alias].record_failure()
                continue
            self._breakers[alias].record_success()
            if first is not None:
                yield alias, first
            try:
                for token in tokens:
                    yield alias, token
            except UpstreamError:
                self._breakers[alias].record_failure()
                raise  # a meio do fluxo já não se muda de modelo
            return
        raise UpstreamError("all_models_failed")
