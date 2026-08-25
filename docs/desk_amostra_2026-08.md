# Amostra — taxa de entrega da informação (n = 1.000, 2026-08-25)

Números **direcionais**, colhidos por amostragem enquanto o censo (que exige
credencial de API ou export) não roda. Não substituem o censo; serão
substituídos pelo `desk_entrega_classificada` completo quando ele rodar.

## Desenho

- Universo: tickets do SAC principal com `cf_area_pi` preenchido,
  01/01–21/08/2026 (N = 39.983 na data da coleta).
- Amostragem sistemática estratificada por mês (proporcional ao volume
  mensal), em **200 clusters de 5 tickets consecutivos** por `createdTime` =
  **n = 1.000** (2,5% do universo). Sementes 20260824 (77 clusters) e
  20260825 (123 clusters); manifestos com todos os offsets na sessão.
- Coleta via conector MCP; classificada pelo **mesmo pipeline do censo**
  (`src/desk_entrega.py`, via modo export). Os 426 casos que as regras não
  decidiram foram resolvidos por leitura do texto (o papel da passada de
  LLM); 30 permaneceram indeterminados por falta de conteúdo.
- IC95% com erro-padrão **entre clusters** (200 PSUs) — mais honesto que o
  binomial simples, que ignoraria a correlação dentro do cluster.
- Limite da API contornado: `from` aceita no máximo 4999, então os clusters
  além dessa posição foram recuperados com `sortBy=-createdTime` e
  `from = N − offset − 5` (mesmas posições, ordem invertida).

## Resultado (n = 1.000, 200 clusters)

| estado | share | IC95% |
|---|---:|---|
| Entregue no Desk | 46,3% | 41,9% – 50,7% |
| Entregue fora do Desk | 10,8% | 8,6% – 13,0% |
| Indeterminado (piso de incerteza) | 13,2% | 10,3% – 16,1% |
| **Não entregue** | **29,7%** | 24,7% – 34,7% |

- **Caixa-preta** (fora do Desk + indeterminado): **24,0%** [20,6–27,4%].
- **Pendência marcada sem disparo rastreável**: **59,4%** [55,3–63,5%] — em
  quase 6 de cada 10 tickets o `cf_area_pi` é preenchido, mas não há macro de
  pendência nem e-mail interno registrando o pedido à área.
- Latência da área (onde rastreável, n=571): mediana **21,9 h**, p90 **187 h**.
- Latência do disparo (abertura → pedido à área, n=406): mediana **100 h**,
  p90 **269 h** — o gargalo mediano está antes de a área ser acionada.

### Estabilidade em relação à amostra menor

A primeira rodada (n=385) deu 48,8% entregue no Desk, 30,1% não entregue e
58,7% sem disparo. Com n=1.000 os valores ficaram em 46,3%, 29,7% e 59,4%:
todos dentro do IC anterior. O que mudou foi a **precisão** (margem do número
principal caiu de ±7,5 para ±4,4 p.p.), não a leitura.

## Por área (n≥20; células pequenas seguem indicativas)

| área | entregue no Desk | caixa-preta | não entregue | n |
|---|---:|---:|---:|---:|
| Operacional | 75,4% | 12,3% | 12,3% | 325 |
| Manutenção | 57,4% | 22,3% | 20,3% | 148 |
| Financeiro | 32,6% | 62,8% | 4,7% | 86 |
| Canais Digitais | 19,2% | 65,4% | 15,4% | 26 |
| Administrativo | 26,1% | 34,8% | 39,1% | 23 |
| Comercial | 23,8% | 22,5% | 53,7% | 391 |

Leitura: **Operacional** (Achados e Perdidos, apuração de atraso) responde
dentro do Desk. **Financeiro e Canais Digitais** resolvem, mas fora do Desk —
Fluig, GLPI, telefone, WhatsApp: a caixa-preta passa de 60% neles, e o
Financeiro quase não tem "não entregue" (4,7%), ou seja, o trabalho acontece,
só não fica registrado. **Comercial** é onde a informação mais **não volta**:
53,7% sem evidência de retorno, na maior área do universo.

## Ressalvas

- Amostra ≈ ±4,4 p.p. no total; recortes por área com n<100 são indicativos.
- A classificação usa o resumo das threads e o texto pleno apenas nos casos
  ambíguos (426 lidos, dos quais 48 exigiram `getThread`). O censo poderá
  refinar puxando texto completo em massa.
- `indeterminado` é reportado separado por definição do estudo: é o piso de
  incerteza, não resto.
- Adjudicação dos ambíguos seguiu critério fixo: **conta como entrega** o
  achado da apuração (inclusive negativo: "não localizado", "improcedente"),
  a confirmação financeira com data/resultado e a explicação do caso concreto;
  **não conta** o encaminhamento ("encaminhamos ao setor responsável"), a
  abertura de chamado, o pedido de dados ao cliente, o ponteiro para outro
  protocolo e a oferta isolada (cupom/cortesia) — coerente com a regra de que
  oferta ≠ entrega de informação.
