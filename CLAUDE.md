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
| Título de PBI criado pelo SGD | `[SGD] - Título` (padrão — nós somos SGD, sempre passar `--sgd`) |
| Título de Task filha de PBI SGD | herda `[SGD] - Título` automaticamente (CLI aplica) |
| Título de Task — forma | verbo no infinitivo (`Integrar…`, `Levantar…`, `Configurar…`), nunca só substantivo ou nome de ambiente |
| Título dos demais | livre; prefixo de módulo entre colchetes (`[CDI]`, `[INFRA]`) |
| Responsável de Feature | `maycon` |
| Responsável de PBI e Task | `fabio` |
| Estado inicial de PBI | `Approved` (padrão do CLI — SGD já triou; nasce liberado pra puxar) |
| Estado inicial de Task | `To Do` (ou `Done` se lançamento retroativo — ver regra abaixo) |
| Activity (Task) | obrigatório — `Deployment` \| `Design` \| `Development` \| `Documentation` \| `Requirements` \| `Testing` |
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

## Lançamento retroativo — Task já nasce `Done`

Se o usuário narra trabalho **já executado** ("eu fiz", "levantei", "documentei", "criei", "estudei", material pronto no repositório, `--data-original` presente), o CLI/skill trata como lançamento retroativo: **todas as Tasks criadas nesse fluxo nascem com `--estado Done`**. O PBI segue o padrão (`Approved`); se o trabalho todo já está pronto, o PBI vai para `Done` explicitamente.

Como identificar retroativo:
- Verbos no passado descrevendo o próprio trabalho.
- Referência a arquivos/repos que já existem no disco com o material.
- Uso do `--data-original` no CLI ou entrada em `lote/*.json`.

**Anexos em Task retroativa vão no PBI pai.** Quando a Task nasce `Done` (retroativa), qualquer artefato/anexo/evidência é vinculado ao **PBI** (agregador da entrega), nunca na Task. Motivo: o PBI é o cartão que os stakeholders abrem; artefato disperso em Task fechada some do radar. Se houver várias Tasks retroativas sob o mesmo PBI, todos os anexos ficam concentrados no PBI. Em Task prospectiva (`To Do`), o anexo pode ir na própria Task quando é insumo daquela etapa específica.

## Saída ao usuário — sempre com link

Toda vez que um work item for criado ou atualizado, o retorno no chat inclui o link clicável do item (`https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/<id>`), não só o id. Vale para PBI, Task, Feature, comentário, anexo — qualquer ação que aponte para um item específico. Formato preferido: tabela `| # | Título | Link |` ou linha `#NNNN — Título — <URL>`.

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
