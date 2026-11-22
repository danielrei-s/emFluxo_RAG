"""Montagem das dependências reais do gateway a partir das ``Settings`` (F6-T07).

Cada parte só é montada se estiver configurada; sem ela o gateway arranca na mesma (``/healthz``
responde) mas ``/readyz`` diz que não está pronto e o chat recusa pedidos.
"""

from __future__ import annotations

from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.interfaces import Clock, TenantPolicyProvider, UsageRecorder
from rag_core.policy_provider import StaticPolicyProvider
from rag_core.providers.factory import build_llm_providers

from rag_gateway.app import GatewayDeps
from rag_gateway.auth import build_authenticator
from rag_gateway.central_providers import (
    CentralDeviceStatusProvider,
    CentralPolicyProvider,
    CentralPrincipalResolver,
    CentralUsageRecorder,
)
from rag_gateway.chat import ChatService
from rag_gateway.limits import GatewayLimiter, InMemoryRateLimiter
from rag_gateway.ports import DeviceStatusProvider, NoDevices, NoPrincipals, PrincipalResolver
from rag_gateway.routing import ModelRouter
from rag_gateway.usage import InMemoryUsageRecorder


def build_deps(settings: Settings, clock: Clock | None = None) -> GatewayDeps:
    """Com ``RAG_CENTRAL_API_URL`` e ``RAG_INTERNAL_API_KEY`` tudo vem da Central API; sem eles
    usa-se o ficheiro de políticas, consumo em memória e só tokens de serviço (staging inicial)."""
    clock = clock or SystemClock()
    resolver: PrincipalResolver = NoPrincipals()
    devices: DeviceStatusProvider = NoDevices()
    policies: TenantPolicyProvider | None = None
    usage: UsageRecorder = InMemoryUsageRecorder(clock)
    if settings.central_api_url and settings.internal_api_key:
        url, key = settings.central_api_url, settings.internal_api_key
        resolver = CentralPrincipalResolver(url, key, clock, None)
        devices = CentralDeviceStatusProvider(url, key, clock, None)
        policies = CentralPolicyProvider(url, key, clock, None)
        usage = CentralUsageRecorder(url, key, clock)
    elif settings.gateway_policies_file is not None and settings.gateway_policies_file.is_file():
        policies = StaticPolicyProvider.from_yaml(settings.gateway_policies_file)
    authenticator = None
    if settings.central_issuer and settings.central_jwks_url:
        authenticator = build_authenticator(settings, resolver, devices)
    chat = None
    if policies is not None:
        chat = ChatService(
            policies=policies,
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
