"""Cliente REST do Azure DevOps Server on-prem (TFS) — coleção Global, projeto XVIA.

Só o necessário: autenticação por PAT, retry, leitura de work items, criação
via JSON-Patch e upload de anexo. Nada aqui conhece as regras de negócio do
backlog — isso vive em xvia.py.
"""
import os
import time

import requests

BASE = "https://tfs.sgi.ms.gov.br/tfs/Global"
PROJETO = "XVIA"
API_VERSION = "4.1"

TRANSIENTES = {429, 500, 502, 503, 504}


class TfsErro(RuntimeError):
    pass


class Tfs:
    def __init__(self, pat=None, base=BASE, projeto=PROJETO):
        pat = pat or os.environ.get("XVIA_PAT")
        if not pat:
            raise TfsErro(
                'XVIA_PAT não definido.\n'
                '  setx XVIA_PAT "<seu-token>"   e abra um terminal novo.'
            )
        self.base = base.rstrip("/")
        self.projeto = projeto
        self.sessao = requests.Session()
        self.sessao.auth = ("", pat)
        self.sessao.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------ HTTP

    def _url(self, path, no_projeto=True):
        raiz = f"{self.base}/{self.projeto}" if no_projeto else self.base
        return f"{raiz}/_apis/{path}"

    def pedir(self, metodo, path, *, no_projeto=True, params=None,
              corpo_json=None, corpo_bruto=None, content_type=None, tentativas=4):
        url = self._url(path, no_projeto)
        params = dict(params or {})
        params.setdefault("api-version", API_VERSION)
        headers = {"Content-Type": content_type} if content_type else {}

        espera = 1
        for n in range(tentativas):
            r = self.sessao.request(
                metodo, url, params=params, json=corpo_json, data=corpo_bruto,
                headers=headers, timeout=30, allow_redirects=False,
            )
            if r.status_code in TRANSIENTES and n < tentativas - 1:
                time.sleep(espera)
                espera *= 2
                continue
            return self._interpretar(r, url)
        raise TfsErro(f"esgotadas {tentativas} tentativas em {url}")

    @staticmethod
    def _interpretar(r, url):
        """Traduz os modos de falha do TFS on-prem em erro legível."""
        if r.status_code in (301, 302, 401, 403):
            raise TfsErro(
                f"HTTP {r.status_code} em {url}\n"
                "PAT recusado. No TFS on-prem isso quase sempre é Basic Auth desabilitado "
                "no IIS. Confirme o token e, se persistir, o fallback é NTLM com conta de domínio."
            )
        # 200 devolvendo HTML = página de login disfarçada de sucesso.
        tipo = r.headers.get("Content-Type", "")
        if "html" in tipo.lower():
            raise TfsErro(
                f"{url} devolveu HTML (provável tela de login), não JSON.\n"
                "O PAT foi ignorado pelo servidor."
            )
        if r.status_code >= 400:
            raise TfsErro(f"HTTP {r.status_code} em {url}\n{r.text[:600]}")
        if not r.content:
            return {}
        return r.json()

    # ------------------------------------------------------------- work items

    def wiql(self, consulta):
        return self.pedir("POST", "wit/wiql", corpo_json={"query": consulta})

    def arvore_de_links(self):
        """Todos os links de hierarquia do projeto, em uma chamada.

        Devolve {filho_id: pai_id}. Mais barato que descer nível a nível.
        """
        consulta = f"""
            SELECT [System.Id] FROM WorkItemLinks
            WHERE ([Source].[System.TeamProject] = '{self.projeto}')
              AND ([System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward')
            MODE (Recursive)
        """
        resp = self.wiql(consulta)
        pais = {}
        for rel in resp.get("workItemRelations", []):
            origem, alvo = rel.get("source"), rel.get("target")
            if origem and alvo:
                pais[alvo["id"]] = origem["id"]
        return pais

    def work_items(self, ids, campos=None):
        """GET em lote. A API limita a 200 ids por chamada."""
        saida = []
        ids = list(ids)
        for i in range(0, len(ids), 200):
            fatia = ids[i:i + 200]
            params = {"ids": ",".join(str(x) for x in fatia)}
            if campos:
                params["fields"] = ",".join(campos)
            saida.extend(self.pedir("GET", "wit/workitems", params=params).get("value", []))
        return saida

    def work_item(self, item_id):
        return self.pedir("GET", f"wit/workitems/{item_id}")

    def criar(self, tipo, patch):
        return self.pedir(
            "POST", f"wit/workitems/${tipo}",
            corpo_json=patch,
            content_type="application/json-patch+json",
        )

    def atualizar(self, item_id, patch):
        return self.pedir(
            "PATCH", f"wit/workitems/{item_id}",
            corpo_json=patch,
            content_type="application/json-patch+json",
        )

    # ----------------------------------------------------------------- anexos

    def subir_anexo(self, caminho, nome=None):
        """Sobe o arquivo e devolve a URL do anexo (ainda solto, sem dono)."""
        nome = nome or os.path.basename(caminho)
        with open(caminho, "rb") as f:
            dados = f.read()
        resp = self.pedir(
            "POST", "wit/attachments",
            params={"fileName": nome},
            corpo_bruto=dados,
            content_type="application/octet-stream",
        )
        return resp["url"]

    def anexar(self, item_id, caminho, comentario=""):
        url = self.subir_anexo(caminho)
        patch = [{
            "op": "add",
            "path": "/relations/-",
            "value": {
                "rel": "AttachedFile",
                "url": url,
                "attributes": {"comment": comentario or os.path.basename(caminho)},
            },
        }]
        return self.atualizar(item_id, patch)

    # -------------------------------------------------------------- identidade

    def membros_do_time(self):
        """Identidades dos times do projeto. Usado para resolver AssignedTo."""
        times = self.pedir(
            "GET", f"projects/{self.projeto}/teams", no_projeto=False
        ).get("value", [])
        pessoas = []
        for time_ in times:
            resp = self.pedir(
                "GET", f"projects/{self.projeto}/teams/{time_['id']}/members",
                no_projeto=False,
            )
            for m in resp.get("value", []):
                ident = m.get("identity", m)
                pessoas.append({
                    "displayName": ident.get("displayName", ""),
                    "uniqueName": ident.get("uniqueName") or ident.get("mailAddress", ""),
                    "time": time_.get("name", ""),
                })
        return pessoas
