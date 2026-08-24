# Dicionário de dados

Todo Parquet em `data/clean/` tem um `.meta.json` ao lado com fonte, URL, data de extração,
nº de registros, SHA-256 e a ressalva metodológica. Este documento descreve as colunas.

## Fonte 2 — consumidor.gov.br

### `consumidor_gov_transporte.parquet`
Reclamações individuais dos segmentos Transporte Terrestre e Transporte Aéreo.

| coluna | tipo | descrição |
|---|---|---|
| `segmento_rotulo` | texto | `Transporte Terrestre` ou `Transporte Aereo`. **Nunca somar os dois.** |
| `empresa` / `empresa_norm` | texto | nome fantasia declarado; a versão `_norm` é minúscula e sem acento |
| `uf`, `cidade`, `regiao` | texto | localização do consumidor |
| `ano`, `mes` | inteiro | data de abertura |
| `grupo_problema`, `problema` | texto | taxonomia de problema da Senacon |
| `resolvida` | booleano nulo | avaliação do consumidor. **Vazio = não avaliou → `NA`, nunca `False`** |
| `nota` | decimal | nota do consumidor (1–5) |
| `tempo_resposta_dias` | decimal | dias até a resposta da empresa |
| `respondida_bool` | booleano nulo | a empresa respondeu |

### `consumidor_gov_empresa_ano.parquet`
| coluna | descrição |
|---|---|
| `reclamacoes` | contagem de reclamações |
| `indice_solucao` | média de `resolvida` — **denominador é só quem avaliou** |
| `avaliadas` | quantas reclamações receberam avaliação |
| `taxa_avaliacao` | `avaliadas / reclamacoes` — leia o índice de solução junto com isto |
| `nota_media`, `tempo_resposta_medio_dias` | médias |

### `consumidor_gov_problema_ano.parquet` · `consumidor_gov_serie_mensal.parquet` · `consumidor_gov_total_segmentos.parquet`
Agregados por problema, por mês e por segmento (este último é o denominador da participação
do transporte no total de reclamações).

## Fonte 1 — DataJud

### `datajud_b2c.parquet` / `datajud_regulatorio.parquet`
Um registro por processo, já deduplicado por `numero_processo`.

| coluna | descrição |
|---|---|
| `numero_processo` | chave de deduplicação. **Toda contagem é por este campo** |
| `universo` | `B2C (Justica Estadual)` ou `Regulatorio (Justica Federal)`. **Nunca somar.** |
| `tribunal`, `uf`, `alias`, `grau` | origem do registro |
| `classe_codigo`, `classe_nome` | classe processual (TPU) |
| `orgao_julgador_codigo`, `orgao_julgador_nome`, `municipio_ibge` | unidade julgadora |
| `data_ajuizamento`, `ano`, `mes` | ajuizamento |
| `n_assuntos` | quantos assuntos o processo carrega |

### `datajud_b2c_serie_mensal.parquet`
`processos` = **contagem de `numero_processo` distintos**, não de ocorrências de assunto.

### `datajud_b2c_por_assunto.parquet`
⚠️ **As linhas não somam ao total.** Um processo com três assuntos aparece em três linhas —
de propósito, para mostrar a composição temática. Para totais, use a série mensal.

### `datajud_b2c_por_orgao.parquet`
Processos distintos por órgão julgador. Insumo do sinal de concentração.

### `datajud_participacao_consumo.parquet`
| coluna | descrição |
|---|---|
| `documentos_total`, `documentos_consumo` | contagem de **documentos** em 1º grau |
| `participacao_consumo` | razão entre os dois |

⚠️ Conta documentos processo-grau, não processos distintos. Numerador e denominador usam o
**mesmo** método e o mesmo grau — é isso que torna a razão válida. Não misture esses números
com as contagens deduplicadas das outras tabelas.

## Fonte 3 — Ouvidoria da ANTT

### `antt_ouvidoria_temas.parquet` / `antt_ouvidoria_categorias.parquet`
| coluna | descrição |
|---|---|
| `tema` | rótulo extraído da tabela do PDF |
| `categoria` | `CX`, `Passe Livre` ou `Outros` — **mutuamente exclusivas, jamais somadas** |
| `quantidade` | manifestações |
| `participacao_passe_livre` | quanto do total é gratuidade |

⚠️ Manifestações ≠ reclamações: pelo próprio relatório, ~73% são pedido de informação e
~12% reclamação sobre serviço delegado.

## Fonte 4 — Grandes Litigantes

### `grandes_litigantes.parquet`
`parece_transporte` é filtro por nome, sujeito a falso positivo e negativo — ponto de partida
para conferência humana, não classificador.

## Fonte 5 — Demanda

### `demanda_passageiros.parquet`
| coluna | descrição |
|---|---|
| `modal` | `Rodoviario` (ANTT) ou `Aereo` (ANAC) |
| `ano`, `mes` | período |
| `passageiros` | denominador das métricas por 100 mil |

⚠️ Ano sem denominador **não vira zero**: `analise.por_100k()` separa essas linhas num
segundo quadro para inspeção.

## Fonte 6 — Zoho Desk (censo de entrega da informação)

### `desk_pi_tickets.parquet`
Universo do censo: um registro por ticket com `cf_area_pi` preenchido no período.

| coluna | tipo | descrição |
|---|---|---|
| `ticket_id` / `ticket_numero` | texto | id da API e nº de protocolo |
| `criado_em`, `fechado_em` | texto ISO | timestamps do Desk (UTC) |
| `status`, `status_tipo` | texto | estado do fluxo. **Não prova entrega de informação** |
| `canal` | texto | canal de abertura (0800, WhatsApp, Agências…) |
| `n_threads`, `n_comentarios` | inteiro | contadores do Desk |
| `cf_area_pi` | texto | área interna acionada (Comercial, Operacional, Financeiro…) |
| `cf_motivo`, `cf_submotivo`, `cf_detalhe_do_motivo` | texto | assunto em três níveis |
| `cf_descricao_area_pi_n2` | texto | o pedido feito à área |
| `cf_solucao` | texto | a OFERTA dada (Diferença Tarifária, Devolução…). **Não é entrega** |
| `assunto` | texto | `cf_detalhe_do_motivo` quando preenchido, senão `cf_motivo` |

### `desk_entrega_classificada.parquet`
Resultado do censo: um registro por ticket classificado.

| coluna | tipo | descrição |
|---|---|---|
| `estado` | texto | `entregue_no_desk` · `entregue_fora_do_desk` · `indeterminado` · `nao_entregue` |
| `disparo_no_desk` | booleano | a pendência foi disparada de forma rastreável no Desk |
| `canal_da_resposta` | texto | `email_interno`, `comentario` ou `cliente` |
| `latencia_disparo_h` | decimal | horas entre a abertura do ticket e o disparo da pendência |
| `latencia_area_h` | decimal | horas entre o disparo e o retorno da área (só onde rastreável) |
| `retorno_cliente_falhou` | booleano | o aviso ao cliente voltou (bounce) |
| `precisa_llm` | booleano | ambíguo aguardando a passada de LLM (`--llm`) |
| `evidencia` / `evidencia_id` | texto | trecho e id do evento que sustenta a classificação |

`indeterminado` é o **piso de incerteza** do censo: entrega provável fora do Desk sem
rastro que confirme o conteúdo. Reportar sempre separado, nunca diluído.
