# Orquestração por agentes (execução em sessão, sem credenciais standalone)

Nesta configuração o Zoho Desk é acessado pelo conector MCP da sessão e a "chamada de
modelo" da Seção 0 do plano é um subagente com instruções fixas. Os artefatos em disco
e o livro-razão em SQLite garantem retomada — qualquer agente que morra no meio é
relançado e pula o que já existe em disco.

Parâmetros fixos Zoho: orgId `855775513`, departmentId `1003707000000006907`.

## Receita A — agente de download (brutos)

Entrada: uma fatia de um arquivo de amostra/lista (`*.jsonl`, um ticket por linha).
Para cada ticket da fatia, PULANDO os que já têm arquivo em disco:

1. `getTicketConversations` (limit 100). Itens `type="comment"`: conteúdo completo em
   HTML (`isPublic=false` = comentário interno). Itens `type="thread"`: só `summary`;
   anotar `id`.
2. Para cada thread: `getThread` com `{ticketId, threadId}` e
   `{orgId, include: "plainText"}`. Sem plainText → limpar HTML do `content`.
3. Montar timeline ordenada por tempo ASC:
   `{tipo: "thread"|"comentario_interno", direcao: "in"|"out"|null,
     autor_tipo: "AGENT"|"END_USER"|null, autor_nome, quando, texto}`.
   Limpar HTML dos comentários (tags fora, quebras de linha preservadas).
4. Gravar `data/raw/sac/brutos_<tema_slug>/{ticketNumber}.json`:
   `{"meta": {id, ticketNumber, createdTime, channel, status, statusType,
     classification, filial, solucao, area_pi, motivo, submotivo, detalhe_motivo,
     origem, destino, subject, description (texto limpo), threadCount, commentCount,
     contactId}, "timeline": [...]}`
   (chaves de `meta` são as que `carregar.py` espera; `description` é a descrição
   inicial do ticket com HTML removido).
5. Falha em um ticket → gravar `{ticketNumber}.erro.txt` com a mensagem e seguir.

Retorno do agente: contagem ok/erro e nada de conteúdo bruto.

## Receita B — agente de extração (modelo)

Entrada: uma fatia de tickets com bruto em disco. Para cada um, PULANDO os que já têm
arquivo em `extraidos_<tema_slug>/`:

1. Ler `brutos_<tema_slug>/{ticketNumber}.json`.
2. Montar o texto: descrição inicial + timeline com rótulos
   `[CLIENTE]` (thread in / END_USER), `[SAC→cliente]` (thread out) e
   `[COMENTÁRIO INTERNO]`, cada um com timestamp.
3. Aplicar RIGOROSAMENTE o prompt de `src/sac/prompt_extracao.md` com o schema de
   `src/sac/schema_extracao.json` (chave `campos`). As regras inegociáveis:
   - só o que está no texto; `nao_informado` ≠ `nao`;
   - desfecho posterior ao atendimento NUNCA vira atributo → `leak_mention=true`;
   - sinais expressos pelo cliente durante o atendimento SÃO válidos;
   - evidência ≤ 15 palavras por campo não-óbvio, sem PII (redigir).
4. Gravar APENAS o objeto JSON em `extraidos_<tema_slug>/{ticketNumber}.json`
   (json válido, ensure_ascii=False). Nada além do JSON no arquivo.
5. Ticket ilegível/vazio → JSON com tudo `nao_informado` e
   `extracao_confianca="baixa"`; anotar no retorno.

Retorno do agente: contagem ok/erro + observações de casos-limite (1 linha cada).

## Depois das ondas

```bash
python3 -m src.sac.carregar --tema "Categoria inferior" \
  --brutos data/raw/sac/brutos_categoria_inferior \
  --extraidos data/raw/sac/extraidos_categoria_inferior
python3 -m src.sac.exportar --tema "Categoria inferior" --csv data/raw/sac/calibracao_categoria_inferior.csv
```

`carregar.py` valida enums (valor inválido → `nao_informado` + linha em `erros`),
redige PII de todo texto livre, computa `divergencia_campo_texto`,
`tempo_ate_primeira_resposta_h` e o livro-razão `processados`.
