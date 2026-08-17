// knob.mjs - o knob circular do TR-EDITOR, em SVG puro.
//
// pathLength="100" e o truque que dispensa trigonometria: o dasharray vira
// porcentagem direta do arco. Varredura de 270 graus (-135 a +135).
// O valor entra por custom property (--pct) - nunca por reflow.
//
// Bipolar: Tune, Pan, Gain e LFO Depth aparecem como -128..+127 no visor mas
// guardam 0-255 com centro em 128 (Reference p.33). O arco cresce do centro
// para os lados - a unica representacao honesta.
import { h, svg, attr, prop, texto } from "../nucleo/dom.mjs";
import { arrastando } from "../nucleo/store.mjs";
import { pct } from "../nucleo/formato.mjs";

export function knob({
  rotulo,
  min = 0,
  max = 255,
  valor = null,
  bipolar = false,
  chave,
  aoSoltar,
  formatar = String,
  dica = "",
  fantasma = false,
  aoCapturar = null,
  // De onde o arrasto parte quando o knob esta em "—" (valor desconhecido).
  // O padrao era o MINIMO, e o PROB da mesa mordia nisso: "—" ali significa
  // steps com probabilidades DIFERENTES, e um arrasto de dois pixels comitava
  // 10% em todos os steps ligados do instrumento. Quem tem valor neutro (o
  // PROB tem: 100%) passa ele aqui.
  baseNula = null,
}) {
  const base = () => (baseNula === null ? min : baseNula);
  const arco = svg("circle", {
    class: "arco",
    cx: 22,
    cy: 22,
    r: 17,
    pathLength: 100,
  });
  const ponteiro = svg("line", {
    class: "ponteiro",
    x1: 22,
    y1: 8,
    x2: 22,
    y2: 14,
  });
  const grafico = svg(
    "svg",
    { viewBox: "0 0 44 44", "aria-hidden": "true" },
    svg("circle", { class: "trilho", cx: 22, cy: 22, r: 17, pathLength: 100 }),
    arco,
    ponteiro,
  );
  const elVal = h("div.knob-val", {}, "—");
  const raiz = h(
    "div.knob",
    {
      role: "slider",
      tabindex: fantasma ? -1 : 0,
      "aria-label": rotulo,
      "aria-valuemin": min,
      "aria-valuemax": max,
      "data-dica": dica || null,
    },
    grafico,
    h("div.knob-rot", {}, rotulo),
    elVal,
  );
  if (bipolar) raiz.setAttribute("data-bipolar", "");

  let v = valor;
  let arrasto = null;

  function pintar(nv) {
    v = nv;
    if (nv == null) {
      texto(elVal, "—");
      raiz.removeAttribute("aria-valuenow");
      return;
    }
    const p = pct(nv, min, max);
    prop(raiz, "--pct", p);
    if (bipolar) {
      // arco do centro (0.5) ate o valor
      prop(raiz, "--ini", Math.min(p, 0.5));
      prop(raiz, "--tam", Math.abs(p - 0.5));
    }
    texto(elVal, formatar(nv));
    attr(raiz, "aria-valuenow", nv);
    attr(raiz, "aria-valuetext", formatar(nv));
  }

  function definirFantasma(f) {
    raiz.toggleAttribute("data-fantasma", f);
    attr(raiz, "tabindex", f ? -1 : 0);
    attr(raiz, "aria-disabled", f ? "true" : null);
  }
  definirFantasma(fantasma);
  pintar(valor);

  // ── arrasto vertical ──
  raiz.addEventListener("pointerdown", (e) => {
    if (raiz.hasAttribute("data-fantasma")) {
      aoCapturar && aoCapturar();
      return;
    }
    if (e.button !== 0) return;
    raiz.setPointerCapture(e.pointerId);
    arrasto = { y: e.clientY, v: v === null ? base() : v };
    arrastando.add(chave);
    e.preventDefault();
  });
  raiz.addEventListener("pointermove", (e) => {
    if (!arrasto) return;
    const fino = e.shiftKey ? 0.25 : 1;
    const d = ((arrasto.y - e.clientY) / 200) * (max - min) * fino;
    pintar(Math.round(Math.max(min, Math.min(max, arrasto.v + d))));
  });
  function terminar(comita) {
    if (!arrasto) return;
    const valorFinal = v;
    const inicial = arrasto.v;
    arrasto = null;
    arrastando.delete(chave);
    if (comita) {
      if (valorFinal !== inicial) aoSoltar && aoSoltar(valorFinal);
    } else pintar(inicial);
  }
  raiz.addEventListener("pointerup", () => terminar(true));
  raiz.addEventListener("lostpointercapture", () => terminar(true));
  raiz.addEventListener("pointercancel", () => terminar(false));
  window.addEventListener("pointerup", () => terminar(true));
  window.addEventListener("blur", () => terminar(true));

  // ── teclado ──
  raiz.addEventListener("keydown", (e) => {
    if (raiz.hasAttribute("data-fantasma")) return;
    const passo = e.shiftKey ? 1 : Math.max(1, Math.round((max - min) / 64));
    const partida = v === null ? base() : v;
    let nv = null;
    if (e.key === "ArrowUp" || e.key === "ArrowRight") nv = partida + passo;
    else if (e.key === "ArrowDown" || e.key === "ArrowLeft") nv = partida - passo;
    else if (e.key === "PageUp") nv = partida + passo * 8;
    else if (e.key === "PageDown") nv = partida - passo * 8;
    else if (e.key === "Home") nv = min;
    else if (e.key === "End") nv = max;
    else return;
    e.preventDefault();
    nv = Math.max(min, Math.min(max, nv));
    pintar(nv);
    aoSoltar && aoSoltar(nv);
  });
  raiz.addEventListener(
    "wheel",
    (e) => {
      if (raiz.hasAttribute("data-fantasma") || document.activeElement !== raiz)
        return;
      e.preventDefault();
      const nv = Math.max(
        min,
        Math.min(
          max,
          (v === null ? base() : v) -
            Math.sign(e.deltaY) * Math.max(1, Math.round((max - min) / 64)),
        ),
      );
      pintar(nv);
      aoSoltar && aoSoltar(nv);
    },
    { passive: false },
  );

  return {
    raiz,
    definir(nv, { pendente = false, fantasma: f } = {}) {
      if (f !== undefined) definirFantasma(f);
      if (arrastando.has(chave)) return;
      pintar(nv);
      raiz.toggleAttribute("data-pendente", pendente);
    },
    acender() {
      raiz.setAttribute("data-acendendo", "");
      setTimeout(() => raiz.removeAttribute("data-acendendo"), 400);
    },
  };
}
