"""Regras de cartão de crédito: em qual fatura cada compra cai, parcelamento e limite."""
import calendar
import secrets
from datetime import date, datetime

CORES_CARTAO = ["roxo", "azul", "verde", "laranja", "rosa", "grafite"]


def _somar_meses(ano, mes, n):
    total = ano * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


def _dia_valido(ano, mes, dia):
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def mes_da_fatura(data_compra, dia_fechamento, dia_vencimento):
    """Mês (AAAA-MM) em que vence a fatura onde a compra entra.

    Compras feitas a partir do dia de fechamento já caem na fatura seguinte.
    Se o vencimento é antes (ou no mesmo dia) do fechamento, ele cai no mês seguinte ao fechamento.
    """
    if isinstance(data_compra, str):
        data_compra = datetime.strptime(data_compra, "%Y-%m-%d").date()
    ano, mes = data_compra.year, data_compra.month
    if data_compra.day >= dia_fechamento:
        ano, mes = _somar_meses(ano, mes, 1)  # mês em que a fatura fecha
    if dia_vencimento <= dia_fechamento:
        ano, mes = _somar_meses(ano, mes, 1)  # mês em que a fatura vence
    return f"{ano:04d}-{mes:02d}"


def datas_da_fatura(mes_fatura, dia_fechamento, dia_vencimento):
    """Data de fechamento e de vencimento de uma fatura (identificada pelo mês de vencimento)."""
    ano, mes = map(int, mes_fatura.split("-"))
    vencimento = _dia_valido(ano, mes, dia_vencimento)
    if dia_vencimento <= dia_fechamento:
        ano, mes = _somar_meses(ano, mes, -1)
    fechamento = _dia_valido(ano, mes, dia_fechamento)
    return fechamento, vencimento


def status_fatura(mes_fatura, cartao, paga, hoje=None, total=None):
    hoje = hoje or date.today()
    fechamento, vencimento = datas_da_fatura(mes_fatura, cartao["dia_fechamento"], cartao["dia_vencimento"])
    if paga:
        return "paga"
    if hoje < fechamento:
        return "aberta"
    if not total:
        return "sem_compras"  # fatura já fechada sem nada para pagar
    if hoje <= vencimento:
        return "fechada"
    return "vencida"


def gerar_parcelas(descricao, valor_total, data_compra, total_parcelas):
    """Divide a compra em parcelas mensais. A última parcela absorve os centavos que sobram."""
    compra = datetime.strptime(data_compra, "%Y-%m-%d").date()
    valor_parcela = int(valor_total * 100 // total_parcelas) / 100
    resto = round(valor_total - valor_parcela * total_parcelas, 2)
    grupo = secrets.token_hex(6) if total_parcelas > 1 else None
    parcelas = []
    for i in range(total_parcelas):
        ano, mes = _somar_meses(compra.year, compra.month, i)
        parcelas.append({
            "descricao": descricao if total_parcelas == 1 else f"{descricao} ({i + 1}/{total_parcelas})",
            "valor": round(valor_parcela + (resto if i == total_parcelas - 1 else 0), 2),
            "data": _dia_valido(ano, mes, compra.day).isoformat(),
            "parcela": i + 1 if total_parcelas > 1 else None,
            "total_parcelas": total_parcelas if total_parcelas > 1 else None,
            "compra_id": grupo,
        })
    return parcelas


def _faturas_pagas(con, cartao_id):
    return {l["mes"] for l in con.execute("SELECT mes FROM faturas_pagas WHERE cartao_id = ?", (cartao_id,))}


def _totais_por_fatura(con, cartao):
    totais = {}
    for t in con.execute(
        "SELECT data, valor FROM transacoes WHERE cartao_id = ? AND tipo = 'despesa'", (cartao["id"],)
    ):
        mes = mes_da_fatura(t["data"], cartao["dia_fechamento"], cartao["dia_vencimento"])
        totais[mes] = totais.get(mes, 0) + t["valor"]
    return totais


def pagamentos_de_fatura(con, usuario_id):
    """Faturas pagas, com a data do pagamento e o valor. É o momento em que o dinheiro sai da conta."""
    lista = []
    for cartao in con.execute("SELECT * FROM cartoes WHERE usuario_id = ?", (usuario_id,)).fetchall():
        totais = _totais_por_fatura(con, cartao)
        for f in con.execute("SELECT mes, pago_em FROM faturas_pagas WHERE cartao_id = ?", (cartao["id"],)):
            lista.append({"data": f["pago_em"][:10], "pago_em": f["pago_em"], "valor": round(totais.get(f["mes"], 0), 2)})
    return lista


def resumo_cartao(con, cartao, hoje=None):
    """Limite usado, fatura atual e fatura fechada (a pagar) de um cartão."""
    hoje = hoje or date.today()
    pagas = _faturas_pagas(con, cartao["id"])
    totais = _totais_por_fatura(con, cartao)

    usado = sum(v for m, v in totais.items() if m not in pagas)
    atual = mes_da_fatura(hoje, cartao["dia_fechamento"], cartao["dia_vencimento"])

    def fatura(mes):
        fechamento, vencimento = datas_da_fatura(mes, cartao["dia_fechamento"], cartao["dia_vencimento"])
        return {
            "mes": mes,
            "total": round(totais.get(mes, 0), 2),
            "status": status_fatura(mes, cartao, mes in pagas, hoje, totais.get(mes, 0)),
            "fechamento": fechamento.isoformat(),
            "vencimento": vencimento.isoformat(),
        }

    # fatura já fechada e ainda não paga (a mais antiga), se existir
    a_pagar = None
    for mes in sorted(totais):
        if mes < atual and mes not in pagas and totais[mes] > 0:
            a_pagar = fatura(mes)
            break

    limite = cartao["limite"]
    return {
        "id": cartao["id"],
        "nome": cartao["nome"],
        "cor": cartao["cor"],
        "limite": limite,
        "dia_fechamento": cartao["dia_fechamento"],
        "dia_vencimento": cartao["dia_vencimento"],
        "usado": round(usado, 2),
        "disponivel": round(limite - usado, 2),
        "percentual_usado": round(usado / limite * 100, 1) if limite else 0,
        "fatura_atual": fatura(atual),
        "fatura_a_pagar": a_pagar,
    }


def fatura_detalhada(con, cartao, mes, hoje=None):
    """Todas as compras que entram em uma fatura."""
    fechamento, vencimento = datas_da_fatura(mes, cartao["dia_fechamento"], cartao["dia_vencimento"])
    # a fatura cobre compras entre o fechamento anterior e o dia antes deste fechamento
    ano_ant, mes_ant = _somar_meses(fechamento.year, fechamento.month, -1)
    inicio = _dia_valido(ano_ant, mes_ant, cartao["dia_fechamento"])
    linhas = con.execute(
        """SELECT id, descricao, valor, categoria, data, parcela, total_parcelas, compra_id
           FROM transacoes
           WHERE cartao_id = ? AND tipo = 'despesa' AND data >= ? AND data < ?
           ORDER BY data, id""",
        (cartao["id"], inicio.isoformat(), fechamento.isoformat()),
    ).fetchall()
    compras = [dict(l) for l in linhas]
    total = round(sum(c["valor"] for c in compras), 2)
    paga = mes in _faturas_pagas(con, cartao["id"])
    return {
        "mes": mes,
        "inicio": inicio.isoformat(),
        "fechamento": fechamento.isoformat(),
        "vencimento": vencimento.isoformat(),
        "status": status_fatura(mes, cartao, paga, hoje, total),
        "total": total,
        "compras": compras,
    }


def _brl(valor):
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def insights_cartoes(con, usuario_id, hoje=None):
    """Alertas de limite quase no fim e de fatura perto do vencimento."""
    hoje = hoje or date.today()
    lista = []
    for c in con.execute("SELECT * FROM cartoes WHERE usuario_id = ? ORDER BY id", (usuario_id,)):
        r = resumo_cartao(con, c, hoje)
        f = r["fatura_a_pagar"]
        if f:
            dias = (date.fromisoformat(f["vencimento"]) - hoje).days
            if dias < 0:
                lista.append({"tipo": "alerta", "texto": f"A fatura do {r['nome']} ({_brl(f['total'])}) venceu há {-dias} {"dia" if dias == -1 else "dias"}. Marque como paga se já pagou."})
            elif dias <= 5:
                quando = {0: "hoje", 1: "amanhã"}.get(dias, f"em {dias} dias")
                lista.append({"tipo": "alerta", "texto": f"A fatura do {r['nome']} ({_brl(f['total'])}) vence {quando}."})
        if r["limite"] and r["percentual_usado"] >= 80:
            lista.append({"tipo": "alerta", "texto": f"Você já usou {r['percentual_usado']:.0f}% do limite do {r['nome']}."})
    return lista
