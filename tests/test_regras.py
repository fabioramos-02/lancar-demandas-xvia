"""Checagem das regras que quebram em silêncio: título, hierarquia, payload.

Roda sem rede e sem PAT — só funções puras de src/xvia.py.

    pytest
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.xvia import (  # noqa: E402
    PBI, Erro, _criar_item, montar_descricao, montar_patch, normalizar_tipo,
    destino_dos_anexos, ids_sob, normalizar_titulo, pai_nas_relacoes,
    sob,
    planejar_sincronizacao,
    rebaixar_para_estado_inicial, resolver_responsavel,
    texto_para_html, validar_estado,
    validar_pai, validar_atividade,
)

PESSOAS = {"maycon": "MS\\maycon", "fabio": "MS\\framos"}


# ------------------------------------------------------------------- títulos

@pytest.mark.parametrize("entrada, sgd, esperado", [
    ("Avaliação do Serviço", True, "[SGD] - Avaliação do Serviço"),
    ("[SGD] - Avaliação do Serviço", False, "[SGD] - Avaliação do Serviço"),
    ("[SGD] Design System", False, "[SGD] - Design System"),   # normaliza o legado
    ("[SGD]Design System", False, "[SGD] - Design System"),
    ("[SGD] - Design System", True, "[SGD] - Design System"),  # não duplica prefixo
    ("Configuração do CMS", False, "Configuração do CMS"),
    ("  espaços   demais  ", False, "espaços demais"),
])
def test_normalizar_titulo(entrada, sgd, esperado):
    assert normalizar_titulo(entrada, sgd=sgd) == esperado


def test_titulo_vazio_falha():
    with pytest.raises(Erro):
        normalizar_titulo("   ")


def test_prefixo_de_modulo_nao_e_confundido_com_sgd():
    assert normalizar_titulo("[CDI] CMS") == "[CDI] CMS"
    assert normalizar_titulo("[INFRA] Instalação") == "[INFRA] Instalação"


# ---------------------------------------------------------------- hierarquia

@pytest.mark.parametrize("tipo, pai", [
    ("Task", PBI),
    (PBI, "Feature"),
    ("Feature", "Epic"),
])
def test_hierarquia_valida(tipo, pai):
    validar_pai(tipo, pai)


@pytest.mark.parametrize("tipo, pai", [
    ("Task", "Feature"),    # o erro mais provável no dia a dia
    ("Task", "Epic"),
    (PBI, "Epic"),
    (PBI, PBI),
    ("Feature", "Feature"),
    ("Task", None),         # sem pai
])
def test_hierarquia_invalida_aborta(tipo, pai):
    with pytest.raises(Erro):
        validar_pai(tipo, pai)


def test_epic_nao_aceita_pai():
    validar_pai("Epic", None)
    with pytest.raises(Erro):
        validar_pai("Epic", "Epic")


# --------------------------------------------------------------------- tipos

@pytest.mark.parametrize("bruto, esperado", [
    ("pbi", PBI), ("PBI", PBI), ("Product Backlog Item", PBI),
    ("task", "Task"), ("Tarefa", "Task"),
    ("feature", "Feature"), ("epic", "Epic"), ("Épico", "Epic"),
])
def test_normalizar_tipo(bruto, esperado):
    assert normalizar_tipo(bruto) == esperado


def test_tipo_desconhecido_aborta():
    with pytest.raises(Erro):
        normalizar_tipo("história")


# ------------------------------------------------------------------- estados

def test_estado_de_task_difere_do_de_pbi():
    validar_estado("Task", "To Do")
    validar_estado(PBI, "New")
    with pytest.raises(Erro):
        validar_estado("Task", "New")        # Task não tem "New"
    with pytest.raises(Erro):
        validar_estado(PBI, "To Do")         # PBI não tem "To Do"


# --------------------------------------------------------------- responsável

def test_responsavel_padrao_por_tipo():
    assert resolver_responsavel("Feature", pessoas=PESSOAS) == "MS\\maycon"
    assert resolver_responsavel(PBI, pessoas=PESSOAS) == "MS\\framos"
    assert resolver_responsavel("Task", pessoas=PESSOAS) == "MS\\framos"


def test_responsavel_sobrescrito():
    assert resolver_responsavel("Task", "maycon", pessoas=PESSOAS) == "MS\\maycon"
    assert resolver_responsavel("Task", "MS\\outro", pessoas=PESSOAS) == "MS\\outro"


def test_apelido_desconhecido_aborta_antes_da_rede():
    with pytest.raises(Erro):
        resolver_responsavel("Task", "ninguem", pessoas=PESSOAS)


# --------------------------------------------------------------------- patch

def _campos(patch):
    return {p["path"]: p["value"] for p in patch if p["path"].startswith("/fields/")}


def test_patch_minimo():
    patch = montar_patch(tipo="Task", titulo="Instalação do CMS", pai_id=1337789,
                         atividade="Development")
    campos = _campos(patch)
    assert campos["/fields/System.Title"] == "Instalação do CMS"
    assert campos["/fields/System.AreaPath"] == "XVIA"
    assert campos["/fields/System.IterationPath"] == "XVIA"
    assert campos["/fields/System.State"] == "To Do"
    assert campos["/fields/Microsoft.VSTS.Common.Activity"] == "Development"


def test_patch_liga_no_pai_com_hierarchy_reverse():
    patch = montar_patch(tipo="Task", titulo="X", pai_id=1337789,
                         atividade="Development")
    relacoes = [p for p in patch if p["path"] == "/relations/-"]
    assert len(relacoes) == 1
    valor = relacoes[0]["value"]
    assert valor["rel"] == "System.LinkTypes.Hierarchy-Reverse"
    assert valor["url"].endswith("/_apis/wit/workItems/1337789")


def test_patch_sem_pai_nao_tem_relacao():
    patch = montar_patch(tipo="Epic", titulo="Novo épico")
    assert not [p for p in patch if p["path"] == "/relations/-"]


def test_esforco_vai_para_campo_diferente_por_tipo():
    task = _campos(montar_patch(tipo="Task", titulo="X", pai_id=1, esforco=4,
                                atividade="Development"))
    pbi = _campos(montar_patch(tipo=PBI, titulo="X", pai_id=1, esforco=8))
    assert task["/fields/Microsoft.VSTS.Scheduling.RemainingWork"] == 4
    assert pbi["/fields/Microsoft.VSTS.Scheduling.Effort"] == 8


def test_estado_invalido_aborta_na_montagem():
    with pytest.raises(Erro):
        montar_patch(tipo="Task", titulo="X", pai_id=1, estado="Committed",
                     atividade="Development")


# --------------------------------------------------------------------- activity

def test_task_sem_activity_aborta():
    with pytest.raises(Erro):
        montar_patch(tipo="Task", titulo="X", pai_id=1)


def test_task_com_activity_invalida_aborta():
    with pytest.raises(Erro):
        validar_atividade("Task", "Coding")


@pytest.mark.parametrize("valor", [
    "Deployment", "Design", "Development",
    "Documentation", "Requirements", "Testing",
])
def test_activity_valida_para_task(valor):
    assert validar_atividade("Task", valor) == valor


def test_activity_nao_aceito_fora_de_task():
    for tipo in ("Feature", PBI, "Epic"):
        with pytest.raises(Erro):
            validar_atividade(tipo, "Development")


# ---------------------------------------------- herança SGD Task -> PBI pai

class _FakeTfs:
    """Mock enxuto: só o que _criar_item chama em dry-run."""
    def __init__(self, pai_titulo, pai_tipo=PBI, area=None, iteration=None):
        campos = {"System.WorkItemType": pai_tipo, "System.Title": pai_titulo}
        if area:
            campos["System.AreaPath"] = area
        if iteration:
            campos["System.IterationPath"] = iteration
        self._pai = {"fields": campos}

    def work_item(self, _id):
        return self._pai


def _titulo(patch):
    return next(p["value"] for p in patch if p["path"] == "/fields/System.Title")


def test_task_herda_sgd_do_pbi_pai():
    spec = {"tipo": "Task", "titulo": "Protótipos (Templates)",
            "pai": 1337784, "activity": "Design"}
    tfs = _FakeTfs("[SGD] - Portal Não Logado")
    patch, _ = _criar_item(tfs, spec, aplicar=False)
    assert _titulo(patch) == "[SGD] - Protótipos (Templates)"


def test_task_sem_pai_sgd_nao_ganha_prefixo():
    spec = {"tipo": "Task", "titulo": "Instalação do CMS",
            "pai": 1337789, "activity": "Development"}
    tfs = _FakeTfs("Configuração do CMS")
    patch, _ = _criar_item(tfs, spec, aplicar=False)
    assert _titulo(patch) == "Instalação do CMS"


# ---------------------------------------------------------------- descrição

def test_descricao_junta_material_e_data_retroativa():
    texto = montar_descricao(
        "Configurar o CMS.",
        links=["https://exemplo.gov.br/doc"],
        data_original="23-06-2026",
    )
    assert "**Material**" in texto
    assert "- https://exemplo.gov.br/doc" in texto
    assert "**Demanda original:** 23-06-2026" in texto


def test_descricao_sem_extras_fica_so_o_corpo():
    assert montar_descricao("Só o corpo.") == "Só o corpo."


def test_html_escapa_entrada_e_monta_lista():
    saida = texto_para_html("**Requisitos**\n- item <script>\n- outro")
    assert "<b>Requisitos</b>" in saida
    assert saida.count("<li>") == 2
    assert "<script>" not in saida          # escapado, não injetado
    assert "&lt;script&gt;" in saida


def test_html_transforma_url_em_link():
    saida = texto_para_html("- https://exemplo.gov.br/a")
    assert '<a href="https://exemplo.gov.br/a">' in saida


def test_rebaixa_estado_nao_criavel_e_devolve_alvo():
    patch = montar_patch(tipo="Task", titulo="Levantar X",
                         estado="Done", atividade="Requirements")
    assert rebaixar_para_estado_inicial(patch, "Task") == "Done"
    estado = next(o["value"] for o in patch if o["path"] == "/fields/System.State")
    assert estado == "To Do"


def test_nao_rebaixa_quando_alvo_ja_e_o_inicial():
    patch = montar_patch(tipo="Task", titulo="Levantar X",
                         estado="To Do", atividade="Requirements")
    assert rebaixar_para_estado_inicial(patch, "Task") is None


# -------------------------------------------------------- destino dos anexos

def test_task_retroativa_manda_anexo_para_o_pbi_pai():
    assert destino_dos_anexos("Task", "Done", 1336978, 1338838) == 1336978


def test_task_prospectiva_segura_o_proprio_anexo():
    assert destino_dos_anexos("Task", "To Do", 1336978, 1338838) == 1338838


def test_pbi_concluido_nao_redireciona_para_a_feature():
    assert destino_dos_anexos(PBI, "Done", 1335829, 1336978) == 1336978


def test_pai_nas_relacoes_le_o_link_de_hierarquia():
    item = {"relations": [
        {"rel": "AttachedFile", "url": "https://tfs/_apis/wit/attachments/abc"},
        {"rel": "System.LinkTypes.Hierarchy-Reverse",
         "url": "https://tfs.sgi.ms.gov.br/tfs/Global/_apis/wit/workItems/1336978"},
    ]}
    assert pai_nas_relacoes(item) == 1336978


def test_pai_nas_relacoes_sem_pai():
    assert pai_nas_relacoes({}) is None
    assert pai_nas_relacoes({"relations": []}) is None


# ------------------------------------------------- área e sprint herdadas do pai

def _campo(patch, nome):
    return next(p["value"] for p in patch if p["path"] == f"/fields/{nome}")


def test_item_herda_area_e_sprint_do_pai():
    tfs = _FakeTfs("[SGD] - Cartas de Serviços", area="XVIA\SGD",
                   iteration="XVIA\Sprint 1")
    patch, _ = _criar_item(
        tfs, {"tipo": "Task", "titulo": "Levantar X", "pai": 1336979,
              "activity": "Requirements"}, aplicar=False)
    assert _campo(patch, "System.AreaPath") == "XVIA\SGD"
    assert _campo(patch, "System.IterationPath") == "XVIA\Sprint 1"


def test_spec_vence_a_heranca_do_pai():
    tfs = _FakeTfs("[SGD] - Cartas de Serviços", area="XVIA\SGD")
    patch, _ = _criar_item(
        tfs, {"tipo": "Task", "titulo": "Levantar X", "pai": 1336979,
              "activity": "Requirements", "area": "XVIA"}, aplicar=False)
    assert _campo(patch, "System.AreaPath") == "XVIA"


def test_sem_pai_cai_no_padrao():
    patch = montar_patch(tipo="Epic", titulo="Novo épico")
    assert _campo(patch, "System.AreaPath") == "XVIA"
    assert _campo(patch, "System.IterationPath") == "XVIA"


# ------------------------------------------ sincronização de área e sprint

def _item(id_, pai, area, iteration):
    return {"id": id_, "titulo": f"item {id_}", "pai_id": pai,
            "area": area, "iteration": iteration}


def test_sincronizar_so_lista_quem_diverge():
    itens = [
        _item(1, None, "XVIA\SGD", "XVIA\Sprint 1"),
        _item(2, 1, "XVIA\SGD", "XVIA\Sprint 1"),   # já certo
        _item(3, 1, "XVIA", "XVIA"),                  # os dois campos errados
    ]
    assert planejar_sincronizacao(itens, [1]) == [
        (3, "XVIA\SGD", "XVIA\Sprint 1")]


def test_sincronizar_propaga_o_valor_corrigido_para_o_neto():
    """Neto herda o valor NOVO do pai, não o que está gravado no pai errado."""
    itens = [
        _item(1, None, "XVIA\SGD", "XVIA\Sprint 1"),
        _item(2, 1, "XVIA", "XVIA"),
        _item(3, 2, "XVIA", "XVIA"),
    ]
    assert planejar_sincronizacao(itens, [1]) == [
        (2, "XVIA\SGD", "XVIA\Sprint 1"),
        (3, "XVIA\SGD", "XVIA\Sprint 1"),
    ]


def test_sincronizar_ignora_o_que_nao_pendura_na_raiz():
    itens = [
        _item(1, None, "XVIA\SGD", "XVIA\Sprint 1"),
        _item(9, None, "XVIA", "XVIA"),      # outro épico
        _item(10, 9, "XVIA", "XVIA"),
    ]
    assert planejar_sincronizacao(itens, [1]) == []


def test_sincronizar_backlog_alinhado_nao_gera_plano():
    itens = [_item(1, None, "XVIA\SGD", "XVIA\Sprint 1"),
             _item(2, 1, "XVIA\SGD", "XVIA\Sprint 1")]
    assert planejar_sincronizacao(itens, [1]) == []


def test_ids_sob_desce_a_arvore_inteira():
    pais = {2: 1, 3: 2, 4: 1, 99: 50}
    assert sorted(ids_sob([1], pais)) == [1, 2, 3, 4]


def test_subarea_e_refinamento_e_nao_e_achatada():
    """`SGD\\Interno` sob `SGD` é de propósito — sync não pode apagar."""
    itens = [
        _item(1, None, "XVIA\\SGD", "XVIA\\Sprint 1"),
        _item(2, 1, "XVIA\\SGD\\Interno", "XVIA\\Sprint 1"),
        _item(3, 2, "XVIA", "XVIA"),   # neto na raiz: herda o Interno do pai
    ]
    assert planejar_sincronizacao(itens, [1]) == [
        (3, "XVIA\\SGD\\Interno", "XVIA\\Sprint 1")]


def test_ramo_irmao_nao_conta_como_refinamento():
    itens = [_item(1, None, "XVIA\\SGD", "XVIA\\Sprint 1"),
             _item(2, 1, "XVIA\\CDI", "XVIA\\Sprint 1")]
    assert planejar_sincronizacao(itens, [1]) == [
        (2, "XVIA\\SGD", "XVIA\\Sprint 1")]


def test_sob_nao_casa_prefixo_parcial():
    assert sob("XVIA\\SGD", "XVIA\\SGD")
    assert sob("XVIA\\SGD\\Interno", "XVIA\\SGD")
    assert not sob("XVIA\\SGDX", "XVIA\\SGD")
    assert not sob("XVIA", "XVIA\\SGD")
