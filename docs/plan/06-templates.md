<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# PARTE G — Templates

## G1. Cartão de tarefa

```markdown
#### F<fase>-T<nn> · <Título no imperativo>
- **Objetivo:** <uma ou duas frases>
- **Depende de:** <IDs ou —> · **Tamanho:** S | M | L
- **Ler antes:** <secções da Parte C>; ficheiros: <caminhos>
- **Criar/alterar:** <caminhos exatos>. Dependências novas: <pacote (licença)>
- **Passos:**
  1. <passo concreto>
- **Testes (obrigatórios):**
  - `test_<comportamento>` — <o que prova>
- **Comandos:** <opcional>
- **DoD específico:** <critério verificável>
- **🧑 Humano:** <— | HR-xx (bloqueante/não bloqueante)>
- **Armadilhas:** <opcional; inclui Plano B>
- **Não fazer:** <opcional>
```

## G2. ADR

```markdown
# ADR-NNNN · <Título>
- **Estado:** proposta | aceite | substituída por ADR-XXXX
- **Data:** AAAA-MM-DD · **Tarefa:** F?-T??

## Contexto
<o problema e as restrições>

## Decisão
<o que se decidiu>

## Alternativas consideradas
<opção — porque não>

## Consequências
<positivas, negativas, riscos residuais, o que muda nos invariantes ou contratos>
```

## G3. Pedido humano (HR)

```markdown
### HR-0NN · <Título curto>
- **Tarefa:** F?-T?? · **Bloqueante:** sim | não · **Pedido em:** AAAA-MM-DD
- **Preciso de:** <exatamente o quê>
- **Porquê:** <ligação a um invariante, marco ou tarefa>
- **Como entregar:** <ficheiro/variável/gestor de segredos — nunca colar segredos no chat>
- **Opções / recomendação:** <se houver>
- **Enquanto isso:** <o que o agente faz: outra tarefa, fake/stub com TODO(HR-0NN)>
- **Estado:** aberto | respondido (<resumo>) | fechado
```

## G4. Descrição de PR

```markdown
## <ID> · <Título>
**O que faz:** <2–3 frases>
**Ficheiros:** <lista>
**Testes:** <n novos; comando; resultado>
**Invariantes cobertos:** <INV-xx>
**Desvios / ADR:** <nenhum | ADR-xxxx>
**Pedidos humanos:** <nenhum | HR-xxx>
**Checklist de segurança (G5):** ✅
```

## G5. Checklist de segurança por PR

- [ ] Nenhum conteúdo (documentos, prompts, respostas, perguntas) em logs, erros, métricas ou auditoria (INV-03).
- [ ] Todo o acesso a dados dentro de `tenant_tx` e com `tenant_id` no SQL (INV-01).
- [ ] Cada endpoint novo tem autorização no servidor e testes de 403/404, incluindo entre tenants (INV-14).
- [ ] Entradas validadas (tipos, tamanhos, limites) e erros em problem+json sem texto livre.
- [ ] Saída para o utilizador sanitizada (INV-08).
- [ ] Sem dependências novas fora da allowlist de licenças (INV-21).
- [ ] Sem segredos; variáveis novas em `.env.example` sem valor (INV-13).
- [ ] Nenhuma ferramenta com efeitos externos (INV-09).
- [ ] Documentação, OpenAPI e STATUS atualizados; ADR se houve desvio.
