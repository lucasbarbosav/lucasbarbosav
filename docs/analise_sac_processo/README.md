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

## Anexo — tratativas reconstruídas mensagem a mensagem

Fluxo interno comum aos dois grupos: reclamação → **pendência interna** por e-mail às
caixas da filial (controle, manutenção, CCO; até 11 destinatários) → verificação da
ocorrência no SIGLA → resposta/proposta ao cliente → termo de quitação (Clicksign) →
Fluig de pagamento. O gargalo da apuração é estrutural e **igual nos dois grupos**
(215 h no caso contido #1143500; 224 h no caso #1197680 que virou processo) — o que
separa os desfechos é o pós-apuração.

**#1197680 (virou processo — quitação).** 18/02 cliente reclama de quebra
(Maringá×SP, 55 pax) e já avisa que acionará o Procon; 25/02 cobra urgência; 27/02
(9,4 dias) 1ª resposta com proposta; 28/02–03/03 cliente aceita por escrito o valor
(R$ 430,88) e recusa apenas a cláusula de quitação total, citando o Juizado; 04/03
SAC mantém a condição e encerra ("cliente não aceita assinar o termo"); cliente ajuíza.

**#1143500 (contido — indenizado).** 10/01 reclamação (quebra 04/01, 4h48 de atraso,
idosa de 71 anos a bordo); 19/01 (9 dias) pendência interna; manutenção confirma no
mesmo dia; 20/01 proposta **com valor de indenização**; dados bancários em 47 min;
termo Clicksign à noite, assinado na manhã seguinte; 21/01 "depósito agendado para
27/01". Da proposta ao acordo: <24 h.

**#1119601 (3 ações — acordo sem SLA).** 26/12 advogado de 3 passageiros
(quebra 04/12, São Sebastião×RJ) propõe acordo; 30/12 SAC encaminha ao jurídico;
02/01 e 05/01 cobranças internas "algum retorno?" (169 h, 236 h); 05/01 advogado:
"diante da ausência de resposta, irei considerar que não há interesse"; 05/01 21h
coordenador jurídico descarta contraproposta ("salvo raríssimas exceções");
06–11/01 repasse às filiais e nova cobrança; 20/01 negativa final (25 dias após a
proposta); 21/01 "iremos ingressar com a devida ação judicial".

**#1110917 (virou processo — contraproposta sem negociação).** 20/12 reclamação;
resposta em 1h08 com oferta padrão devolução+cortesia; 21/12 cliente: "disponível
para um acordo, só acho que essa proposta não é cabível… alimentação, desconforto,
constrangimento"; 23/12 SAC responde com empatia mas mantém a mesma oferta; sem novas
mensagens; fechado "Sem Interação"; 26/12 a cliente está entre os representados do
advogado acima.

**#1125439 (virou processo — gasto reflexo).** 30/12 reclamação via Consumidor.gov
com pedido itemizado de 10 gastos e comprovantes (dupla quebra em 02/12, BSB); 04/01
N2 confirma no SIGLA ("reclamação procede, atraso superior a 3 horas"); 05–07/01
pendência com 14 anexos, jurídico copiado, cobrança interna; 07/01 coordenador
jurídico questiona a extensão do atraso citando relatório de pontualidade; 08/01
resposta final em template de negativa; fechado "Sem Interação"; vira ação.

**#1093892 (virou processo — aviso ignorado).** 10/12 reclamação (quebra 24/11);
decisão interna em 4 min ("realizar a devolução e ofertar uma cortesia"); oferta só
chega em 13/12 (72 h); 14/12 cliente: "já estou buscando os meus direitos com
advogado"; 15/12 SAC reenvia o mesmo template de oferta; fechado "Sem Interação";
ação ~30 dias depois.

**#1142988 (contido — sem oferta).** 10/01 reclamação (troca de carro por ar
inoperante, 1h48 de atraso); 16/01 pendência interna (163 h), manutenção diverge e
depois confirma; 18/01 resposta com explicação, sem oferta; encerra
"Procedente / Sem Oferta", contido — gravidade menor compra tolerância.

## Hipótese testada — menção a dano moral / via jurídica como flag preditivo

Hipótese: "sempre que houver pedido de compensação além do material (dano moral) ou
menção à via jurídica, marcar o ticket como potencial processante".

Teste na **primeira mensagem** (texto de abertura disponível em 46 tickets do grupo
processo e 255 do controle), por família de termos:

| Família de termos | Virou processo | Contido | Lift |
|---|---|---|---|
| Dano moral (moral, constrangimento, humilhação, abalo, indeniza…) | 4% | 2% | ~2,8x |
| Órgãos/via formal (Procon, Juizado, Consumidor.gov, denúncia…) | 4% | 1% | ~3,7x |
| Direitos/CDC ("meus direitos", código de defesa…) | 9% | 2% | ~4,4x |
| **Qualquer flag** | **13%** | **4%** | **3,7x** |

Leitura:

- **Como sinalizador de priorização, funciona**: presença de flag na abertura ≈ 3,7x
  mais frequente entre futuros processantes. Com conversão-base de ~1,7%, um ticket
  com flag sobe para ~6% de probabilidade — vale fila prioritária e revisão de alçada.
- **Como preditor, é insuficiente sozinho**: 87% dos que processaram NÃO exibem flag
  na primeira mensagem, e ~94% dos que exibem flag não processam. Não usar para
  "desistir" de um caso nem para tratá-lo como litigante hostil.
- **O flag mais forte aparece no meio da conversa, não na abertura**: na leitura
  qualitativa, os sinais decisivos foram (a) a **contraproposta recusando a oferta
  padrão** com pedido além do material (#1110917 "alimentação, desconforto,
  constrangimento"; #1197680 citando o Juizado) e (b) a **menção explícita a advogado**
  em resposta (#1093892 "já estou buscando meus direitos com advogado"). Um flag útil
  precisa escanear as respostas do cliente, não só o registro inicial.
- Flag composto recomendado: `menção jurídica/dano moral` **+** `gravidade apurada
  (atraso > 3–4 h ou quebra dupla)` **+** `contraproposta recusada` — na amostra lida,
  essa tríade antecedeu todas as ações com passagem pelo SAC.

## Ressalvas

- Correlação ≠ causa: casos que viraram processo tendem a ser incidentes mais graves;
  parte da resolução mais lenta reflete complexidade, não só condução.
- Ações ajuizadas após ago/2026 ainda não aparecem; o controle pode conter futuros
  processos (viés a favor do controle, mitigado pela janela nov/2025–abr/2026).
- `Solicitação de Subsídios` cobre o fluxo padrão do jurídico; ações que entram por
  outros formatos (citações diretas, Procon administrativo) não estão no denominador.
