"""Ponto de entrada (``uvicorn rag_central.main:app``); o que não estiver configurado fica de fora.

Sem chaves de assinatura o JWKS sai vazio; sem BD o ``/readyz`` diz que não está pronto.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rag_core.clock import SystemClock
from rag_core.config import Settings, get_settings
from rag_core.logging import configure_logging
from rag_core.modules import ModuleRegistry

from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver, build_identity_verifier
from rag_central.auth_admin import SupabaseAuthAdmin
from rag_central.db import Database, make_pool
from rag_central.features import FeatureService
from rag_central.signing import Signer, load_keys


def build_deps(settings: Settings) -> CentralDeps:
    clock = SystemClock()
    signer = None
    if settings.central_signing_keys is not None and settings.central_issuer:
        signer = Signer(load_keys(settings.central_signing_keys), settings.central_issuer, clock)
    auth = None
    db = None
    readiness: dict[str, Callable[[], bool]] = {}
    if settings.database_url is not None:
        pool = make_pool(settings.database_url.get_secret_value())
        pool.open(wait=False)
        db = Database(pool)
        auth = CentralAuth(build_identity_verifier(settings), PrincipalResolver(db, clock))
        readiness["database"] = db.ping
    features = None
    modules_dir = Path(__file__).resolve().parents[3] / "modules"
    if db is not None and modules_dir.is_dir():
        features = FeatureService(db, ModuleRegistry.load(modules_dir), clock)
    admin = None
    if settings.supabase_url and settings.supabase_service_role_key is not None:
        admin = SupabaseAuthAdmin(settings.supabase_url, settings.supabase_service_role_key)
    return CentralDeps(
        signer=signer, auth=auth, db=db, auth_admin=admin, features=features, readiness=readiness
    )


_settings = get_settings()
configure_logging("central-api", _settings.log_level, _settings.log_tracebacks)
app = create_app(_settings, build_deps(_settings))
