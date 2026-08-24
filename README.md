# Judicialização do direito do consumidor — recorte: transporte rodoviário interestadual de passageiros

Pipeline reprodutível que mede a judicialização do consumo no Brasil, isola o setor de
transporte rodoviário de passageiros e avalia sinais de litigância de massa.

**Estado**: em construção. Veja `python run_all.py --listar` para o que já está pronto
e o que falta.

## Perguntas que o pipeline responde

1. A judicialização do consumo está aumentando? (série nacional e por UF: SP, RJ, MG, CE)
2. Como isolar e visualizar o setor de transporte rodoviário de passageiros?
3. Há sinais de litigância de massa/predatória no recorte?

## Como rodar

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env      # preencha DATAJUD_API_KEY com a chave pública do CNJ

./venv/bin/python run_all.py --listar          # o que existe e o que falta
./venv/bin/python run_all.py                   # roda as etapas pendentes
./venv/bin/python run_all.py --etapas consumidor
./venv/bin/python run_all.py --refresh         # rebaixa tudo (ignora cache)
```

O pipeline é **idempotente**: uma etapa cujo Parquet já existe é pulada. `--refresh`
rebaixa os brutos; `--recalcular` refaz só o tratamento a partir do cache.

Testes de unidade (fixtures sintéticas, não alimentam nenhum gráfico):

```bash
./venv/bin/python tests/test_consumidor_gov.py
```

## Estrutura

```
src/               um módulo por fonte + infraestrutura comum (_common.py)
data/raw/          brutos baixados (não versionados)
data/clean/        datasets tratados em Parquet + .meta.json de proveniência
output/charts/     gráficos, cada um com rodapé de fonte/ano-base/data de extração
output/dashboard/  index.html estático (Plotly embutido, sem backend)
docs/              fontes.md (log append-only), log_extracoes.csv, dicionários
tests/             testes de unidade da lógica de transformação
```

## Proveniência

Nenhum número sem proveniência. Toda extração — de rede ou de cache — vira uma linha em
`docs/log_extracoes.csv` e um parágrafo em `docs/fontes.md`, com fonte, URL, data de
extração, nº de registros e SHA-256. Todo Parquet em `data/clean/` tem um `.meta.json` ao
lado com o mesmo cartão de identidade, e é dele que sai o rodapé dos gráficos.

Se uma fonte estiver indisponível, o pipeline **para com erro** (`ErroDeFonte`) em vez de
estimar, interpolar ou preencher lacuna. Não há dado sintético em `data/clean/`.

## Regras metodológicas embutidas no código

- **B2C ≠ regulatório.** Dois universos separados que nunca se somam. B2C = Justiça
  Estadual + assunto de consumo. Regulatório/concorrencial = Justiça Federal com a ANTT
  como parte (casos tipo Buser, Gadotti, Rota Transportes). O segundo é dimensionado e
  **excluído** da leitura de experiência do cliente.
- **Um processo, um voto.** No DataJud um processo pode ter vários assuntos. A contagem é
  por `numeroProcesso` distinto, nunca por ocorrência de assunto — somar ocorrências infla
  o volume.
- **Terrestre ≠ aéreo.** Transporte Terrestre e Transporte Aéreo são rótulos distintos; o
  aéreo entra só como benchmark comparativo.
- **CX ≠ Passe Livre.** Na base da Ouvidoria da ANTT, temas de experiência do cliente
  (atraso, cancelamento, bagagem, reembolso, overbooking) ficam separados de
  Passe Livre/gratuidade, que não é conflito de consumo comercial.
- **Normalização.** Comparações entre empresas ou modais usam a métrica por 100 mil
  passageiros, não o volume absoluto.
- **Não-avaliada ≠ não-resolvida.** No consumidor.gov.br, reclamação sem avaliação do
  consumidor vira `NA`, não `False` — contá-la como não resolvida penalizaria quem tem
  muita reclamação sem avaliação.

## Fontes

| # | Fonte | Uso | Situação |
|---|---|---|---|
| 1 | [DataJud — API Pública (CNJ)](https://datajud-wiki.cnj.jus.br/api-publica) | tendência judicial por assunto/classe/tribunal | pendente |
| 2 | [consumidor.gov.br (Senacon/MJ)](https://dados.mj.gov.br/dataset/reclamacoes-do-consumidor-gov-br) | recorte B2C **por empresa** | implementada |
| 3 | [Ouvidoria da ANTT](https://www.gov.br/antt/pt-br/canais-atendimento/ouvidoria) | reclamações do setor (parse de PDF) | pendente |
| 4 | [Painel dos Grandes Litigantes (CNJ)](https://www.cnj.jus.br/primeira-versao-de-painel-sobre-grandes-litigantes-no-brasil-e-lancada/) | checagem de concentração | pendente |
| 5 | [Dados abertos ANTT](https://dados.antt.gov.br/dataset/transporte-rodoviario-de-passageiros) / ANAC | passageiros transportados (denominador) | pendente |

O log completo, com URL exata e data de cada extração, fica em `docs/fontes.md`.

## Ressalvas (leia antes de citar qualquer número)

- **As partes não são expostas pela API do DataJud.** A API pública não traz o nome das
  partes de forma estruturada e consultável. É impossível filtrar "ações contra a viação
  X" por ela. A API mede volume por assunto, classe, tribunal e tempo — nada mais. Toda
  análise por empresa vem do consumidor.gov.br.
- **Lacuna do rodoviário B2C no DataJud.** Não há código de assunto na TPU que isole
  "transporte rodoviário interestadual de passageiros" no consumo. O que existe são
  assuntos de transporte e de consumo que se cruzam de forma imperfeita. Qualquer recorte
  setorial pelo DataJud é uma aproximação, e o pipeline o rotula como tal.
- **Passe Livre domina a base da ANTT.** O principal motivo de manifestação na Ouvidoria
  costuma ser Passe Livre/gratuidade, que é acesso a política pública, não conflito de
  consumo comercial. Somar Passe Livre com atraso/bagagem produz um número sem sentido.
  Segundo o relatório anual da Ouvidoria, ~73% das manifestações são pedido de informação
  e apenas ~12% são reclamação sobre serviço delegado.
- **Cobertura do consumidor.gov.br é voluntária.** Só aparecem empresas aderentes à
  plataforma. Ausência de uma empresa não é ausência de conflito.
- **Estimativas de litigância predatória são contestadas.** Como o DataJud não expõe
  partes nem peças, é **impossível** medir similaridade textual ou repetição de petições.
  O que este pipeline mede são *sinais indiretos*: concentração de réus, razão entre ações
  judiciais e reclamações pré-judiciais, e picos anômalos por comarca. Sinal não é prova:
  concentração alta pode indicar litigância predatória **ou** simplesmente uma empresa
  grande com muitos clientes e serviço ruim. Os gráficos dizem isso explicitamente.
- **Reclamação não é processo.** consumidor.gov.br é etapa pré-judicial. Comparações entre
  as duas bases medem propensão a judicializar, não o mesmo fenômeno.
