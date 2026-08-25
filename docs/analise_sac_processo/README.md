# SAC × Judicialização — mesmo assunto, desfechos diferentes (Problema Mecânico)

Análise comparativa das tratativas do SAC (Zoho Desk, org Expresso Guanabara) entre
casos **do mesmo assunto** em que um virou processo judicial e outro foi contido no
atendimento. Extração: 25/08/2026, via API do Zoho Desk (departamentos
`expressoguanabara` e `Apuração Jurídica - Procon`).

## Pergunta

Sob o mesmo denominador (Motivo `Viagem` → Detalhe `Problema Mecânico` → Submotivo
`Veículo`), a condução do atendimento influenciou a decisão de processar? Até onde o
SAC consegue agir e onde não consegue?

## Como os grupos foram montados

1. **Universo judicializado**: tickets do dept. Apuração Jurídica com assunto
   `*Subsídios*` criados em 2026 (cada um = ação judicial nova pedindo subsídios ao
   SAC) → **2.043 ações**. Distribuição por motivo em `acoes_2026_por_motivo.csv`.
2. **Assunto selecionado**: `Problema Mecânico` — maior categoria substantiva
   (130 ações, 87 com Localizador da venda preenchido → 94 localizadores únicos).
3. **Grupo "virou processo"**: busca de todos os tickets com esses localizadores →
   68 tickets de SAC prévios à ação (`grupo_virou_processo.csv`).
4. **Grupo de controle "contido"**: amostra de 299 tickets SAC com o mesmo Detalhe
   do Motivo, criados nov/2025–abr/2026, excluindo qualquer localizador/consumidor
   presente no universo judicializado (`grupo_controle_contido.csv`).

Arquivos pseudonimizados: sem nome, CPF ou e-mail do consumidor; chave de
rastreio é `ticketNumber` + `localizador`.

## Resultados quantitativos

| Métrica | Virou processo (n=68) | Contido (n=299) |
|---|---|---|
| Resolução (mediana) | **141 h (~6 dias)** | **31 h (~1,3 dia)** |
| Resolução (p90) | 342 h | 190 h |
| Threads (mediana) | 3 | 2 |
| Fechado - Procedente | 65% | 74% |
| Fechado - Sem Interação | 19% | 16% |
| Duplicado | 9% | 8% |
| Solução registrada | 69% | 44% |
| Dias viagem→reclamação (mediana) | 4,7 | 2,7 |

Contexto de funil (nov/2025–abr/2026): **3.256** tickets SAC de Problema Mecânico;
**~55** deles viraram processo (≈ **1,7%** de conversão). Metade das ações (47/94
localizadores) **não tem ticket de SAC** — o consumidor foi direto ao Judiciário.
Mediana entre a reclamação no SAC e a distribuição da ação: **58 dias** (janela real
de contenção).

## Mecanismos observados na leitura das conversas (pares casados)

Onde a condução **influenciou**:

1. **Exigência de quitação total para pagar valor incontroverso** — cliente aceitou
   o valor (R$ 430,88) três vezes e recusou o termo; caso encerrado e judicializado
   (#1197680 vs. controle #1143500, que assinou o termo e recebeu em 7 dias).
2. **Lentidão nos loops internos (N2/manutenção/jurídico das filiais)** — respostas
   de 44–224 h; advogado com proposta de acordo esperou **25 dias** e ajuizou 3 ações
   (#1119601, incidente 1EN862). O SAC cobrou "algum retorno?" 4 vezes sem SLA.
3. **Fechamento "Sem Interação" sem confirmar a oferta** — 19% do grupo processo;
   oferta de devolução+cortesia enviada e nunca confirmada (#1093892: cliente avisou
   "já estou com advogado" 30 dias antes da ação; recebeu o mesmo template de novo).
4. **Alçada travada em devolução+cortesia** — pedido documentado de gastos reflexos
   (voo, hotel, Uber) recebe negativa padrão; jurídico interno orienta acordo além da
   devolução só em "raríssimas exceções" (#1125439, Consumidor.gov → ação).

Onde a condução **não alcança** (limites):

- **50% das ações chegam sem passagem pelo SAC** identificável.
- **Gravidade do incidente domina**: quebras duplas/triplas com 4–8 h de atraso e
  50+ passageiros (1EN862, 14VDUB) geram múltiplas ações do mesmo evento — a causa é
  operacional/manutenção, não a tratativa.
- **Dano moral**: quem já busca compensação além do material dificilmente é contido
  por cortesia; a decisão de litigar às vezes precede o contato (cliente informa
  Procon/advogado na 1ª mensagem).

## Ressalvas

- Correlação ≠ causa: casos que viraram processo tendem a ser incidentes mais graves;
  parte da resolução mais lenta reflete complexidade, não só condução.
- Ações ajuizadas após ago/2026 ainda não aparecem; o controle pode conter futuros
  processos (viés a favor do controle, mitigado pela janela nov/2025–abr/2026).
- `Solicitação de Subsídios` cobre o fluxo padrão do jurídico; ações que entram por
  outros formatos (citações diretas, Procon administrativo) não estão no denominador.
