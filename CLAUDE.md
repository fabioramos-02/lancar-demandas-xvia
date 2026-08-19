# lancar-demandas-xvia — instruções do projeto

CLI que lança demandas no backlog **XVIA** do TFS on-prem (`tfs.sgi.ms.gov.br/tfs/Global/XVIA`),
projeto Scrum, Epic raiz **1335269 — Implantação - Plataforma X-VIA**.

## Antes de sugerir onde encaixar qualquer demanda

**Leia `dicionario/DICIONARIO.md`.** Ele é gerado a partir do backlog real e traz a árvore
completa, os prefixos em uso e as divergências. Não deduza a hierarquia de memória — ela muda.

Se o arquivo não existir ou estiver velho:

```bash
python -m src.xvia export
```

## Hierarquia

```
Epic  <-  Feature  <-  Product Backlog Item  <-  Task
```

O CLI aborta se o pai for do tipo errado. Task nunca pendura direto em Feature.

## Regras de lançamento

| Regra | Valor |
|---|---|
| Título de PBI da SGD | `[SGD] - Título` (hífen cercado de espaços) |
| Título dos demais | livre; prefixo de módulo entre colchetes (`[CDI]`, `[INFRA]`) |
| Responsável de Feature | `maycon` |
| Responsável de PBI e Task | `fabio` |
| Estado inicial de PBI | `New` |
| Estado inicial de Task | `To Do` |
| Area / Iteration | `XVIA` |

Responsáveis vivem em `dicionario/pessoas.json` (apelido → identidade), preenchido por `quem`.
Nunca hardcode identidade no código.

## Descrição — linguagem simples

Lei 15.263/2025 e Decreto 16.744/2026. Texto curto, voz ativa, sem jargão. Estrutura:

```
Frase única dizendo o que precisa ser feito.

**Por quê**
Uma ou duas frases de contexto.

**Critérios de aceitação**
- Verificável, no que dá pra conferir olhando o resultado.
- Um por linha.
```

O `--descricao` aceita esse texto direto: `- ` vira lista, `**x**` vira negrito e URLs viram
links. Não escreva HTML à mão.

Para textos que vão para o cidadão, use os agentes `linguagem-simples-escritor` e
`linguagem-simples-revisor`.

## Fluxo padrão

```bash
python -m src.xvia novo --tipo Task --pai 1337789 --titulo "Instalação do CMS" --descricao "..."
```

Isso é **dry-run**: imprime o payload e não escreve nada. Confira o pai e o título, depois
repita com `--apply`.

Demandas retroativas vão por lote (`lote/*.json`), com `data_original` e `anexos`.
Ver `lote/exemplo-retroativas.json`.

## O que o CLI não faz — por design

- Não deleta e não fecha item.
- Não corrige título de item que já existe. Divergência é **relatada** no dicionário;
  a correção é manual e consciente na UI.
- Não adivinha o pai. Quem decide é você lendo o dicionário; o CLI só valida.

## Segurança

PAT em `XVIA_PAT` (variável de ambiente). Nunca em commit, chat ou ticket.
`.gitignore` bloqueia `.env`, `*.token`, `*.pat`.

## Não confundir com `setdig-tfs-backlog`

`../setdig-tfs-backlog` é um **espelho JSON local** de outro backlog (projeto SETDIG),
com sua própria taxonomia e a skill `/tfs`. Este repo escreve no **TFS real**, projeto XVIA.
São backlogs distintos — não misture ids nem regras de título entre os dois.
