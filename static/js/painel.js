const formulario = document.getElementById("form-transacao");
const lista = document.getElementById("lista-transacoes");
const mensagem = document.getElementById("mensagem");
let grafico = null;

// ---------- Funções de formatação ----------

function formatarMoeda(valor) {
    return valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatarData(dataISO) {
    const [ano, mes, dia] = dataISO.split("-");
    return `${dia}/${mes}/${ano}`;
}

function definirDataDeHoje() {
    const hoje = new Date();
    hoje.setMinutes(hoje.getMinutes() - hoje.getTimezoneOffset()); // ajusta para o fuso local
    document.getElementById("data").value = hoje.toISOString().slice(0, 10);
}

function mostrarMensagem(texto, tipo) {
    mensagem.textContent = texto;
    mensagem.className = `mensagem ${tipo}`;
    setTimeout(() => (mensagem.textContent = ""), 3000);
}

// ---------- Buscar dados no Python ----------

async function carregarTransacoes() {
    const resposta = await fetch("/api/transacoes");
    const transacoes = await resposta.json();

    atualizarResumo(transacoes);
    atualizarLista(transacoes);
    atualizarGrafico(transacoes);
}

// ---------- Atualizar a tela ----------

function atualizarResumo(transacoes) {
    let receitas = 0;
    let despesas = 0;

    transacoes.forEach((t) => {
        if (t.tipo === "receita") receitas += t.valor;
        else despesas += t.valor;
    });

    const saldo = receitas - despesas;
    document.getElementById("total-receitas").textContent = formatarMoeda(receitas);
    document.getElementById("total-despesas").textContent = formatarMoeda(despesas);

    const elementoSaldo = document.getElementById("saldo");
    elementoSaldo.textContent = formatarMoeda(saldo);
    elementoSaldo.classList.toggle("negativo", saldo < 0);
}

function atualizarLista(transacoes) {
    lista.innerHTML = "";
    document.getElementById("sem-transacoes").style.display = transacoes.length ? "none" : "block";

    transacoes.forEach((t) => {
        const item = document.createElement("li");
        item.className = t.tipo;
        item.innerHTML = `
            <div>
                <strong></strong>
                <small></small>
            </div>
            <div class="direita">
                <span class="valor"></span>
                <button class="excluir" title="Excluir">✕</button>
            </div>
        `;

        // textContent evita que alguém injete HTML pela descrição
        item.querySelector("strong").textContent = t.descricao;
        item.querySelector("small").textContent = `${t.categoria} · ${formatarData(t.data)}`;
        item.querySelector(".valor").textContent =
            `${t.tipo === "despesa" ? "-" : "+"} ${formatarMoeda(t.valor)}`;

        item.querySelector(".excluir").addEventListener("click", () => excluirTransacao(t.id));
        lista.appendChild(item);
    });
}

function atualizarGrafico(transacoes) {
    const totais = {};

    transacoes
        .filter((t) => t.tipo === "despesa")
        .forEach((t) => {
            totais[t.categoria] = (totais[t.categoria] || 0) + t.valor;
        });

    const categorias = Object.keys(totais);
    document.getElementById("sem-dados-grafico").style.display = categorias.length ? "none" : "block";

    if (grafico) {
        grafico.destroy();
        grafico = null;
    }
    if (!categorias.length) return;

    grafico = new Chart(document.getElementById("grafico"), {
        type: "doughnut",
        data: {
            labels: categorias,
            datasets: [{
                data: Object.values(totais),
                backgroundColor: [
                    "#4f46e5", "#16a34a", "#f59e0b", "#dc2626",
                    "#0ea5e9", "#a855f7", "#14b8a6", "#64748b",
                ],
            }],
        },
        options: {
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom" } },
        },
    });
}

// ---------- Ações do usuário ----------

formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault(); // impede a página de recarregar

    const transacao = {
        descricao: document.getElementById("descricao").value,
        valor: document.getElementById("valor").value,
        tipo: document.getElementById("tipo").value,
        categoria: document.getElementById("categoria").value,
        data: document.getElementById("data").value,
    };

    const resposta = await fetch("/api/transacoes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(transacao),
    });

    if (resposta.ok) {
        formulario.reset();
        definirDataDeHoje();
        mostrarMensagem("Transação adicionada!", "sucesso");
        carregarTransacoes();
    } else {
        const erro = await resposta.json();
        mostrarMensagem(erro.erro, "erro");
    }
});

async function excluirTransacao(id) {
    if (!confirm("Deseja excluir esta transação?")) return;

    await fetch(`/api/transacoes/${id}`, { method: "DELETE" });
    carregarTransacoes();
}

// ---------- Início ----------

definirDataDeHoje();
carregarTransacoes();