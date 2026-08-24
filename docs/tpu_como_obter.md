# Como obter o dicionário TPU de assuntos (SGT/CNJ)

`docs/tpu_dicionario.csv` é **pré-requisito** de qualquer consulta em massa ao DataJud.
Sem ele, `src/datajud.py` para com erro — de propósito. Códigos de assunto escritos de
memória são a forma mais fácil de produzir uma série inteira que parece certa e está errada.

## Caminho 1 — exportação manual (recomendado, auditável)

1. Abra o SGT: <https://www.cnj.jus.br/sgt/consulta_publica_assuntos.php>
2. Navegue até o ramo **Direito do Consumidor** e exporte/copie a listagem de assuntos
   (código + nome + hierarquia). Repita para os assuntos de **Transporte**.
3. Salve como CSV e importe:

```bash
./venv/bin/python -m src.tpu --de-csv ~/Downloads/assuntos_sgt.csv
./venv/bin/python -m src.tpu --resumo
```

O importador aceita variações de cabeçalho (`cod`/`codigo`/`cod_assunto`,
`nome`/`assunto`/`descricao`, `pai`/`codigo_pai`, `caminho`/`hierarquia`) e falha alto se
faltar `codigo` ou `nome`.

## Caminho 2 — consulta pública automatizada

```bash
./venv/bin/python -m src.tpu --do-sgt
```

⚠️ **O endpoint usado por esse modo não foi confirmado contra a documentação viva** — o
domínio `cnj.jus.br` estava inacessível quando o módulo foi escrito. A função valida a
estrutura do que voltar e se recusa a gravar um dicionário que não tenha código + nome,
mas confira o resultado com `--resumo` antes de confiar nele.

## Formato do arquivo

| coluna | obrigatória | descrição |
|---|---|---|
| `codigo` | sim | código numérico do assunto na TPU |
| `nome` | sim | nome do assunto |
| `ramo` | não | ramo de primeiro nível (ex.: `DIREITO DO CONSUMIDOR`) |
| `codigo_pai` | não | código do assunto pai, para reconstruir a hierarquia |
| `nivel` | não | profundidade na árvore |
| `caminho` | não | hierarquia completa concatenada |

`ramo` e `caminho` não são obrigatórios, mas melhoram muito o recorte: os filtros de
consumo e transporte procuram os termos em `nome`, `ramo` e `caminho` somados.

## Ressalva sobre o recorte setorial

A TPU **não tem** um assunto que isole "transporte rodoviário interestadual de passageiros".
`tpu.codigos_consumo_transporte()` cruza os assuntos de consumo com os de transporte e emite
um `WARNING` dizendo exatamente isso. É a melhor aproximação disponível e deve ser rotulada
como aproximação em todo gráfico que a use — nunca apresentada como recorte exato do setor.
