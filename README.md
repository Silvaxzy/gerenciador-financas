# 💰 Gerenciador de Finanças

Aplicação web Full Stack para controle de finanças pessoais. O usuário cria uma conta, faz login e registra receitas e despesas, acompanhando o saldo e os gastos por categoria em um painel interativo.

![Painel](screenshots/painel.png)

## ✨ Funcionalidades

- Cadastro e login de usuários com senha criptografada (hash)
- Cada usuário vê apenas as próprias transações
- Cadastro e exclusão de receitas e despesas sem recarregar a página
- Cards de resumo com saldo, total de receitas e total de despesas
- Gráfico de despesas por categoria
- Histórico de transações ordenado por data

## 🛠️ Tecnologias

| Camada | Tecnologias |
|---|---|
| Back-end | Python, Flask |
| Banco de dados | SQLite |
| Front-end | HTML, CSS, JavaScript (Fetch API) |
| Gráficos | Chart.js |

## 🏗️ Arquitetura

O back-end em Flask funciona como uma **API REST** que retorna dados em JSON. O front-end em JavaScript consome essa API com `fetch` e atualiza a tela dinamicamente.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/transacoes` | Lista as transações do usuário logado |
| POST | `/api/transacoes` | Cria uma nova transação |
| DELETE | `/api/transacoes/<id>` | Exclui uma transação |

## 🚀 Como rodar o projeto

```bash
# Clonar o repositório
git clone https://github.com/Silvaxzy/gerenciador-financas.git
cd gerenciador-financas

# Criar e ativar o ambiente virtual
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac

# Instalar as dependências
pip install -r requirements.txt

# Rodar
python app.py
```

Acesse **http://127.0.0.1:5000** no navegador.

## 📸 Telas

| Login | Painel |
|---|---|
| ![Login](screenshots/login.png) | ![Painel](screenshots/painel.png) |

## 📌 Próximas melhorias

- [ ] Editar transações
- [ ] Filtrar por mês e categoria
- [ ] Exportar relatório em CSV
- [ ] Deploy online

## 👤 Autor

Feito por **Bruno Silva**, estudante de Análise e Desenvolvimento de Sistemas.

[GitHub](https://github.com/Silvaxzy) · [LinkedIn](https://www.linkedin.com/in/bruno-silva-2846)