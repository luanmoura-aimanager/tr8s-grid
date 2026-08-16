// abas/estocastica.mjs - as ideias do Stochas nos recursos nativos da TR-8S.
//
// Reforma 2: a fileira BD-RC multi-selecao substitui o dropdown - cada
// instrumento selecionado ganha SUA linha de sliders, e cada Aplicar tem um
// Reverter proprio. O Reverter-por-edicao funciona comparando o rotulo que
// este Aplicar gerou com o TOPO de e.desfazer_pilha: se outra edicao veio
// depois, o botao trava e aponta o historico (desfazer e uma pilha, so o
// topo sai sem refazer as de cima).
import { h, texto, attr } from "../nucleo/dom.mjs";
import { fader } from "../comp/fader.mjs";
import { painel, campo } from "../comp/painel.mjs";
import { agir } from "../app.mjs";

const OPS = [
  [
    "densidade",
    "densidade %",
    25,
    200,
    100,
    "escala a probability dos steps ligados — o poly bias do Stochas",
  ],
  [
    "humanize",
    "humanize ±",
    0,
    40,
    15,
    "velocity ± aleatório nos steps ligados",
  ],
  ["retrig", "retrig %", 0, 50, 15, "sorteia flam e sub steps — o retrigger"],
  [
    "ghosts",
    "ghosts %",
    0,
    50,
    20,
    "liga steps vazios fracos com probability baixa: a máquina decide a " +
      "cada volta",
  ],
];

let D_;
let inSeed,
  selecao = new Set(), // indices selecionados; vazio = todos
  elLinhas,
  elHist,
  fadersStep = [],
  ultimaPilha = [];
// aplicacoes vivas: rotulo esperado -> botao Reverter daquela linha
const reverters = new Map();

export default {
  id: "estocastica",
  rotulo: "Estocástica",

  montar(raiz, D) {
    D_ = D;
    inSeed = h("input", {
      type: "number",
      value: 1,
      style: { width: "90px" },
      "aria-label": "seed",
    });

    // fileira BD-RC multi-selecao
    const tabs = h("div.inst-tabs");
    const bTodos = h(
      "button.bt",
      { type: "button", "aria-pressed": "true" },
      "TODOS",
    );
    bTodos.onclick = () => {
      selecao.clear();
      sincronizarTabs(tabs, bTodos);
      montarLinhas();
    };
    tabs.append(bTodos);
    D.instrumentos.forEach((n, i) => {
      const b = h(
        "button.bt",
        { type: "button", "data-i": i, "aria-pressed": "false" },
        n,
      );
      b.onclick = () => {
        if (selecao.has(i)) selecao.delete(i);
        else selecao.add(i);
        sincronizarTabs(tabs, bTodos);
        montarLinhas();
      };
      tabs.append(b);
    });

    elLinhas = h("div.col");
    elHist = h("div.col");

    // regua de probability por step (segue o 1o instrumento selecionado)
    const fila = h("div.fila-inst", {}, h("div.rot-fila", {}, "PROB por step"));
    for (let s = 0; s < 16; s++) {
      const f = fader({
        rotulo: String(s + 1),
        min: 0,
        max: 100,
        chave: "ps" + s,
        desabilitado: true,
        aoSoltar: (v) =>
          agir({ acao: "prob_step", inst: instRegua(), step: s, pct: v }),
      });
      fadersStep.push(f);
      fila.append(f.raiz);
    }

    raiz.append(
      painel(
        "Estocástica",
        { dir: [campo("Seed", inSeed)] },
        h(
          "p.dica",
          {},
          "opera na variação aberta; cada Aplicar empilha um snapshot e " +
            "ganha o seu Reverter. Probability é nativa: a máquina " +
            "sorteia a cada volta. Mesma seed = mesmo resultado.",
        ),
        tabs,
        elLinhas,
      ),
      painel("Histórico de edições", elHist),
      painel(
        "Probability por step",
        h(
          "p.dica",
          {},
          "segue o primeiro instrumento selecionado acima — steps " +
            "apagados ficam travados (0% existe: o step nunca toca)",
        ),
        fila,
      ),
    );
    montarLinhas();
  },

  atualizar(e) {
    // regua
    const i = instRegua();
    const vels = (e.pattern || {})[i] || [];
    const pr = (e.probs || {})[i] || [];
    for (let s = 0; s < 16; s++) {
      const on = !!vels[s];
      fadersStep[s].definir(on ? (pr[s] ?? null) : null, { off: !on });
    }
    // pilha de desfazer: habilita/trava os Reverter por edicao e o historico
    const pilha = e.desfazer_pilha || [];
    const mudou = pilha.join("|") !== ultimaPilha.join("|");
    ultimaPilha = pilha;
    const topo = pilha[pilha.length - 1];
    for (const [rotulo, b] of reverters) {
      const ok = topo === rotulo;
      attr(b, "aria-disabled", ok ? null : "true");
      b.title = ok ? "" : "outra edição veio depois — use o histórico";
    }
    if (mudou) desenharHistorico(pilha);
  },
};

function sincronizarTabs(tabs, bTodos) {
  attr(bTodos, "aria-pressed", selecao.size ? "false" : "true");
  [...tabs.querySelectorAll("[data-i]")].forEach((b) =>
    attr(b, "aria-pressed", selecao.has(+b.dataset.i) ? "true" : "false"),
  );
}

function instRegua() {
  return selecao.size ? Math.min(...selecao) : 0;
}

/** o rotulo que o backend vai gerar - CONTRATO com Estocastica.rotulo() */
function rotuloEsperado(op, insts) {
  if (!insts) return `${op} todos`;
  return op + " " + insts.map((i) => D_.instrumentos[i]).join("+");
}

function montarLinhas() {
  elLinhas.replaceChildren();
  reverters.clear();
  const grupos = selecao.size
    ? [...selecao].sort((a, b) => a - b).map((i) => [i])
    : [null]; // null = todos
  grupos.forEach((g) => {
    const nome = g ? D_.instrumentos[g[0]] : "TODOS";
    const linhaCx = h(
      "div.painel",
      {},
      h("header", {}, nome),
      h("div.corpo.linha-ops"),
    );
    const corpo = linhaCx.querySelector(".corpo");
    OPS.forEach(([op, rot, min, max, ini, dica]) => {
      const inp = h("input", {
        type: "range",
        class: "h",
        min,
        max,
        value: ini,
        "aria-label": `${rot} ${nome}`,
      });
      const val = h("span.mono", {}, String(ini));
      inp.oninput = () => (val.textContent = inp.value);
      const bAp = h("button.bt.bt-peq", { type: "button" }, "Aplicar");
      const bRev = h(
        "button.bt.bt-peq",
        { type: "button", "aria-disabled": "true" },
        "Reverter",
      );
      const rotulo = rotuloEsperado(op, g);
      bAp.onclick = () => {
        agir({
          acao: "estocastica",
          op,
          valor: op === "densidade" ? +inp.value / 100 : +inp.value,
          seed: +inSeed.value || 0,
          insts: g,
        });
        // este Reverter passa a vigiar o topo da pilha por este rotulo
        reverters.set(rotulo, bRev);
      };
      bRev.onclick = () => {
        if (bRev.getAttribute("aria-disabled") === "true") return;
        agir({ acao: "estocastica", op: "reverter" });
      };
      corpo.append(
        h(
          "div.linha",
          { "data-dica": dica },
          h("label", { style: { width: "110px" } }, rot),
          inp,
          val,
          bAp,
          bRev,
        ),
      );
    });
    elLinhas.append(linhaCx);
  });
}

function desenharHistorico(pilha) {
  elHist.replaceChildren();
  if (!pilha.length) {
    elHist.append(h("p.vazio", {}, "nenhuma edição na pilha"));
    return;
  }
  const bUlt = h("button.bt.bt-peq", { type: "button" }, "Reverter última");
  bUlt.onclick = () => agir({ acao: "estocastica", op: "reverter" });
  const bTudo = h(
    "button.bt.bt-peq.bt-perigo",
    { type: "button" },
    "Reverter tudo",
  );
  bTudo.onclick = () => agir({ acao: "desfazer_tudo" });
  elHist.append(
    h(
      "div.linha",
      {},
      h("span.dica", {}, "topo primeiro:"),
      ...pilha
        .slice()
        .reverse()
        .map((r, i) => h("span.chip", { "data-on": i === 0 ? "1" : null }, r)),
    ),
    h("div.linha", {}, bUlt, bTudo),
  );
}
