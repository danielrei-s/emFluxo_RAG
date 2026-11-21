# ADR-0008 · Python síncrono

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

O código é escrito e revisto por agentes com contexto limitado. Código assíncrono (`async`/`await`)
aumenta o risco de erros subtis: bloqueios do event loop, contexto de tenant que se perde entre
tarefas, testes mais difíceis de tornar determinísticos. O MVP tem poucos utilizadores
simultâneos, e o limite de capacidade está nos modelos (GPU) e não nos endpoints.

## Decisão

- Python **síncrono**: endpoints FastAPI com `def` (executados no pool de threads), psycopg 3 com
  `psycopg_pool` síncrono e SQL explícito, sem ORM.
- O contexto de tenant é explícito: cada transação faz `set_config('app.tenant_id', …)` e o acesso
  à BD recebe o contexto por argumento.
- Streaming de tokens para o cliente usa geradores síncronos.
- Reavaliar se os testes de carga (F13-T05) mostrarem que a concorrência em E/S é o gargalo.

## Alternativas consideradas

- **`async` em todo o lado** — melhor concorrência em E/S, mas mais complexidade e mais maneiras
  de falhar sem que os testes o detetem.
- **Misto (async nos endpoints, síncrono no core)** — duas formas de chamar o mesmo código e
  risco de bloquear o event loop.
- **ORM (SQLAlchemy)** — esconde o contexto de tenant; com SQL explícito ele fica visível em
  cada consulta.

## Consequências

- Código mais simples de ler, testar e rever; testes determinísticos com `FakeClock`.
- Menos pedidos simultâneos por instância; escala-se com mais processos ou threads.
- Migrar para `async` mais tarde exigiria rever a camada de acesso à BD e os clientes HTTP, e
  uma nova ADR.
