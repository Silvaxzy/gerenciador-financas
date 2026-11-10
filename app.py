import csv
import io
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import analises
import cartoes as regras_cartao
from database import CATEGORIAS, conectar, criar_tabelas
from exemplo import criar_cartao_exemplo, gerar_transacoes_exemplo
from pluggy import ClientePluggy, ErroPluggy, converter_transacao

load_dotenv()  # lê as variáveis do arquivo .env

app = Flask(__name__)


def chave_secreta():
    """Usa a SECRET_KEY do .env; sem ela, cria uma e guarda num arquivo local (fora do Git)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    arquivo = "chave_secreta.txt"
    if not os.path.exists(arquivo):
        with open(arquivo, "w") as f:
            f.write(secrets.token_hex(32))
    with open(arquivo) as f:
        return f.read().strip()


app.secret_key = chave_secreta()

PLUGGY_CLIENT_ID = os.environ.get("PLUGGY_CLIENT_ID", "")
PLUGGY_CLIENT_SECRET = os.environ.get("PLUGGY_CLIENT_SECRET", "")
MESES_HISTORICO = int(os.environ.get("MESES_HISTORICO", "12"))  # quanto do passado importar do banco
MODO_DEMO = os.environ.get("DEMO") == "1"  # versão online de demonstração

criar_tabelas()


SEM_CONEXAO = "Não foi possível conectar à Pluggy. Verifique sua internet e tente de novo."


def pluggy_configurada():
    return bool(PLUGGY_CLIENT_ID and PLUGGY_CLIENT_SECRET)


_cliente_pluggy = None


def cliente_pluggy():
    global _cliente_pluggy
    if _cliente_pluggy is None:
        _cliente_pluggy = ClientePluggy(PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET)
    return _cliente_pluggy


def sessao_valida():
    """Confere se o usuário da sessão ainda existe no banco.

    No Render gratuito o banco é apagado quando o servidor reinicia, mas o cookie
    de login continua no navegador. Sem essa checagem, a sessão apontaria para um
    usuário que não existe mais (ou para outra pessoa com o mesmo id).
    """
    usuario_id, email = session.get("usuario_id"), session.get("email")
    if not usuario_id or not email:
        return False
    with conectar() as conexao:
        linha = conexao.execute("SELECT email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return bool(linha) and linha["email"] == email


def login_obrigatorio(rota):
    """Bloqueia a rota para quem não está logado."""
    @wraps(rota)
    def verificar(*args, **kwargs):
        if not sessao_valida():
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"erro": "Faça login novamente."}), 401
            return redirect(url_for("login"))
        return rota(*args, **kwargs)
    return verificar


def erro(mensagem, status=400):
    return jsonify({"erro": mensagem}), status


# ================= Páginas =================

@app.route("/")
def inicio():
    if "usuario_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form["nome"].strip()
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]

        if len(senha) < 6:
            flash("A senha precisa ter pelo menos 6 caracteres.", "erro")
            return redirect(url_for("cadastro"))

        try:
            with conectar() as conexao:
                conexao.execute(
                    "INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)",
                    (nome, email, generate_password_hash(senha)),
                )
        except sqlite3.IntegrityError:
            flash("Este e-mail já está cadastrado.", "erro")
            return redirect(url_for("cadastro"))

        flash("Conta criada com sucesso! Faça login.", "sucesso")
        return redirect(url_for("login"))

    return render_template("cadastro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]

        with conectar() as conexao:
            usuario = conexao.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

        if usuario and check_password_hash(usuario["senha_hash"], senha):
            session.clear()
            session["usuario_id"] = usuario["id"]
            session["email"] = usuario["email"]
            session["nome"] = usuario["nome"]
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos.", "erro")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.context_processor
def variaveis_globais():
    return {"modo_demo": MODO_DEMO}


@app.route("/demo")
def entrar_demo():
    """Cria uma conta de visitante com dados de exemplo e já entra no painel."""
    if not MODO_DEMO:
        return redirect(url_for("login"))
    with conectar() as conexao:
        # mantém só os 100 visitantes mais recentes para o banco não crescer
        antigos = conexao.execute(
            """SELECT id FROM usuarios WHERE email LIKE 'visitante-%@demo.local'
               ORDER BY id DESC LIMIT -1 OFFSET 100"""
        ).fetchall()
        for linha in antigos:
            for tabela in ("transacoes", "orcamentos", "conexoes_bancarias", "cartoes"):
                conexao.execute(f"DELETE FROM {tabela} WHERE usuario_id = ?", (linha["id"],))
            conexao.execute("DELETE FROM usuarios WHERE id = ?", (linha["id"],))

        email_visitante = f"visitante-{secrets.token_hex(6)}@demo.local"
        cursor = conexao.execute(
            "INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)",
            ("Visitante", email_visitante, generate_password_hash(secrets.token_hex(16))),
        )
        usuario_id = cursor.lastrowid
        conexao.executemany(
            """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem)
               VALUES (?, ?, ?, ?, ?, ?, 'exemplo')""",
            [(usuario_id, *t) for t in gerar_transacoes_exemplo(semente=usuario_id)],
        )
        conexao.executemany(
            "INSERT INTO orcamentos (usuario_id, categoria, limite) VALUES (?, ?, ?)",
            [(usuario_id, "Alimentação", 900), (usuario_id, "Transporte", 250), (usuario_id, "Lazer", 200)],
        )
        criar_cartao_exemplo(conexao, usuario_id)
    session.clear()
    session["usuario_id"] = usuario_id
    session["email"] = email_visitante
    session["nome"] = "Visitante"
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_obrigatorio
def dashboard():
    return render_template(
        "dashboard.html",
        nome=session["nome"],
        categorias=CATEGORIAS,
        pluggy=pluggy_configurada(),
        cores_cartao=regras_cartao.CORES_CARTAO,
    )


# ================= API: transações =================

def ler_transacao(dados):
    """Valida o JSON de uma transação. Devolve (dados, mensagem_de_erro)."""
    descricao = (dados.get("descricao") or "").strip()
    tipo = dados.get("tipo")
    categoria = dados.get("categoria") or "Outros"
    data = dados.get("data") or ""
    try:
        valor = round(float(dados.get("valor")), 2)
    except (TypeError, ValueError):
        return None, "Valor inválido."
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        return None, "Data inválida."
    if not descricao or len(descricao) > 120:
        return None, "Informe uma descrição de até 120 caracteres."
    if valor <= 0:
        return None, "O valor precisa ser maior que zero."
    if tipo not in ("receita", "despesa"):
        return None, "Tipo inválido."
    if categoria not in CATEGORIAS:
        return None, "Categoria inválida."

    forma = dados.get("forma_pagamento") or "conta"
    if tipo == "receita":
        forma = "conta"  # receita sempre entra na conta
    if forma not in ("conta", "credito"):
        return None, "Forma de pagamento inválida."
    cartao_id = None
    parcelas = 1
    if forma == "credito":
        try:
            cartao_id = int(dados.get("cartao_id"))
        except (TypeError, ValueError):
            return None, "Escolha o cartão de crédito."
        with conectar() as conexao:
            dono = conexao.execute(
                "SELECT 1 FROM cartoes WHERE id = ? AND usuario_id = ?", (cartao_id, session["usuario_id"])
            ).fetchone()
        if not dono:
            return None, "Cartão não encontrado."
        try:
            parcelas = int(dados.get("parcelas") or 1)
        except (TypeError, ValueError):
            return None, "Número de parcelas inválido."
        if not 1 <= parcelas <= 24:
            return None, "Escolha entre 1 e 24 parcelas."
        if valor / parcelas < 0.01:
            return None, "Valor muito baixo para esse número de parcelas."

    return {
        "descricao": descricao, "valor": valor, "tipo": tipo, "categoria": categoria, "data": data,
        "forma_pagamento": forma, "cartao_id": cartao_id, "parcelas": parcelas,
    }, None


def filtros_transacoes():
    """Monta o WHERE a partir dos filtros da URL."""
    condicoes = ["t.usuario_id = ?"]
    valores = [session["usuario_id"]]
    args = request.args
    if args.get("inicio"):
        condicoes.append("t.data >= ?")
        valores.append(args["inicio"])
    if args.get("fim"):
        condicoes.append("t.data <= ?")
        valores.append(args["fim"])
    if args.get("tipo") in ("receita", "despesa"):
        condicoes.append("t.tipo = ?")
        valores.append(args["tipo"])
    if args.get("categoria") in CATEGORIAS:
        condicoes.append("t.categoria = ?")
        valores.append(args["categoria"])
    if args.get("origem") in ("manual", "banco", "exemplo"):
        condicoes.append("t.origem = ?")
        valores.append(args["origem"])
    pagamento = args.get("pagamento", "")
    if pagamento == "conta":
        condicoes.append("t.forma_pagamento = 'conta'")
    elif pagamento == "credito":
        condicoes.append("t.forma_pagamento = 'credito'")
    elif pagamento.isdigit():
        condicoes.append("t.cartao_id = ?")
        valores.append(int(pagamento))
    if args.get("busca"):
        condicoes.append("t.descricao LIKE ?")
        valores.append(f"%{args['busca'].strip()}%")
    return " AND ".join(condicoes), valores


@app.route("/api/transacoes", methods=["GET"])
@login_obrigatorio
def listar_transacoes():
    where, valores = filtros_transacoes()
    with conectar() as conexao:
        linhas = conexao.execute(
            f"""SELECT t.id, t.descricao, t.valor, t.tipo, t.categoria, t.data, t.origem, t.conta,
                       t.forma_pagamento, t.cartao_id, t.parcela, t.total_parcelas, t.compra_id,
                       c.nome AS cartao_nome, c.cor AS cartao_cor
                FROM transacoes t LEFT JOIN cartoes c ON c.id = t.cartao_id
                WHERE {where}
                ORDER BY t.data DESC, t.id DESC LIMIT 2000""",
            valores,
        ).fetchall()
    return jsonify([dict(l) for l in linhas])


@app.route("/api/transacoes", methods=["POST"])
@login_obrigatorio
def criar_transacao():
    t, msg = ler_transacao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    parcelas = regras_cartao.gerar_parcelas(t["descricao"], t["valor"], t["data"], t["parcelas"])
    with conectar() as conexao:
        for p in parcelas:
            cursor = conexao.execute(
                """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem,
                                           forma_pagamento, cartao_id, parcela, total_parcelas, compra_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, ?, ?, ?, ?)""",
                (session["usuario_id"], p["descricao"], p["valor"], t["tipo"], t["categoria"], p["data"],
                 t["forma_pagamento"], t["cartao_id"], p["parcela"], p["total_parcelas"], p["compra_id"]),
            )
    return jsonify({"id": cursor.lastrowid, "parcelas": len(parcelas)}), 201


@app.route("/api/transacoes/<int:transacao_id>", methods=["PUT"])
@login_obrigatorio
def editar_transacao(transacao_id):
    t, msg = ler_transacao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    with conectar() as conexao:
        cursor = conexao.execute(
            """UPDATE transacoes SET descricao = ?, valor = ?, tipo = ?, categoria = ?, data = ?,
                                     forma_pagamento = ?, cartao_id = ?
               WHERE id = ? AND usuario_id = ?""",
            (t["descricao"], t["valor"], t["tipo"], t["categoria"], t["data"],
             t["forma_pagamento"], t["cartao_id"], transacao_id, session["usuario_id"]),
        )
    if cursor.rowcount == 0:
        return erro("Transação não encontrada.", 404)
    return jsonify({"ok": True})


@app.route("/api/transacoes/<int:transacao_id>", methods=["DELETE"])
@login_obrigatorio
def excluir_transacao(transacao_id):
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT compra_id FROM transacoes WHERE id = ? AND usuario_id = ?", (transacao_id, session["usuario_id"])
        ).fetchone()
        if linha and linha["compra_id"] and request.args.get("todas") == "1":
            # compra parcelada: apaga todas as parcelas
            cursor = conexao.execute(
                "DELETE FROM transacoes WHERE compra_id = ? AND usuario_id = ?", (linha["compra_id"], session["usuario_id"])
            )
        else:
            cursor = conexao.execute(
                "DELETE FROM transacoes WHERE id = ? AND usuario_id = ?",  # só apaga as do próprio usuário
                (transacao_id, session["usuario_id"]),
            )
    return jsonify({"ok": True, "excluidas": cursor.rowcount})


@app.route("/api/exportar.csv")
@login_obrigatorio
def exportar_csv():
    where, valores = filtros_transacoes()
    with conectar() as conexao:
        linhas = conexao.execute(
            f"""SELECT t.data, t.descricao, t.categoria, t.tipo, t.valor, t.origem, t.conta, c.nome AS cartao_nome
                FROM transacoes t LEFT JOIN cartoes c ON c.id = t.cartao_id
                WHERE {where} ORDER BY t.data""",
            valores,
        ).fetchall()
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")  # ";" abre direto no Excel em português
    escritor.writerow(["Data", "Descrição", "Categoria", "Tipo", "Valor", "Pagamento", "Origem", "Conta"])
    for l in linhas:
        pagamento = f"Cartão {l['cartao_nome']}" if l["cartao_nome"] else "Conta"
        escritor.writerow([l["data"], l["descricao"], l["categoria"], l["tipo"],
                           f"{l['valor']:.2f}".replace(".", ","), pagamento, l["origem"], l["conta"] or ""])
    return Response(
        "﻿" + saida.getvalue(),  # BOM: acentos certos no Excel
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=transacoes-{date.today()}.csv"},
    )


# ================= API: análises e orçamentos =================

@app.route("/api/resumo")
@login_obrigatorio
def api_resumo():
    with conectar() as conexao:
        mes = request.args.get("mes") or analises.mes_padrao(conexao, session["usuario_id"])
        try:
            datetime.strptime(mes, "%Y-%m")
        except ValueError:
            return erro("Mês inválido.")
        r = analises.resumo(conexao, session["usuario_id"], mes)
        # alertas dos cartões aparecem primeiro, por serem mais urgentes
        r["insights"] = (regras_cartao.insights_cartoes(conexao, session["usuario_id"]) + r["insights"])[:6]
        return jsonify(r)


@app.route("/api/orcamentos", methods=["PUT"])
@login_obrigatorio
def salvar_orcamento():
    dados = request.get_json(silent=True) or {}
    categoria = dados.get("categoria")
    try:
        limite = float(dados.get("limite") or 0)
    except (TypeError, ValueError):
        return erro("Limite inválido.")
    if categoria not in CATEGORIAS:
        return erro("Categoria inválida.")
    with conectar() as conexao:
        if limite <= 0:  # limite zero remove o orçamento
            conexao.execute("DELETE FROM orcamentos WHERE usuario_id = ? AND categoria = ?",
                            (session["usuario_id"], categoria))
        else:
            conexao.execute(
                """INSERT INTO orcamentos (usuario_id, categoria, limite) VALUES (?, ?, ?)
                   ON CONFLICT (usuario_id, categoria) DO UPDATE SET limite = excluded.limite""",
                (session["usuario_id"], categoria, limite),
            )
    return jsonify({"ok": True})


# ================= API: cartões de crédito =================

def ler_cartao(dados):
    nome = (dados.get("nome") or "").strip()
    if not nome or len(nome) > 40:
        return None, "Informe o nome do cartão (até 40 caracteres)."
    try:
        limite = round(float(dados.get("limite") or 0), 2)
        fechamento = int(dados.get("dia_fechamento"))
        vencimento = int(dados.get("dia_vencimento"))
    except (TypeError, ValueError):
        return None, "Preencha limite, dia de fechamento e dia de vencimento."
    if limite < 0:
        return None, "O limite não pode ser negativo."
    if not (1 <= fechamento <= 28 and 1 <= vencimento <= 28):
        return None, "Os dias de fechamento e vencimento devem ser entre 1 e 28."
    cor = dados.get("cor") if dados.get("cor") in regras_cartao.CORES_CARTAO else "roxo"
    return {"nome": nome, "limite": limite, "dia_fechamento": fechamento, "dia_vencimento": vencimento, "cor": cor}, None


def buscar_cartao(conexao, cartao_id):
    return conexao.execute(
        "SELECT * FROM cartoes WHERE id = ? AND usuario_id = ?", (cartao_id, session["usuario_id"])
    ).fetchone()


def desvincular_cartao(conexao, cartao_id):
    """As compras continuam como despesas, só deixam de estar ligadas ao cartão."""
    conexao.execute(
        "UPDATE transacoes SET cartao_id = NULL, forma_pagamento = 'conta' WHERE cartao_id = ?", (cartao_id,)
    )


@app.route("/api/cartoes")
@login_obrigatorio
def listar_cartoes():
    with conectar() as conexao:
        cartoes = conexao.execute(
            "SELECT * FROM cartoes WHERE usuario_id = ? ORDER BY id", (session["usuario_id"],)
        ).fetchall()
        return jsonify([regras_cartao.resumo_cartao(conexao, c) for c in cartoes])


@app.route("/api/cartoes", methods=["POST"])
@login_obrigatorio
def criar_cartao():
    c, msg = ler_cartao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    with conectar() as conexao:
        cursor = conexao.execute(
            """INSERT INTO cartoes (usuario_id, nome, limite, dia_fechamento, dia_vencimento, cor)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session["usuario_id"], c["nome"], c["limite"], c["dia_fechamento"], c["dia_vencimento"], c["cor"]),
        )
    return jsonify({"id": cursor.lastrowid}), 201


@app.route("/api/cartoes/<int:cartao_id>", methods=["PUT"])
@login_obrigatorio
def editar_cartao(cartao_id):
    c, msg = ler_cartao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    with conectar() as conexao:
        cursor = conexao.execute(
            """UPDATE cartoes SET nome = ?, limite = ?, dia_fechamento = ?, dia_vencimento = ?, cor = ?
               WHERE id = ? AND usuario_id = ?""",
            (c["nome"], c["limite"], c["dia_fechamento"], c["dia_vencimento"], c["cor"], cartao_id, session["usuario_id"]),
        )
    if cursor.rowcount == 0:
        return erro("Cartão não encontrado.", 404)
    return jsonify({"ok": True})


@app.route("/api/cartoes/<int:cartao_id>", methods=["DELETE"])
@login_obrigatorio
def excluir_cartao(cartao_id):
    with conectar() as conexao:
        if not buscar_cartao(conexao, cartao_id):
            return erro("Cartão não encontrado.", 404)
        desvincular_cartao(conexao, cartao_id)
        conexao.execute("DELETE FROM cartoes WHERE id = ?", (cartao_id,))
    return jsonify({"ok": True})


@app.route("/api/cartoes/<int:cartao_id>/fatura")
@login_obrigatorio
def ver_fatura(cartao_id):
    with conectar() as conexao:
        cartao = buscar_cartao(conexao, cartao_id)
        if not cartao:
            return erro("Cartão não encontrado.", 404)
        mes = request.args.get("mes") or regras_cartao.mes_da_fatura(
            date.today(), cartao["dia_fechamento"], cartao["dia_vencimento"]
        )
        try:
            datetime.strptime(mes, "%Y-%m")
        except ValueError:
            return erro("Mês inválido.")
        return jsonify(regras_cartao.fatura_detalhada(conexao, cartao, mes))


@app.route("/api/cartoes/<int:cartao_id>/fatura/<mes>/pagamento", methods=["PUT", "DELETE"])
@login_obrigatorio
def pagamento_fatura(cartao_id, mes):
    """Marca (PUT) ou desmarca (DELETE) a fatura como paga.

    Pagar a fatura não cria uma nova despesa: as compras já contam como despesa
    no mês em que foram feitas, então lançar o pagamento contaria tudo em dobro.
    """
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        return erro("Mês inválido.")
    with conectar() as conexao:
        if not buscar_cartao(conexao, cartao_id):
            return erro("Cartão não encontrado.", 404)
        if request.method == "PUT":
            conexao.execute("INSERT OR IGNORE INTO faturas_pagas (cartao_id, mes) VALUES (?, ?)", (cartao_id, mes))
        else:
            conexao.execute("DELETE FROM faturas_pagas WHERE cartao_id = ? AND mes = ?", (cartao_id, mes))
    return jsonify({"ok": True})


# ================= API: dados de exemplo =================

def remover_exemplo(conexao, usuario_id):
    """Apaga as transações e o cartão de exemplo (sem mexer no que o usuário criou)."""
    conexao.execute("DELETE FROM transacoes WHERE usuario_id = ? AND origem = 'exemplo'", (usuario_id,))
    for c in conexao.execute("SELECT id FROM cartoes WHERE usuario_id = ? AND exemplo = 1", (usuario_id,)).fetchall():
        desvincular_cartao(conexao, c["id"])
        conexao.execute("DELETE FROM cartoes WHERE id = ?", (c["id"],))


@app.route("/api/exemplo", methods=["POST"])
@login_obrigatorio
def carregar_exemplo():
    with conectar() as conexao:
        remover_exemplo(conexao, session["usuario_id"])
        conexao.executemany(
            """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem)
               VALUES (?, ?, ?, ?, ?, ?, 'exemplo')""",
            [(session["usuario_id"], *t) for t in gerar_transacoes_exemplo(semente=session["usuario_id"])],
        )
        criar_cartao_exemplo(conexao, session["usuario_id"])
    return jsonify({"ok": True})


@app.route("/api/exemplo", methods=["DELETE"])
@login_obrigatorio
def apagar_exemplo():
    with conectar() as conexao:
        remover_exemplo(conexao, session["usuario_id"])
    return jsonify({"ok": True})


# ================= API: Open Finance (Pluggy) =================

def importar_item(conexao, usuario_id, item_id):
    """Busca contas e transações antigas de um banco conectado e salva sem duplicar."""
    cliente = cliente_pluggy()
    item = cliente.aguardar_item(item_id)
    banco = (item.get("connector") or {}).get("name") or "Banco conectado"
    desde = (date.today() - timedelta(days=30 * MESES_HISTORICO)).isoformat()

    novas = 0
    total = 0
    for conta in cliente.contas(item_id):
        nome_conta = f"{banco} · {conta.get('name') or conta.get('type', 'Conta')}"
        for t in cliente.transacoes(conta["id"], desde):
            r = converter_transacao(t, nome_conta)
            if not r["id_externo"] or not r["data"] or r["valor"] <= 0:
                continue
            total += 1
            cursor = conexao.execute(
                """INSERT OR IGNORE INTO transacoes
                   (usuario_id, descricao, valor, tipo, categoria, data, origem, id_externo, conta)
                   VALUES (?, ?, ?, ?, ?, ?, 'banco', ?, ?)""",
                (usuario_id, r["descricao"], r["valor"], r["tipo"], r["categoria"], r["data"], r["id_externo"], r["conta"]),
            )
            novas += cursor.rowcount

    conexao.execute(
        """INSERT INTO conexoes_bancarias (usuario_id, item_id, banco, ultima_sincronizacao)
           VALUES (?, ?, ?, datetime('now', 'localtime'))
           ON CONFLICT (usuario_id, item_id)
           DO UPDATE SET banco = excluded.banco, ultima_sincronizacao = excluded.ultima_sincronizacao""",
        (usuario_id, item_id, banco),
    )
    return {"banco": banco, "novas": novas, "ja_existentes": total - novas}


@app.route("/api/pluggy/status")
@login_obrigatorio
def pluggy_status():
    with conectar() as conexao:
        conexoes = conexao.execute(
            """SELECT id, banco, ultima_sincronizacao, criado_em FROM conexoes_bancarias
               WHERE usuario_id = ? ORDER BY criado_em""",
            (session["usuario_id"],),
        ).fetchall()
    return jsonify({"configurada": pluggy_configurada(), "conexoes": [dict(c) for c in conexoes]})


@app.route("/api/pluggy/token", methods=["POST"])
@login_obrigatorio
def pluggy_token():
    if not pluggy_configurada():
        return erro("A integração com a Pluggy não está configurada. Veja o arquivo .env.example.", 503)
    try:
        return jsonify({"accessToken": cliente_pluggy().criar_connect_token(session["usuario_id"])})
    except ErroPluggy as e:
        return erro(str(e), 502)
    except requests.RequestException:
        return erro(SEM_CONEXAO, 502)


@app.route("/api/pluggy/conexoes", methods=["POST"])
@login_obrigatorio
def pluggy_nova_conexao():
    if not pluggy_configurada():
        return erro("A integração com a Pluggy não está configurada.", 503)
    item_id = (request.get_json(silent=True) or {}).get("itemId")
    if not item_id:
        return erro("itemId ausente.")
    try:
        with conectar() as conexao:
            return jsonify(importar_item(conexao, session["usuario_id"], item_id))
    except ErroPluggy as e:
        return erro(str(e), 502)
    except requests.RequestException:
        return erro(SEM_CONEXAO, 502)


@app.route("/api/pluggy/sincronizar", methods=["POST"])
@login_obrigatorio
def pluggy_sincronizar():
    if not pluggy_configurada():
        return erro("A integração com a Pluggy não está configurada.", 503)
    resultados = []
    try:
        with conectar() as conexao:
            itens = conexao.execute(
                "SELECT item_id FROM conexoes_bancarias WHERE usuario_id = ?", (session["usuario_id"],)
            ).fetchall()
            for i in itens:
                resultados.append(importar_item(conexao, session["usuario_id"], i["item_id"]))
    except ErroPluggy as e:
        return erro(str(e), 502)
    except requests.RequestException:
        return erro(SEM_CONEXAO, 502)
    return jsonify({"resultados": resultados, "novas": sum(r["novas"] for r in resultados)})


@app.route("/api/pluggy/conexoes/<int:conexao_id>", methods=["DELETE"])
@login_obrigatorio
def pluggy_remover_conexao(conexao_id):
    with conectar() as conexao:
        conexao.execute(
            "DELETE FROM conexoes_bancarias WHERE id = ? AND usuario_id = ?", (conexao_id, session["usuario_id"])
        )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
