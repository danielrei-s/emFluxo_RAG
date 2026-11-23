> **RASCUNHO — validar com advogado.** Documento-base coerente com a arquitetura da plataforma; não tem valor jurídico até ser revisto (HR-20).

# Acordo de tratamento de dados (DPA) — modelo

Entre o **Cliente** (responsável pelo tratamento) e o **Prestador** (subcontratante), nos termos do art. 28.º do RGPD.

## 1. Objeto e duração

Tratamento de documentos e conversas do Cliente para pesquisa e respostas assistidas por IA, durante a vigência do contrato.

## 2. Tipos de dados e titulares

Documentos carregados pelo Cliente (podem conter dados pessoais de colaboradores, clientes e terceiros) e dados de utilizadores (email, nome, papel). Categorias especiais só se o Cliente as carregar; o Cliente deve classificá-las como `restricted`.

## 3. Instruções e finalidade

O Prestador trata os dados apenas para prestar o serviço e segundo as instruções documentadas do Cliente.

## 4. Localização e subcontratantes

Dados em repouso na UE. Subcontratantes ulteriores: fornecedor de base de dados e autenticação (UE), fornecedor de alojamento/rede e, apenas se o Cliente ativar, fornecedor externo de modelo de linguagem na UE. Lista atualizada em `[URL]`; o Cliente é avisado com `[30]` dias de antecedência de alterações.

## 5. Medidas de segurança

Isolamento por cliente com segurança ao nível da linha (RLS forçado), encriptação em trânsito e em repouso, encriptação envelope por cliente dos ficheiros originais, controlo de acesso por papel e por classificação, auditoria com cadeia de hashes, registos sem conteúdo, redução de PII antes de qualquer fornecedor externo, conteúdo `restricted` e `local_only` nunca enviado a fornecedores externos.

## 6. Direitos dos titulares, exportação e eliminação

Apoio nos pedidos de acesso, retificação e apagamento. Exportação do cliente em formato aberto; eliminação do cliente propaga-se a ficheiros, índices, conversas e cópias, com prova de eliminação.

## 7. Incidentes

Notificação ao Cliente sem demora injustificada e em `[48]` horas após ter conhecimento de uma violação de dados.

## 8. Auditorias e fim do contrato

O Cliente pode auditar mediante pré-aviso. No fim, o Prestador devolve e elimina os dados em `[30]` dias.
