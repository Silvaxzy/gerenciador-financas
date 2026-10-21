import sqlite3
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from database import conectar, criar_tabelas

app = Flask(__name__)
app.secret_key = "troque-isto-por-uma-frase-secreta-qualquer"

criar_tabelas()


def login_obrigatorio(rota):
    """Bloqueia a página para quem não está logado."""
    @wraps(rota)
    def verificar(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return rota(*args, **kwargs)
    return verificar


# ---------------- Páginas ----------------

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
            usuario = conexao.execute(
                "SELECT * FROM usuarios WHERE email = ?", (email,)
            ).fetchone()

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
    return render_template("dashboard.html", nome=session["nome"])


# ---------------- API (usada pelo JavaScript) ----------------

@app.route("/api/transacoes", methods=["GET"])
@login_obrigatorio
def listar_transacoes():
    with conectar() as conexao:
        linhas = conexao.execute(
            """SELECT id, descricao, valor, tipo, categoria, data
               FROM transacoes
               WHERE usuario_id = ?
               ORDER BY data DESC, id DESC""",
            (session["usuario_id"],),
        ).fetchall()
    return jsonify([dict(linha) for linha in linhas])


@app.route("/api/transacoes", methods=["POST"])
@login_obrigatorio
def criar_transacao():
    dados = request.get_json(silent=True) or {}

    descricao = (dados.get("descricao") or "").strip()
    tipo = dados.get("tipo")
    categoria = (dados.get("categoria") or "Outros").strip()
    data = dados.get("data")

    try:
        valor = float(dados.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Valor inválido."}), 400

    if not descricao or valor <= 0 or tipo not in ("receita", "despesa") or not data:
        return jsonify({"erro": "Preencha todos os campos corretamente."}), 400

    with conectar() as conexao:
        cursor = conexao.execute(
            """INSERT INTO transacoes (usuario_id, descricao, valor, tipo, categoria, data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session["usuario_id"], descricao, valor, tipo, categoria, data),
        )
    return jsonify({"id": cursor.lastrowid}), 201


@app.route("/api/transacoes/<int:transacao_id>", methods=["DELETE"])
@login_obrigatorio
def excluir_transacao(transacao_id):
    with conectar() as conexao:
        conexao.execute(
            "DELETE FROM transacoes WHERE id = ? AND usuario_id = ?",
            (transacao_id, session["usuario_id"]),
        )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)