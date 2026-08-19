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
    normalizar_titulo, resolver_responsavel, texto_para_html, validar_estado,
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
    def __init__(self, pai_titulo, pai_tipo=PBI):
        self._pai = {"fields": {"System.WorkItemType": pai_tipo,
                                "System.Title": pai_titulo}}

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
