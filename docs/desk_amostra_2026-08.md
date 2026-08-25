# Amostra preliminar — taxa de entrega da informação (2026-08-25)

Números **preliminares e direcionais**, colhidos por amostragem enquanto o
censo (que exige credencial de API ou export) não roda. NÃO substituem o
censo; substituí-los-á o `desk_entrega_classificada` completo.

## Desenho

- Universo: tickets do SAC principal com `cf_area_pi` preenchido,
  01/01–21/08/2026 (N = 39.983 na data da coleta).
- Amostragem sistemática estratificada por mês (proporcional ao volume
  mensal), em **77 clusters de 5 tickets consecutivos** por `createdTime` =
  **n = 385**. Semente 20260824; offsets no manifesto da sessão de coleta.
- Coleta via conector MCP; classificada pelo **mesmo pipeline do censo**
  (`src/desk_entrega.py`, via modo export). Os 147 casos ambíguos das regras
  foram resolvidos por leitura dos textos (papel da passada de LLM); 6
  permaneceram indeterminados.
- IC95% com erro-padrão **entre clusters** (77 PSUs) — mais honesto que o
  binomial simples; deff observado ~1,0–2,0.
- Fev/2026 concentra um pico: 19–21/02 tem 6.067 tickets (15% do universo) —
  semana de transferência massiva. A amostra a representa proporcionalmente.

## Resultado (n=385)

| estado | share | IC95% |
|---|---:|---|
| Entregue no Desk | 48,8% | 41,3% – 56,4% |
| Entregue fora do Desk | 12,7% | 8,8% – 16,6% |
| Indeterminado (piso de incerteza) | 8,3% | 4,7% – 11,9% |
| Não entregue | 30,1% | 21,7% – 38,6% |

- **Caixa-preta** (fora do Desk + indeterminado): **21,0%** [15,9–26,2%].
- **Pendência marcada sem disparo rastreável no Desk**: **58,7%** [51,8–65,6%]
  — em mais da metade dos tickets o `cf_area_pi` é marcado, mas não há macro
  de pendência nem e-mail interno registrando o pedido.
- Latência da área (onde rastreável, n=237): mediana **25,6 h**, p90 **210 h**.
- Latência do disparo (abertura → pedido à área, n=159): mediana **102 h**,
  p90 **248 h** — o gargalo mediano está antes da área ser acionada.

## Por área (pontual, sem IC — células pequenas)

| área | entregue no Desk | caixa-preta | não entregue | n |
|---|---:|---:|---:|---:|
| Operacional | 80,2% | 8,3% | 11,6% | 121 |
| Manutenção | 55,6% | 25,9% | 18,5% | 54 |
| Financeiro | 39,4% | 57,6% | 3,0% | 33 |
| Comercial | 27,0% | 18,2% | 54,7% | 159 |

Leitura: Operacional (Achados e Perdidos etc.) responde no Desk; o Financeiro
resolve, mas fora do Desk (Fluig/GLPI/telefone — caixa-preta de 58%); o
Comercial é onde a informação mais **não volta** (55% sem evidência de
retorno).

## Ressalvas

- Amostra ≈ ±5 p.p. no total e ±7–8 p.p. nos recortes; células por
  área/assunto são indicativas.
- A classificação usa o resumo das threads (~150 caracteres) e o texto pleno
  somente nos ambíguos; o censo poderá refinar com `getThread` em massa.
- `indeterminado` é reportado separado por definição do estudo: é o piso de
  incerteza, não resto.
