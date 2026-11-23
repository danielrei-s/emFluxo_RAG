"""Testes de F11-T03: sugestão de classificação pelo nome e caminho."""

from __future__ import annotations

import pytest
from rag_local.classification import suggest_classification

CASES = [
    ("RH/folha.xlsx", "restricted"),
    ("Recursos Humanos/lista.docx", "restricted"),
    ("financas/Salário_2025.xlsx", "restricted"),
    ("financas/salario-joao.pdf", "restricted"),
    ("vencimentos/maio.pdf", "internal"),  # "vencimentos" não é "vencimento": só palavras inteiras
    ("legal/Contrato de arrendamento.pdf", "restricted"),
    ("pessoais/NIF.txt", "restricted"),
    ("banco/IBAN_conta.txt", "restricted"),
    ("saúde/exames.pdf", "restricted"),
    ("Médico/receita.pdf", "restricted"),
    ("pasta/pessoal/nota.md", "restricted"),
    ("Confidencial/estrategia.pptx", "confidential"),
    ("clientes/Cliente_Acme.docx", "confidential"),
    ("marketing/campanha.pptx", "internal"),
    ("relatorio.pdf", "internal"),
    ("rh-ferias.docx", "restricted"),
    ("c:\\docs\\RH\\x.pdf", "restricted"),
    ("confidencial/contrato.pdf", "restricted"),  # restricted tem prioridade
    ("shrhub/x.pdf", "internal"),  # "rh" dentro de outra palavra não conta
]


@pytest.mark.parametrize(("path", "expected"), CASES)
def test_classification_suggestions(path: str, expected: str) -> None:
    assert suggest_classification(path) == expected, path
