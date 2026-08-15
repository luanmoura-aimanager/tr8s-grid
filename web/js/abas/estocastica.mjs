// abas/estocastica.mjs - as ideias do Stochas nos recursos nativos da TR-8S,
// mais a regua de probability por step (o painel so mostra um step por vez).
import { h, attr } from "../nucleo/dom.mjs";
import { fader } from "../comp/fader.mjs";
import { agir } from "../app.mjs";

const OPS = [
  [
    "densidade",
    "densidade (%)",
    25,
    200,
    100,
    "escala a probability de todos os steps ligados — o poly bias do Stochas",
  ],
  [
    "humanize",
    "humanize velocity (±)",
    0,
    40,
    15,
    "velocity ± aleatório nos steps ligados",
  ],
  [
    "retrig",
    "retrig / sub steps (%)",
    0,
    50,
    15,
    "sorteia flam e sub steps — o retrigger",
  ],
  [
    "ghosts",
    "ghost notes (%)",
    0,
    50,
    20,
    "liga steps vazios com velocity fraca e probability baixa: a máquina decide a cada volta",
  ],
];
let inSeed,
  selInst,
  fadersStep = [],
  inst = 0;

export default {
  id: "estocastica",
  rotulo: "Estocástica",

  montar(raiz, D) {
    inSeed = h("input", {
      type: "number",
      value: 1,
      style: { width: "90px" },
      "aria-label": "seed",
    });
    const controles = OPS.map(([op, rot, min, max, ini, dica]) => {
      const inp = h("input", {
        type: "range",
        class: "h",
        min,
        max,
        value: ini,
        "aria-label": rot,
      });
      const val = h("span.mono", {}, String(ini));
      inp.oninput = () => (val.textContent = inp.value);
      const b = h("button.bt.bt-peq", { type: "button" }, "Aplicar");
      b.onclick = () =>
        agir({
          acao: "estocastica",
          op,
          valor: op === "densidade" ? +inp.value / 100 : +inp.value,
          seed: +inSeed.value || 0,
        });
      return h(
        "div.linha",
        { "data-dica": dica },
        h("label", { style: { width: "180px" } }, rot),
        inp,
        val,
        b,
      );
    });
    const bRev = h("button.bt.bt-perigo", { type: "button" }, "Reverter tudo");
    bRev.onclick = () => agir({ acao: "estocastica", op: "reverter" });

    selInst = h("select", { "aria-label": "instrumento" });
    D.instrumentos.forEach((n, i) => selInst.append(new Option(n, i)));
    selInst.onchange = () => {
      inst = +selInst.value;
    };

    const fila = h("div.fila-inst", {}, h("div.rot-fila", {}, "PROB por step"));
    for (let s = 0; s < 16; s++) {
      const f = fader({
        rotulo: String(s + 1),
        min: 10,
        max: 100,
        chave: "ps" + s,
        desabilitado: true,
        aoSoltar: (v) => agir({ acao: "prob_step", inst, step: s, pct: v }),
      });
      fadersStep.push(f);
      fila.append(f.raiz);
    }

    raiz.append(
      h(
        "p.dica",
        {},
        "opera na variação aberta; o primeiro uso guarda um " +
          "snapshot — Reverter volta tudo. Probability é nativa da TR-8S: " +
          "a máquina sorteia a cada volta.",
      ),
      h(
        "div.linha",
        {},
        h("label", {}, "seed"),
        inSeed,
        h(
          "span.dica",
          {},
          "mesma seed sobre o mesmo pattern = mesmo resultado",
        ),
      ),
      h("div.secao", {}, ...controles, h("div.linha", {}, bRev)),
      h(
        "div.secao",
        {},
        h("h3", {}, "probability por step"),
        h("div.linha", {}, h("label", {}, "instrumento"), selInst),
        h(
          "p.dica",
          {},
          "steps apagados ficam travados — probability só existe " +
            "em step ligado",
        ),
        fila,
      ),
    );
  },

  atualizar(e) {
    const vels = (e.pattern || {})[inst] || [];
    const pr = (e.probs || {})[inst] || [];
    for (let s = 0; s < 16; s++) {
      const on = !!vels[s];
      fadersStep[s].definir(on ? (pr[s] ?? null) : null, { off: !on });
    }
  },
};
