// =========================================================
//  Finanças 2.0 — painel
// =========================================================
const CORES_CATEGORIAS = [
    "#10b981", "#38bdf8", "#f59e0b", "#a78bfa", "#f43f5e", "#22d3ee",
    "#84cc16", "#fb923c", "#e879f9", "#94a3b8", "#14b8a6", "#64748b",
];

const estado = {
    aba: "visao",
    mes: null,
    resumo: null,
    editandoId: null,
    graficos: {},
};

const $ = (seletor) => document.querySelector(seletor);

// ---------------- utilidades ----------------

const formatarMoeda = (v) => Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

function formatarData(iso) {
    const [ano, mes, dia] = iso.split("-");
    return `${dia}/${mes}/${ano}`;
}

function nomeMes(anoMes, curto = false) {
    const [ano, mes] = anoMes.split("-").map(Number);
    const texto = new Date(ano, mes - 1, 1).toLocaleDateString("pt-BR", { month: curto ? "short" : "long", year: curto ? "2-digit" : "numeric" });
    return texto.replace(".", "").replace(" de ", " ");
}

function hojeISO() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
}

function corCategoria(nome) {
    const i = (window.CATEGORIAS || []).indexOf(nome);
    return CORES_CATEGORIAS[(i >= 0 ? i : 11) % CORES_CATEGORIAS.length];
}

function avisar(texto, tipo = "ok") {
    const t = $("#toast");
    t.textContent = texto;
    t.className = `toast visivel ${tipo === "erro" ? "erro" : ""}`;
    clearTimeout(avisar.timer);
    avisar.timer = setTimeout(() => (t.className = "toast"), 4000);
}

async function api(url, opcoes = {}) {
    const resposta = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...opcoes,
        body: opcoes.body ? JSON.stringify(opcoes.body) : undefined,
    });
    if (resposta.status === 401) {
        window.location.href = "/login";
        throw new Error("Sessão expirada");
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(dados.erro || "Algo deu errado.");
    return dados;
}

function variacaoHTML(el, valor, inverter = false, comparacao = "mês anterior") {
    // inverter: para despesas, subir é ruim
    el.textContent = "";
    if (valor === null || valor === undefined) {
        el.textContent = "Sem dados do mês anterior";
        return;
    }
    if (valor === 0) {
        el.textContent = `Estável vs. ${comparacao}`;
        return;
    }
    const subiu = valor > 0;
    const bom = inverter ? !subiu : subiu;
    const seta = document.createElement("span");
    seta.className = bom ? "positivo" : "negativo";
    seta.textContent = `${subiu ? "▲" : "▼"} ${Math.abs(valor).toLocaleString("pt-BR")}%`;
    el.append(seta, ` vs. ${comparacao}`);
}

// ---------------- abas ----------------

const TITULOS = { visao: "Visão geral", transacoes: "Transações", orcamentos: "Orçamentos", conexoes: "Bancos conectados" };

function abrirAba(aba) {
    estado.aba = aba;
    document.querySelectorAll(".menu-item").forEach((b) => b.classList.toggle("ativo", b.dataset.aba === aba));
    document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== `aba-${aba}`));
    $("#titulo-aba").textContent = TITULOS[aba];
    if (aba === "transacoes") carregarTransacoes();
    if (aba === "conexoes") carregarConexoes();
    if (aba === "orcamentos") renderOrcamentos();
}

// ---------------- visão geral ----------------

async function carregarResumo() {
    const url = estado.mes ? `/api/resumo?mes=${estado.mes}` : "/api/resumo";
    const r = await api(url);
    estado.resumo = r;
    estado.mes = r.mes;
    $("#mes").value = r.mes;
    renderResumo(r);
    if (estado.aba === "orcamentos") renderOrcamentos();
}

function renderResumo(r) {
    const k = r.indicadores;

    const saldo = $("#kpi-saldo");
    saldo.textContent = formatarMoeda(k.saldo_mes);
    saldo.classList.toggle("negativo", k.saldo_mes < 0);
    $("#kpi-saldo-total").textContent = `Saldo acumulado: ${formatarMoeda(k.saldo_total)}`;

    $("#kpi-receitas").textContent = formatarMoeda(k.receitas);
    $("#kpi-despesas").textContent = formatarMoeda(k.despesas);
    variacaoHTML($("#kpi-var-receitas"), k.variacao_receitas, false, k.comparacao);
    variacaoHTML($("#kpi-var-despesas"), k.variacao_despesas, true, k.comparacao);

    const taxa = k.taxa_poupanca;
    $("#kpi-poupanca").textContent = taxa === null ? "—" : `${taxa.toLocaleString("pt-BR")}%`;
    $("#kpi-poupanca").className = taxa !== null && taxa < 0 ? "negativo" : "";
    $("#barra-poupanca").style.width = `${Math.max(0, Math.min(100, taxa || 0))}%`;

    $("#kpi-media").textContent = formatarMoeda(k.media_diaria);
    $("#kpi-projecao").textContent = formatarMoeda(k.projecao_mes);
    $("#rotulo-projecao").textContent = k.mes_corrente ? "Projeção do mês" : "Gasto total do mês";

    renderInsights(r.insights);
    renderEvolucao(r.serie);
    renderCategorias(r.categorias, k.despesas);
    renderMaiores(r.maiores_despesas);
}

function renderInsights(lista) {
    const ul = $("#insights");
    ul.innerHTML = "";
    const icones = { positivo: "✅", alerta: "⚠️", info: "💡" };
    lista.forEach((i) => {
        const li = document.createElement("li");
        li.className = `${i.tipo}-i`;
        const icone = document.createElement("span");
        icone.className = "icone-i";
        icone.textContent = icones[i.tipo] || "💡";
        const texto = document.createElement("span");
        texto.textContent = i.texto;
        li.append(icone, texto);
        ul.append(li);
    });
}

function destruir(nome) {
    if (estado.graficos[nome]) {
        estado.graficos[nome].destroy();
        delete estado.graficos[nome];
    }
}

function renderEvolucao(serie) {
    if (!window.Chart) return;
    destruir("evolucao");
    const ctx = $("#grafico-evolucao");
    const verde = ctx.getContext("2d").createLinearGradient(0, 0, 0, 300);
    verde.addColorStop(0, "rgba(16,185,129,0.95)");
    verde.addColorStop(1, "rgba(16,185,129,0.35)");

    estado.graficos.evolucao = new Chart(ctx, {
        data: {
            labels: serie.map((s) => nomeMes(s.mes, true)),
            datasets: [
                { type: "bar", label: "Receitas", data: serie.map((s) => s.receitas), backgroundColor: verde, borderRadius: 6, maxBarThickness: 22 },
                { type: "bar", label: "Despesas", data: serie.map((s) => s.despesas), backgroundColor: "rgba(244,63,94,0.75)", borderRadius: 6, maxBarThickness: 22 },
                {
                    type: "line", label: "Saldo", data: serie.map((s) => s.saldo), borderColor: "#38bdf8",
                    backgroundColor: "#38bdf8", tension: 0.35, pointRadius: 3, borderWidth: 2,
                },
            ],
        },
        options: {
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "top", align: "end", labels: { usePointStyle: true, boxWidth: 8 } },
                tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${formatarMoeda(c.parsed.y)}` } },
            },
            scales: {
                x: { grid: { display: false } },
                y: { ticks: { callback: (v) => `R$ ${(v / 1000).toLocaleString("pt-BR")} mil` } },
            },
        },
    });
}

function renderCategorias(categorias, totalDespesas) {
    $("#sub-categorias").textContent = `Total: ${formatarMoeda(totalDespesas)}`;
    const ul = $("#lista-categorias");
    ul.innerHTML = "";
    categorias.forEach((c) => {
        const li = document.createElement("li");
        const ponto = document.createElement("span");
        ponto.className = "ponto";
        ponto.style.background = corCategoria(c.categoria);
        const nome = document.createElement("span");
        nome.textContent = `${c.categoria} · ${c.percentual.toLocaleString("pt-BR")}%`;
        const valor = document.createElement("span");
        valor.className = "valor-cat";
        valor.textContent = formatarMoeda(c.total);
        const variacao = document.createElement("span");
        variacao.className = "var-cat";
        if (c.variacao !== null) {
            variacao.textContent = `${c.variacao > 0 ? "▲" : "▼"} ${Math.abs(c.variacao).toLocaleString("pt-BR")}%`;
            variacao.classList.add(c.variacao > 0 ? "negativo" : "positivo");
        }
        li.append(ponto, nome, valor, variacao);
        ul.append(li);
    });
    if (!categorias.length) ul.innerHTML = '<li class="vazio">Sem despesas neste mês.</li>';

    if (!window.Chart) return;
    destruir("categorias");
    estado.graficos.categorias = new Chart($("#grafico-categorias"), {
        type: "doughnut",
        data: {
            labels: categorias.map((c) => c.categoria),
            datasets: [{
                data: categorias.map((c) => c.total),
                backgroundColor: categorias.map((c) => corCategoria(c.categoria)),
                borderColor: "#0e1519",
                borderWidth: 3,
                hoverOffset: 8,
            }],
        },
        options: {
            maintainAspectRatio: false,
            cutout: "68%",
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (c) => ` ${c.label}: ${formatarMoeda(c.parsed)}` } },
            },
        },
    });
}

function renderMaiores(lista) {
    const ol = $("#maiores");
    ol.innerHTML = "";
    lista.forEach((t) => {
        const li = document.createElement("li");
        const info = document.createElement("div");
        const nome = document.createElement("strong");
        nome.textContent = t.descricao;
        const sub = document.createElement("small");
        sub.textContent = `${t.categoria} · ${formatarData(t.data)}`;
        info.append(nome, sub);
        const valor = document.createElement("span");
        valor.className = "valor";
        valor.textContent = formatarMoeda(t.valor);
        li.append(info, valor);
        ol.append(li);
    });
    if (!lista.length) ol.innerHTML = '<li class="vazio" style="display:block">Sem despesas neste mês.</li>';
}

// ---------------- transações ----------------

function parametrosFiltro() {
    const dados = new FormData($("#filtros"));
    const params = new URLSearchParams();
    for (const [chave, valor] of dados.entries()) if (valor) params.set(chave, valor);
    return params;
}

async function carregarTransacoes() {
    const tabela = $("#tabela-transacoes");
    tabela.classList.add("carregando");
    try {
        const lista = await api(`/api/transacoes?${parametrosFiltro()}`);
        renderTabela(lista);
    } catch (e) {
        avisar(e.message, "erro");
    } finally {
        tabela.classList.remove("carregando");
    }
}

const ROTULO_ORIGEM = { manual: "Manual", banco: "Banco", exemplo: "Exemplo" };

function renderTabela(lista) {
    const corpo = $("#tabela-transacoes");
    corpo.innerHTML = "";
    $("#sem-transacoes").hidden = lista.length > 0;
    $("#contagem-transacoes").textContent = `${lista.length} transaç${lista.length === 1 ? "ão" : "ões"}`;

    lista.forEach((t) => {
        const tr = document.createElement("tr");

        const data = document.createElement("td");
        data.textContent = formatarData(t.data);

        const desc = document.createElement("td");
        desc.className = "descricao";
        desc.textContent = t.descricao;

        const cat = document.createElement("td");
        const etiquetaCat = document.createElement("span");
        etiquetaCat.className = "etiqueta";
        etiquetaCat.style.boxShadow = `inset 3px 0 0 ${corCategoria(t.categoria)}`;
        etiquetaCat.textContent = t.categoria || "Outros";
        cat.append(etiquetaCat);

        const origem = document.createElement("td");
        const etiquetaOrigem = document.createElement("span");
        etiquetaOrigem.className = `etiqueta ${t.origem}`;
        etiquetaOrigem.textContent = ROTULO_ORIGEM[t.origem] || t.origem;
        if (t.conta) etiquetaOrigem.title = t.conta;
        origem.append(etiquetaOrigem);

        const valor = document.createElement("td");
        valor.className = `direita ${t.tipo === "receita" ? "positivo" : "negativo"}`;
        valor.textContent = `${t.tipo === "receita" ? "+" : "−"} ${formatarMoeda(t.valor)}`;

        const acoes = document.createElement("td");
        const caixa = document.createElement("div");
        caixa.className = "acoes-tabela";
        const editar = document.createElement("button");
        editar.className = "icone-botao";
        editar.title = "Editar";
        editar.setAttribute("aria-label", `Editar ${t.descricao}`);
        editar.textContent = "✎";
        editar.addEventListener("click", () => abrirModal(t));
        const excluir = document.createElement("button");
        excluir.className = "icone-botao perigo";
        excluir.title = "Excluir";
        excluir.setAttribute("aria-label", `Excluir ${t.descricao}`);
        excluir.textContent = "✕";
        excluir.addEventListener("click", () => excluirTransacao(t));
        caixa.append(editar, excluir);
        acoes.append(caixa);

        tr.append(data, desc, cat, origem, valor, acoes);
        corpo.append(tr);
    });
}

async function excluirTransacao(t) {
    if (!confirm(`Excluir "${t.descricao}"?`)) return;
    try {
        await api(`/api/transacoes/${t.id}`, { method: "DELETE" });
        avisar("Transação excluída.");
        await Promise.all([carregarTransacoes(), carregarResumo()]);
    } catch (e) {
        avisar(e.message, "erro");
    }
}

// ---------------- modal ----------------

function abrirModal(t = null) {
    estado.editandoId = t ? t.id : null;
    $("#titulo-modal").textContent = t ? "Editar transação" : "Nova transação";
    $("#descricao").value = t ? t.descricao : "";
    $("#valor").value = t ? t.valor : "";
    $("#data").value = t ? t.data : hojeISO();
    $("#categoria").value = t ? t.categoria || "Outros" : "Alimentação";
    document.querySelector(`input[name="tipo"][value="${t ? t.tipo : "despesa"}"]`).checked = true;
    $("#mensagem-modal").textContent = "";
    $("#modal").showModal();
    $("#descricao").focus();
}

async function salvarTransacao(evento) {
    evento.preventDefault();
    const corpo = {
        descricao: $("#descricao").value,
        valor: $("#valor").value,
        data: $("#data").value,
        categoria: $("#categoria").value,
        tipo: document.querySelector('input[name="tipo"]:checked').value,
    };
    const botao = evento.target.querySelector("button[type=submit]");
    botao.disabled = true;
    try {
        if (estado.editandoId) {
            await api(`/api/transacoes/${estado.editandoId}`, { method: "PUT", body: corpo });
        } else {
            await api("/api/transacoes", { method: "POST", body: corpo });
        }
        $("#modal").close();
        avisar(estado.editandoId ? "Transação atualizada." : "Transação adicionada.");
        await carregarResumo();
        if (estado.aba === "transacoes") carregarTransacoes();
    } catch (e) {
        $("#mensagem-modal").textContent = e.message;
    } finally {
        botao.disabled = false;
    }
}

// ---------------- orçamentos ----------------

function renderOrcamentos() {
    if (!estado.resumo) return;
    const ul = $("#orcamentos");
    ul.innerHTML = "";
    const definidos = Object.fromEntries(estado.resumo.orcamentos.map((o) => [o.categoria, o]));
    const gastos = Object.fromEntries(estado.resumo.categorias.map((c) => [c.categoria, c.total]));
    const categoriasDespesa = (window.CATEGORIAS || []).filter((c) => c !== "Salário");

    categoriasDespesa.forEach((categoria) => {
        const o = definidos[categoria];
        const gasto = gastos[categoria] || 0;
        const limite = o ? o.limite : 0;
        const pct = limite ? (gasto / limite) * 100 : 0;

        const li = document.createElement("li");
        if (pct >= 100) li.classList.add("estourado");

        const topo = document.createElement("div");
        topo.className = "orc-topo";
        const nome = document.createElement("strong");
        nome.textContent = categoria;
        const caixaLimite = document.createElement("label");
        caixaLimite.className = "orc-limite";
        caixaLimite.textContent = "Limite R$";
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.step = "10";
        input.placeholder = "—";
        input.value = limite || "";
        input.setAttribute("aria-label", `Limite mensal para ${categoria}`);
        input.addEventListener("change", () => salvarOrcamento(categoria, input.value));
        caixaLimite.append(input);
        topo.append(nome, caixaLimite);

        const barra = document.createElement("div");
        barra.className = `barra ${pct >= 100 ? "alta" : pct >= 80 ? "media" : ""}`;
        const preenchimento = document.createElement("span");
        barra.append(preenchimento);
        requestAnimationFrame(() => (preenchimento.style.width = `${Math.min(100, pct)}%`));

        const info = document.createElement("div");
        info.className = "orc-info";
        const gastoTxt = document.createElement("span");
        gastoTxt.textContent = `Gasto: ${formatarMoeda(gasto)}`;
        const pctTxt = document.createElement("span");
        pctTxt.textContent = limite ? `${pct.toFixed(0)}% usado` : "Sem limite";
        info.append(gastoTxt, pctTxt);

        li.append(topo, barra, info);
        ul.append(li);
    });
}

async function salvarOrcamento(categoria, valor) {
    try {
        await api("/api/orcamentos", { method: "PUT", body: { categoria, limite: valor || 0 } });
        avisar(Number(valor) > 0 ? `Orçamento de ${categoria} salvo.` : `Orçamento de ${categoria} removido.`);
        await carregarResumo();
        renderOrcamentos();
    } catch (e) {
        avisar(e.message, "erro");
    }
}

// ---------------- bancos (Pluggy) ----------------

async function carregarConexoes() {
    try {
        const s = await api("/api/pluggy/status");
        $("#aviso-pluggy").hidden = s.configurada;
        $("#conectar-banco").disabled = !s.configurada;
        $("#sincronizar").disabled = !s.configurada || !s.conexoes.length;
        $("#sem-conexoes").hidden = s.conexoes.length > 0;

        const ul = $("#lista-conexoes");
        ul.innerHTML = "";
        s.conexoes.forEach((c) => {
            const li = document.createElement("li");
            const icone = document.createElement("span");
            icone.className = "banco-icone";
            icone.textContent = (c.banco || "B").slice(0, 1).toUpperCase();
            const info = document.createElement("div");
            const nome = document.createElement("strong");
            nome.textContent = c.banco || "Banco";
            const sub = document.createElement("small");
            sub.textContent = c.ultima_sincronizacao ? `Última sincronização: ${c.ultima_sincronizacao}` : "Ainda não sincronizado";
            info.append(nome, sub);
            const remover = document.createElement("button");
            remover.className = "icone-botao perigo";
            remover.textContent = "Desconectar";
            remover.addEventListener("click", async () => {
                if (!confirm(`Desconectar ${c.banco}? As transações já importadas continuam salvas.`)) return;
                await api(`/api/pluggy/conexoes/${c.id}`, { method: "DELETE" });
                carregarConexoes();
            });
            li.append(icone, info, remover);
            ul.append(li);
        });
    } catch (e) {
        avisar(e.message, "erro");
    }
}

function carregarScriptPluggy() {
    if (window.PluggyConnect) return Promise.resolve();
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdn.pluggy.ai/pluggy-connect/v2.8.2/pluggy-connect.js";
        s.onload = resolve;
        s.onerror = () => reject(new Error("Não foi possível carregar o widget da Pluggy."));
        document.head.append(s);
    });
}

async function conectarBanco() {
    const botao = $("#conectar-banco");
    botao.disabled = true;
    try {
        const [{ accessToken }] = await Promise.all([api("/api/pluggy/token", { method: "POST" }), carregarScriptPluggy()]);
        const widget = new PluggyConnect({
            connectToken: accessToken,
            includeSandbox: true, // mostra o "Pluggy Bank" para testes
            onSuccess: async ({ item }) => {
                avisar("Banco conectado! Importando histórico, isso pode levar alguns segundos...");
                try {
                    const r = await api("/api/pluggy/conexoes", { method: "POST", body: { itemId: item.id } });
                    avisar(`${r.banco}: ${r.novas} transações importadas.`);
                    await Promise.all([carregarConexoes(), carregarResumo()]);
                } catch (e) {
                    avisar(e.message, "erro");
                }
            },
            onError: (erro) => avisar(erro?.message || "Erro ao conectar o banco.", "erro"),
        });
        widget.init();
    } catch (e) {
        avisar(e.message, "erro");
    } finally {
        botao.disabled = false;
    }
}

async function sincronizar() {
    const botao = $("#sincronizar");
    botao.disabled = true;
    botao.textContent = "Sincronizando...";
    try {
        const r = await api("/api/pluggy/sincronizar", { method: "POST" });
        avisar(`Sincronização concluída: ${r.novas} transações novas.`);
        await Promise.all([carregarConexoes(), carregarResumo()]);
    } catch (e) {
        avisar(e.message, "erro");
    } finally {
        botao.disabled = false;
        botao.textContent = "Sincronizar agora";
    }
}

// ---------------- dados de exemplo ----------------

async function dadosExemplo(carregar) {
    try {
        await api("/api/exemplo", { method: carregar ? "POST" : "DELETE" });
        avisar(carregar ? "Dados de exemplo carregados." : "Dados de exemplo removidos.");
        estado.mes = null;
        await carregarResumo();
        if (carregar) abrirAba("visao");
    } catch (e) {
        avisar(e.message, "erro");
    }
}

// ---------------- início ----------------

function configurarGraficos() {
    if (!window.Chart) return;
    Chart.defaults.color = "#8ba49a";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.borderColor = "rgba(52, 211, 153, 0.08)";
}

function iniciar() {
    configurarGraficos();

    document.querySelectorAll(".menu-item").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));
    $("#nova-transacao").addEventListener("click", () => abrirModal());
    $("#fechar-modal").addEventListener("click", () => $("#modal").close());
    $("#form-transacao").addEventListener("submit", salvarTransacao);

    $("#mes").addEventListener("change", (e) => {
        if (!e.target.value) return;
        estado.mes = e.target.value;
        carregarResumo().catch((err) => avisar(err.message, "erro"));
    });

    let espera;
    $("#filtros").addEventListener("input", () => {
        clearTimeout(espera);
        espera = setTimeout(carregarTransacoes, 300);
    });
    $("#exportar").addEventListener("click", () => {
        window.location.href = `/api/exportar.csv?${parametrosFiltro()}`;
    });

    $("#conectar-banco").addEventListener("click", conectarBanco);
    $("#sincronizar").addEventListener("click", sincronizar);
    $("#carregar-exemplo").addEventListener("click", () => dadosExemplo(true));
    $("#apagar-exemplo").addEventListener("click", () => dadosExemplo(false));

    carregarResumo().catch((e) => avisar(e.message, "erro"));
}

iniciar();
