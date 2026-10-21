import sqlite3

BANCO = "financas.db"


def conectar():
    conexao = sqlite3.connect(BANCO)
    conexao.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
    return conexao


def criar_tabelas():
    with conectar() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL
            )
        """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
                categoria TEXT,
                data TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            )
        """)