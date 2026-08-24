# Calibração das regras de classificação (dados reais, 2026-08-24)

As regras de `src/desk_entrega.py` não foram escritas de cabeça: cada uma vem
de um padrão observado em tickets reais do portal `viajeguanabara` (produção),
lidos via conector MCP em 24/08/2026. Este documento é o registro do que foi
visto, para que uma mudança de regra futura saiba o que não pode quebrar.
Os testes (`tests/test_desk_entrega.py`) replicam cada caso com fixture
sintética.

## Fatos do esquema, validados em produção

- `searchTickets` devolve `count` = total de matches independente de `limit`.
  Conferido: `cf_area_pi:${notempty}` + jan–21/ago/2026 + departamento SAC
  devolve **39.941** (o contador fechado do estudo, 42.102, foi apurado sem
  filtro de departamento — a diferença está nos departamentos menores).
- Thread `in` de remetente externo ao Desk vem com `author.email = null`;
  o campo confiável é **`fromEmailAddress`**.
- `respondedIn` (formato `HH:MM:SS` cumulativo) aparece nas threads `out` e
  mede o tempo do agente desde a última `in` — não serve de latência da área.
  A latência é calculada por diferença de `createdTime` entre eventos.
- Threads internas com vários destinatários aparecem **duplicadas** (mesmo
  segundo, mesmo texto, ids diferentes) → dedupe por (direção, remetente,
  segundo, prefixo do texto).
- Respostas da área também chegam como **comentário privado** de outro agente,
  não só por e-mail (caso #1352645).
- O parâmetro `fields` de `GET /tickets` não aceitou nenhuma combinação via
  conector MCP (`UNPROCESSABLE_ENTITY`); a busca devolve o payload completo
  (~10 mil tokens por ticket). Irrelevante para o pipeline local, mas torna
  inviável fazer o censo por MCP.

## Casos-borda e o que cada um calibrou

### `#1491212` (Achados e Perdidos → Operacional) — `entregue_no_desk`
- Pedido: "Verificar se o objeto foi localizado" (`cf_descricao_area_pi_n2`).
- `out` 24/08 13:40 com o template **"PENDÊNCIA INTERNA"** para
  `filial.blm@expressoguanabara`, `trafego.blm@…`, `ricardo.mendes@viajeguanabara`,
  `achadoseperdidosmatriz@viajeguanabara` — `respondedIn 89:49:14` ⇒ a
  latência de ~90 h é do **disparo**, não da área.
- `in` 14:04 de `trafego.blm@expressoguanabara`: "houve a sobra de uma bolsa
  vermelha" (duplicada) ⇒ área respondeu em **24 min**.
- `out` 14:17 ao cliente com foto; 14:18 **bounce** (Mailer-daemon) ⇒ entrega
  interna OK **e** falha no retorno ao cliente — daí a flag
  `retorno_cliente_falhou`.

### `#1128567` (Categoria inferior → Comercial) — `entregue_fora_do_desk`
- "PENDÊNCIA INTERNA" 08/01 17:38 para `util.com.br` / `realexpresso.com.br`
  (⇒ os domínios internos incluem **todas as marcas do grupo**).
- 4 minutos depois, resposta ao cliente com a explicação completa ("por
  motivos operacionais emergenciais, foi necessária…") **sem nenhuma thread
  de retorno da área** ⇒ a informação circulou fora do Desk.

### `#1128254` (Categoria inferior → Comercial) — `nao_entregue`
- `cf_area_pi` preenchido, mas nenhum disparo, nenhum retorno, nenhuma
  resposta ao cliente (status "Duplicado"). ⇒ marcação de área **não implica**
  pendência disparada: a flag `disparo_no_desk` mede isso no censo.

### `#1352645` (estorno → Financeiro) — `entregue_no_desk` via comentário
- Aberto por **agência** (canal "Agências", e-mail de contato inválido ⇒
  bounce imediato do auto-reply).
- Auto-reply "Resposta Automática" também vai para endereço **interno**
  (o agente da agência) ⇒ auto-reply nunca pode ser lido como disparo.
- Pedido como comentário ("Márcia, boa tarde! Gentileza seguir com o
  estorno…") e retorno como comentário privado de outro usuário
  (`comercial.civil@viajeguanabara`, assinado "Setor Financeiro"):
  "Lançado pedido de estorno, prazo… 48 horas".

### `#1493204` (Achados, "Análise N2") — zero threads
- Não localizável hoje por `ticketNumber` (possivelmente arquivado/excluído).
  O padrão que ele representa — pendência sem nenhuma thread — cai em
  `nao_entregue`/`indeterminado` conforme haja ou não resposta ao cliente.

### `#1492916` (Depósito) — fora do escopo da classificação
- "Oferta registrada, cliente diz que não recebeu o valor": mostra que
  `cf_solucao` ≠ resolução. Não é pedido de informação; fica como lembrete de
  que **oferta não prova entrega** (está no rodapé dos painéis e nos metas).

## Léxico observado (base dos marcadores)

- Template do disparo: "PENDÊNCIA INTERNA … Aqui vão as informações
  necessárias para a sua análise: Protocolo … Comentários N2: …"
- Auto-reply: "Resposta Automática … Recebemos o seu contato, que gerou o
  protocolo N. Retornaremos em breve!"
- Respostas com informação: "houve a sobra de…", "identificamos um objeto…",
  "não foi localizado", "Lançado pedido de estorno, prazo…", "informamos
  que… foi necessária a troca…".
- Caixas internas típicas: `achadoseperdidosmatriz@`, `plantaocomercial@`,
  `trafego.*@`, `filial.*@`, `comercial.civil@`.
