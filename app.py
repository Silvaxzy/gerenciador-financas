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
from database import CATEGORIAS, conectar, criar_tabelas
from exemplo import gerar_transacoes_exemplo
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


def login_obrigatorio(rota):
    """Bloqueia a rota para quem não está logado."""
    @wraps(rota)
    def verificar(*args, **kwargs):
        if "usuario_id" not in session:
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
            session["usuario_id"] = usuario["id"]
            session["nome"] = usuario["nome"]
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos.", "erro")
        return redirect(url_for("login"))

    return render_template("login.html")


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
    return {"descricao": descricao, "valor": valor, "tipo": tipo, "categoria": categoria, "data": data}, None


def filtros_transacoes():
    """Monta o WHERE a partir dos filtros da URL."""
    condicoes = ["usuario_id = ?"]
    valores = [session["usuario_id"]]
    args = request.args
    if args.get("inicio"):
        condicoes.append("data >= ?")
        valores.append(args["inicio"])
    if args.get("fim"):
        condicoes.append("data <= ?")
        valores.append(args["fim"])
    if args.get("tipo") in ("receita", "despesa"):
        condicoes.append("tipo = ?")
        valores.append(args["tipo"])
    if args.get("categoria") in CATEGORIAS:
        condicoes.append("categoria = ?")
        valores.append(args["categoria"])
    if args.get("origem") in ("manual", "banco", "exemplo"):
        condicoes.append("origem = ?")
        valores.append(args["origem"])
    if args.get("busca"):
        condicoes.append("descricao LIKE ?")
        valores.append(f"%{args['busca'].strip()}%")
    return " AND ".join(condicoes), valores


@app.route("/api/transacoes", methods=["GET"])
@login_obrigatorio
def listar_transacoes():
    where, valores = filtros_transacoes()
    with conectar() as conexao:
        linhas = conexao.execute(
            f"""SELECT id, descricao, valor, tipo, categoria, data, origem, conta
                FROM transacoes WHERE {where}
                ORDER BY data DESC, id DESC LIMIT 2000""",
            valores,
        ).fetchall()
    return jsonify([dict(l) for l in linhas])


@app.route("/api/transacoes", methods=["POST"])
@login_obrigatorio
def criar_transacao():
    t, msg = ler_transacao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    with conectar() as conexao:
        cursor = conexao.execute(
            """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem)
               VALUES (?, ?, ?, ?, ?, ?, 'manual')""",
            (session["usuario_id"], t["descricao"], t["valor"], t["tipo"], t["categoria"], t["data"]),
        )
    return jsonify({"id": cursor.lastrowid}), 201


@app.route("/api/transacoes/<int:transacao_id>", methods=["PUT"])
@login_obrigatorio
def editar_transacao(transacao_id):
    t, msg = ler_transacao(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    with conectar() as conexao:
        cursor = conexao.execute(
            """UPDATE transacoes SET descricao = ?, valor = ?, tipo = ?, categoria = ?, data = ?
               WHERE id = ? AND usuario_id = ?""",
            (t["descricao"], t["valor"], t["tipo"], t["categoria"], t["data"], transacao_id, session["usuario_id"]),
        )
    if cursor.rowcount == 0:
        return erro("Transação não encontrada.", 404)
    return jsonify({"ok": True})


@app.route("/api/transacoes/<int:transacao_id>", methods=["DELETE"])
@login_obrigatorio
def excluir_transacao(transacao_id):
    with conectar() as conexao:
        conexao.execute(
            "DELETE FROM transacoes WHERE id = ? AND usuario_id = ?",  # só apaga as do próprio usuário
            (transacao_id, session["usuario_id"]),
        )
    return jsonify({"ok": True})


@app.route("/api/exportar.csv")
@login_obrigatorio
def exportar_csv():
    where, valores = filtros_transacoes()
    with conectar() as conexao:
        linhas = conexao.execute(
            f"SELECT data, descricao, categoria, tipo, valor, origem, conta FROM transacoes WHERE {where} ORDER BY data",
            valores,
        ).fetchall()
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")  # ";" abre direto no Excel em português
    escritor.writerow(["Data", "Descrição", "Categoria", "Tipo", "Valor", "Origem", "Conta"])
    for l in linhas:
        escritor.writerow([l["data"], l["descricao"], l["categoria"], l["tipo"],
                           f"{l['valor']:.2f}".replace(".", ","), l["origem"], l["conta"] or ""])
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
        return jsonify(analises.resumo(conexao, session["usuario_id"], mes))


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


# ================= API: dados de exemplo =================

@app.route("/api/exemplo", methods=["POST"])
@login_obrigatorio
def carregar_exemplo():
    with conectar() as conexao:
        conexao.execute("DELETE FROM transacoes WHERE usuario_id = ? AND origem = 'exemplo'", (session["usuario_id"],))
        conexao.executemany(
            """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data, origem)
               VALUES (?, ?, ?, ?, ?, ?, 'exemplo')""",
            [(session["usuario_id"], *t) for t in gerar_transacoes_exemplo(semente=session["usuario_id"])],
        )
    return jsonify({"ok": True})


@app.route("/api/exemplo", methods=["DELETE"])
@login_obrigatorio
def apagar_exemplo():
    with conectar() as conexao:
        conexao.execute("DELETE FROM transacoes WHERE usuario_id = ? AND origem = 'exemplo'", (session["usuario_id"],))
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
