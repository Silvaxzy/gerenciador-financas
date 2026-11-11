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
    editando: null,
    graficos: {},
    cartoes: [],
    fatura: { cartaoId: null, mes: null, status: null },
    editandoCartaoId: null,
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

const TITULOS = {
    visao: "Visão geral", transacoes: "Transações", orcamentos: "Orçamentos",
    cartoes: "Cartões de crédito", conexoes: "Bancos conectados",
};

function abrirAba(aba) {
    estado.aba = aba;
    document.querySelectorAll(".menu-item").forEach((b) => b.classList.toggle("ativo", b.dataset.aba === aba));
    document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== `aba-${aba}`));
    $("#titulo-aba").textContent = TITULOS[aba];
    if (aba === "transacoes") carregarTransacoes();
    if (aba === "conexoes") carregarConexoes();
    if (aba === "orcamentos") renderOrcamentos();
    if (aba === "cartoes") carregarCartoes().catch((e) => avisar(e.message, "erro"));
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

    // card principal: quanto há na conta (hoje, ou no fim do mês escolhido)
    const saldo = $("#kpi-saldo");
    saldo.textContent = formatarMoeda(k.saldo_total);
    saldo.classList.toggle("negativo", k.saldo_total < 0);
    $("#kpi-saldo-titulo").textContent = k.mes_corrente ? "Saldo em conta" : "Saldo em conta no fim do mês";
    const sinal = k.saldo_mes > 0 ? "+" : "";
    $("#kpi-saldo-total").textContent = `Resultado do mês: ${sinal}${formatarMoeda(k.saldo_mes)}`
        + (k.cartao_a_pagar > 0 ? ` · Cartão a pagar: ${formatarMoeda(k.cartao_a_pagar)}` : "");

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
                y: {
                    ticks: {
                        callback: (v) => Math.abs(v) >= 1000
                            ? `R$ ${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`
                            : `R$ ${v.toLocaleString("pt-BR")}`,
                    },
                },
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

        const pagamento = document.createElement("td");
        const etiquetaPag = document.createElement("span");
        if (t.forma_pagamento === "credito" && t.cartao_nome) {
            etiquetaPag.className = "etiqueta credito";
            etiquetaPag.textContent = `💳 ${t.cartao_nome}`;
        } else {
            etiquetaPag.className = "etiqueta conta";
            etiquetaPag.textContent = t.tipo === "receita" ? "Conta" : "Conta / Pix";
        }
        pagamento.append(etiquetaPag);

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

        tr.append(data, desc, cat, pagamento, origem, valor, acoes);
        corpo.append(tr);
    });
}

async function excluirTransacao(t) {
    const parcelada = t.total_parcelas > 1;
    const pergunta = parcelada
        ? `"${t.descricao}" é uma compra parcelada. Excluir todas as ${t.total_parcelas} parcelas?`
        : `Excluir "${t.descricao}"?`;
    if (!confirm(pergunta)) return;
    try {
        const r = await api(`/api/transacoes/${t.id}${parcelada ? "?todas=1" : ""}`, { method: "DELETE" });
        avisar(parcelada ? `${r.excluidas} parcelas excluídas.` : "Transação excluída.");
        await Promise.all([carregarTransacoes(), carregarResumo(), carregarCartoes()]);
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
    estado.editando = t;
    $("#parcelas").innerHTML = "";
    preencherSelectCartoes();
    const credito = t ? t.forma_pagamento === "credito" && t.cartao_id : false;
    document.querySelector(`input[name="forma"][value="${credito ? "credito" : "conta"}"]`).checked = true;
    if (credito) $("#cartao-transacao").value = t.cartao_id;
    atualizarPagamento();
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
        forma_pagamento: document.querySelector('input[name="forma"]:checked').value,
        cartao_id: $("#cartao-transacao").value || null,
        parcelas: $("#parcelas").value || 1,
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
        const n = Number(corpo.parcelas);
        avisar(estado.editandoId ? "Transação atualizada."
            : corpo.forma_pagamento === "credito" && n > 1 ? `Compra lançada em ${n} parcelas.` : "Transação adicionada.");
        await Promise.all([carregarResumo(), carregarCartoes()]);
        if (estado.aba === "transacoes") carregarTransacoes();
    } catch (e) {
        $("#mensagem-modal").textContent = e.message;
    } finally {
        botao.disabled = false;
    }
}

// ---------------- forma de pagamento (modal de transação) ----------------

function somarMeses(ano, mes, n) {
    const total = ano * 12 + (mes - 1) + n;
    return [Math.floor(total / 12), (total % 12) + 1];
}

function mesDaFatura(iso, fechamento, vencimento) {
    // mesma regra do back-end (cartoes.py)
    let [ano, mes, dia] = iso.split("-").map(Number);
    if (dia >= fechamento) [ano, mes] = somarMeses(ano, mes, 1);
    if (vencimento <= fechamento) [ano, mes] = somarMeses(ano, mes, 1);
    return `${ano}-${String(mes).padStart(2, "0")}`;
}

function preencherSelectCartoes() {
    const sel = $("#cartao-transacao");
    const atual = sel.value;
    sel.innerHTML = "";
    estado.cartoes.forEach((c) => {
        const op = document.createElement("option");
        op.value = c.id;
        op.textContent = c.nome;
        sel.append(op);
    });
    if (atual && estado.cartoes.some((c) => String(c.id) === atual)) sel.value = atual;
}

function atualizarParcelas() {
    const sel = $("#parcelas");
    const valor = Number($("#valor").value) || 0;
    const t = estado.editando;
    if (t && t.total_parcelas > 1) {
        // ao editar, muda só esta parcela
        sel.innerHTML = `<option value="1">Parcela ${t.parcela} de ${t.total_parcelas}</option>`;
        sel.disabled = true;
        return;
    }
    if (t) {
        sel.innerHTML = '<option value="1">À vista</option>';
        sel.disabled = true;
        return;
    }
    const escolhido = sel.value || "1";
    sel.disabled = false;
    sel.innerHTML = "";
    for (let n = 1; n <= 24; n++) {
        const op = document.createElement("option");
        op.value = n;
        op.textContent = n === 1 ? `À vista${valor ? ` · ${formatarMoeda(valor)}` : ""}` : `${n}x${valor ? ` de ${formatarMoeda(valor / n)}` : ""}`;
        sel.append(op);
    }
    sel.value = escolhido;
}

function atualizarPagamento() {
    const despesa = document.querySelector('input[name="tipo"]:checked').value === "despesa";
    $("#bloco-pagamento").hidden = !despesa;
    const credito = despesa && document.querySelector('input[name="forma"]:checked').value === "credito";
    $("#bloco-cartao").hidden = !credito;
    if (!credito) return;

    atualizarParcelas();
    const dica = $("#dica-cartao");
    if (!estado.cartoes.length) {
        dica.innerHTML = 'Você ainda não tem cartão cadastrado. <a href="#" id="link-novo-cartao">Cadastrar agora</a>';
        $("#link-novo-cartao").addEventListener("click", (e) => {
            e.preventDefault();
            $("#modal").close();
            abrirAba("cartoes");
            abrirModalCartao();
        });
        return;
    }
    const cartao = estado.cartoes.find((c) => String(c.id) === $("#cartao-transacao").value);
    const data = $("#data").value;
    if (!cartao || !data) {
        dica.textContent = "";
        return;
    }
    const mes = mesDaFatura(data, cartao.dia_fechamento, cartao.dia_vencimento);
    const n = Number($("#parcelas").value) || 1;
    dica.textContent = n > 1 && !estado.editando
        ? `1ª parcela na fatura de ${nomeMes(mes)}, as outras nos ${n - 1} meses seguintes.`
        : `Entra na fatura de ${nomeMes(mes)} (vence dia ${cartao.dia_vencimento}).`;
}

// ---------------- cartões de crédito ----------------

const STATUS_FATURA = {
    aberta: "Aberta", fechada: "Fechada · a pagar", vencida: "Vencida", paga: "Paga", sem_compras: "Sem compras",
};

async function carregarCartoes() {
    estado.cartoes = await api("/api/cartoes");
    // filtro da aba Transações
    const filtro = $("#filtro-pagamento");
    const escolhido = filtro.value;
    filtro.querySelectorAll("option[data-cartao]").forEach((o) => o.remove());
    estado.cartoes.forEach((c) => {
        const op = document.createElement("option");
        op.value = c.id;
        op.dataset.cartao = "1";
        op.textContent = `💳 ${c.nome}`;
        filtro.append(op);
    });
    filtro.value = escolhido;
    preencherSelectCartoes();
    if (estado.aba === "cartoes") renderCartoes();
}

function renderCartoes() {
    const lista = $("#cartoes-lista");
    lista.innerHTML = "";
    $("#sem-cartoes").hidden = estado.cartoes.length > 0;
    $("#painel-fatura").hidden = !estado.cartoes.length;
    if (!estado.cartoes.length) return;

    if (!estado.cartoes.some((c) => c.id === estado.fatura.cartaoId)) {
        estado.fatura = { cartaoId: estado.cartoes[0].id, mes: null, status: null };
    }

    estado.cartoes.forEach((c) => {
        const item = document.createElement("article");
        item.className = `cc-item ${c.id === estado.fatura.cartaoId ? "ativo" : ""}`;

        const plastico = document.createElement("button");
        plastico.type = "button";
        plastico.className = `cc cc-${c.cor}`;
        plastico.setAttribute("aria-label", `Ver fatura do ${c.nome}`);
        const chip = document.createElement("span");
        chip.className = "cc-chip";
        const nome = document.createElement("strong");
        nome.className = "cc-nome";
        nome.textContent = c.nome;
        const rodape = document.createElement("div");
        rodape.className = "cc-rodape";
        rodape.innerHTML = `<span>Fecha dia ${c.dia_fechamento}</span><span>Vence dia ${c.dia_vencimento}</span>`;
        plastico.append(chip, nome, rodape);
        plastico.addEventListener("click", () => {
            estado.fatura = { cartaoId: c.id, mes: null, status: null };
            renderCartoes();
        });

        const editar = document.createElement("button");
        editar.type = "button";
        editar.className = "cc-editar";
        editar.textContent = "✎";
        editar.title = "Editar cartão";
        editar.setAttribute("aria-label", `Editar ${c.nome}`);
        editar.addEventListener("click", (e) => {
            e.stopPropagation();
            abrirModalCartao(c);
        });
        plastico.append(editar);

        const info = document.createElement("div");
        info.className = "cc-info";
        const fatura = document.createElement("div");
        fatura.className = "cc-linha";
        fatura.innerHTML = `<span>Fatura atual (${STATUS_FATURA[c.fatura_atual.status].toLowerCase()})</span>`;
        const totalFatura = document.createElement("strong");
        totalFatura.textContent = formatarMoeda(c.fatura_atual.total);
        fatura.append(totalFatura);

        const barra = document.createElement("div");
        const pct = c.percentual_usado;
        barra.className = `barra ${pct >= 90 ? "alta" : pct >= 70 ? "media" : ""}`;
        const preenchimento = document.createElement("span");
        barra.append(preenchimento);
        requestAnimationFrame(() => (preenchimento.style.width = `${Math.min(100, pct)}%`));

        const limite = document.createElement("div");
        limite.className = "cc-linha";
        limite.innerHTML = `<span>Usado ${formatarMoeda(c.usado)}</span><span>Disponível ${formatarMoeda(c.disponivel)}</span>`;

        info.append(fatura, barra, limite);
        if (c.fatura_a_pagar) {
            const f = c.fatura_a_pagar;
            const alerta = document.createElement("div");
            alerta.className = `cc-alerta ${f.status === "vencida" ? "vencida" : ""}`;
            alerta.textContent = f.status === "vencida"
                ? `Fatura de ${nomeMes(f.mes)} vencida: ${formatarMoeda(f.total)}`
                : `Fatura de ${nomeMes(f.mes)} a pagar: ${formatarMoeda(f.total)} até ${formatarData(f.vencimento)}`;
            info.append(alerta);
        }

        item.append(plastico, info);
        lista.append(item);
    });

    carregarFatura();
}

async function carregarFatura() {
    const { cartaoId, mes } = estado.fatura;
    const cartao = estado.cartoes.find((c) => c.id === cartaoId);
    if (!cartao) return;
    try {
        const f = await api(`/api/cartoes/${cartaoId}/fatura${mes ? `?mes=${mes}` : ""}`);
        estado.fatura.mes = f.mes;
        estado.fatura.status = f.status;
        $("#fatura-titulo").textContent = `Fatura · ${cartao.nome}`;
        $("#fatura-mes").textContent = nomeMes(f.mes);
        $("#fatura-periodo").textContent = `Compras de ${formatarData(f.inicio)} até a véspera de ${formatarData(f.fechamento)} (fechamento)`;
        $("#fatura-total").textContent = formatarMoeda(f.total);
        $("#fatura-vencimento").textContent = formatarData(f.vencimento);
        const status = $("#fatura-status");
        status.className = `status-fatura ${f.status}`;
        status.textContent = STATUS_FATURA[f.status];
        const pagar = $("#fatura-pagar");
        pagar.textContent = f.status === "paga" ? "Desmarcar pagamento" : "Marcar como paga";
        pagar.hidden = f.total === 0 && f.status !== "paga";

        const ul = $("#fatura-compras");
        ul.innerHTML = "";
        $("#fatura-vazia").hidden = f.compras.length > 0;
        f.compras.forEach((c) => {
            const li = document.createElement("li");
            const data = document.createElement("span");
            data.className = "data-compra";
            data.textContent = formatarData(c.data).slice(0, 5);
            const info = document.createElement("div");
            const nome = document.createElement("strong");
            nome.textContent = c.descricao;
            const sub = document.createElement("small");
            sub.textContent = c.total_parcelas ? `${c.categoria} · parcela ${c.parcela} de ${c.total_parcelas}` : c.categoria;
            info.append(nome, sub);
            const valor = document.createElement("span");
            valor.className = "valor";
            valor.textContent = formatarMoeda(c.valor);
            li.append(data, info, valor);
            ul.append(li);
        });
    } catch (e) {
        avisar(e.message, "erro");
    }
}

function navegarFatura(passo) {
    if (!estado.fatura.mes) return;
    const [ano, mes] = estado.fatura.mes.split("-").map(Number);
    const [a, m] = somarMeses(ano, mes, passo);
    estado.fatura.mes = `${a}-${String(m).padStart(2, "0")}`;
    carregarFatura();
}

async function alternarPagamentoFatura() {
    const { cartaoId, mes, status } = estado.fatura;
    try {
        await api(`/api/cartoes/${cartaoId}/fatura/${mes}/pagamento`, { method: status === "paga" ? "DELETE" : "PUT" });
        avisar(status === "paga" ? "Pagamento desmarcado." : "Fatura marcada como paga. O limite foi liberado.");
        await Promise.all([carregarCartoes(), carregarResumo()]);
    } catch (e) {
        avisar(e.message, "erro");
    }
}

function atualizarPreviaCartao() {
    const cor = document.querySelector('input[name="cor"]:checked').value;
    $("#cc-previa").className = `cc cc-previa cc-${cor}`;
    $("#cc-previa-nome").textContent = $("#cartao-nome").value || "Meu cartão";
    $("#cc-previa-limite").textContent = `Limite ${formatarMoeda($("#cartao-limite").value)}`;
}

function abrirModalCartao(c = null) {
    estado.editandoCartaoId = c ? c.id : null;
    $("#titulo-modal-cartao").textContent = c ? "Editar cartão" : "Novo cartão";
    $("#cartao-nome").value = c ? c.nome : "";
    $("#cartao-limite").value = c ? c.limite : "";
    $("#cartao-fechamento").value = c ? c.dia_fechamento : "";
    $("#cartao-vencimento").value = c ? c.dia_vencimento : "";
    const cor = document.querySelector(`input[name="cor"][value="${c ? c.cor : "roxo"}"]`) || document.querySelector('input[name="cor"]');
    cor.checked = true;
    $("#excluir-cartao").hidden = !c;
    $("#mensagem-cartao").textContent = "";
    atualizarPreviaCartao();
    $("#modal-cartao").showModal();
    $("#cartao-nome").focus();
}

async function salvarCartao(evento) {
    evento.preventDefault();
    const corpo = {
        nome: $("#cartao-nome").value,
        limite: $("#cartao-limite").value,
        dia_fechamento: $("#cartao-fechamento").value,
        dia_vencimento: $("#cartao-vencimento").value,
        cor: document.querySelector('input[name="cor"]:checked').value,
    };
    const botao = evento.target.querySelector("button[type=submit]");
    botao.disabled = true;
    try {
        if (estado.editandoCartaoId) {
            await api(`/api/cartoes/${estado.editandoCartaoId}`, { method: "PUT", body: corpo });
        } else {
            const r = await api("/api/cartoes", { method: "POST", body: corpo });
            estado.fatura = { cartaoId: r.id, mes: null, status: null };
        }
        $("#modal-cartao").close();
        avisar(estado.editandoCartaoId ? "Cartão atualizado." : "Cartão cadastrado!");
        await carregarCartoes();
    } catch (e) {
        $("#mensagem-cartao").textContent = e.message;
    } finally {
        botao.disabled = false;
    }
}

async function excluirCartao() {
    const c = estado.cartoes.find((x) => x.id === estado.editandoCartaoId);
    if (!c || !confirm(`Excluir o cartão ${c.nome}? As compras continuam salvas como despesas, só deixam de ficar ligadas ao cartão.`)) return;
    try {
        await api(`/api/cartoes/${c.id}`, { method: "DELETE" });
        $("#modal-cartao").close();
        avisar("Cartão excluído.");
        await Promise.all([carregarCartoes(), carregarResumo()]);
    } catch (e) {
        $("#mensagem-cartao").textContent = e.message;
    }
}

// ---------------- saldo em conta ----------------

async function abrirModalSaldo() {
    $("#mensagem-saldo").textContent = "";
    $("#saldo-data").value = hojeISO();
    $("#saldo-valor").value = "";
    $("#saldo-calculado").textContent = "";
    $("#remover-ajuste").hidden = true;
    $("#modal-saldo").showModal();
    $("#saldo-valor").focus();
    try {
        const s = await api("/api/saldo");
        $("#saldo-calculado").innerHTML = "";
        const linha = document.createElement("span");
        linha.append("Pelo app, o saldo hoje é ");
        const valor = document.createElement("strong");
        valor.textContent = formatarMoeda(s.saldo_atual);
        linha.append(valor, ".");
        if (s.ajuste) linha.append(` Último ajuste: ${formatarMoeda(s.ajuste.valor)} em ${formatarData(s.ajuste.data)}.`);
        $("#saldo-calculado").append(linha);
        $("#remover-ajuste").hidden = !s.ajuste;
    } catch (e) {
        $("#mensagem-saldo").textContent = e.message;
    }
}

async function salvarSaldo(evento) {
    evento.preventDefault();
    const botao = evento.target.querySelector("button[type=submit]");
    botao.disabled = true;
    try {
        await api("/api/saldo", { method: "PUT", body: { valor: $("#saldo-valor").value, data: $("#saldo-data").value } });
        $("#modal-saldo").close();
        avisar("Saldo atualizado.");
        await carregarResumo();
    } catch (e) {
        $("#mensagem-saldo").textContent = e.message;
    } finally {
        botao.disabled = false;
    }
}

async function removerAjusteSaldo() {
    if (!confirm("Voltar a calcular o saldo só pelos lançamentos? Os ajustes informados serão apagados.")) return;
    try {
        await api("/api/saldo", { method: "DELETE" });
        $("#modal-saldo").close();
        avisar("Saldo voltou ao cálculo automático.");
        await carregarResumo();
    } catch (e) {
        $("#mensagem-saldo").textContent = e.message;
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
        await Promise.all([carregarResumo(), carregarCartoes()]);
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
    document.querySelectorAll('input[name="tipo"], input[name="forma"]').forEach((r) => r.addEventListener("change", atualizarPagamento));
    ["#cartao-transacao", "#data", "#parcelas"].forEach((s) => $(s).addEventListener("change", atualizarPagamento));
    $("#valor").addEventListener("input", () => {
        if (!$("#bloco-cartao").hidden) atualizarParcelas();
    });

    $("#ajustar-saldo").addEventListener("click", abrirModalSaldo);
    $("#fechar-modal-saldo").addEventListener("click", () => $("#modal-saldo").close());
    $("#form-saldo").addEventListener("submit", salvarSaldo);
    $("#remover-ajuste").addEventListener("click", removerAjusteSaldo);
    $("#novo-cartao").addEventListener("click", () => abrirModalCartao());
    $("#novo-cartao-vazio").addEventListener("click", () => abrirModalCartao());
    $("#fechar-modal-cartao").addEventListener("click", () => $("#modal-cartao").close());
    $("#form-cartao").addEventListener("submit", salvarCartao);
    $("#excluir-cartao").addEventListener("click", excluirCartao);
    ["#cartao-nome", "#cartao-limite"].forEach((s) => $(s).addEventListener("input", atualizarPreviaCartao));
    document.querySelectorAll('input[name="cor"]').forEach((r) => r.addEventListener("change", atualizarPreviaCartao));
    $("#fatura-anterior").addEventListener("click", () => navegarFatura(-1));
    $("#fatura-proxima").addEventListener("click", () => navegarFatura(1));
    $("#fatura-pagar").addEventListener("click", alternarPagamentoFatura);

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
    carregarCartoes().catch((e) => avisar(e.message, "erro"));
}

iniciar();
