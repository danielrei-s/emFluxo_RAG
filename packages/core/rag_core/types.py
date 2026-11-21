"""Modelos de domínio do core (contrato C6, congelado).

Todos os modelos são imutáveis e rejeitam campos desconhecidos. Mudar este módulo exige ADR.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Frozen(BaseModel):
    """Base imutável que rejeita campos extra."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Classification(StrEnum):
    """Classificação de sensibilidade de um documento."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


CLASSIFICATION_RANK: dict[Classification, int] = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}


class Role(StrEnum):
    """Papel de um utilizador num tenant."""

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.MEMBER: 2,
    Role.EDITOR: 3,
    Role.ADMIN: 4,
    Role.OWNER: 5,
}


class Product(StrEnum):
    """Produto a que um utilizador tem direito (entitlement)."""

    WEB = "web"
    LOCAL = "local"


class Origin(StrEnum):
    """De onde vem um documento ou chunk."""

    CENTRAL = "central"
    LOCAL = "local"


class DetectedType(StrEnum):
    """Tipo de ficheiro detetado pelo conteúdo."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    HTML = "html"
    EML = "eml"
    MSG = "msg"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"


class Acl(Frozen):
    """Lista de controlo de acesso de um documento."""

    all_members: bool = False
    users: frozenset[str] = frozenset()
    groups: frozenset[str] = frozenset()


class Principal(Frozen):
    """Identidade já resolvida no servidor para um pedido."""

    tenant_id: str
    user_id: str
    role: Role
    groups: frozenset[str] = frozenset()
    products: frozenset[Product] = frozenset()
    aal: Literal["aal1", "aal2"] = "aal1"
    device_id: str | None = None


class AccessFilter(Frozen):
    """Filtro de acesso aplicado na recuperação, antes do LLM (INV-02)."""

    tenant_id: str
    user_id: str
    role: Role
    groups: frozenset[str] = frozenset()
    origins: frozenset[Origin] = frozenset({Origin.CENTRAL})
    exclude_local_only: bool = False
    exclude_classifications: frozenset[Classification] = frozenset()
    workspace_ids: frozenset[str] | None = None  # None = todos

    @classmethod
    def for_principal(
        cls,
        p: Principal,
        *,
        origins: frozenset[Origin],
        exclude_local_only: bool = False,
        exclude_classifications: frozenset[Classification] = frozenset(),
    ) -> AccessFilter:
        """Constrói o filtro a partir do ``Principal``, copiando tenant, utilizador e grupos."""
        return cls(
            tenant_id=p.tenant_id,
            user_id=p.user_id,
            role=p.role,
            groups=p.groups,
            origins=origins,
            exclude_local_only=exclude_local_only,
            exclude_classifications=exclude_classifications,
        )


BlockKind = Literal["heading", "paragraph", "list_item", "table", "image_text", "email_header"]


class Block(Frozen):
    """Bloco de texto estruturado extraído de um documento."""

    kind: BlockKind
    text: str  # tabelas: versão markdown
    level: int | None = None  # headings: 1..6
    page: int | None = None  # 1-based; None se não houver páginas
    rows: tuple[tuple[str, ...], ...] | None = None  # tabelas: 1.ª linha = cabeçalho
    flags: frozenset[str] = frozenset()  # ex.: {"hidden_text_removed", "ocr"}


class RawAttachment(Frozen):
    """Anexo em bruto; os bytes serializam-se em base64 no JSON."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )
    filename: str
    data: bytes


class StructuredDocument(Frozen):
    """Resultado de um parser: o mesmo formato nos perfis lite e full."""

    title: str | None = None
    detected_type: DetectedType
    blocks: tuple[Block, ...]
    page_count: int | None = None
    language: str | None = None
    parser_name: str
    parser_version: str
    meta: dict[str, str] = {}  # ex.: {"email_from_domain": "exemplo.pt"}
    warnings: tuple[str, ...] = ()
    attachments: tuple[RawAttachment, ...] = ()


class SourceFile(Frozen):
    """Ficheiro de origem a ingerir, com a sua ACL e classificação."""

    tenant_id: str
    workspace_id: str
    doc_id: str  # central: UUID da BD · local: ids.doc_id_local(...)
    source_uri: str  # central: "upload://<doc_id>/<ficheiro>" · local: "file://<caminho relativo>"
    filename: str
    acl: Acl
    classification: Classification = Classification.INTERNAL
    origin: Origin = Origin.CENTRAL
    local_only: bool = False
    parent_doc_id: str | None = None


class ChunkMetadata(Frozen):
    """Metadados de um chunk (INV-01, INV-02: tenant, ACL e classificação viajam com ele)."""

    tenant_id: str
    workspace_id: str
    doc_id: str
    source_uri: str
    title: str | None = None
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    content_hash: str  # sha256 hex do texto do chunk
    doc_hash: str  # sha256 hex do ficheiro original
    acl: Acl
    classification: Classification
    language: str | None = None
    ingested_at: datetime
    parser_version: str
    origin: Origin
    local_only: bool = False
    flags: frozenset[str] = frozenset()

    @field_validator("content_hash", "doc_hash")
    @classmethod
    def _sha256(cls, v: str) -> str:
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("expected lowercase sha256 hex")
        return v

    @model_validator(mode="after")
    def _pages(self) -> ChunkMetadata:
        if self.page_start and self.page_end and self.page_end < self.page_start:
            raise ValueError("page_end < page_start")
        return self


class Chunk(Frozen):
    """Fragmento de documento indexável."""

    chunk_id: str  # ids.chunk_id(doc_id, ordinal, content_hash)
    ordinal: int
    text: str
    metadata: ChunkMetadata
    embedding: tuple[float, ...] | None = None
    embedding_model: str | None = None


class SearchHit(Frozen):
    """Resultado de pesquisa, com a fase do pipeline que o produziu."""

    chunk: Chunk
    score: float
    stage: Literal["vector", "keyword", "fused", "reranked"]


class ChatMessage(Frozen):
    """Mensagem de uma conversa enviada ao LLM."""

    role: Literal["system", "user", "assistant"]
    content: str


class GenerationParams(Frozen):
    """Parâmetros de geração."""

    max_tokens: int = 700
    temperature: float = 0.1


class LLMResult(Frozen):
    """Resposta de um LLM."""

    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    finish_reason: str | None = None


class Citation(Frozen):
    """Citação de uma fonte numa resposta."""

    index: int  # o [n] da resposta
    chunk_id: str
    doc_id: str
    source_uri: str
    title: str | None = None
    page_start: int | None = None


class SentExcerpt(Frozen):  # painel de transparência do Produto B
    """Excerto enviado a um serviço externo, tal como foi enviado."""

    chunk_id: str
    destination: str  # ex.: "gateway:https://gw.exemplo.pt/v1"
    text_sent: str  # exatamente o que foi enviado (após redação)
    redactions: int = 0


AnswerKind = Literal["grounded", "general_knowledge", "not_found", "refused"]


class Answer(Frozen):
    """Resposta final ao utilizador."""

    kind: AnswerKind
    text: str
    citations: tuple[Citation, ...] = ()
    used_chunk_ids: tuple[str, ...] = ()
    sent_excerpts: tuple[SentExcerpt, ...] = ()
    warnings: tuple[str, ...] = ()  # ex.: "local_only_excluded", "central_unavailable"
    model: str | None = None
    timings_ms: dict[str, int] = {}
