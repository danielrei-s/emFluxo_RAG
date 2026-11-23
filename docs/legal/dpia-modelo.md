> **RASCUNHO — validar com advogado.** Documento-base coerente com a arquitetura da plataforma; não tem valor jurídico até ser revisto (HR-20).

# Avaliação de impacto sobre a proteção de dados (DPIA) — modelo

## 1. Descrição do tratamento

Natureza, âmbito, contexto e finalidades: pesquisa e perguntas sobre documentos do cliente com IA generativa.

## 2. Necessidade e proporcionalidade

Minimização: só se indexa o que o cliente carrega; PII reduzida antes de fornecedores externos; conversas com retenção 0/30/90 dias.

## 3. Riscos para os titulares e medidas

| Risco                                 | Medida                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------ |
| Acesso de um cliente a dados de outro | RLS forçado, filtros de ACL antes do modelo, testes de isolamento com canários |
| Fuga de conteúdo por logs             | Registos só com metadados, validados por testes                                |
| Injeção de instruções nos documentos  | Documentos tratados como dados, isolamento no prompt, saída sanitizada         |
| Resposta errada ou inventada          | Citações obrigatórias, recusa quando não há fonte, avaliação contínua          |
| Envio a fornecedor externo            | Opcional, UE, PII redigida, `restricted` e `local_only` nunca saem             |
| Perda de dispositivo                  | Índice encriptado, revogação com apagamento remoto                             |

## 4. Consulta e parecer

Encarregado de proteção de dados: `[nome]`. Consulta prévia à CNPD se o risco residual for elevado.

## 5. Decisão e revisão

Aprovação por `[responsável]`; revisão anual ou quando mudar o tratamento.
