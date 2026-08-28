"""CLI de lançamento de demandas no backlog XVIA (TFS on-prem).

Comandos:
    quem    resolve identidades e grava dicionario/pessoas.json
    export  puxa a árvore do épico e gera o dicionário de dados
    sincronizar  alinha área e sprint dos filhos ao pai (dry-run por padrão)
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

# Dois épicos convivem no projeto XVIA. As Features do time SGD nascem no
# épico da SGD; o de implantação da plataforma é tocado pelos outros times.
EPICO_SGD = 1333593
EPICO_PLATAFORMA = 1335269
EPICOS_PADRAO = [EPICO_SGD, EPICO_PLATAFORMA]
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
ESTADO_PADRAO = {"Epic": "New", "Feature": "New", PBI: "Approved", "Task": "To Do"}
# O TFS só aceita o estado inicial do tipo no POST de criação; o resto exige
# transição por PATCH. Sem isso, Task retroativa (Done) morre com HTTP 400.
ESTADO_INICIAL = {"Epic": "New", "Feature": "New", PBI: "New", "Task": "To Do"}

ATIVIDADES_TASK = {
    "Deployment", "Design", "Development",
    "Documentation", "Requirements", "Testing",
}

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


def validar_atividade(tipo, atividade):
    """Activity é obrigatório para Task e só aceito para Task."""
    if tipo == "Task":
        if not atividade:
            raise Erro(
                "Task exige --activity. Válidos: "
                + " | ".join(sorted(ATIVIDADES_TASK))
            )
        if atividade not in ATIVIDADES_TASK:
            raise Erro(
                f"activity {atividade!r} inválido. "
                f"Válidos: {' | '.join(sorted(ATIVIDADES_TASK))}"
            )
        return atividade
    if atividade:
        raise Erro(f"--activity só se aplica a Task, não a {tipo}")
    return None


def destino_dos_anexos(tipo, estado, pai_id, item_id=None):
    """Onde o anexo é pendurado. Task retroativa manda o material para o PBI pai.

    Task que nasce Done já entra fechada: artefato preso nela some do radar.
    O PBI é o cartão que os stakeholders abrem, então é lá que o material fica
    concentrado. Task prospectiva (To Do) segura o próprio anexo, que é insumo
    daquela etapa.
    """
    if tipo == "Task" and estado == "Done" and pai_id:
        return pai_id
    return item_id


def pai_nas_relacoes(item):
    """Id do pai a partir das relations de um work item, ou None."""
    for rel in item.get("relations") or []:
        if rel.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
            return int(rel["url"].rstrip("/").rsplit("/", 1)[-1])
    return None


def indexar_filhos(itens):
    """{pai_id: [filho_id, ...]} a partir de uma lista de itens com pai_id."""
    filhos = defaultdict(list)
    for i in itens:
        if i.get("pai_id"):
            filhos[i["pai_id"]].append(i["id"])
    return filhos


def ids_sob(epics, pais):
    """Ids que pendura nos épicos, a partir do mapa {filho: pai} do TFS."""
    filhos = defaultdict(list)
    for filho, pai in pais.items():
        filhos[pai].append(filho)
    ids, fila = list(epics), list(epics)
    while fila:
        atual = fila.pop()
        for f in filhos.get(atual, []):
            ids.append(f)
            fila.append(f)
    return ids


def sob(valor, do_pai):
    """O caminho está dentro do do pai? Subárea/sub-sprint é refinamento válido."""
    return valor == do_pai or valor.startswith(do_pai + "\\")


def planejar_sincronizacao(itens, raizes):
    r"""Quem precisa de PATCH para voltar para debaixo da área/sprint do pai.

    Devolve [(id, area, iteration)] de cima para baixo. Só entra no plano quem
    está FORA do caminho do pai — item na raiz `XVIA` ou em outro ramo. Quem
    refinou (`XVIA\SGD\Interno` sob `XVIA\SGD`) fica como está e propaga o
    próprio valor para os filhos; achatar isso apagaria a subárea de propósito.
    """
    por_id = {i["id"]: i for i in itens}
    filhos = indexar_filhos(itens)
    plano = []
    fila = [(r, por_id[r]["area"], por_id[r]["iteration"])
            for r in raizes if r in por_id]
    while fila:
        atual, area, iteration = fila.pop(0)
        for fid in sorted(filhos.get(atual, [])):
            f = por_id[fid]
            nova_area = f["area"] if sob(f["area"], area) else area
            nova_iter = (f["iteration"] if sob(f["iteration"], iteration)
                         else iteration)
            if nova_area != f["area"] or nova_iter != f["iteration"]:
                plano.append((fid, nova_area, nova_iter))
            fila.append((fid, nova_area, nova_iter))
    return plano


def rebaixar_para_estado_inicial(patch, tipo):
    """Reescreve o patch para o item nascer no estado inicial do tipo.

    Devolve o estado alvo quando houve rebaixamento (a transição precisa de um
    PATCH depois da criação) ou None quando o alvo já era o inicial.
    """
    inicial = ESTADO_INICIAL[tipo]
    for op in patch:
        if op.get("path") == "/fields/System.State":
            alvo = op["value"]
            if alvo == inicial:
                return None
            op["value"] = inicial
            return alvo
    return None


def montar_patch(*, tipo, titulo, pai_id=None, descricao="", responsavel=None,
                 estado=None, area=AREA_PADRAO, iteration=ITERATION_PADRAO,
                 esforco=None, tags=None, atividade=None, base=BASE):
    """Monta o corpo JSON-Patch de criação. Função pura — testável sem rede."""
    estado = validar_estado(tipo, estado or ESTADO_PADRAO[tipo])
    atividade = validar_atividade(tipo, atividade)
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
    if atividade:
        patch.append({"op": "add",
                      "path": "/fields/Microsoft.VSTS.Common.Activity",
                      "value": atividade})
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
    epics = args.epic or EPICOS_PADRAO
    pais = tfs.arvore_de_links()
    # só o que pendura nos épicos entra no dicionário
    ids = ids_sob(epics, pais)

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
        json.dumps({"epics": epics, "itens": itens}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    MD_DICIONARIO.write_text(gerar_dicionario(epics, itens), encoding="utf-8")
    print(f"[OK] {len(itens)} itens -> {JSON_BACKLOG.name} + {MD_DICIONARIO.name}")
    return 0


CAMPOS_SINCRONIZAR = [
    "System.Id", "System.WorkItemType", "System.Title",
    "System.AreaPath", "System.IterationPath",
]


def cmd_sincronizar(args):
    """Alinha área e sprint ao pai. Não toca em título, estado ou responsável."""
    tfs = Tfs()
    epics = args.epic or [EPICO_SGD]
    pais = tfs.arvore_de_links()
    itens = [{
        "id": b["id"],
        "titulo": b.get("fields", {}).get("System.Title", ""),
        "pai_id": pais.get(b["id"]),
        "area": b.get("fields", {}).get("System.AreaPath", ""),
        "iteration": b.get("fields", {}).get("System.IterationPath", ""),
    } for b in tfs.work_items(ids_sob(epics, pais), campos=CAMPOS_SINCRONIZAR)]

    plano = planejar_sincronizacao(itens, epics)
    if not plano:
        print("[OK] nada a sincronizar — área e sprint já batem com o pai.")
        return 0

    por_id = {i["id"]: i for i in itens}
    for item_id, area, iteration in plano:
        i = por_id[item_id]
        print(f"#{item_id}  {i['titulo']}")
        if i["area"] != area:
            print(f"    area       {i['area'] or '(vazia)'}  ->  {area}")
        if i["iteration"] != iteration:
            print(f"    iteration  {i['iteration'] or '(vazia)'}  ->  {iteration}")
        print(f"    {BASE}/{tfs.projeto}/_workitems/edit/{item_id}")
        if args.apply:
            tfs.atualizar(item_id, [
                {"op": "add", "path": "/fields/System.AreaPath", "value": area},
                {"op": "add", "path": "/fields/System.IterationPath",
                 "value": iteration},
            ])

    if args.apply:
        print(f"\n{len(plano)} item(ns) sincronizado(s). "
              "Rode `export` para atualizar o dicionário.")
    else:
        print(f"\n{len(plano)} item(ns) seriam alterados.  "
              "[DRY-RUN — nada foi escrito]\nRode de novo com --apply.")
    return 0


def gerar_dicionario(epics, itens):
    epics = [epics] if isinstance(epics, int) else list(epics)
    por_id = {i["id"]: i for i in itens}
    filhos = defaultdict(list)
    for i in itens:
        if i["pai_id"] in por_id:
            filhos[i["pai_id"]].append(i["id"])

    linhas = [
        "# Dicionário de dados — Backlog XVIA",
        "",
        "Gerado por `python -m src.xvia export` a partir dos Epics "
        + ", ".join(f"**{e}**" for e in epics)
        + ". Não editar à mão — as alterações são sobrescritas.",
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

    for e in epics:
        desenhar(e)
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
        if esperado and not pai and i["id"] not in epics:
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
    pai_id = spec.get("pai")
    sgd = bool(spec.get("sgd"))

    tipo_do_pai = None
    titulo_do_pai = ""
    campos_pai = {}
    if pai_id:
        pai = tfs.work_item(pai_id)
        campos_pai = pai.get("fields", {})
        tipo_do_pai = campos_pai.get("System.WorkItemType")
        titulo_do_pai = campos_pai.get("System.Title", "")
    validar_pai(tipo, tipo_do_pai)

    # Task herda [SGD] do PBI pai. Cadeia SGD é convenção do backlog XVIA.
    if tipo == "Task" and SGD_RE.match(titulo_do_pai):
        sgd = True
    titulo = normalizar_titulo(spec["titulo"], sgd=sgd)

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
        # herda a área e a sprint do pai: o épico SGD vive em XVIA\SGD +
        # XVIA\Sprint 1, e item nascendo na raiz some do quadro do time
        area=spec.get("area") or campos_pai.get("System.AreaPath") or AREA_PADRAO,
        iteration=(spec.get("iteration") or campos_pai.get("System.IterationPath")
                   or ITERATION_PADRAO),
        esforco=spec.get("esforco"),
        tags=spec.get("tags"),
        atividade=spec.get("activity") or spec.get("atividade"),
    )
    estado_final = next(
        op["value"] for op in patch if op["path"] == "/fields/System.State")
    estado_alvo = rebaixar_para_estado_inicial(patch, tipo)
    anexos = spec.get("anexos") or []

    if not aplicar:
        if anexos:
            destino = destino_dos_anexos(tipo, estado_final, pai_id)
            onde = f"PBI pai #{destino}" if destino else "o próprio item criado"
            print(f"[DRY-RUN] {len(anexos)} anexo(s) iriam para {onde}.")
        return patch, None

    criado = tfs.criar(tipo, patch)
    if estado_alvo:
        criado = tfs.atualizar(criado["id"], [
            {"op": "add", "path": "/fields/System.State", "value": estado_alvo}])
    destino = destino_dos_anexos(tipo, estado_final, pai_id, criado["id"])
    for caminho in anexos:
        tfs.anexar(destino, caminho)
    if anexos and destino != criado["id"]:
        print(f"[ANEXADO] {len(anexos)} arquivo(s) no PBI pai #{destino}")
        print(f"          {BASE}/{tfs.projeto}/_workitems/edit/{destino}")
    return patch, criado


def cmd_novo(args):
    tfs = Tfs()
    spec = {
        "tipo": args.tipo, "titulo": args.titulo, "pai": args.pai,
        "sgd": args.sgd, "descricao": args.descricao or "",
        "responsavel": args.responsavel, "estado": args.estado,
        "esforco": args.esforco, "links": args.link, "anexos": args.anexo,
        "data_original": args.data_original, "activity": args.activity,
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

    item = tfs.work_item(args.id, expandir="relations")
    campos = item.get("fields", {})
    destino = destino_dos_anexos(
        campos.get("System.WorkItemType"), campos.get("System.State"),
        pai_nas_relacoes(item), args.id)
    if destino != args.id:
        print(f"[REDIRECIONADO] #{args.id} é Task concluída — o material vai "
              f"para o PBI pai #{destino}, que é o cartão que fica visível.")

    if not args.apply:
        print(f"[DRY-RUN] anexaria em #{destino}: {', '.join(args.arquivos)}")
        print(f"          {BASE}/{tfs.projeto}/_workitems/edit/{destino}")
        print("Rode de novo com --apply.")
        return 0
    for caminho in args.arquivos:
        tfs.anexar(destino, caminho, comentario=args.comentario or "")
        print(f"[ANEXADO] {caminho} -> #{destino}")
    print(f"          {BASE}/{tfs.projeto}/_workitems/edit/{destino}")
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
    e.add_argument("--epic", type=int, action="append",
                   help=f"repetível; padrão: {' e '.join(str(x) for x in EPICOS_PADRAO)}")
    e.set_defaults(func=cmd_export)

    s_ = sub.add_parser(
        "sincronizar", help="alinha área e sprint dos filhos ao pai")
    s_.add_argument("--epic", type=int, action="append",
                    help=f"repetível; padrão: {EPICO_SGD} (só o épico do SGD)")
    s_.add_argument("--apply", action="store_true", help="escreve de fato no TFS")
    s_.set_defaults(func=cmd_sincronizar)

    n = sub.add_parser("novo", help="cria um work item")
    n.add_argument("--tipo", required=True, help="Epic | Feature | PBI | Task")
    n.add_argument("--titulo", required=True)
    n.add_argument("--pai", type=int, help="id do work item pai")
    n.add_argument("--sgd", action="store_true", help="aplica o prefixo '[SGD] - '")
    n.add_argument("--descricao", help="texto simples; '- ' vira lista, ** vira negrito")
    n.add_argument("--responsavel", help="apelido de pessoas.json ou identidade completa")
    n.add_argument("--estado")
    n.add_argument("--esforco", type=float, help="Effort (PBI) ou Remaining Work (Task)")
    n.add_argument("--activity", choices=sorted(ATIVIDADES_TASK),
                   help="obrigatório para Task: Deployment | Design | "
                        "Development | Documentation | Requirements | Testing")
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
