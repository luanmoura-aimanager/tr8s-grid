// abas/grooves.mjs - Biblioteca + Chain numa aba so (reforma 2).
//
// Tres paineis: FONTES (biblioteca com filtro, ou a grade A1-H16 da
// maquina), SELECIONADO (preview + KIT/BPM + acoes) e a FILA de
// encadeamento em cards. Encadeaveis: grooves da biblioteca E patterns da
// maquina, na mesma fila (chain modo "misto").
//
// Honestidade em dois pontos que a tela repete:
// - groove ESCREVE na variacao aberta do pattern corrente da maquina; vindo
//   depois de uma entrada de pattern, altera aquele pattern. Desfazer volta.
// - "Auto BPM" escreve o TEMPO junto com o pattern, e FUNCIONA desde
//   17/08/2026: o endereco certo e o no do pattern (OFF_TEMPO_NO, quatro
//   nibbles), achado por sniff do TR-EDITOR. A versao de 16/08 escrevia no
//   espelho da performance, que a maquina aceita e ignora - por isso o toggle
//   parecia morto. O tempo e por PATTERN.
import { h, texto, attr } from "../nucleo/dom.mjs";
import { painel, campo, toggle } from "../comp/painel.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

const KITS = ["TR-808", "TR-909", "TR-707", "TR-727", "TR-606", "TR-626"];
// como o visor: banco 1-8 (numero!), pattern 1-16 -> "2-05". Letra e variacao.
const nomePat = (n) =>
  (n >> 4) + 1 + "-" + String((n % 16) + 1).padStart(2, "0");

let D_;
let sel = null; // {tipo:"groove", p} | {tipo:"pattern", n}
// A fila e um LOOP persistente (pedido de 16/08): sobrevive a recarregar a
// pagina, e cada card pode ser tirado do loop sem ser apagado (off:true).
let fila = []; // [{tipo, id?|alvo?, nome, reps, off?}]
try {
  fila = JSON.parse(localStorage.getItem("filaGrooves") || "[]");
} catch {
  fila = [];
}
let ultimo = {};
let armado = 0;

function salvarFila() {
  localStorage.setItem("filaGrooves", JSON.stringify(fila));
}

// elementos vivos
let tbodyBib, gradeMaq, elSel, elFilaCards, elFilaEstado, bArmar, bParar;
let inFiltro, inReps;
let autoKit = localStorage.getItem("autoKit") === "1";
let autoBpm = localStorage.getItem("autoBpm") === "1";

export default {
  id: "grooves",
  rotulo: "Grooves",

  montar(raiz, D) {
    D_ = D;

    // ── FONTES ───────────────────────────────────────────
    inFiltro = h("input", {
      type: "search",
      placeholder: "filtrar por nome ou estilo…",
      "aria-label": "filtrar biblioteca",
    });
    inFiltro.oninput = () => filtrar();

    tbodyBib = h("tbody");
    // agrupa por estilo DE VERDADE (nao pela ordem da lista): a expansao da
    // biblioteca poe patterns novos de estilos antigos no fim do arquivo
    const porEstilo = new Map();
    D.biblioteca.forEach((p) => {
      if (!porEstilo.has(p.estilo)) porEstilo.set(p.estilo, []);
      porEstilo.get(p.estilo).push(p);
    });
    for (const [estilo, ps] of porEstilo) {
      tbodyBib.append(
        h(
          "tr.grupo",
          { "data-estilo": estilo },
          h("td", { colspan: 2 }, estilo),
        ),
      );
      ps.forEach((p) => {
        const tr = h(
          "tr",
          { "data-nome": (p.nome + " " + p.estilo).toLowerCase() },
          h("td", {}, p.nome),
          h("td.mono", {}, p.bpm + " bpm"),
        );
        tr.onclick = () => {
          selecionar({ tipo: "groove", p });
          [...tbodyBib.children].forEach((x) =>
            attr(x, "aria-selected", x === tr ? "true" : "false"),
          );
        };
        tbodyBib.append(tr);
      });
    }

    // grade A1-H16 da maquina
    gradeMaq = h("div.grade-maquina", { hidden: true });
    for (let b = 0; b < 8; b++) {
      gradeMaq.append(h("span.rot-banco", {}, String(b + 1)));
      for (let i = 0; i < 16; i++) {
        const n = b * 16 + i;
        const bt = h(
          "button.bt.bt-peq",
          { type: "button", "data-n": n, title: nomePat(n) },
          String(i + 1),
        );
        bt.onclick = () => {
          selecionar({ tipo: "pattern", n });
          [...gradeMaq.querySelectorAll(".bt")].forEach((x) =>
            attr(x, "aria-selected", x === bt ? "true" : "false"),
          );
        };
        gradeMaq.append(bt);
      }
    }

    const cxBib = h(
      "div",
      {},
      inFiltro,
      h("div.lista", {}, h("table", {}, tbodyBib)),
    );
    const subBib = h(
      "button.bt.bt-peq",
      { type: "button", "aria-pressed": "true" },
      "Biblioteca",
    );
    const subMaq = h(
      "button.bt.bt-peq",
      { type: "button", "aria-pressed": "false" },
      "Máquina",
    );
    subBib.onclick = () => {
      attr(subBib, "aria-pressed", "true");
      attr(subMaq, "aria-pressed", "false");
      cxBib.hidden = false;
      gradeMaq.hidden = true;
    };
    subMaq.onclick = () => {
      attr(subBib, "aria-pressed", "false");
      attr(subMaq, "aria-pressed", "true");
      cxBib.hidden = true;
      gradeMaq.hidden = false;
    };

    const pnFontes = painel(
      "Fontes",
      { dir: [subBib, subMaq] },
      cxBib,
      gradeMaq,
      h(
        "p.dica",
        {},
        "a grade Máquina troca/encadeia os patterns A1–H16 que já vivem " +
          "na TR-8S — o conteúdo deles não é lido, então não há preview.",
      ),
    );

    // ── SELECIONADO ──────────────────────────────────────
    elSel = h(
      "div.corpo-sel",
      {},
      h("p.vazio", {}, "escolha um groove ou um pattern ao lado"),
    );
    const pnSel = painel("Selecionado", elSel);

    // ── FILA (loop persistente) ──────────────────────────
    elFilaCards = h("div.fila-cards");
    // texto fixo, visibilidade alternada: assim o botao "Limpar" ao lado nao
    // desliza quando o chip entra (o grupo do cabecalho e alinhado a direita)
    elFilaEstado = h(
      "span.chip",
      { "data-oculto": "" },
      "esperando play na TR-8S",
    );
    bArmar = h("button.bt", { type: "button" }, "Tocar loop");
    bArmar.onclick = armarFila;
    bParar = h("button.bt.bt-perigo", { type: "button" }, "Parar");
    bParar.onclick = () => agir({ acao: "chain_parar" });
    const bLimpar = h("button.bt.bt-peq", { type: "button" }, "Limpar");
    bLimpar.onclick = () => {
      fila = [];
      salvarFila();
      desenharFila(ultimo.chain);
    };
    const pnFila = painel(
      "Loop de encadeamento",
      { dir: [elFilaEstado, bLimpar] },
      elFilaCards,
      h("div.linha", {}, bArmar, bParar),
      h(
        "p.dica",
        {},
        "o loop repete do começo quando acaba, e fica salvo. Clique no " +
          "nome de um card para tirá-lo do loop sem apagar (× apaga). " +
          "Groove ESCREVE na variação aberta do pattern corrente — o " +
          "Desfazer volta.",
      ),
    );

    raiz.append(h("div.grooves", {}, pnFontes, pnSel), pnFila);
    desenharFila();
  },

  atualizar(e, D) {
    ultimo = e;
    // marca o pattern corrente da maquina na grade
    if (!gradeMaq.hidden || true) {
      const atual = e.pattern_atual;
      if (gradeMaq.dataset.atual !== String(atual)) {
        gradeMaq.dataset.atual = String(atual);
        [...gradeMaq.querySelectorAll(".bt")].forEach((b) =>
          attr(b, "data-atual", +b.dataset.n === atual ? "" : null),
        );
      }
    }
    // painel selecionado: partes vivas (bpm medido, habilitacoes)
    const bpmEl = elSel.querySelector("[data-bpm-medido]");
    if (bpmEl)
      texto(bpmEl, e.bpm != null ? `agora: ${e.bpm.toFixed(1)}` : "sem clock");
    const chipBpm = elSel.querySelector("[data-chip-bpm]");
    if (chipBpm && sel && sel.tipo === "groove") {
      const alvo = sel.p.bpm;
      const longe = e.bpm != null && Math.abs(e.bpm - alvo) > 1;
      chipBpm.hidden = !longe;
      if (longe)
        texto(
          chipBpm,
          `máquina em ${e.bpm.toFixed(1)} — clique no BPM ` +
            `para escrever ${alvo}`,
        );
    }
    const bEscrever = elSel.querySelector("[data-escrever]");
    if (bEscrever)
      attr(bEscrever, "aria-disabled", e.carregado ? null : "true");

    // fila: sempre a LOCAL na tela (com os controles); o resumo do motor so
    // fornece a posicao ativa e os ciclos restantes do card em destaque
    const c = e.chain;
    const armadoAgora = !!(c && c.ativo);
    attr(elFilaEstado, "data-oculto", armadoAgora && !e.tocando ? null : "");
    attr(bParar, "aria-disabled", armadoAgora ? null : "true");
    const chave =
      (armadoAgora ? `arm:${c.posicao}:${c.reps_restantes}|` : "solto|") +
      fila.map((f) => f.nome + f.reps + (f.off ? "!" : "")).join("|");
    if (elFilaCards.dataset.chave !== chave) {
      elFilaCards.dataset.chave = chave;
      desenharFila(c);
    }
  },
};

// ── selecao ────────────────────────────────────────────────
function selecionar(s) {
  sel = s;
  elSel.replaceChildren();
  if (s.tipo === "groove") montarSelGroove(s.p);
  else montarSelPattern(s.n);
  // automatismos na selecao (os toggles)
  if (s.tipo === "groove") {
    if (autoKit && s.p.kit_num) agir({ acao: "kit", n: s.p.kit_num - 1 });
    // BPM de verdade: o tempo_watch de 16/08 achou o byte (OFF_TEMPO)
    if (autoBpm) agir({ acao: "bpm", valor: s.p.bpm });
  }
}

function montarSelGroove(p) {
  const bKit = h(
    "button.bt",
    { type: "button" },
    p.kit_num ? KITS[p.kit_num - 1] || `kit ${p.kit_num}` : "—",
  );
  if (p.kit_num) bKit.onclick = () => agir({ acao: "kit", n: p.kit_num - 1 });
  else {
    attr(bKit, "aria-disabled", "true");
    bKit.title = "este groove só tem sugestão textual de kit";
  }

  const bEscrever = h(
    "button.bt.bt-perigo",
    { type: "button", "data-escrever": "" },
    "Escrever",
  );
  // o aviso de "vai sobrescrever a variacao X" aparece por 2 s no arme e sai:
  // a altura fica reservada para o botao Escrever nao pular debaixo do dedo
  const avisoAlvo = h("p.dica.reserva-2linhas");
  bEscrever.onclick = () => escrever(p, bEscrever, avisoAlvo);
  const bDesfazer = h("button.bt", { type: "button" }, "Desfazer");
  bDesfazer.onclick = () => agir({ acao: "desfazer" });

  inReps = h("input", {
    type: "number",
    min: 1,
    max: 16,
    value: 2,
    "aria-label": "repetições",
  });
  const bFila = h("button.bt", { type: "button" }, "+ Loop");
  bFila.onclick = () => {
    fila.push({
      tipo: "groove",
      id: p.id,
      nome: p.nome,
      reps: repsEscolhidas(),
    });
    salvarFila();
    desenharFila(ultimo.chain);
  };

  elSel.append(
    h("h2", {}, p.nome),
    h("p.dica", {}, `${p.estilo} · ${p.bpm} bpm · ${p.kit}`),
    p.obs ? h("p.aviso", {}, p.obs) : "",
    previewEl(p),
    h(
      "div.linha.sel-campos",
      {},
      campo("Kit", bKit),
      campo(
        "BPM",
        h(
          "div.linha",
          {},
          (() => {
            const b = h(
              "button.bt",
              { type: "button", title: "escreve o TEMPO na TR-8S" },
              String(p.bpm),
            );
            b.onclick = () => agir({ acao: "bpm", valor: p.bpm });
            return b;
          })(),
          // "agora: 86.5" e "sem clock" tem larguras diferentes: largura
          // minima para o resto da linha nao dancar a cada leitura
          h("span.dica.medida-bpm", { "data-bpm-medido": "" }, ""),
        ),
      ),
    ),
    // o chip "maquina em 86.5 - clique no BPM..." entra e sai conforme o clock
    // se aproxima do BPM do groove: a linha fica reservada
    h(
      "div.reserva-chip",
      {},
      h("span.chip", { "data-chip-bpm": "", hidden: true }),
    ),
    h(
      "div.linha",
      {},
      toggle(
        "Auto kit",
        (v) => {
          autoKit = v;
          localStorage.setItem("autoKit", v ? "1" : "0");
        },
        autoKit,
      ),
      toggle(
        "Auto BPM",
        (v) => {
          autoBpm = v;
          localStorage.setItem("autoBpm", v ? "1" : "0");
        },
        autoBpm,
      ),
    ),
    h(
      "div.linha",
      {},
      bEscrever,
      bDesfazer,
      campo("Repetições", inReps),
      bFila,
    ),
    avisoAlvo,
  );
}

function montarSelPattern(n) {
  // simplificado a pedido (16/08): a troca e SEMPRE na virada, um botao so
  const bTocar = h("button.bt", { type: "button" }, "Tocar");
  bTocar.onclick = () => agir({ acao: "pattern", n, agora: false });
  inReps = h("input", {
    type: "number",
    min: 1,
    max: 16,
    value: 2,
    "aria-label": "repetições",
  });
  const bFila = h("button.bt", { type: "button" }, "+ Loop");
  bFila.onclick = () => {
    fila.push({
      tipo: "pattern",
      alvo: n,
      nome: nomePat(n),
      reps: repsEscolhidas(),
    });
    salvarFila();
    desenharFila(ultimo.chain);
  };
  const meta =
    ultimo.pattern_atual === n && ultimo.pattern_nome
      ? `tocando agora · “${ultimo.pattern_nome}”`
      : "a troca acontece na virada do compasso, como no painel. O nome " +
        "do pattern só é legível quando ele está tocando.";
  elSel.append(
    h("h2", {}, "Pattern " + nomePat(n)),
    h("p.dica", {}, meta),
    h("div.linha", {}, bTocar, campo("Repetições", inReps), bFila),
  );
}

function repsEscolhidas() {
  return Math.max(1, Math.min(16, +inReps.value || 1));
}

// ── escrita (arme de 2 cliques, como antes) ────────────────
function escrever(p, botao, aviso) {
  const agora = Date.now();
  if (agora - armado > 2000) {
    armado = agora;
    botao.setAttribute("data-armado", "");
    botao.style.setProperty("--ms", "2000ms");
    texto(botao, "Clique de novo (2 s)");
    texto(
      aviso,
      `vai sobrescrever a variação ${ultimo.variacao_nome || "?"}` +
        (ultimo.variacao_tocando === ultimo.variacao
          ? " — que está TOCANDO agora"
          : "") +
        ". O Desfazer volta o que estava.",
    );
    setTimeout(() => {
      if (Date.now() - armado >= 2000) {
        botao.removeAttribute("data-armado");
        texto(botao, "Escrever");
        texto(aviso, "");
      }
    }, 2000);
    return;
  }
  armado = 0;
  botao.removeAttribute("data-armado");
  texto(botao, "Escrever");
  texto(aviso, "");
  agir({ acao: "biblioteca", id: p.id });
}

// ── fila (loop persistente) ────────────────────────────────
// A tela mostra SEMPRE a fila local, com todos os controles. Quando o loop
// esta tocando, o resumo do motor so diz qual entrada esta ativa - o
// destaque cai no n-esimo card LIGADO (os desligados nao foram enviados).
function noLoop() {
  return fila.filter((f) => !f.off);
}

function desenharFila(chain) {
  elFilaCards.replaceChildren();
  if (!fila.length) {
    elFilaCards.append(
      h("p.vazio", {}, "loop vazio — selecione algo e clique “+ Loop”"),
    );
    return;
  }
  const armadoAgora = !!(chain && chain.ativo);
  const ligados = noLoop();
  const ativo =
    armadoAgora && ligados.length
      ? ligados[chain.posicao % ligados.length]
      : null;
  fila.forEach((f, i) => {
    const nome = h("strong", { title: "clique: tira/volta do loop" }, f.nome);
    const card = h(
      "div.card-chain",
      { "data-tipo": f.tipo, "data-off": f.off ? "" : null },
      h("span.badge", {}, f.tipo === "groove" ? "groove" : "pattern"),
      nome,
    );
    nome.onclick = () => {
      f.off = !f.off;
      salvarFila();
      desenharFila(ultimo.chain);
    };
    if (f === ativo) {
      attr(card, "data-ativo", "");
      card.append(h("span.dica", {}, `faltam ${chain.reps_restantes}`));
    }
    const menos = h("button.bt.bt-peq", { type: "button" }, "−");
    const mais = h("button.bt.bt-peq", { type: "button" }, "+");
    const nreps = h("span.mono", {}, `${f.reps}×`);
    menos.onclick = () => {
      f.reps = Math.max(1, f.reps - 1);
      salvarFila();
      desenharFila(ultimo.chain);
    };
    mais.onclick = () => {
      f.reps = Math.min(16, f.reps + 1);
      salvarFila();
      desenharFila(ultimo.chain);
    };
    const esq = h("button.bt.bt-peq", { type: "button", title: "mover" }, "◀");
    const dir = h("button.bt.bt-peq", { type: "button", title: "mover" }, "▶");
    esq.onclick = () => {
      if (i > 0) {
        [fila[i - 1], fila[i]] = [fila[i], fila[i - 1]];
        salvarFila();
        desenharFila(ultimo.chain);
      }
    };
    dir.onclick = () => {
      if (i < fila.length - 1) {
        [fila[i + 1], fila[i]] = [fila[i], fila[i + 1]];
        salvarFila();
        desenharFila(ultimo.chain);
      }
    };
    const rem = h("button.bt.bt-peq", { type: "button", title: "apagar" }, "×");
    rem.onclick = () => {
      fila.splice(i, 1);
      salvarFila();
      desenharFila(ultimo.chain);
    };
    card.append(menos, nreps, mais, esq, dir, rem);
    elFilaCards.append(card);
    if (i < fila.length - 1)
      elFilaCards.append(h("span.dica.seta-fila", {}, "→"));
  });
}

function armarFila() {
  const ligados = noLoop();
  if (!ligados.length) {
    toast("o loop está vazio (ou tudo está desligado)");
    return;
  }
  agir({
    acao: "chain_armar",
    modo: "misto",
    entradas: ligados.map((f) =>
      f.tipo === "groove"
        ? { tipo: "groove", id: f.id, reps: f.reps }
        : { tipo: "pattern", alvo: f.alvo, reps: f.reps },
    ),
  });
}

// ── filtro e preview ───────────────────────────────────────
function filtrar() {
  const q = inFiltro.value.trim().toLowerCase();
  const visiveisPorEstilo = {};
  [...tbodyBib.children].forEach((tr) => {
    if (tr.classList.contains("grupo")) return;
    const some = !q || tr.dataset.nome.includes(q);
    tr.hidden = !some;
    if (some) {
      // acha o estilo deste tr (o grupo anterior)
      let g = tr.previousElementSibling;
      while (g && !g.classList.contains("grupo")) g = g.previousElementSibling;
      if (g) visiveisPorEstilo[g.dataset.estilo] = true;
    }
  });
  [...tbodyBib.querySelectorAll("tr.grupo")].forEach((g) => {
    g.hidden = !visiveisPorEstilo[g.dataset.estilo];
  });
}

function previewEl(p) {
  const cx = h("div.prev");
  D_.instrumentos.forEach((n) => {
    const linha = p.grade[n];
    if (!linha || !linha.some((c) => c.v)) return;
    const g = h("div.g");
    for (let s = 0; s < 16; s++) {
      const c = linha[s],
        i = h("i");
      if (s >= (p.last_var || 16)) i.style.background = "var(--c-fora)";
      else if (c.v) {
        i.style.background = c.s
          ? c.s === 1
            ? "var(--c-flam)"
            : "var(--c-sub)"
          : c.v >= 80
            ? "var(--c-nota)"
            : "var(--c-nota_fraca)";
        if (c.p < 100) i.style.opacity = 0.35 + c.p / 160;
      }
      g.append(i);
    }
    cx.append(h("div.l", {}, h("span.n", {}, n), g));
  });
  if (p.accent) {
    const g = h("div.g");
    for (let s = 0; s < 16; s++) {
      const i = h("i");
      if (p.accent & (1 << s)) i.style.background = "var(--c-acc)";
      g.append(i);
    }
    cx.append(h("div.l", {}, h("span.n", {}, "ACC"), g));
  }
  return cx;
}
