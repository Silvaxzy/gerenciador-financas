import sqlite3
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
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


if __name__ == "__main__":
    app.run(debug=True)