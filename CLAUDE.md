# lancar-demandas-xvia — instruções do projeto

CLI que lança demandas no backlog **XVIA** do TFS on-prem (`tfs.sgi.ms.gov.br/tfs/Global/XVIA`),
projeto Scrum. Dois épicos raiz convivem:

| Epic | Título | De quem é |
|---|---|---|
| **1333593** | `[SGD] - Documentação PGD-MS` | **nosso** — toda Feature do time SGD nasce aqui |
| 1335269 | `Implantação - Plataforma X-VIA` | implantação da plataforma, tocada pelos outros times |

`export` puxa os dois de uma vez. Ver <https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/1333593>.

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

**Feature nova do time SGD vai sob o Epic 1333593.** Não sob o 1335269 — lá ficam as Features
de implantação da plataforma (`[CDI]`, `[CS]`, `[INFRA]`, `[IA]`), que não são nossas. A chefia
já criou boa parte das Features do épico SGD; antes de criar uma nova, confira no dicionário se
já existe (`[SGD] - Portal`, `[SGD] - Cartas de Serviços`, `[SGD] - Aplicativo MS Digital`,
`[SGD] - Design System`, `[SGD] - Autenticação SSO`, …) e pendure o PBI na existente.

## Regras de lançamento

| Regra | Valor |
|---|---|
| Título de Feature do time SGD | `[SGD] - Título` (passar `--sgd`); pai = Epic **1333593** |
| Título de PBI criado pelo SGD | `[SGD] - Título` (padrão — nós somos SGD, sempre passar `--sgd`) |
| Título de Task filha de PBI SGD | herda `[SGD] - Título` automaticamente (CLI aplica) |
| Título de Task — forma | verbo no infinitivo (`Integrar…`, `Levantar…`, `Configurar…`), nunca só substantivo ou nome de ambiente |
| Título dos demais | livre; prefixo de módulo entre colchetes (`[CDI]`, `[INFRA]`) |
| Responsável de Feature | `maycon` |
| Responsável de PBI e Task | `fabio` |
| Estado inicial de PBI | `Approved` (padrão do CLI — SGD já triou; nasce liberado pra puxar) |
| Estado inicial de Task | `To Do` (ou `Done` se lançamento retroativo — ver regra abaixo) |
| Transição de estado | o TFS só aceita o estado inicial do tipo na criação; o CLI cria e transiciona por PATCH |
| Activity (Task) | obrigatório — `Deployment` \| `Design` \| `Development` \| `Documentation` \| `Requirements` \| `Testing` |
| Area / Iteration | **herdadas do pai** pelo CLI (o épico SGD usa `XVIA\SGD` + `XVIA\Sprint 1`); só passar `--area`/`--iteration` para divergir de propósito |

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

**Anexos em Task retroativa vão no PBI pai — o CLI força isso.** Quando a Task nasce `Done` (retroativa), qualquer artefato/anexo/evidência é vinculado ao **PBI** (agregador da entrega), nunca na Task. Vale tanto para `--anexo` no `novo`/`lote` quanto para `xvia anexar <id-da-task>`, que redireciona e avisa. Motivo: o PBI é o cartão que os stakeholders abrem; artefato disperso em Task fechada some do radar. Se houver várias Tasks retroativas sob o mesmo PBI, todos os anexos ficam concentrados no PBI. Em Task prospectiva (`To Do`), o anexo pode ir na própria Task quando é insumo daquela etapa específica.

## Evidência visual — print e foto sempre viram anexo

Print, screenshot, foto de tela, recorte de e-mail ou de conversa que o usuário mandar **é anexo
do work item**, não só texto na descrição. Nunca lançar a demanda e deixar a imagem no chat.

Onde pendura: mesma regra do anexo retroativo. Task `Done` manda para o **PBI pai**; Task
`To Do` pode segurar o próprio anexo quando a imagem é insumo daquela etapa. O CLI já força.

```bash
python -m src.xvia anexar <id> print1.png print2.png --apply
```

Imagem colada no chat **não é arquivo** — o CLI só sobe o que existe em disco. Quando o usuário
colar print, pedir o caminho ou combinar uma pasta de despejo antes de criar o item.

**Nunca anexar imagem com credencial.** Print com usuário e senha, token ou chave não sobe:
o work item é lido por todo o time e vira vazamento permanente. Pedir a versão tarjada, ou
registrar só a referência (número do chamado) e deixar a credencial no cofre de senha.

## Saída ao usuário — sempre com link

Toda vez que um work item for criado ou atualizado, o retorno no chat inclui o link clicável do item (`https://tfs.sgi.ms.gov.br/tfs/Global/XVIA/_workitems/edit/<id>`), não só o id. Vale para PBI, Task, Feature, comentário, anexo — qualquer ação que aponte para um item específico. Formato preferido: tabela `| # | Título | Link |` ou linha `#NNNN — Título — <URL>`.

## Comentário na Discussion — o CLI não faz, é PATCH direto

Não existe `xvia comentar`. Comentário vai por PATCH em `System.History`, usando o cliente:

```python
from src.tfs import Tfs
Tfs().atualizar(<id>, [{"op": "add", "path": "/fields/System.History", "value": html}])
```

O valor é HTML (`<div>` por parágrafo), não texto puro. Conferir depois em
`GET wit/workitems/<id>/updates`, campo `System.History.newValue`.

**Menção só notifica com o GUID de identidade.** `pessoas.json` guarda `DOMINIO\usuario`
(serve para `AssignedTo`), que **não** funciona em menção — vira texto morto, sem
notificação. O markup exigido é:

```html
<a href="#" data-vss-mention="version:2.0,GUID">@Nome Completo</a>
```

GUIDs já resolvidos:

| Apelido | Nome no TFS | GUID |
|---|---|---|
| maycon | Maycon Renato de Andrade Lisboa | `0211f0fa-3489-4854-a265-31d70628aea5` |

Para resolver um GUID novo, varrer os membros dos times — o comando `quem` descarta o `id`,
então é consulta direta:

```python
t = Tfs()
for tm in t.pedir("GET", "projects/XVIA/teams", no_projeto=False)["value"]:
    r = t.pedir("GET", f"projects/XVIA/teams/{tm['id']}/members", no_projeto=False)
    # m["identity"]["id"] é o GUID; m["identity"]["displayName"] é o nome da menção
```

Comentário de alinhamento ou divergência vai no **PBI**, não na Task — mesma lógica do
anexo: o PBI é o cartão que os stakeholders abrem.

## Reunião — uma task por participante do time

Task de reunião vai sob o PBI **#1339795 `[SGD] - Alinhamento Técnico`** (Feature #1339628),
com título no formato `DD/MM/AAAA - Assunto` (o CLI aplica o prefixo `[SGD]`).

**Toda reunião gera uma task idêntica para cada participante do time interno**, cada uma com
`--responsavel` da pessoa. Mesmo título, mesma descrição, mesma data — muda só o responsável.
Reunião é trabalho de todo mundo que sentou nela; uma task só no nome de quem lançou esconde
as horas das outras.

Quem entra na réplica — **exclusivamente** o time interno SGD/SETDIG, hoje:

| Apelido | Identidade |
|---|---|
| `fabio` | `SEGOVramos` |
| `glaucia` | `SEGOV\goliveira` |
| `daniele` | `SEGOV\dichiy` |

Participante de fornecedor (X-VIA e afins) **não** recebe task — aparece só na lista de
participantes, dentro da descrição. Apelido novo entra por `python -m src.xvia quem "<nome>"
--salvar-como <apelido>`, nunca hardcode.

A descrição é a mesma nas três e traz **quando** (data e hora), **onde** (link da sala) e
**quem** (todos os participantes, inclusive os de fornecedor, com o órgão de cada um).

Fechamento segue a regra abaixo: cada task recebe o próprio comentário quando a reunião
acontece.

## Task fechada sem comentário é task sem contexto

**Nenhuma Task vai para `Done` sem um comentário de fechamento na própria Task.** Vale
tanto para lançamento retroativo quanto para task que fecha no fluxo normal. `Done` sozinho
não diz o que foi descoberto, e daqui a duas sprints ninguém reconstrói isso.

O comentário responde, em linguagem simples e no passado:

```
**Fechamento em DD/MM/AAAA.**
O que foi descoberto ou entregue — o achado concreto, com número, nome ou mensagem de erro.
Quem respondeu o quê, quando a task dependeu de terceiro.
Próximo passo, se ficou algum — apontando a task ou o PBI que segue.
Onde estão as evidências — o PBI que recebeu os anexos.
```

Duas ou quatro linhas bastam. Se a task fechou porque virou outra coisa, o comentário diz
qual item assumiu.

Esse comentário é a exceção à regra acima: fechamento vai **na Task**, porque é o registro
daquela etapa. Alinhamento e divergência continuam no PBI.

## Área e sprint — `sincronizar` conserta quem escapou

Item criado fora do CLI (ou antes da herança de área/sprint existir) nasce na raiz
`XVIA` e some do quadro da sprint. O `sincronizar` devolve esses itens para debaixo
do pai, de cima para baixo. Só mexe em `AreaPath` e `IterationPath` — não toca em
título, estado, responsável ou descrição.

```bash
python -m src.xvia sincronizar            # dry-run: lista o que mudaria
python -m src.xvia sincronizar --apply    # escreve
```

Padrão é só o Epic **1333593** (SGD). O 1335269 é dos outros times — passar `--epic`
para incluí-lo é decisão consciente.

**Subárea é refinamento, não erro.** Item em `XVIA\SGD\Interno` sob um pai em
`XVIA\SGD` fica como está e propaga o próprio caminho para os filhos. Só entra no
plano quem está FORA do ramo do pai (raiz `XVIA` ou outro ramo).

Rodar em dry-run depois de cada lote grande. Se acusar diferença, ou o pai mudou de
sprint ou alguém criou item fora do CLI.

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
