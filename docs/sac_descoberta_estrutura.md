# SAC / Zoho Desk — Descoberta de estrutura (Seção 4 do plano de extração)

Data da descoberta: 2026-08-24. Fonte: API do Zoho Desk via conector MCP.
Janela-alvo: `createdTime` de 2026-01-01T00:00:00Z a 2026-07-31T23:59:59Z.

## Organização e departamento

| Item | Valor |
|---|---|
| Organização | `expressoguanabara` (portal `viajeguanabara`) |
| `orgId` | `855775513` |
| Departamento do SAC | `expressoguanabara` — `departmentId 1003707000000006907` (default) |

Outros departamentos (fora do escopo, mas relevantes ao contexto): "Apuração Jurídica -
Procon" (`1003707000299134542`), "Viva Fidelidade", "Casos de Bagagem", "Gipsyy PT".
Atenção: a existência de um departamento jurídico separado significa que menções a
processo dentro do SAC podem ganhar continuação fora do ticket — reforça a regra de
não capturar desfecho (target leakage).

## Onde vive o "tema" (assunto)

A taxonomia é uma hierarquia de 3 níveis em custom fields:
`cf_motivo` (Motivo) → `cf_submotivo` (Submotivo) → `cf_detalhe_do_motivo` (Detalhe do Motivo).

Os temas homogêneos NÃO estão todos no mesmo nível:

| Tema | Campo Zoho | Valor exato | Tickets na janela |
|---|---|---|---|
| Categoria inferior | `cf_detalhe_do_motivo` | `Categoria inferior` | **5.715** |
| Estorno pendente | `cf_detalhe_do_motivo` | `Estorno pendente` | **1.572** |
| Depósito | `cf_motivo` | `Depósito` | **936** |
| Achados e Perdidos | `cf_motivo` | `Achados e Perdidos` | **7.515** |

Total homogêneo ≈ 15.7 mil. (O departamento inteiro tem 289.257 tickets na janela —
o filtro por tema é obrigatório já na consulta, não em pós-processamento.)

Exemplo de hierarquia observada num ticket de Categoria inferior:
`Motivo="Viagem" → Submotivo="Embarque / Desembarque" → Detalhe="Categoria inferior"`.
Em "Estorno pendente" o pai varia (ex.: `Motivo="Site/app terceiros" →
Submotivo="Financeiro - Terceiros"`), então o filtro correto é pelo campo folha, não
pela trilha completa.

Nota: existe também `cf_submotivo="Depósito"` (apenas 6 tickets na janela) — é outra
coisa (submotivo de Cancelamento de Passagem). O tema Depósito é o `cf_motivo`.

A consulta usada (endpoint de busca):
`GET /api/v1/tickets/search?departmentId=...&createdTimeRange=<ini>,<fim>&customField1=cf_detalhe_do_motivo:Categoria inferior`
com paginação `from`/`limit` e `sortBy=createdTime`. O total vem no campo `count` da resposta.

## Mapa campo_zoho → campo_do_schema

### Contexto (não-PII)

| Campo do schema | Campo Zoho | Observação |
|---|---|---|
| `ticket_id` | `id` (usar também `ticketNumber` p/ referência humana) | |
| `empresa` | `cf.cf_filial` | Valores vistos: "Expresso Guanabara", "Real Expresso", "Util", "Outros". Cobre o subconjunto jurídico (Real, Util, ...) |
| `assunto` (tema) | `cf.cf_motivo` / `cf.cf_submotivo` / `cf.cf_detalhe_do_motivo` | gravar os 3 níveis |
| `submotivo` | `cf.cf_submotivo` | |
| `canal` | `channel` | Valores vistos: "0800 - Expresso Guanabara", "0800 - UTIL", "0800 - Real Expresso", "Web to Case", "Fale Conosco", "Reclame Aqui", "Agências", "Instagram VG" |
| `created_date` / `mes` | `createdTime` | derivar `mes` |
| `status` | `status` + `statusType` | Ex.: "Fechado - Procedente", "Fechado - Improcedente", "Duplicado" |

### Impacto ao passageiro (estruturado disponível; o resto vem do texto)

| Campo do schema | Campo Zoho estruturado | Observação |
|---|---|---|
| `trecho_origem_destino` | `cf.cf_origem_viagem` + `cf.cf_destino_viagem` (`cf.cf_linha_1` como fallback) | |
| `categoria_comprada`/`viajada` | — (só texto) | ex. visto no texto: "leito cama para semi leito" |
| data/hora da viagem | `cf.cf_data_hora_da_viagem` | contexto, ajuda a datar o evento |
| poltrona | `cf.cf_poltrona` | contexto |

### Controlável pelo SAC / pendência interna

| Campo do schema | Campo Zoho | Observação |
|---|---|---|
| `area_destino` | `cf.cf_area_pi` | Valores vistos: "Operacional", "Financeiro". Há também `cf_descricao_area_pi_n2` |
| `passou_por_pendencia_interna` | comentários internos (`isPublic=false`) + `cf_area_pi` preenchido + `onholdTime` | derivar |
| `houve_retorno_da_area` | sequência de comentários internos antes do fechamento | derivar do texto/timeline |
| `tempo_ate_primeira_resposta_h` | `respondedIn` da primeira thread `direction=out` (ou métricas do ticket via `getTicketsMetrics`) | |

### Oferta — os dois lados

| Campo do schema | Campo Zoho | Observação |
|---|---|---|
| `oferta_campo` | `cf.cf_solucao` (campo "Solução") | Valores vistos: "Diferença Tarifária", "Cortesia"; frequentemente `null` |
| `oferta_valor_texto` (apoio) | `cf.cf_valor_a_ser_reembolsado`, `cf.cf_valor_do_ressarcimento_numero_e_por_extenso`, `cf.cf_valor_para_estorno` | quando estruturado existir, comparar com o texto |
| `oferta_texto` | — (extração da thread) | |
| `divergencia_campo_texto` | derivado | |
| sinais de processo interno de pagamento | `cf.cf_gerou_fluig`, `cf.cf_n_do_fluig`, `cf.cf_data_do_pagamento`, `cf.cf_gerou_termo_de_quitacao`, `cf.cf_link_do_termo_de_quitacao` | fortes indicadores de oferta executada (Fluig = workflow financeiro TOTVS) |

### PII presente (NÃO persistir na tabela analítica)

`contact.*` (nome, e-mail, telefone), `cf_cpf`, `cf_cpf_do_assinante`,
`cf_cpf_titular_da_conta`, `cf_numero_da_conta`, `cf_agencia_bancaria`,
`cf_nome_do_banco`, `cf_nome_do_titular_do_cartao`, `cf_numero_do_cartao*`.
Dados bancários aparecem TAMBÉM em texto livre (descrição e threads) — a varredura de
PII da evidência é obrigatória. `contactId` + e-mail/CPF alimentam apenas a tabela
`chave` com hash salgado (reincidência).

### Outros campos úteis

- `threadCount`, `commentCount` — tamanho da conversa sem precisar baixá-la.
- `classification` — "Reclamação" / "Solicitação" / "Informação".
- `cf_categorizado_por_ia`, `cf_revisado_pela_ia`, `cf_disparo_automatico` — mensagens
  automáticas; úteis para descontar ruído.
- `resolution` — resumo de fechamento escrito pelo agente (às vezes preenchido; bom
  insumo, mas CUIDADO: pode conter linguagem pós-fato → passa pelo mesmo crivo de leakage.

## Estrutura de conversas (confirmada em ticket real com 15 threads + 6 comentários)

`GET /tickets/{id}/conversations` devolve timeline única com dois tipos:

- `type="comment"`: comentário interno (`isPublic=false`), **conteúdo HTML completo**
  na resposta, com autor e anexos. É aqui que a pendência interna aparece
  (ex.: "Solicitado o comprovante de depósito" + link para sistema interno GLPI/Fluig).
- `type="thread"`: e-mail/mensagem com o cliente — **a resposta traz só `summary`
  (~180 caracteres)**, não o corpo. O corpo completo exige
  `GET /tickets/{id}/threads/{threadId}` (aceita `include=plainText`), UMA CHAMADA POR THREAD.

Implicação de custo: ticket médio ≈ 3–5 threads → extração completa do tema homogêneo
(≈15.7k tickets) ≈ 60–90 mil chamadas de leitura + 15.7k chamadas de modelo. O pipeline
precisa de rate-limit handling e do livro-razão de retomada (já previsto na Seção 8).

Metadados úteis da thread: `direction` (in/out), `author.type` (AGENT/END_USER),
`createdTime`, `respondedIn`, `channel`, `hasAttach`.

## Restrição de ambiente (a decidir antes da Seção 5→10)

Nesta sessão o acesso ao Zoho é via conector MCP (OAuth do claude.ai) — um script
Python standalone NÃO herda essa credencial. Para o pipeline programático da Seção 0
há dois caminhos:

1. **Credenciais próprias**: usuário fornece OAuth do Zoho Desk (client_id/secret/refresh
   token, escopo `Desk.tickets.READ`) + `ANTHROPIC_API_KEY` num `.env`; o script roda
   independente (preferível: reprodutível, retomável, auditável fora da sessão).
2. **Orquestração via sessão**: as leituras Zoho passam pelo conector MCP e a extração
   por subagentes, gravando em SQLite. Funciona sem credenciais novas, mas o run fica
   preso à sessão.

O código do pipeline será escrito para o caminho 1, com a camada de acesso isolada para
permitir o caminho 2 na calibração.
