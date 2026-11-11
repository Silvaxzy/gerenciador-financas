"""Gera 12 meses de transações fictícias para demonstrar o painel."""
import calendar
import random
from datetime import date


def gerar_transacoes_exemplo(semente=42):
    rand = random.Random(semente)
    hoje = date.today()
    lista = []

    def add(dia_ref, descricao, valor, tipo, categoria):
        if dia_ref <= hoje:
            lista.append((descricao, round(valor, 2), tipo, categoria, dia_ref.isoformat()))

    for passo in range(11, -1, -1):
        ano, mes = hoje.year, hoje.month - passo
        while mes <= 0:
            ano, mes = ano - 1, mes + 12
        ultimo_dia = calendar.monthrange(ano, mes)[1]

        def dia(n):
            return date(ano, mes, min(n, ultimo_dia))

        # receitas
        add(dia(1), "Salário", 3200, "receita", "Salário")
        if rand.random() < 0.35:
            add(dia(rand.randint(12, 25)), "Freelance - site institucional", rand.choice([350, 480, 600]), "receita", "Salário")

        # despesas fixas
        add(dia(10), "Aluguel", 1100, "despesa", "Moradia")
        add(dia(12), "Internet fibra", 119.90, "despesa", "Contas e serviços")
        add(dia(15), "Conta de luz", rand.uniform(85, 165), "despesa", "Contas e serviços")
        add(dia(8), "Mensalidade faculdade", 289, "despesa", "Educação")
        add(dia(18), "Streaming", 39.90, "despesa", "Lazer")
        add(dia(20), "Plano de celular", 59.99, "despesa", "Contas e serviços")

        # despesas variáveis
        for semana in range(4):
            add(dia(3 + semana * 7), "Supermercado", rand.uniform(140, 290) * (1.15 if mes == 12 else 1), "despesa", "Alimentação")
        for _ in range(rand.randint(4, 8)):
            add(dia(rand.randint(1, 28)), rand.choice(["iFood", "Restaurante", "Padaria", "Lanchonete"]), rand.uniform(18, 75), "despesa", "Alimentação")
        for _ in range(rand.randint(8, 14)):
            add(dia(rand.randint(1, 28)), rand.choice(["Uber", "Metrô", "Ônibus", "99"]), rand.uniform(4.4, 38), "despesa", "Transporte")
        if rand.random() < 0.6:
            add(dia(rand.randint(1, 28)), rand.choice(["Cinema", "Show", "Bar com amigos"]), rand.uniform(45, 160), "despesa", "Lazer")
        if rand.random() < 0.4:
            add(dia(rand.randint(1, 28)), "Farmácia", rand.uniform(25, 120), "despesa", "Saúde")
        if rand.random() < 0.45 or mes in (11, 12):
            add(dia(rand.randint(1, 28)), rand.choice(["Loja de roupas", "Eletrônicos", "Compra online"]), rand.uniform(80, 420), "despesa", "Compras")
        if rand.random() < 0.5:
            add(dia(25), "Aplicação Tesouro Selic", rand.choice([150, 200, 300]), "despesa", "Investimentos")

    return lista


# compras do exemplo que passam a ser feitas no cartão de crédito
COMPRAS_NO_CARTAO = (
    "iFood", "Restaurante", "Uber", "99", "Streaming", "Cinema", "Show", "Bar com amigos",
    "Loja de roupas", "Eletrônicos", "Compra online", "Farmácia", "Plano de celular",
)


def criar_cartao_exemplo(conexao, usuario_id):
    """Cria um cartão fictício, move parte das compras do exemplo para ele e adiciona compras parceladas."""
    from cartoes import gerar_parcelas, mes_da_fatura  # import local evita dependência circular

    fechamento, vencimento = 3, 10
    cartao_id = conexao.execute(
        """INSERT INTO cartoes (usuario_id, nome, limite, dia_fechamento, dia_vencimento, cor, exemplo)
           VALUES (?, 'Nubank', 6000, ?, ?, 'roxo', 1)""",
        (usuario_id, fechamento, vencimento),
    ).lastrowid

    marcadores = ",".join("?" * len(COMPRAS_NO_CARTAO))
    conexao.execute(
        f"""UPDATE transacoes SET forma_pagamento = 'credito', cartao_id = ?
            WHERE usuario_id = ? AND origem = 'exemplo' AND tipo = 'despesa' AND descricao IN ({marcadores})""",
        (cartao_id, usuario_id, *COMPRAS_NO_CARTAO),
    )

    hoje = date.today()

    def meses_atras(n, dia):
        total = hoje.year * 12 + hoje.month - 1 - n
        ano, mes = total // 12, total % 12 + 1
        return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1])).isoformat()

    for descricao, valor, categoria, data_compra, vezes in (
        ("Curso de inglês online", 899.40, "Educação", meses_atras(4, 6), 6),
        ("Fone de ouvido bluetooth", 299.70, "Compras", meses_atras(1, 20), 3),
    ):
        for p in gerar_parcelas(descricao, valor, data_compra, vezes):
            conexao.execute(
                """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem,
                                           forma_pagamento, cartao_id, parcela, total_parcelas, compra_id)
                   VALUES (?, ?, ?, 'despesa', ?, ?, 'exemplo', 'credito', ?, ?, ?, ?)""",
                (usuario_id, p["descricao"], p["valor"], categoria, p["data"], cartao_id,
                 p["parcela"], p["total_parcelas"], p["compra_id"]),
            )

    # faturas que já venceram ficam como pagas
    meses = {
        mes_da_fatura(l["data"], fechamento, vencimento)
        for l in conexao.execute("SELECT data FROM transacoes WHERE cartao_id = ?", (cartao_id,))
    }
    for mes in meses:
        ano, m = map(int, mes.split("-"))
        if date(ano, m, vencimento) < hoje:
            # pago no dia do vencimento: é quando o dinheiro sai da conta
            conexao.execute(
                "INSERT INTO faturas_pagas (cartao_id, mes, pago_em) VALUES (?, ?, ?)",
                (cartao_id, mes, date(ano, m, vencimento).isoformat()),
            )
    return cartao_id
