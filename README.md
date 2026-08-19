# lancar-demandas-xvia

Dicionário de dados do backlog **XVIA** e CLI para lançar demandas no TFS on-prem
(`tfs.sgi.ms.gov.br/tfs/Global/XVIA`, Epic raiz `1335269`).

Resolve duas coisas: dar visibilidade da estrutura real do backlog (pra pessoas e pro Claude)
e padronizar o lançamento de Feature / PBI / Task, inclusive retroativo com material anexado.

## Instalação

```bash
pip install -r requirements.txt
```

Gere um PAT no TFS (**escopo `Work Items (Read & write)`**, 90 dias) e grave em variável
de ambiente — nunca em arquivo do repo:

```bash
setx XVIA_PAT "seu-token"
```

Abra um terminal novo depois do `setx`.

## Uso

### 1. Resolver as identidades (uma vez)

```bash
python -m src.xvia quem "Maycon" --salvar-como maycon
```

```bash
python -m src.xvia quem "Fabio" --salvar-como fabio
```

Grava em `dicionario/pessoas.json`. Sem isso, a criação falha cedo com mensagem explícita
em vez de gerar item sem responsável.

### 2. Gerar o dicionário

```bash
python -m src.xvia export
```

Produz `dicionario/backlog-xvia.json` (dados) e `dicionario/DICIONARIO.md` (árvore, prefixos
em uso, regras e divergências). Rode de novo sempre que o backlog mudar na UI.

### 3. Criar um item

```bash
python -m src.xvia novo --tipo Task --pai 1337789 --titulo "Instalação do CMS"
```

Dry-run por padrão: imprime o payload, não escreve. Para valer:

```bash
python -m src.xvia novo --tipo Task --pai 1337789 --titulo "Instalação do CMS" --apply
```

PBI de demanda da SGD recebe o prefixo automaticamente com `--sgd`:

```bash
python -m src.xvia novo --tipo PBI --pai 1336102 --sgd --titulo "Avaliação do Serviço" --apply
```

### 4. Anexar material

```bash
python -m src.xvia anexar 1337789 relatorio.pdf print.png --apply
```

### 5. Demandas retroativas em lote

```bash
python -m src.xvia lote lote/exemplo-retroativas.json
```

```bash
python -m src.xvia lote lote/exemplo-retroativas.json --apply
```

O `id` de cada item criado é gravado de volta no arquivo, item a item. Reexecutar o mesmo
lote pula o que já existe — inclusive se a execução anterior foi interrompida no meio.

Itens do mesmo lote se referenciam por `chave` / `pai_ref`, então dá pra criar um PBI e
suas Tasks numa só passada. O pai precisa aparecer antes dos filhos no arquivo.

## Comandos

| Comando | O que faz |
|---|---|
| `quem <nome> [--salvar-como <apelido>]` | Resolve identidade para `AssignedTo` |
| `export [--epic <id>]` | Gera o dicionário de dados |
| `novo --tipo --titulo [...] [--apply]` | Cria um work item |
| `lote <arquivo.json> [--apply]` | Cria vários (retroativas) |
| `anexar <id> <arquivos...> [--apply]` | Sobe anexos num work item |

Toda escrita exige `--apply`. Sem a flag, é simulação.

## Regras aplicadas

- **Hierarquia**: `Epic <- Feature <- PBI <- Task`. Pai de tipo errado aborta antes de qualquer escrita.
- **Título SGD**: PBI da SGD vira `[SGD] - Título`. Prefixo existente não é duplicado.
- **Responsável**: Feature → Maycon; PBI e Task → Fabio. `--responsavel` sobrescreve.
- **Estados**: PBI `New|Approved|Committed|Done`; Task `To Do|In Progress|Done`.

Detalhe e racional em [`CLAUDE.md`](CLAUDE.md).

## O que não faz

Não deleta, não fecha item e não corrige título de item existente. Divergências (ex.:
`[SGD] Design System` sem hífen) aparecem na seção 4 do dicionário para correção manual.

Também não sincroniza: é um caminho de mão única, do comando para o TFS. Não existe
motor de diff — se alguém editar na UI, o `export` seguinte reflete a mudança.

## Testes

```bash
python -m pytest tests/ -q
```

Rodam offline, sem PAT.

## Não confundir com `setdig-tfs-backlog`

`../setdig-tfs-backlog` é um espelho JSON local de **outro** backlog (projeto SETDIG), com
taxonomia própria e a skill `/tfs`. Este repo escreve no TFS real, projeto XVIA. Ids e
regras de título não são intercambiáveis entre os dois.
