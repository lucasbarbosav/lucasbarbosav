# Zoho Desk — como obter acesso para o censo

Duas vias. A API é a mais simples de operar (e é resumível); o export (Data
Backup) evita as ~42 mil chamadas e o rate limit, mas depende de um passo
manual do admin e de uma conversão de layout.

## Via 1 — API (OAuth self client)

1. Acesse <https://api-console.zoho.com> logado como admin do portal
   `viajeguanabara` e crie um **Self Client**.
2. Gere um *grant code* com os escopos:
   `Desk.tickets.READ,Desk.search.READ,Desk.basic.READ`
3. Troque o grant code por um **refresh token**:

   ```bash
   curl -s https://accounts.zoho.com/oauth/v2/token \
     -d grant_type=authorization_code \
     -d client_id=SEU_CLIENT_ID -d client_secret=SEU_SECRET \
     -d code=GRANT_CODE
   ```

4. Preencha no `.env`: `ZOHO_DESK_CLIENT_ID`, `ZOHO_DESK_CLIENT_SECRET`,
   `ZOHO_DESK_REFRESH_TOKEN`. O pipeline renova o access token sozinho.

   Alternativa rápida (vale ~1 h): cole um token pronto em
   `ZOHO_DESK_ACCESS_TOKEN` — bom para testar, ruim para o job longo.

5. Rode e deixe rodando; é idempotente e resumível por ticket:

   ```bash
   ./venv/bin/python run_all.py --etapas desk_ingestao
   ```

   Cada ticket baixado vira `data/raw/zoho_desk/conversas/<ticketId>.json` e
   não é rebaixado. Caiu no meio? Rode de novo. O intervalo entre chamadas é
   `ZOHO_DESK_SLEEP_S` (padrão 0,75 s — ~115 mil chamadas/dia, dentro do
   limite dos planos pagos; aperte ou folgue conforme o plano).

Se a conta estiver em outro data center, ajuste `ZOHO_DESK_BASE_URL`
(ex.: `https://desk.zoho.eu/api/v1`) e `ZOHO_ACCOUNTS_URL`.

## Via 2 — Export (Data Backup)

1. No Desk: **Setup → Data Administration → Export/Backup** e solicite o
   backup completo (admin). O Zoho entrega um zip com JSONs por módulo.
2. O layout do backup **muda entre versões** — por isso o pipeline não tenta
   adivinhá-lo. Converta para o contrato simples que a etapa lê:

   ```
   <export-dir>/
     tickets/*.json            # listas de objetos de ticket (formato da API)
     conversas/<ticketId>.json # lista de threads+comentários por ticket
   ```

   Os objetos devem ter os mesmos nomes de campo da API v1 (`id`,
   `ticketNumber`, `createdTime`, `cf.*`; threads com `direction`,
   `fromEmailAddress`, `to`, `summary`, `createdTime`; comentários com
   `commenter`, `commentedTime`, `content`).

3. `./venv/bin/python -m src.zoho_desk --export-dir <export-dir>`

## Limites que o código já respeita

- A busca (`/tickets/search`) devolve `count` e pagina até ~10 mil resultados
  por consulta: o período é fatiado por mês e janelas grandes são divididas.
- Busca de campo custom é wildcard/substring; o filtro do universo é
  `cf_area_pi:${notempty}`.
- 429 respeita `Retry-After`; 401 renova o token; 5xx recua exponencialmente.

## Departamentos (referência)

| departamento | id |
|---|---|
| SAC principal (`expressoguanabara`) | `1003707000000006907` |
| Apuração Jurídica - Procon | `1003707000299134542` |
| Casos de Bagagem | `1003707000362923608` |

O censo padrão roda no SAC principal (`ZOHO_DESK_DEPARTMENT_ID`); os outros
departamentos podem ser rodados à parte mudando a variável — os contadores
fechados do estudo (42.102 em 2026) foram apurados sem filtro de departamento,
e a mesma busca filtrada no SAC devolve 39.941: a diferença são os tickets
com `cf_area_pi` nos departamentos menores.
