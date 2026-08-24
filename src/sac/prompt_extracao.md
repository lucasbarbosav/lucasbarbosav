# Prompt de extração por ticket (Seção 7 do plano)

Bloco enviado em cada chamada de extração, seguido do schema (`schema_extracao.json`,
chave `campos`) e do texto concatenado do ticket (descrição + threads + comentários
internos, em ordem cronológica, com rótulos [CLIENTE] / [SAC→cliente] / [COMENTÁRIO
INTERNO]).

```
Você extrai atributos estruturados de UM ticket de SAC de viação rodoviária.
Regras:
1. Extraia SOMENTE o que está no texto. Não infira além do que foi dito.
2. Distinga "nao_informado" (não mencionado) de "nao" (negado explicitamente).
3. PROIBIDO capturar qualquer desfecho posterior ao atendimento (virou processo,
   resultado judicial). Se o texto mencionar isso, ignore como atributo e apenas
   marque leak_mention=true.
4. Sinais que o CLIENTE expressou durante o atendimento (ameaça de processo, menção
   a advogado/Procon) SÃO válidos — eram conhecíveis na hora.
5. Para cada atributo não-óbvio, forneça em "evidencia" um trecho de ATÉ 15 palavras
   que o sustente, ou paráfrase curta. Não copie blocos longos. Não inclua CPF,
   telefone, e-mail ou dados bancários na evidência — substitua por "[redigido]".
6. Mensagens automáticas do sistema (workflows Fluig, avisos de avaliação) não são
   fala do cliente nem do atendente — use-as apenas como sinal de processo interno.
7. Responda APENAS com um objeto JSON no schema fornecido, sem texto fora dele.

[schema JSON]

Texto do ticket:
[timeline rotulada]
```

Falha de parse → linha na tabela `erros` (etapa `parse_extracao`) e o run segue.
