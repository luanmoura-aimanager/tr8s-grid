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
// - "Auto BPM" e so aviso: escrever BPM nao tem endereco conhecido
//   (REFERENCIA 7). O tempo continua sendo o knob da maquina.
import { h, texto, attr } from "../nucleo/dom.mjs";
import { painel, campo, toggle } from "../comp/painel.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

const KITS = ["TR-808", "TR-909", "TR-707", "TR-727", "TR-606", "TR-626"];
const nomePat = (n) => "ABCDEFGH"[n >> 4] + ((n % 16) + 1);

let D_;
let sel = null; // {tipo:"groove", p} | {tipo:"pattern", n}
let fila = []; // [{tipo, id?|alvo?, nome, reps}]
let ultimo = {};
let armado = 0;

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
      gradeMaq.append(h("span.rot-banco", {}, "ABCDEFGH"[b]));
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

    // ── FILA ─────────────────────────────────────────────
    elFilaCards = h("div.fila-cards");
    elFilaEstado = h("span.chip", { hidden: true });
    bArmar = h("button.bt", { type: "button" }, "Armar");
    bArmar.onclick = armarFila;
    bParar = h("button.bt.bt-perigo", { type: "button" }, "Parar");
    bParar.onclick = () => agir({ acao: "chain_parar" });
    const pnFila = painel(
      "Fila de encadeamento",
      { dir: [elFilaEstado] },
      elFilaCards,
      h("div.linha", {}, bArmar, bParar),
      h(
        "p.aviso",
        {},
        "groove na fila ESCREVE na variação aberta do pattern corrente — " +
          "o Desfazer volta.",
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
      if (longe) texto(chipBpm, `gire o TEMPO para ${alvo}`);
    }
    const bEscrever = elSel.querySelector("[data-escrever]");
    if (bEscrever)
      attr(bEscrever, "aria-disabled", e.carregado ? null : "true");

    // fila: armado, o resumo do motor e a verdade e a local trava
    const c = e.chain;
    const armadoAgora = !!(c && c.ativo);
    elFilaEstado.hidden = !armadoAgora || e.tocando;
    if (armadoAgora && !e.tocando)
      texto(elFilaEstado, "esperando play na TR-8S");
    attr(bParar, "aria-disabled", armadoAgora ? null : "true");
    attr(bArmar, "aria-disabled", armadoAgora ? "true" : null);
    const chave = armadoAgora
      ? `arm:${c.posicao}:${c.reps_restantes}`
      : "local:" + fila.map((f) => f.nome + f.reps).join("|");
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
    if (autoBpm && ultimo.bpm != null && Math.abs(ultimo.bpm - s.p.bpm) > 1)
      toast(
        `BPM alvo ${s.p.bpm} — gire o TEMPO da TR-8S (agora: ` +
          `${ultimo.bpm.toFixed(1)})`,
        { ttl: 6000 },
      );
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
  const avisoAlvo = h("p.dica");
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
  const bFila = h("button.bt", { type: "button" }, "+ Fila");
  bFila.onclick = () => {
    fila.push({
      tipo: "groove",
      id: p.id,
      nome: p.nome,
      reps: repsEscolhidas(),
    });
    desenharFila();
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
          h("span.mono.bpm-alvo", {}, String(p.bpm)),
          h("span.dica", { "data-bpm-medido": "" }, ""),
        ),
      ),
    ),
    h("span.chip", { "data-chip-bpm": "", hidden: true }),
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
        "Auto BPM (aviso apenas)",
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
  const bVirada = h("button.bt", { type: "button" }, "Na virada");
  bVirada.onclick = () => agir({ acao: "pattern", n, agora: false });
  const bAgora = h("button.bt", { type: "button" }, "Agora");
  bAgora.onclick = () => agir({ acao: "pattern", n, agora: true });
  inReps = h("input", {
    type: "number",
    min: 1,
    max: 16,
    value: 2,
    "aria-label": "repetições",
  });
  const bFila = h("button.bt", { type: "button" }, "+ Fila");
  bFila.onclick = () => {
    fila.push({
      tipo: "pattern",
      alvo: n,
      nome: nomePat(n),
      reps: repsEscolhidas(),
    });
    desenharFila();
  };
  elSel.append(
    h("h2", {}, "Pattern " + nomePat(n)),
    h(
      "p.dica",
      {},
      "provado em hardware: “Na virada” espera o compasso acabar, como no " +
        "painel; “Agora” corta no meio preservando o step — troca de " +
        "conteúdo com o relógio intacto.",
    ),
    h("div.linha", {}, bVirada, bAgora, campo("Repetições", inReps), bFila),
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

// ── fila ───────────────────────────────────────────────────
function desenharFila(chain) {
  elFilaCards.replaceChildren();
  const armadoAgora = !!(chain && chain.ativo);
  const itens = armadoAgora ? chain.entradas : fila;
  if (!itens.length) {
    elFilaCards.append(
      h("p.vazio", {}, "fila vazia — selecione algo e clique “+ Fila”"),
    );
    return;
  }
  itens.forEach((f, i) => {
    const card = h(
      "div.card-chain",
      { "data-tipo": f.tipo },
      h("span.badge", {}, f.tipo === "groove" ? "groove" : "pattern"),
      h("strong", {}, f.nome),
    );
    if (armadoAgora) {
      if (i === chain.posicao) {
        attr(card, "data-ativo", "");
        card.append(
          h("span.dica", {}, `faltam ${chain.reps_restantes} ciclos`),
        );
      } else card.append(h("span.dica", {}, `${f.reps}×`));
    } else {
      // editavel: stepper de reps, reordenar, remover
      const menos = h("button.bt.bt-peq", { type: "button" }, "−");
      const mais = h("button.bt.bt-peq", { type: "button" }, "+");
      const nreps = h("span.mono", {}, `${f.reps}×`);
      menos.onclick = () => {
        f.reps = Math.max(1, f.reps - 1);
        desenharFila();
      };
      mais.onclick = () => {
        f.reps = Math.min(16, f.reps + 1);
        desenharFila();
      };
      const esq = h(
        "button.bt.bt-peq",
        { type: "button", title: "mover" },
        "◀",
      );
      const dir = h(
        "button.bt.bt-peq",
        { type: "button", title: "mover" },
        "▶",
      );
      esq.onclick = () => {
        if (i > 0) {
          [fila[i - 1], fila[i]] = [fila[i], fila[i - 1]];
          desenharFila();
        }
      };
      dir.onclick = () => {
        if (i < fila.length - 1) {
          [fila[i + 1], fila[i]] = [fila[i], fila[i + 1]];
          desenharFila();
        }
      };
      const rem = h(
        "button.bt.bt-peq",
        { type: "button", title: "remover" },
        "×",
      );
      rem.onclick = () => {
        fila.splice(i, 1);
        desenharFila();
      };
      card.append(menos, nreps, mais, esq, dir, rem);
    }
    elFilaCards.append(card);
    if (i < itens.length - 1)
      elFilaCards.append(h("span.dica.seta-fila", {}, "→"));
  });
}

function armarFila() {
  if (!fila.length) {
    toast("a fila está vazia");
    return;
  }
  agir({
    acao: "chain_armar",
    modo: "misto",
    entradas: fila.map((f) =>
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
