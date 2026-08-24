# Painel dos Grandes Litigantes (CNJ) — passo manual

O painel do CNJ é um **produto publicado**, não uma API consultável. Os números são
servidos por um painel interativo, sem endpoint documentado que aceite consulta arbitrária.

Optamos deliberadamente por **não raspar** a camada interna do painel: um scraper de painel
interativo quebra em silêncio na primeira mudança de layout, e um número errado que ninguém
percebe é pior do que um passo manual explícito.

## Como exportar

1. Abra o painel: <https://painelgrandeslitigantes.cnj.jus.br/>
   (contexto e histórico: [notícia de lançamento do CNJ](https://www.cnj.jus.br/primeira-versao-de-painel-sobre-grandes-litigantes-no-brasil-e-lancada/))
2. Filtre por **ramo da Justiça = Estadual** e pela UF de interesse (SP, RJ, MG, CE).
3. Selecione a visão de **maiores réus** (polo passivo).
4. Exporte a tabela para CSV/Excel — a maioria dos painéis oferece exportação no menu de
   cada visual.
5. Importe:

```bash
./venv/bin/python -m src.grandes_litigantes --de-csv ~/Downloads/grandes_litigantes.csv
```

## Colunas esperadas

| coluna | obrigatória | sinônimos aceitos |
|---|---|---|
| `litigante` | sim | nome, parte, razão social |
| `processos` | sim | quantidade, casos novos, pendentes, total |
| `polo` | não | posição, tipo |
| `ramo_justica` | não | ramo, segmento, justiça |
| `uf` | não | estado, tribunal |
| `setor` | não | atividade, CNAE |
| `ano` | não | ano base, período |

## Como ler o resultado

A coluna `parece_transporte` marca litigantes cujo nome ou setor sugere transporte rodoviário
de passageiros. **É um filtro por texto, não um classificador**: pega falso positivo
("Turismo" também aparece em agência de viagem) e perde falso negativo (holding com nome
neutro). Serve para dirigir a conferência humana.

**Se nenhuma viação aparecer, isso é um achado, não uma falha.** Sugere que as empresas de
transporte rodoviário não estão entre os maiores réus — o que é coerente com a lacuna do
rodoviário B2C observada no DataJud, e é justamente uma das respostas que o projeto procura.
