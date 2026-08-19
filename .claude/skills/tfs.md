---
name: tfs
description: Cria PBI no backlog XVIA (TFS on-prem) inferindo a Feature-pai a partir de uma instrução em texto livre. Dispara em `/tfs`, "criar pbi xvia", "lançar demanda xvia", "novo item no backlog xvia". Escopo do repo `lancar-demandas-xvia` — não confundir com o `/tfs` global (backlog SETDIG).
---

# `/tfs` — lançar PBI no backlog XVIA

Este skill orquestra o CLI `python -m src.xvia` (arquivo `src/xvia.py`) para criar um **Product Backlog Item** sob a Feature correta do Epic `1335269 — Implantação - Plataforma X-VIA`, e devolver o link do work item.

## Entrada esperada

```
/tfs <título curto> — <instrução em texto livre>
```

Exemplo:

```
/tfs Levantamento de Formulários — fazer levantamento dos formulários do FormFlow para ter a relação no X-Forms
```

O separador aceito é `—`, `-` ou `:`. Se o usuário só passar o título, peça a instrução em um turno seguinte antes de continuar.

## Algoritmo

### 1. Pré-requisitos (rodar em paralelo quando possível)

- **`dicionario/backlog-xvia.json`**: se não existir ou tiver mais de 24 h, rode `python -m src.xvia export`. Se o export falhar por falta de `XVIA_PAT`, pare e diga ao usuário: `setx XVIA_PAT "<token>"` num terminal novo.
- **`dicionario/features-xvia.json`**: obrigatório. Se faltar, pare e peça pra o usuário abrir issue no repo — não invente aliases sem revisão humana.
- **`dicionario/pessoas.json`**: precisa ter a chave `fabio` (responsável default de PBI, `src/xvia.py:41`). Se faltar: `python -m src.xvia quem "Fabio Ramos" --salvar-como fabio`.

### 2. Inferir a Feature (match híbrido)

1. Normalize o texto de entrada: minúsculas, sem acento (`unicodedata.normalize('NFKD')` + strip combining).
2. Para cada feature em `features-xvia.json`, conte quantos aliases ocorrem como substring do texto normalizado.
3. Cruze `titulo` com `dicionario/backlog-xvia.json` (`itens[]` onde `tipo == "Feature"`) para pegar o `id`. Se um título não casa, sinalize: mapa está fora de sincronia com o backlog.
4. **Confiança alta** → prosseguir sem perguntar quando:
   - existe um único vencedor com score ≥ 2, **ou**
   - existe um match de alias multi-palavra único (ex.: `formflow`, `carta de servico`).
5. **Ambiguidade** → use `AskUserQuestion` com os top-3 candidatos (label = `[CS] X-Forms`, description = 1 linha sobre o módulo). Sem chute.

### 3. Título

- **PBI criado pelo `/tfs` sempre leva `--sgd`.** A gente (SGD) é quem cria; portanto o prefixo `[SGD] - ` é padrão, não exceção. Só omita se o usuário disser explicitamente "sem SGD".
- Task filha de PBI `[SGD] - ...`: o CLI aplica `[SGD] - ` automaticamente. Não duplique o prefixo no `--titulo`.
- **Título de Task começa com verbo no infinitivo** (Integrar, Levantar, Configurar, Documentar, Validar, Publicar). Nunca só substantivo ou nome de ambiente.
  - Ruim: `"Desenvolvimento"` · Bom: `"Integrar sistemas ao SmartPass no ambiente de Desenvolvimento"`
  - Ruim: `"Homologação"` · Bom: `"Validar integração dos sistemas em Homologação"`
- Não adicione prefixo `[CS]`/`[CDI]`/`[INFRA]` automaticamente. O usuário decide.

### 4. Descrição — linguagem simples (Lei 15.263/2025)

Gere um rascunho no formato do CLAUDE.md do repo:

```
<uma frase dizendo o que precisa ser feito>

**Por quê**
<uma ou duas frases de contexto>

**Critérios de aceitação**
- <verificável 1>
- <verificável 2>
```

Regras:
- Voz ativa, sem jargão, sem "conforme", "no que tange", "supracitado".
- Critérios são verificáveis olhando o resultado (`Planilha X entregue`, não `Fazer levantamento`).
- Se o texto do usuário for muito curto pra gerar critérios honestos, peça mais contexto.

### 5. Preview + confirmação

Mostre em uma mensagem só:

```
Feature-alvo: [CS] X-Forms (#NNNN)
Título:       Levantamento de Formulários
Responsável:  fabio (default)

<descrição rascunhada>
```

Pergunte via `AskUserQuestion` com opções: **Criar**, **Editar descrição**, **Trocar Feature**, **Cancelar**. Pule esta etapa apenas se o usuário já disse "cria direto" na mensagem inicial.

### 5b. Detectar lançamento retroativo

Se o usuário narra trabalho **já feito** ("eu fiz", "levantei", "documentei", "criei", "estudei"), ou aponta arquivos/repos que já existem com o material, é lançamento retroativo:

- **Todas as Tasks nascem `--estado Done`** (herda para as filhas do PBI).
- PBI segue padrão `Approved` (do CLI). Se o trabalho todo já está pronto, marcar o PBI também como `--estado Done`.
- **Anexos/artefatos vão no PBI, não na Task.** Task retroativa é `Done` e fica "fechada" no radar — artefato disperso lá some. Concentrar tudo no PBI, que é o cartão que os stakeholders abrem.
- Se possível, passar `--data-original DD-MM-YYYY` quando o usuário sabe a data em que fez o trabalho.

Prospectivo (padrão): PBI = `Approved`, Task = `To Do`. Anexo pode ir na própria Task quando é insumo específico daquela etapa.

### 6. Executar

Dry-run primeiro:

```bash
python -m src.xvia novo --tipo PBI --pai <ID_FEATURE> \
  --titulo "<TITULO>" --descricao "<DESCRICAO>"
```

Se a saída for limpa (código 0 e payload coerente), rode com `--apply`. Escape aspas duplas do texto no shell do Windows (PowerShell) trocando `"` internas por `""` dentro do argumento, ou use here-strings (`@'...'@`).

### 7. Devolver o link — sempre

A saída do `--apply` contém:

```
[CRIADO] #1339123  <titulo>
         https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1339123
```

**Toda mensagem de conclusão deve trazer o link clicável de cada item criado ou atualizado.** Nunca listar só o id — o usuário precisa navegar direto no navegador. Vale para PBI, Task, Feature, comentário, anexo.

Formato preferido quando há mais de um item: tabela

```
| # | Tipo | Título | Link |
|---|---|---|---|
| 1339123 | PBI | ... | https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1339123 |
```

Item único: linha `#NNNN — Título — <URL completa>`.

## Activity — obrigatório quando criar Task

Task no XVIA exige o campo `Microsoft.VSTS.Common.Activity`. Valores válidos:
`Deployment | Design | Development | Documentation | Requirements | Testing`.

Regras de inferência (aplicar por ordem — primeira que casa vence):

| Sinal no título/descrição | Activity |
|---|---|
| levantamento, mapeamento, análise, especificação, requisito | **Requirements** |
| protótipo, wireframe, design, UI, UX, layout | **Design** |
| teste, validação, homologação, QA | **Testing** |
| deploy, publicar, subir para produção, ambiente | **Deployment** |
| documentar, tutorial, manual, guia | **Documentation** |
| desenvolver, implementar, codificar, instalar, integrar, configurar | **Development** |
| nenhum casou | **perguntar via AskUserQuestion** — nunca chutar |

Passe `--activity <Valor>` ao criar Task. O CLI aborta se faltar.

## O que este skill NÃO faz

- Não cria Feature (só PBI e Task). Para Task, use `--tipo Task --pai <PBI_ID> --activity <Valor>`.
- Não edita item existente. Divergência de título vira nota no `DICIONARIO.md`, correção é manual na UI.
- Não fecha nem deleta.
- Não inventa aliases: se a Feature-alvo não estiver no `features-xvia.json`, pare e peça pra atualizar o mapa.

## Referências no código

- `src/xvia.py:236` — `cmd_export` (gera o dicionário).
- `src/xvia.py:384` — `_criar_item` (valida hierarquia).
- `src/xvia.py:421` — `cmd_novo` (o comando que este skill invoca).
- `src/xvia.py:41` — mapa de responsáveis padrão por tipo.
- `src/xvia.py:75` — normalização de título (só SGD é reescrito).
