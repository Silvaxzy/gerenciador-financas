"""Cálculos do painel: indicadores, séries mensais, categorias e insights automáticos."""
import calendar
from datetime import date


def _mes_anterior(ano_mes, passos=1):
    ano, mes = map(int, ano_mes.split("-"))
    for _ in range(passos):
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return f"{ano:04d}-{mes:02d}"


def _variacao(atual, anterior):
    """Variação percentual; None quando não há base de comparação."""
    if not anterior:
        return None
    return round((atual - anterior) / anterior * 100, 1)


def _totais_mes(con, usuario_id, ano_mes, ate_dia=31):
    """Receitas e despesas do mês (opcionalmente só até um dia, para comparar períodos iguais)."""
    linha = con.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN tipo = 'receita' THEN valor END), 0) AS receitas,
             COALESCE(SUM(CASE WHEN tipo = 'despesa' THEN valor END), 0) AS despesas
           FROM transacoes
           WHERE usuario_id = ? AND substr(data, 1, 7) = ? AND CAST(substr(data, 9, 2) AS INTEGER) <= ?""",
        (usuario_id, ano_mes, ate_dia),
    ).fetchone()
    return float(linha["receitas"]), float(linha["despesas"])


def _gastos_por_categoria(con, usuario_id, ano_mes, ate_dia=31):
    linhas = con.execute(
        """SELECT COALESCE(categoria, 'Outros') AS categoria, SUM(valor) AS total
           FROM transacoes
           WHERE usuario_id = ? AND tipo = 'despesa' AND substr(data, 1, 7) = ?
             AND CAST(substr(data, 9, 2) AS INTEGER) <= ?
           GROUP BY COALESCE(categoria, 'Outros')
           ORDER BY total DESC""",
        (usuario_id, ano_mes, ate_dia),
    ).fetchall()
    return {l["categoria"]: float(l["total"]) for l in linhas}


def _saida_conta_mes(con, usuario_id, ano_mes, pagamentos):
    """Despesas pagas pela conta (Pix/débito) + faturas de cartão pagas no mês."""
    linha = con.execute(
        """SELECT COALESCE(SUM(valor), 0) AS total FROM transacoes
           WHERE usuario_id = ? AND tipo = 'despesa' AND forma_pagamento = 'conta' AND substr(data, 1, 7) = ?""",
        (usuario_id, ano_mes),
    ).fetchone()
    return float(linha["total"]) + sum(p["valor"] for p in pagamentos if p["data"][:7] == ano_mes)


def saldo_em_conta(con, usuario_id, ate, pagamentos):
    """Quanto há na conta em uma data.

    Se o usuário informou o saldo real (ajuste), parte desse valor e soma só o que
    aconteceu depois. Sem ajuste, soma todo o histórico. Compras no crédito só saem
    da conta quando a fatura é paga.
    """
    ate = ate.isoformat()
    ajuste = con.execute(
        """SELECT data, valor, ultima_transacao_id, criado_em FROM ajustes_saldo
           WHERE usuario_id = ? AND data <= ? ORDER BY data DESC, id DESC LIMIT 1""",
        (usuario_id, ate),
    ).fetchone()

    movimento = """COALESCE(SUM(CASE WHEN tipo = 'receita' THEN valor
                                     WHEN forma_pagamento = 'conta' THEN -valor ELSE 0 END), 0)"""
    if not ajuste:
        base = con.execute(
            f"SELECT {movimento} AS s FROM transacoes WHERE usuario_id = ? AND data <= ?", (usuario_id, ate)
        ).fetchone()["s"]
        return base - sum(p["valor"] for p in pagamentos if p["data"] <= ate)

    # depois do ajuste: dias seguintes, ou o mesmo dia mas lançado depois do ajuste
    depois = con.execute(
        f"""SELECT {movimento} AS s FROM transacoes
            WHERE usuario_id = ? AND data <= ?
              AND (data > ? OR (data = ? AND id > ?))""",
        (usuario_id, ate, ajuste["data"], ajuste["data"], ajuste["ultima_transacao_id"]),
    ).fetchone()["s"]
    faturas = sum(p["valor"] for p in pagamentos if p["data"] <= ate and p["pago_em"] >= ajuste["criado_em"])
    return ajuste["valor"] + depois - faturas


def mes_padrao(con, usuario_id):
    """Mês atual; se ele estiver vazio, o último mês com dados."""
    atual = date.today().strftime("%Y-%m")
    tem_atual = con.execute(
        "SELECT 1 FROM transacoes WHERE usuario_id = ? AND substr(data, 1, 7) = ? LIMIT 1",
        (usuario_id, atual),
    ).fetchone()
    if tem_atual:
        return atual
    ultimo = con.execute(
        "SELECT substr(MAX(data), 1, 7) AS mes FROM transacoes WHERE usuario_id = ? AND data <= ?",
        (usuario_id, date.today().isoformat()),
    ).fetchone()
    return ultimo["mes"] or atual


def resumo(con, usuario_id, ano_mes):
    from cartoes import pagamentos_de_fatura, resumo_cartao

    pagamentos = pagamentos_de_fatura(con, usuario_id)
    receitas, despesas = _totais_mes(con, usuario_id, ano_mes)
    mes_ant = _mes_anterior(ano_mes)

    ano, mes = map(int, ano_mes.split("-"))
    hoje = date.today()
    mes_corrente = hoje.year == ano and hoje.month == mes
    # no mês atual, compara com o MESMO período do mês anterior (dia 1 até hoje)
    ate_dia = hoje.day if mes_corrente else 31
    receitas_ant, despesas_ant = _totais_mes(con, usuario_id, mes_ant, ate_dia)
    # o que já aconteceu até hoje (parcelas futuras do cartão podem já estar lançadas no mês)
    receitas_hoje, despesas_hoje = _totais_mes(con, usuario_id, ano_mes, ate_dia)

    # ---- série dos últimos 12 meses ----
    serie = []
    for i in range(11, -1, -1):
        m = _mes_anterior(ano_mes, i)
        r, d = _totais_mes(con, usuario_id, m)
        saldo_caixa = r - _saida_conta_mes(con, usuario_id, m, pagamentos)
        serie.append({"mes": m, "receitas": round(r, 2), "despesas": round(d, 2), "saldo": round(saldo_caixa, 2)})

    # ---- ritmo de gastos e projeção do mês ----
    dias_no_mes = calendar.monthrange(ano, mes)[1]
    dias_passados = hoje.day if mes_corrente else dias_no_mes
    media_diaria = despesas_hoje / dias_passados if dias_passados else 0
    if mes_corrente:
        projecao = _projetar_gastos(con, usuario_id, ano_mes, hoje.day, despesas, despesas_hoje, media_diaria, dias_no_mes)
    else:
        projecao = despesas

    # saldo em conta: hoje (no mês atual) ou no último dia do mês escolhido
    data_saldo = hoje if mes_corrente else date(ano, mes, dias_no_mes)
    saldo_total = saldo_em_conta(con, usuario_id, data_saldo, pagamentos)
    saida_conta = _saida_conta_mes(con, usuario_id, ano_mes, pagamentos)
    despesas_cartao = con.execute(
        """SELECT COALESCE(SUM(valor), 0) AS s FROM transacoes
           WHERE usuario_id = ? AND tipo = 'despesa' AND forma_pagamento = 'credito' AND substr(data, 1, 7) = ?""",
        (usuario_id, ano_mes),
    ).fetchone()["s"]
    cartao_a_pagar = sum(
        resumo_cartao(con, c)["usado"]
        for c in con.execute("SELECT * FROM cartoes WHERE usuario_id = ?", (usuario_id,)).fetchall()
    )

    taxa_poupanca = round((receitas - despesas) / receitas * 100, 1) if receitas else None

    # ---- categorias ----
    cats = _gastos_por_categoria(con, usuario_id, ano_mes)
    cats_ant = _gastos_por_categoria(con, usuario_id, mes_ant, ate_dia)
    cats_hoje = _gastos_por_categoria(con, usuario_id, ano_mes, ate_dia) if mes_corrente else cats
    categorias = [
        {
            "categoria": c,
            "total": round(v, 2),
            "percentual": round(v / despesas * 100, 1) if despesas else 0,
            "variacao": _variacao(cats_hoje.get(c, 0), cats_ant.get(c, 0)),
        }
        for c, v in cats.items()
    ]

    # ---- maiores despesas ----
    top = con.execute(
        """SELECT descricao, valor, categoria, data FROM transacoes
           WHERE usuario_id = ? AND tipo = 'despesa' AND substr(data, 1, 7) = ?
           ORDER BY valor DESC LIMIT 5""",
        (usuario_id, ano_mes),
    ).fetchall()

    # ---- orçamentos ----
    orcamentos = []
    for o in con.execute(
        "SELECT categoria, limite FROM orcamentos WHERE usuario_id = ? ORDER BY categoria", (usuario_id,)
    ):
        gasto = cats.get(o["categoria"], 0)
        orcamentos.append({
            "categoria": o["categoria"],
            "limite": o["limite"],
            "gasto": round(gasto, 2),
            "percentual": round(gasto / o["limite"] * 100, 1),
        })

    # ---- média de despesas dos 3 meses anteriores ----
    anteriores = [_totais_mes(con, usuario_id, _mes_anterior(ano_mes, i))[1] for i in (1, 2, 3)]
    com_dados = [x for x in anteriores if x > 0]
    # com só um mês de histórico a comparação engana (ex.: "551% acima da média")
    media_3m = sum(com_dados) / len(com_dados) if len(com_dados) >= 2 else 0

    insights = gerar_insights(
        receitas, despesas, taxa_poupanca, categorias, projecao, mes_corrente, orcamentos, media_3m
    )
    comparacao = "mesmo período do mês anterior" if mes_corrente else "mês anterior"

    return {
        "mes": ano_mes,
        "indicadores": {
            "receitas": round(receitas, 2),
            "despesas": round(despesas, 2),
            "saldo_mes": round(receitas - saida_conta, 2),
            "saldo_total": round(float(saldo_total), 2),
            "despesas_cartao": round(float(despesas_cartao), 2),
            "cartao_a_pagar": round(cartao_a_pagar, 2),
            "variacao_receitas": _variacao(receitas_hoje, receitas_ant),
            "variacao_despesas": _variacao(despesas_hoje, despesas_ant),
            "taxa_poupanca": taxa_poupanca,
            "media_diaria": round(media_diaria, 2),
            "projecao_mes": round(projecao, 2),
            "mes_corrente": mes_corrente,
            "comparacao": comparacao,
        },
        "serie": serie,
        "categorias": categorias,
        "maiores_despesas": [dict(t) for t in top],
        "orcamentos": orcamentos,
        "insights": insights,
    }


def _projetar_gastos(con, usuario_id, ano_mes, dia_hoje, despesas, despesas_hoje, media_diaria, dias_no_mes):
    """Estimativa de quanto o mês vai fechar.

    Soma o que já foi gasto até hoje com o que costuma ser gasto no resto do mês
    (média dos 3 meses anteriores, do dia seguinte até o fim). Se já houver despesas
    agendadas maiores que isso (ex.: parcelas do cartão), usa as agendadas.
    Sem histórico, projeta o ritmo diário atual.
    """
    agendado = despesas - despesas_hoje
    restantes = []
    for i in (1, 2, 3):
        m = _mes_anterior(ano_mes, i)
        total = _totais_mes(con, usuario_id, m)[1]
        if total > 0:
            restantes.append(total - _totais_mes(con, usuario_id, m, dia_hoje)[1])
    if restantes:
        return despesas_hoje + max(agendado, sum(restantes) / len(restantes))
    return max(despesas, media_diaria * dias_no_mes)


def _brl(valor):
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def gerar_insights(receitas, despesas, taxa, categorias, projecao, mes_corrente, orcamentos, media_3m):
    """Frases automáticas que explicam os números. tipo: positivo | alerta | info"""
    lista = []

    if receitas == 0 and despesas == 0:
        return [{"tipo": "info", "texto": "Ainda não há transações neste mês. Adicione uma ou conecte seu banco."}]

    if mes_corrente and receitas:
        # mês em andamento: avalia pela projeção, não pelo que já foi gasto até hoje
        taxa = round((receitas - projecao) / receitas * 100, 1)
        if taxa >= 20:
            lista.append({"tipo": "positivo", "texto": f"No ritmo atual, você deve guardar {taxa:.0f}% da renda este mês."})
        elif taxa < 0:
            lista.append({"tipo": "alerta", "texto": "No ritmo atual, seus gastos vão passar das receitas este mês."})
        else:
            lista.append({"tipo": "info", "texto": f"No ritmo atual, você deve guardar {taxa:.0f}% da renda. A meta recomendada é a partir de 20%."})
    elif taxa is not None:
        if taxa >= 20:
            lista.append({"tipo": "positivo", "texto": f"Ótimo! Você guardou {taxa:.0f}% da sua renda este mês."})
        elif taxa < 0:
            lista.append({"tipo": "alerta", "texto": f"Você gastou {_brl(despesas - receitas)} a mais do que ganhou neste mês."})
        else:
            lista.append({"tipo": "info", "texto": f"Você guardou {taxa:.0f}% da renda. A meta recomendada é a partir de 20%."})

    if mes_corrente and receitas and projecao > receitas:
        lista[-1] = {"tipo": "alerta", "texto": f"No ritmo atual, seus gastos devem fechar o mês em {_brl(projecao)}, acima das receitas."}

    # no mês atual, usa a projeção para não comparar meio mês com meses inteiros
    gasto_comparavel = projecao if mes_corrente else despesas
    verbo = "devem fechar" if mes_corrente else "ficaram"
    if media_3m and gasto_comparavel:
        dif = (gasto_comparavel - media_3m) / media_3m * 100
        if dif >= 15:
            lista.append({"tipo": "alerta", "texto": f"Seus gastos {verbo} {dif:.0f}% acima da média dos últimos 3 meses."})
        elif dif <= -10:
            lista.append({"tipo": "positivo", "texto": f"Seus gastos {verbo} {abs(dif):.0f}% abaixo da média dos últimos 3 meses."})

    subidas = [c for c in categorias if c["variacao"] is not None and c["variacao"] >= 20 and c["total"] >= 50]
    if subidas:
        c = max(subidas, key=lambda x: x["variacao"])
        lista.append({"tipo": "alerta", "texto": f"Gastos com {c['categoria']} subiram {c['variacao']:.0f}% em relação ao " + ("mesmo período do mês passado." if mes_corrente else "mês passado.")})

    if categorias:
        c = categorias[0]
        lista.append({"tipo": "info", "texto": f"{c['categoria']} é sua maior despesa: {c['percentual']:.0f}% do total ({_brl(c['total'])})."})

    for o in orcamentos:
        if o["percentual"] >= 100:
            lista.append({"tipo": "alerta", "texto": f"Orçamento de {o['categoria']} estourado: {_brl(o['gasto'])} de {_brl(o['limite'])}."})
        elif o["percentual"] >= 80:
            lista.append({"tipo": "info", "texto": f"Atenção: você já usou {o['percentual']:.0f}% do orçamento de {o['categoria']}."})

    return lista[:6]
