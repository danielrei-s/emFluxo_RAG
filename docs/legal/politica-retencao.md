> **RASCUNHO — validar com advogado.** Documento-base coerente com a arquitetura da plataforma; não tem valor jurídico até ser revisto (HR-20).

# Política de retenção e eliminação

| Dados                  | Retenção                                | Eliminação                                           |
| ---------------------- | --------------------------------------- | ---------------------------------------------------- |
| Documentos e índices   | Enquanto o cliente os mantiver          | A pedido do cliente ou no fim do contrato (+30 dias) |
| Conversas              | 0, 30 ou 90 dias (definição do cliente) | Automática, diária                                   |
| Auditoria              | `[12]` meses                            | Automática                                           |
| Consumo (sem conteúdo) | `[24]` meses                            | Automática                                           |
| Cópias de segurança    | `[35]` dias                             | Rotação                                              |
| Dispositivos revogados | `[90]` dias                             | Automática                                           |

## Eliminação de um cliente

Pedido do proprietário do cliente, estado `deleting`, remoção de ficheiros, chunks, conversas, jobs e chaves, e prova de eliminação enviada ao cliente. A eliminação propaga-se às cópias dentro do prazo de rotação das cópias de segurança.

## Exportação

O proprietário pode exportar os documentos e metadados em formato aberto antes da eliminação.
