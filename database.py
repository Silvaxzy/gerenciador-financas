import sqlite3

BANCO = "financas.db"

CATEGORIAS = [
    "Alimentação",
    "Transporte",
    "Moradia",
    "Contas e serviços",
    "Saúde",
    "Educação",
    "Lazer",
    "Compras",
    "Transferências",
    "Investimentos",
    "Salário",
    "Outros",
]


def conectar():
    conexao = sqlite3.connect(BANCO)
    conexao.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def _colunas(conexao, tabela):
    return {linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}


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

        # migração: colunas novas da versão 2.0 (não apaga os dados antigos)
        existentes = _colunas(conexao, "transacoes")
        novas = {
            "origem": "TEXT NOT NULL DEFAULT 'manual'",  # manual | banco | exemplo
            "id_externo": "TEXT",                         # id da transação no banco (Pluggy)
            "conta": "TEXT",                              # nome da conta de origem
        }
        for coluna, definicao in novas.items():
            if coluna not in existentes:
                conexao.execute(f"ALTER TABLE transacoes ADD COLUMN {coluna} {definicao}")

        # impede importar a mesma transação do banco duas vezes
        conexao.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transacao_externa
            ON transacoes (usuario_id, id_externo) WHERE id_externo IS NOT NULL
        """)
        conexao.execute("CREATE INDEX IF NOT EXISTS ix_transacao_data ON transacoes (usuario_id, data)")

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS orcamentos (
                usuario_id INTEGER NOT NULL,
                categoria TEXT NOT NULL,
                limite REAL NOT NULL CHECK (limite > 0),
                PRIMARY KEY (usuario_id, categoria),
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            )
        """)

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS conexoes_bancarias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                banco TEXT,
                ultima_sincronizacao TEXT,
                criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE (usuario_id, item_id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            )
        """)
