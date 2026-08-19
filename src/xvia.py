"""CLI de lançamento de demandas no backlog XVIA (TFS on-prem).

Comandos:
    quem    resolve identidades e grava dicionario/pessoas.json
    export  puxa a árvore do épico e gera o dicionário de dados
    novo    cria um work item (dry-run por padrão)
    lote    cria vários a partir de um JSON (demandas retroativas)
    anexar  sobe arquivo como anexo de um work item

O CLI valida e executa; ele não adivinha. A inferência de onde encaixar uma
demanda é feita por quem lê dicionario/DICIONARIO.md — ver CLAUDE.md.
"""
import argparse
import html
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

from .tfs import BASE, Tfs, TfsErro

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DICIONARIO = RAIZ / "dicionario"
JSON_BACKLOG = DICIONARIO / "backlog-xvia.json"
MD_DICIONARIO = DICIONARIO / "DICIONARIO.md"
JSON_PESSOAS = DICIONARIO / "pessoas.json"

EPICO_PADRAO = 1335269
AREA_PADRAO = "XVIA"
ITERATION_PADRAO = "XVIA"

PBI = "Product Backlog Item"
APELIDOS_TIPO = {
    "epic": "Epic", "épico": "Epic", "epico": "Epic",
    "feature": "Feature",
    "pbi": PBI, "product backlog item": PBI,
    "task": "Task", "tarefa": "Task",
}
PAI_ESPERADO = {"Task": PBI, PBI: "Feature", "Feature": "Epic"}
RESPONSAVEL_PADRAO = {"Feature": "maycon", PBI: "fabio", "Task": "fabio"}
ESTADOS_VALIDOS = {
    "Epic": {"New", "In Progress", "Done", "Removed"},
    "Feature": {"New", "In Progress", "Done", "Removed"},
    PBI: {"New", "Approved", "Committed", "Done", "Removed"},
    "Task": {"To Do", "In Progress", "Done", "Removed"},
}
ESTADO_PADRAO = {"Epic": "New", "Feature": "New", PBI: "New", "Task": "To Do"}

CAMPOS_EXPORT = [
    "System.Id", "System.WorkItemType", "System.Title", "System.State",
    "System.AreaPath", "System.IterationPath", "System.Tags",
    "System.AssignedTo", "System.Description",
    "Microsoft.VSTS.Scheduling.Effort",
    "Microsoft.VSTS.Scheduling.RemainingWork",
]

PREFIXO_RE = re.compile(r"^\[([^\]]+)\]")
SGD_RE = re.compile(r"^\[SGD\]\s*-?\s*(.*)$", re.IGNORECASE)


class Erro(RuntimeError):
    pass


# --------------------------------------------------------------------- regras

def normalizar_tipo(bruto):
    tipo = APELIDOS_TIPO.get(str(bruto).strip().lower())
    if not tipo:
        raise Erro(f"tipo desconhecido: {bruto!r}. Use Epic, Feature, PBI ou Task.")
    return tipo


def normalizar_titulo(titulo, sgd=False):
    """Aplica o padrão '[SGD] - Título'. Não duplica prefixo já existente."""
    t = " ".join(str(titulo).split())
    if not t:
        raise Erro("título vazio")
    m = SGD_RE.match(t)
    if m:
        t = m.group(1).strip()
        sgd = True
    if sgd and not t:
        raise Erro("título vazio depois de remover o prefixo [SGD]")
    return f"[SGD] - {t}" if sgd else t


def validar_pai(tipo, tipo_do_pai):
    esperado = PAI_ESPERADO.get(tipo)
    if esperado is None:
        if tipo_do_pai is not None:
            raise Erro("Epic não tem pai neste backlog")
        return
    if tipo_do_pai is None:
        raise Erro(f"{tipo} exige um pai do tipo {esperado}")
    if tipo_do_pai != esperado:
        raise Erro(f"{tipo} deve ficar sob {esperado}, não sob {tipo_do_pai}")


def validar_estado(tipo, estado):
    if estado not in ESTADOS_VALIDOS[tipo]:
        validos = " | ".join(sorted(ESTADOS_VALIDOS[tipo]))
        raise Erro(f"estado {estado!r} inválido para {tipo}. Válidos: {validos}")
    return estado


def texto_para_html(texto):
    """Markdown pobre -> HTML. Cobre o que o template de descrição usa:
    parágrafos, **negrito**, links e listas com '- '."""
    linhas = str(texto).replace("\r\n", "\n").split("\n")
    saida, lista_aberta = [], False
    for linha in linhas:
        crua = linha.strip()
        if not crua:
            if lista_aberta:
                saida.append("</ul>")
                lista_aberta = False
            continue
        escapada = html.escape(crua)
        escapada = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escapada)
        escapada = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escapada)
        if crua.startswith("- "):
            if not lista_aberta:
                saida.append("<ul>")
                lista_aberta = True
            saida.append(f"<li>{escapada[2:].strip()}</li>")
        else:
            if lista_aberta:
                saida.append("</ul>")
                lista_aberta = False
            saida.append(f"<div>{escapada}</div>")
    if lista_aberta:
        saida.append("</ul>")
    return "".join(saida)


def montar_descricao(corpo, links=None, data_original=None):
    partes = [str(corpo).strip()]
    if links:
        partes.append("**Material**\n" + "\n".join(f"- {u}" for u in links))
    if data_original:
        partes.append(f"**Demanda original:** {data_original}")
    return "\n\n".join(p for p in partes if p)


def montar_patch(*, tipo, titulo, pai_id=None, descricao="", responsavel=None,
                 estado=None, area=AREA_PADRAO, iteration=ITERATION_PADRAO,
                 esforco=None, tags=None, base=BASE):
    """Monta o corpo JSON-Patch de criação. Função pura — testável sem rede."""
    estado = validar_estado(tipo, estado or ESTADO_PADRAO[tipo])
    patch = [
        {"op": "add", "path": "/fields/System.Title", "value": titulo},
        {"op": "add", "path": "/fields/System.AreaPath", "value": area},
        {"op": "add", "path": "/fields/System.IterationPath", "value": iteration},
        {"op": "add", "path": "/fields/System.State", "value": estado},
    ]
    if descricao:
        patch.append({"op": "add", "path": "/fields/System.Description",
                      "value": texto_para_html(descricao)})
    if responsavel:
        patch.append({"op": "add", "path": "/fields/System.AssignedTo",
                      "value": responsavel})
    if tags:
        patch.append({"op": "add", "path": "/fields/System.Tags",
                      "value": "; ".join(tags) if isinstance(tags, list) else tags})
    if esforco is not None:
        campo = ("Microsoft.VSTS.Scheduling.RemainingWork" if tipo == "Task"
                 else "Microsoft.VSTS.Scheduling.Effort")
        patch.append({"op": "add", "path": f"/fields/{campo}", "value": esforco})
    if pai_id:
        patch.append({"op": "add", "path": "/relations/-", "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"{base}/_apis/wit/workItems/{pai_id}",
        }})
    return patch


# ----------------------------------------------------------------- identidade

def _texto_identidade(valor):
    if isinstance(valor, dict):
        return valor.get("uniqueName") or valor.get("displayName") or ""
    return valor or ""


def carregar_pessoas():
    if not JSON_PESSOAS.exists():
        return {}
    return json.loads(JSON_PESSOAS.read_text(encoding="utf-8"))


def resolver_responsavel(tipo, informado=None, pessoas=None):
    pessoas = carregar_pessoas() if pessoas is None else pessoas
    apelido = (informado or RESPONSAVEL_PADRAO.get(tipo) or "").strip()
    if not apelido:
        return None
    if apelido in pessoas:
        return pessoas[apelido]
    if "@" in apelido or "\\" in apelido:
        return apelido  # já veio uma identidade completa
    raise Erro(
        f"apelido {apelido!r} não está em {JSON_PESSOAS.name}.\n"
        f'Rode:  python -m src.xvia quem "{apelido}" --salvar-como {apelido}'
    )


# -------------------------------------------------------------------- comandos

def cmd_quem(args):
    tfs = Tfs()
    pessoas = tfs.membros_do_time()
    alvo = args.nome.lower()
    achados = [p for p in pessoas
               if alvo in p["displayName"].lower() or alvo in p["uniqueName"].lower()]
    if not achados:
        print(f"Nenhuma identidade casa com {args.nome!r}. Membros visíveis:")
        for p in sorted(pessoas, key=lambda x: x["displayName"]):
            print(f"  {p['displayName']:<35} {p['uniqueName']}")
        return 1
    for p in achados:
        print(f"{p['displayName']:<35} {p['uniqueName']}   (time: {p['time']})")
    if args.salvar_como:
        if len(achados) > 1:
            raise Erro("mais de uma identidade casou — refine o nome antes de salvar")
        pessoas_salvas = carregar_pessoas()
        escolhido = achados[0]["uniqueName"] or achados[0]["displayName"]
        pessoas_salvas[args.salvar_como] = escolhido
        DICIONARIO.mkdir(exist_ok=True)
        JSON_PESSOAS.write_text(
            json.dumps(pessoas_salvas, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] salvo como {args.salvar_como!r} em {JSON_PESSOAS}")
    return 0


def cmd_export(args):
    tfs = Tfs()
    pais = tfs.arvore_de_links()

    filhos = defaultdict(list)
    for filho, pai in pais.items():
        filhos[pai].append(filho)

    # BFS a partir do épico — só o que pendura nele entra no dicionário
    ids, fila = [args.epic], [args.epic]
    while fila:
        atual = fila.pop()
        for f in filhos.get(atual, []):
            ids.append(f)
            fila.append(f)

    brutos = tfs.work_items(ids, campos=CAMPOS_EXPORT)
    itens = []
    for b in brutos:
        c = b.get("fields", {})
        itens.append({
            "id": b["id"],
            "tipo": c.get("System.WorkItemType", ""),
            "titulo": c.get("System.Title", ""),
            "estado": c.get("System.State", ""),
            "pai_id": pais.get(b["id"]),
            "area": c.get("System.AreaPath", ""),
            "iteration": c.get("System.IterationPath", ""),
            "tags": c.get("System.Tags", ""),
            "responsavel": _texto_identidade(c.get("System.AssignedTo")),
            "esforco": c.get("Microsoft.VSTS.Scheduling.Effort"),
            "restante": c.get("Microsoft.VSTS.Scheduling.RemainingWork"),
            "descricao": c.get("System.Description", ""),
        })
    itens.sort(key=lambda i: i["id"])

    DICIONARIO.mkdir(exist_ok=True)
    JSON_BACKLOG.write_text(
        json.dumps({"epic": args.epic, "itens": itens}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    MD_DICIONARIO.write_text(gerar_dicionario(args.epic, itens), encoding="utf-8")
    print(f"[OK] {len(itens)} itens -> {JSON_BACKLOG.name} + {MD_DICIONARIO.name}")
    return 0


def gerar_dicionario(epic_id, itens):
    por_id = {i["id"]: i for i in itens}
    filhos = defaultdict(list)
    for i in itens:
        if i["pai_id"] in por_id:
            filhos[i["pai_id"]].append(i["id"])

    linhas = [
        "# Dicionário de dados — Backlog XVIA",
        "",
        f"Gerado por `python -m src.xvia export` a partir do Epic **{epic_id}**. "
        "Não editar à mão — as alterações são sobrescritas.",
        "",
        f"Total: **{len(itens)} itens**.",
        "",
    ]

    contagem = Counter(i["tipo"] for i in itens)
    linhas += ["| Tipo | Qtd |", "|---|---|"]
    linhas += [f"| {t} | {n} |" for t, n in contagem.most_common()]
    linhas += ["", "## 1. Árvore", "", "```"]

    def desenhar(item_id, nivel=0):
        i = por_id.get(item_id)
        if i is None:
            return
        recuo = "  " * nivel
        linhas.append(f"{recuo}{i['tipo']:<22} #{i['id']:<8} {i['titulo']}  [{i['estado']}]")
        for f in sorted(filhos.get(item_id, []), key=lambda x: por_id[x]["titulo"]):
            desenhar(f, nivel + 1)

    desenhar(epic_id)
    linhas += ["```", "", "## 2. Prefixos em uso", ""]

    prefixos = defaultdict(list)
    for i in itens:
        m = PREFIXO_RE.match(i["titulo"])
        if m:
            prefixos[m.group(1).strip().upper()].append(i)
    if prefixos:
        linhas += ["| Prefixo | Qtd | Tipos | Exemplo |", "|---|---|---|---|"]
        for p, lista in sorted(prefixos.items(), key=lambda kv: -len(kv[1])):
            tipos = ", ".join(sorted({x["tipo"] for x in lista}))
            linhas.append(f"| `[{p}]` | {len(lista)} | {tipos} | {lista[0]['titulo']} |")
    else:
        linhas.append("_Nenhum prefixo encontrado._")

    linhas += [
        "", "## 3. Regras de lançamento", "",
        "**Hierarquia obrigatória** — validada pelo CLI; a criação aborta se violada:",
        "",
        "```",
        "Epic  <-  Feature  <-  Product Backlog Item  <-  Task",
        "```",
        "",
        "**Título**",
        "",
        "- PBI de demanda da SGD: `[SGD] - Título` (com hífen cercado de espaços).",
        "- Demais itens: título livre; prefixo de módulo entre colchetes quando houver.",
        "",
        "**Responsável padrão**",
        "",
        "| Tipo | Responsável |",
        "|---|---|",
        "| Feature | Maycon |",
        "| Product Backlog Item | Fabio Ramos |",
        "| Task | Fabio Ramos |",
        "",
        "**Estados válidos**",
        "",
        "| Tipo | Estados |",
        "|---|---|",
    ]
    for t in ["Epic", "Feature", PBI, "Task"]:
        linhas.append(f"| {t} | {' · '.join(sorted(ESTADOS_VALIDOS[t]))} |")

    linhas += [
        "", "## 4. Divergências", "",
        "Itens fora do padrão. A correção é manual e consciente — "
        "o CLI sinaliza, não reescreve o que já existe.", "",
    ]
    divergentes = []
    for i in itens:
        t = i["titulo"]
        if re.match(r"^\[SGD\]", t, re.IGNORECASE) and not t.startswith("[SGD] - "):
            divergentes.append((i, "prefixo SGD fora do padrão `[SGD] - `"))
        pai = por_id.get(i["pai_id"])
        esperado = PAI_ESPERADO.get(i["tipo"])
        if esperado and pai and pai["tipo"] != esperado:
            divergentes.append((i, f"pai é {pai['tipo']}, esperado {esperado}"))
        if esperado and not pai and i["id"] != epic_id:
            divergentes.append((i, f"órfão — deveria estar sob um {esperado}"))
    if divergentes:
        linhas += ["| Id | Tipo | Título | Problema |", "|---|---|---|---|"]
        linhas += [f"| {i['id']} | {i['tipo']} | {i['titulo']} | {p} |"
                   for i, p in divergentes]
    else:
        linhas.append("_Nenhuma divergência._")

    linhas.append("")
    return "\n".join(linhas)


def _criar_item(tfs, spec, aplicar):
    """spec -> (patch, criado|None). Valida tudo antes de qualquer escrita."""
    tipo = normalizar_tipo(spec["tipo"])
    titulo = normalizar_titulo(spec["titulo"], sgd=bool(spec.get("sgd")))
    pai_id = spec.get("pai")

    tipo_do_pai = None
    if pai_id:
        pai = tfs.work_item(pai_id)
        tipo_do_pai = pai.get("fields", {}).get("System.WorkItemType")
    validar_pai(tipo, tipo_do_pai)

    for caminho in spec.get("anexos", []) or []:
        if not pathlib.Path(caminho).is_file():
            raise Erro(f"anexo não encontrado: {caminho}")

    patch = montar_patch(
        tipo=tipo,
        titulo=titulo,
        pai_id=pai_id,
        descricao=montar_descricao(
            spec.get("descricao", ""), spec.get("links"), spec.get("data_original")),
        responsavel=resolver_responsavel(tipo, spec.get("responsavel")),
        estado=spec.get("estado"),
        area=spec.get("area", AREA_PADRAO),
        iteration=spec.get("iteration", ITERATION_PADRAO),
        esforco=spec.get("esforco"),
        tags=spec.get("tags"),
    )
    if not aplicar:
        return patch, None
    criado = tfs.criar(tipo, patch)
    for caminho in spec.get("anexos", []) or []:
        tfs.anexar(criado["id"], caminho)
    return patch, criado


def cmd_novo(args):
    tfs = Tfs()
    spec = {
        "tipo": args.tipo, "titulo": args.titulo, "pai": args.pai,
        "sgd": args.sgd, "descricao": args.descricao or "",
        "responsavel": args.responsavel, "estado": args.estado,
        "esforco": args.esforco, "links": args.link, "anexos": args.anexo,
        "data_original": args.data_original,
    }
    patch, criado = _criar_item(tfs, spec, args.apply)
    if criado:
        print(f"[CRIADO] #{criado['id']}  {patch[0]['value']}")
        print(f"         {BASE}/{tfs.projeto}/_workitems/edit/{criado['id']}")
    else:
        print("[DRY-RUN] nada foi escrito. Payload que seria enviado:\n")
        print(json.dumps(patch, ensure_ascii=False, indent=2))
        print("\nRode de novo com --apply para criar.")
    return 0


def cmd_lote(args):
    tfs = Tfs()
    caminho = pathlib.Path(args.arquivo)
    specs = json.loads(caminho.read_text(encoding="utf-8"))
    por_chave = {}
    criados = 0

    for n, spec in enumerate(specs, 1):
        if spec.get("id"):
            print(f"  {n:>3}. pulado (já existe #{spec['id']}): {spec['titulo']}")
            if spec.get("chave"):
                por_chave[spec["chave"]] = spec["id"]
            continue
        if spec.get("pai_ref"):
            ref = spec["pai_ref"]
            if not por_chave.get(ref):
                raise Erro(f"item {n}: pai_ref {ref!r} ainda não existe — "
                           "pais devem vir antes dos filhos no arquivo")
            spec["pai"] = por_chave[ref]

        patch, criado = _criar_item(tfs, spec, args.apply)
        if criado:
            spec["id"] = criado["id"]
            criados += 1
            print(f"  {n:>3}. [CRIADO] #{criado['id']}  {patch[0]['value']}")
            # grava o id a cada item: interrupção no meio não vira duplicata
            caminho.write_text(json.dumps(specs, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        else:
            sufixo = f"  (pai #{spec['pai']})" if spec.get("pai") else ""
            print(f"  {n:>3}. [DRY-RUN] {patch[0]['value']}{sufixo}")
        if spec.get("chave"):
            por_chave[spec["chave"]] = spec.get("id")

    resumo = f"\n{criados} criado(s) de {len(specs)}."
    print(resumo if args.apply else resumo + "  [DRY-RUN — nada foi escrito]")
    return 0


def cmd_anexar(args):
    tfs = Tfs()
    for caminho in args.arquivos:
        if not pathlib.Path(caminho).is_file():
            raise Erro(f"arquivo não encontrado: {caminho}")
    if not args.apply:
        print(f"[DRY-RUN] anexaria em #{args.id}: {', '.join(args.arquivos)}")
        print("Rode de novo com --apply.")
        return 0
    for caminho in args.arquivos:
        tfs.anexar(args.id, caminho, comentario=args.comentario or "")
        print(f"[ANEXADO] {caminho} -> #{args.id}")
    return 0


# ------------------------------------------------------------------------ CLI

def montar_parser():
    p = argparse.ArgumentParser(
        prog="xvia", description="Lançamento de demandas no backlog XVIA (TFS)")
    sub = p.add_subparsers(dest="comando", required=True)

    q = sub.add_parser("quem", help="resolve identidade para AssignedTo")
    q.add_argument("nome")
    q.add_argument("--salvar-como", dest="salvar_como",
                   help="apelido a gravar em dicionario/pessoas.json (ex.: maycon)")
    q.set_defaults(func=cmd_quem)

    e = sub.add_parser("export", help="gera o dicionário de dados do épico")
    e.add_argument("--epic", type=int, default=EPICO_PADRAO)
    e.set_defaults(func=cmd_export)

    n = sub.add_parser("novo", help="cria um work item")
    n.add_argument("--tipo", required=True, help="Epic | Feature | PBI | Task")
    n.add_argument("--titulo", required=True)
    n.add_argument("--pai", type=int, help="id do work item pai")
    n.add_argument("--sgd", action="store_true", help="aplica o prefixo '[SGD] - '")
    n.add_argument("--descricao", help="texto simples; '- ' vira lista, ** vira negrito")
    n.add_argument("--responsavel", help="apelido de pessoas.json ou identidade completa")
    n.add_argument("--estado")
    n.add_argument("--esforco", type=float, help="Effort (PBI) ou Remaining Work (Task)")
    n.add_argument("--link", action="append", help="URL de material (repetível)")
    n.add_argument("--anexo", action="append", help="arquivo a anexar (repetível)")
    n.add_argument("--data-original", dest="data_original",
                   help="DD-MM-YYYY, para demandas retroativas")
    n.add_argument("--apply", action="store_true", help="escreve de fato no TFS")
    n.set_defaults(func=cmd_novo)

    lt = sub.add_parser("lote", help="cria vários itens a partir de um JSON")
    lt.add_argument("arquivo")
    lt.add_argument("--apply", action="store_true")
    lt.set_defaults(func=cmd_lote)

    a = sub.add_parser("anexar", help="anexa arquivos a um work item")
    a.add_argument("id", type=int)
    a.add_argument("arquivos", nargs="+")
    a.add_argument("--comentario")
    a.add_argument("--apply", action="store_true")
    a.set_defaults(func=cmd_anexar)

    return p


def main(argv=None):
    # console do Windows abre em cp1252 e come os acentos do backlog
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = montar_parser().parse_args(argv)
    try:
        return args.func(args)
    except (Erro, TfsErro) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
