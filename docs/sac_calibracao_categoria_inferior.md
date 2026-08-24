# Calibração — Categoria inferior, 100 tickets (Seção 10 do plano)

Amostra: 100 tickets estratificados por mês (14–15/mês, jan–jul/2026) do tema
`cf_detalhe_do_motivo = "Categoria inferior"` (população: 5.715). Download: 100/100,
0 erros. Extração (schema v1): 100/100, 0 erros de validação de enum na carga.
CSV: `data/raw/sac/calibracao_categoria_inferior.csv` (não versionado; entregue à mão).

População mensal do tema: jan 845, fev 766, mar 983, abr 911, mai 646, jun 512, jul 1.052.

## % não_informado por campo (n=100)

| Campo | % não_informado |
|---|---|
| duracao_interrupcao_faixa | 100 |
| perda_de_conexao | 100 |
| retido_rodovia_terminal | 99 |
| gasto_comprovado | 99 |
| hospedagem_necessaria | 99 |
| qualidade_informacao_ocorrencia | 79 |
| viagem_concluida | 42 |
| oferta_escolhida_pelo_cliente | 36 |
| troca_de_veiculo | 30 |
| oferta_executada_no_ticket | 26 |
| demais (pendência, sinais jurídicos, confiança) | 0 |

**Veredito dos campos ≥95%**: os cinco campos de interrupção/gasto/hospedagem não
carregam sinal NESTE tema (dano constante, como previsto no desenho — o "laboratório
limpo"). Recomendação: manter no schema (são os campos de gravidade dos temas
heterogêneos da fase 2), mas tratá-los como estruturalmente vazios em Categoria
inferior — não usar em comparação de política dentro do tema.

## Distribuições com sinal (sanidade: nada 100% num valor, exceto os vazios acima)

- `troca_de_veiculo`: sim 69 / não_informado 30 / não 1.
- `viagem_concluida`: sim 56 / não_informado 42 / não 2.
- `passou_por_pendencia_interna`: não 59 / sim 41. `houve_retorno_da_area`:
  não_aplicável 65 / **não 23 / sim 12** — quando o SAC pergunta à área, ~2/3 das
  vezes ninguém responde dentro do ticket.
- **Funil da oferta**: escolhida — reembolso_diferenca 38, sem_resposta 15, cupom_50 5,
  cortesia 3, reembolso_integral 2, recusou 1, não_informado 36 (inclui cortesia/reembolso
  concedidos unilateralmente, sem funil de escolha). Executada no ticket: sim 60 / não 14 /
  não_informado 26.
- **Sinais jurídicos** (pré-desfecho): advogado 1, processo/danos morais 3,
  Reclame Aqui/Consumidor.gov 5, tom leve 3 + explícito 3. `leak_mention`: **0**.
- `extracao_confianca`: alta 58 / média 38 / baixa 4 (baixa = tickets-casca de
  disparo massivo).

## Divergência campo Solução × texto

56/100 têm `cf_solucao` preenchido (divergência 0 por definição). Dos 44 com campo
vazio, **25 (57%) mostram oferta real no texto** — o campo estruturado perde quase
metade das ofertas quando vazio. Por canal (n entre parênteses):

| Canal | divergência |
|---|---|
| 0800 Real Expresso (8) | 50% |
| WhatsApp Chat (11) | 27% |
| Agências (41) | 27% |
| 0800 Expresso Guanabara (19) | 26% |
| Fale Conosco (12) | 0% |
| Reclame Aqui (2) / NPS (2) / Instagram (1) | 0% |

Atenção: o padrão esperado ("cegueira alta em Agências/RA, baixa em 0800/WhatsApp")
NÃO se reproduziu limpo — a divergência é espalhada (0800 inclusive) e Fale Conosco
veio zerada, em parte porque muitos tickets desse canal morrem antes de qualquer
oferta ("Sem Interação"). Interpretação a validar na auditoria manual: a divergência
mede menos o canal e mais o momento em que o atendente desiste de preencher o campo.

## Tempos de resposta

- Primeira resposta (qualquer, inclui robô): média ~85h.
- **Primeira resposta substantiva** (humana, com conteúdo): mediana **~126h (5,2 dias)**;
  19/100 nunca tiveram resposta substantiva.

## Achados operacionais da amostra (para a auditoria manual)

1. ~10% da amostra é ticket-casca de contingência/disparo massivo (lotes 1245xxx,
   1413xxx) — quase sem texto; ficam com confiança baixa/média.
2. ~8% são duplicatas/continuações apontando para outro protocolo — o funil acontece
   no ticket irmão; atributos vêm de citações (confiança média).
3. Erros de classificação reais: cobrança indevida/duplicada e até "classe superior"
   rotulados como Categoria inferior (≥5 casos na amostra).
4. "Sem Interação" nem sempre é cliente que sumiu: há bounces de e-mail digitado
   errado pela agência — a oferta pode nunca ter chegado (≥3 casos).
5. Voz indireta domina (0800/Agências/WhatsApp): o END_USER frequentemente é agente
   de guichê, parceiro ou o atendente narrando; categorias às vezes nunca são
   nomeadas no texto ("classe inferior" genérico) → `categoria_comprada` fica
   não_informado mesmo com funil completo.
6. Divergências de valor entre formulário da agência e oferta do SAC (typos como
   R$ 5.970,00 por R$ 59,70 e R$ 11.099,00) — regra aplicada: vale o valor da oferta.

## Próximo passo (gate da Seção 10)

Auditoria manual do CSV (30 tickets contra as threads originais no Zoho). Só depois
do ajuste fino liberar o tema inteiro (5.715). Custo estimado do tema completo na
orquestração atual: ~230 fatias de download + ~440 fatias de extração por agentes.
