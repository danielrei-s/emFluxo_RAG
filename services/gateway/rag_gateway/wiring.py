"""Montagem das dependências reais do gateway a partir das ``Settings`` (F6-T07).

Cada parte só é montada se estiver configurada; sem ela o gateway arranca na mesma (``/healthz``
responde) mas ``/readyz`` diz que não está pronto e o chat recusa pedidos.
"""

from __future__ import annotations

from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.interfaces import Clock
from rag_core.policy_provider import StaticPolicyProvider
from rag_core.providers.factory import build_llm_providers

from rag_gateway.app import GatewayDeps
from rag_gateway.auth import build_authenticator
from rag_gateway.chat import ChatService
from rag_gateway.limits import GatewayLimiter, InMemoryRateLimiter
from rag_gateway.ports import NoDevices, NoPrincipals
from rag_gateway.routing import ModelRouter
from rag_gateway.usage import InMemoryUsageRecorder


def build_deps(settings: Settings, clock: Clock | None = None) -> GatewayDeps:
    clock = clock or SystemClock()
    authenticator = None
    if settings.central_issuer and settings.central_jwks_url:
        authenticator = build_authenticator(settings, NoPrincipals(), NoDevices())
    chat = None
    policies_file = settings.gateway_policies_file
    if policies_file is not None and policies_file.is_file():
        usage = InMemoryUsageRecorder(clock)  # a persistência chega com a BD central (F7/F8)
        chat = ChatService(
            policies=StaticPolicyProvider.from_yaml(policies_file),
            limiter=GatewayLimiter(InMemoryRateLimiter(clock), usage),
            usage=usage,
            router=ModelRouter(build_llm_providers(settings), clock),
            clock=clock,
        )
    return GatewayDeps(
        readiness={"auth": lambda: authenticator is not None, "chat": lambda: chat is not None},
        authenticator=authenticator,
        chat=chat,
    )
