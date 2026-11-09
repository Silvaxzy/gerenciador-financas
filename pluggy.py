"""
Cliente da API da Pluggy (Open Finance).

Fluxo:
1. O servidor troca CLIENT_ID + CLIENT_SECRET por uma chave de API (válida por 2 horas).
2. O servidor cria um "connect token" e entrega ao navegador.
3. O navegador abre o widget da Pluggy, o usuário conecta o banco e recebe um itemId.
4. O servidor usa o itemId para buscar as contas e as transações antigas.

As credenciais nunca vão para o navegador.
"""
import time
from urllib.parse import parse_qs, urlparse

import requests

URL_API = "https://api.pluggy.ai"


class ErroPluggy(Exception):
    """Erro vindo da Pluggy, com uma mensagem amigável."""


class ClientePluggy:
    def __init__(self, client_id, client_secret, sessao=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.sessao = sessao or requests.Session()
        self._chave = None
        self._chave_expira = 0.0

    # ---------------- autenticação ----------------

    def _chave_api(self):
        if self._chave and time.time() < self._chave_expira:
            return self._chave
        resposta = self.sessao.post(
            f"{URL_API}/auth",
            json={"clientId": self.client_id, "clientSecret": self.client_secret},
            timeout=30,
        )
        if resposta.status_code >= 400:
            raise ErroPluggy("Não foi possível autenticar na Pluggy. Confira o CLIENT_ID e o CLIENT_SECRET no arquivo .env.")
        self._chave = resposta.json()["apiKey"]
        self._chave_expira = time.time() + 110 * 60  # a chave vale 2 horas; renova antes
        return self._chave

    def _requisicao(self, metodo, caminho, **kwargs):
        resposta = self.sessao.request(
            metodo,
            f"{URL_API}{caminho}",
            headers={"X-API-KEY": self._chave_api()},
            timeout=30,
            **kwargs,
        )
        if resposta.status_code >= 400:
            try:
                detalhe = resposta.json().get("message", "")
            except ValueError:
                detalhe = resposta.text[:200]
            raise ErroPluggy(f"Erro na Pluggy ({resposta.status_code}): {detalhe}")
        return resposta.json()

    # ---------------- endpoints ----------------

    def criar_connect_token(self, id_usuario=None):
        corpo = {"options": {"clientUserId": str(id_usuario)}} if id_usuario else {}
        return self._requisicao("POST", "/connect_token", json=corpo)["accessToken"]

    def item(self, item_id):
        return self._requisicao("GET", f"/items/{item_id}")

    def aguardar_item(self, item_id, limite_segundos=90, intervalo=3):
        """Espera o banco terminar de sincronizar (status UPDATED)."""
        inicio = time.time()
        while True:
            item = self.item(item_id)
            status = item.get("status")
            if status in ("UPDATED", "OUTDATED"):
                return item
            if status == "LOGIN_ERROR":
                raise ErroPluggy("O banco recusou o login. Tente conectar de novo.")
            if status in ("WAITING_USER_INPUT", "WAITING_USER_ACTION"):
                raise ErroPluggy("O banco está aguardando uma ação sua no widget da Pluggy.")
            if time.time() - inicio > limite_segundos:
                raise ErroPluggy("O banco demorou para sincronizar. Clique em 'Sincronizar' daqui a pouco.")
            time.sleep(intervalo)

    def contas(self, item_id):
        return self._requisicao("GET", "/accounts", params={"itemId": item_id}).get("results", [])

    def transacoes(self, conta_id, desde):
        """Todas as transações da conta desde a data (AAAA-MM-DD), página por página."""
        todas = []
        params = {"accountId": conta_id, "dateFrom": desde}
        while True:
            pagina = self._requisicao("GET", "/v2/transactions", params=params)
            todas.extend(pagina.get("results", []))
            proxima = pagina.get("next")
            if not proxima:
                return todas
            cursor = parse_qs(urlparse(proxima).query).get("after", [None])[0]
            if not cursor:
                return todas
            params = {"accountId": conta_id, "dateFrom": desde, "after": cursor}


# ---------------- conversão para o formato do gerenciador ----------------

# palavras-chave das categorias da Pluggy -> categorias do gerenciador
MAPA_CATEGORIAS = [
    (("salary", "payroll", "wage", "income", "salário", "salario"), "Salário"),
    (("investment", "investiment", "investimento"), "Investimentos"),
    (("transfer", "pix", "ted", "doc", "transferência"), "Transferências"),
    (("food", "restaurant", "grocer", "supermarket", "eating", "delivery", "aliment"), "Alimentação"),
    (("transport", "taxi", "ride", "fuel", "gas station", "parking", "mobility", "uber", "toll"), "Transporte"),
    (("housing", "rent", "mortgage", "home", "aluguel", "moradia"), "Moradia"),
    (("health", "pharmac", "drugstore", "hospital", "medical", "dental", "gym", "wellness", "saúde"), "Saúde"),
    (("education", "school", "universit", "course", "educação"), "Educação"),
    (("leisure", "entertainment", "travel", "ticket", "streaming", "gaming", "lazer"), "Lazer"),
    (("shopping", "clothing", "electronic", "compras"), "Compras"),
    (("utilit", "telecom", "internet", "electric", "water", "bill", "service", "tax", "fee", "insurance"), "Contas e serviços"),
]


def mapear_categoria(categoria_pluggy):
    texto = (categoria_pluggy or "").lower()
    for palavras, categoria in MAPA_CATEGORIAS:
        if any(p in texto for p in palavras):
            return categoria
    return "Outros"


def converter_transacao(t, nome_conta):
    """Transforma uma transação da Pluggy em um registro do gerenciador."""
    tipo = "receita" if t.get("type") == "CREDIT" else "despesa"
    return {
        "descricao": (t.get("description") or "Transação bancária").strip()[:120],
        "valor": round(abs(float(t.get("amount") or 0)), 2),
        "tipo": tipo,
        "categoria": mapear_categoria(t.get("category")),
        "data": str(t.get("date", ""))[:10],
        "id_externo": t.get("id"),
        "conta": nome_conta,
    }
