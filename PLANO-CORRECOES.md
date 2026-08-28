# Plano de correção do backlog XVIA

Estado do backlog em **28/08/2026**, apurado com `python -m src.xvia export`
(365 itens, Epics `1333593` — SGD — e `1335269` — plataforma).

O plano corrige o que já está errado no TFS e fecha a porta para o erro se repetir.
Cada fase é independente: dá para parar depois de qualquer uma.

**Regra de escopo:** só mexemos no que pendura no Epic `1333593` (SGD) ou no que
o nosso CLI criou. O Epic `1335269` é dos outros times — lá a gente só relata.

---

## Fase 0 — feito

- [x] `export` puxa os dois épicos numa passada (`--epic` virou repetível).
- [x] Item novo herda `AreaPath` e `IterationPath` do pai — ver `src/xvia.py`.
- [x] Regra dos dois épicos escrita em `CLAUDE.md` e `README.md`.
- [x] 3 testes cobrindo a herança (`tests/test_regras.py`).

Isso resolve os itens **futuros**. Os já criados continuam errados — Fase 1.

---

## Fase 1 — feito em 28/08/2026

Criado o subcomando `xvia sincronizar` (`src/xvia.py`), dry-run por padrão. Ele alinha
**só** `AreaPath` e `IterationPath` ao valor do pai, de cima para baixo.

```bash
python -m src.xvia sincronizar            # dry-run: lista o que mudaria
python -m src.xvia sincronizar --apply    # escreve
```

**43 itens corrigidos** sob o Epic `1333593`:

| Mudança | Qtd |
|---|---|
| `iteration XVIA` -> `XVIA\Sprint 1` | 40 |
| `area XVIA` -> `XVIA\SGD\Interno` | 5 |
| `area XVIA` -> `XVIA\SGD` | 3 |

São 43 itens porque oito tinham os dois campos errados. O número passou dos 39 previstos
porque a apuração original só contou a iteration.

### Subárea é refinamento, não erro

A primeira versão herdava o valor do pai sem ressalva e achatava `XVIA\SGD\Interno`
para `XVIA\SGD` — 19 itens perderiam a subárea de propósito. A regra final: só entra no
plano quem está **fora do ramo** do pai (raiz `XVIA` ou outro ramo). Quem refinou fica
como está e propaga o próprio caminho para os filhos.

### Conferido

```
python -m src.xvia sincronizar   ->  [OK] nada a sincronizar
python -m src.xvia export        ->  368 itens
```

Épico SGD: **242 itens, 0 fora de `XVIA\Sprint 1`**. Áreas: 217 em `XVIA\SGD`,
25 em `XVIA\SGD\Interno`.

Testes: 70 passando, 6 novos sobre `planejar_sincronizacao`, `sob` e `ids_sob`.

---

## Fase 2 — correções manuais na interface

O CLI não reescreve título nem move item de pai, por decisão registrada em `CLAUDE.md`.
Estas correções são de quem conhece o conteúdo. Abra o item pelo link e ajuste.

### 2.1 Cinco PBIs sem título

Nasceram só com o prefixo, sob a Feature `1340258 [CDI] CMS Notícias` (épico da plataforma).

| Id | Título atual | Link |
|---|---|---|
| 1340260 | `[SGD]` | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1340260 |
| 1340261 | `[SGD]` | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1340261 |
| 1340262 | `[SGD]` | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1340262 |
| 1340263 | `[SGD]` | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1340263 |
| 1340264 | `[SGD]` | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1340264 |

Decidir com quem criou: nomear cada um no padrão `[SGD] - Título` ou remover os que
foram criados por engano. Cartão sem título não é puxável.

### 2.2 Três títulos `[SGD]` sem o hífen

O padrão é `[SGD] - Título`, com hífen cercado de espaços.

| Id | Título atual | Vira |
|---|---|---|
| 1338555 | `[SGD] Realizar benchmark mais atualizado` | `[SGD] - Realizar benchmark mais atualizado` |
| 1339560 | `[SGD] Validar nome para novo app` | `[SGD] - Validar nome para novo app` |
| 1340259 | `[SGD] API do Portal MS` | `[SGD] - API do Portal MS` |

### 2.3 Uma Task pendurada em Task

`1341740 Desenvolvimento de proposta login` está sob a Task `1336815`. A hierarquia do
backlog é `Epic ← Feature ← PBI ← Task`; Task não tem Task filha.

Duas saídas: mover a `1341740` para o PBI `1336233 Configuração do CMS`, ou transformar
o conteúdo em item de checklist da própria `1336815`. Item do épico da plataforma —
alinhar com o time responsável antes de mexer.

---

## Fase 3 — revisão de conteúdo das Tasks de reunião

Sob o PBI `1339795 [SGD] - Alinhamento Técnico`. Não é erro de ferramenta, é revisão
de quem participou:

- `1341965` — reunião de **19/08/2026**, ainda em `To Do`. Data passada: fechar como `Done`
  ou dizer o que ficou pendente.
- `1339814` — reunião de **10/06/2026**, ainda em `To Do`. Mesma pergunta.
- `1339798` — título começa com **22/07/2016**. Provável erro de digitação do ano: 2026.
- `1341973` — título começa com **13/0//2026**, mês faltando. Ainda em `To Do`.

---

## Fase 4 — evitar a volta do problema

- [x] `export` rodado depois da Fase 1; dicionário atualizado e commitado.
- [x] `sincronizar` documentado em `CLAUDE.md` e `README.md` como rotina pós-lote.
- [x] `--area` e `--iteration` registrados em `CLAUDE.md` como exceção consciente.

---

## Ordem sugerida

1. ~~Fase 1 (código + apply)~~ — **feito em 28/08/2026**.
2. Fase 2.2 e 2.3 — correções rápidas de título.
3. Fase 3 — revisão com o time.
4. Fase 2.1 — depende de decisão de quem criou os cinco PBIs.

Fases 2 e 3 são manuais por decisão registrada em `CLAUDE.md`: o CLI relata divergência
de título e de pai, não reescreve item que já existe.
