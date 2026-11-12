# Analise de erros da extracao (NER/RE)

Gerado por `python evaluate_extraction.py --analysis`. Cada divergencia entre o gabarito e a extracao foi classificada automaticamente:

- **enumeracao separada**: o gabarito tem um item e o LLM separou em varios (ex.: "justificativa, data e responsavel" -> 3 itens). Conteudo correto, granularidade diferente.
- **variacao de nome**: mesmo conceito com nome diferente (um contido no outro ou sobreposicao >= 50% das palavras).
- **tipo/relacao diferente**: conceito encontrado, mas com tipo de entidade ou relacao errado. Erro real.
- **omissao**: item do gabarito que nao foi extraido. Erro real.
- **extra (fora do gabarito)**: item extraido sem correspondente no gabarito. Pode ser erro ou item valido nao anotado.

## Metricas

| | Precisao | Recall | F1 |
|---|---|---|---|
| Entidades (NER), estrita | 0.62 | 0.75 | 0.68 |
| Entidades (NER), relaxada | 0.91 | 0.89 | 0.90 |
| Relacoes (RE), estrita | 0.43 | 0.56 | 0.49 |
| Relacoes (RE), relaxada | 0.87 | 0.78 | 0.82 |

A relaxada aceita enumeracao separada e variacao de nome como acerto; tipo errado, omissao e extra continuam erro.

## Divergencias por categoria

| Categoria | Entidades | Relacoes |
|---|---|---|
| enumeracao separada | 3 | 3 |
| variacao de nome | 1 | 1 |
| tipo/relacao diferente | 1 | 1 |
| omissao | 2 | 3 |
| extra (fora do gabarito) | 2 | 2 |

## Detalhe

| Doc | Tipo | Categoria | Gabarito | Extraido |
|---|---|---|---|---|
| DOC001 | ENT | variacao de nome | Limit / r 2 000 por dia | Limit / r 2 000 |
| DOC001 | REL | variacao de nome | limite de transferencia pix / HAS_LIMIT / r 2 000 por dia | limite de transferencia pix / HAS_LIMIT / r 2 000 |
| DOC002 | REL | omissao | valores muito superiores ao padrao historico / MAY_TRIGGER / analise manual | - |
| DOC004 | ENT | omissao | Action / revisao dos dados cadastrais | - |
| DOC004 | REL | omissao | alteracao relevante de endereco renda ou contato / MAY_TRIGGER / revisao dos dados cadastrais | - |
| DOC005 | ENT | omissao | Condition / mais de um titular | - |
| DOC005 | ENT | tipo/relacao diferente | Obligation / considerar todos os vinculos | Action / consultas devem considerar todos os vinculos |
| DOC005 | ENT | extra (fora do gabarito) | - | Condition / contas conjuntas |
| DOC005 | REL | tipo/relacao diferente | conta compartilhada / MUST_RECORD / considerar todos os vinculos | contas conjuntas / MAY_TRIGGER / consultas devem considerar todos os vinculos |
| DOC005 | REL | omissao | conta compartilhada / REQUIRES / mais de um titular | - |
| DOC005 | REL | extra (fora do gabarito) | - | conta compartilhada / REQUIRES / contas conjuntas |
| DOC008 | ENT | enumeracao separada | Obligation / registrar justificativa data e responsavel | Obligation / data; Obligation / justificativa; Obligation / responsavel |
| DOC008 | REL | enumeracao separada | bloqueio preventivo / MUST_RECORD / registrar justificativa data e responsavel | bloqueio preventivo / MUST_RECORD / data; bloqueio preventivo / MUST_RECORD / justificativa; bloqueio preventivo / MUST_RECORD / responsavel |
| DOC009 | ENT | enumeracao separada | Obligation / identificador transacao relacionada motivo e status | Obligation / identificador; Obligation / motivo; Obligation / status; Obligation / transacao relacionada |
| DOC009 | REL | enumeracao separada | contestacao de compra / MUST_RECORD / identificador transacao relacionada motivo e status | contestacao de compra / MUST_RECORD / identificador; contestacao de compra / MUST_RECORD / motivo; contestacao de compra / MUST_RECORD / status; contestacao de compra / MUST_RECORD / transacao relacionada |
| DOC010 | ENT | enumeracao separada | Condition / perfis autorizados e finalidade legitima | Condition / finalidade legitima; Condition / perfis autorizados |
| DOC010 | ENT | extra (fora do gabarito) | - | Obligation / dados de clientes |
| DOC010 | REL | enumeracao separada | privacidade e acesso / REQUIRES / perfis autorizados e finalidade legitima | privacidade e acesso / REQUIRES / finalidade legitima; privacidade e acesso / REQUIRES / perfis autorizados |
| DOC010 | REL | extra (fora do gabarito) | - | privacidade e acesso / MUST_RECORD / dados de clientes |

## Limitacoes

- O gabarito cobre DOC001-DOC010 (um documento por tema), anotado por uma pessoa so; sem concordancia entre anotadores.
- Os 30 documentos sao 10 textos identicos em 3 versoes. A extracao dos splits dev/test e igual a do train, entao nao ha avaliacao independente por split.
- A classificacao das divergencias e heuristica (sobreposicao de palavras); confira o detalhe acima.
