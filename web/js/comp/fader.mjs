// fader.mjs - fader vertical com escala.
//
// O <input type=range> e REAL (so girado pelo involucro em CSS): teclado,
// leitor de tela e acessibilidade vem de graca. A versao anterior usava
// writing-mode:vertical-lr, que so existe em navegador recente e quebrava o
// layout nos outros - e, pior, so comitava no pointerup, entao mover com as
// setas do teclado nunca escrevia na maquina.
import { h } from "../nucleo/dom.mjs";
import { arrastando } from "../nucleo/store.mjs";

export function fader({
  rotulo,
  min = 0,
  max = 127,
  valor = min,
  aoSoltar,
  chave,
  formatar = String,
  desabilitado = false,
}) {
  const val = h("div.fader-val", {}, "—");
  const inp = h("input", {
    type: "range",
    min,
    max,
    value: valor,
    "aria-label": rotulo,
  });
  if (desabilitado) inp.disabled = true;
  const cx = h("div.fader-cx", {}, inp);
  const raiz = h("div.fader", {}, val, cx, h("div.fader-rot", {}, rotulo));

  const pintar = (v) => {
    val.textContent = v === null ? "—" : formatar(v);
  };
  pintar(desabilitado ? null : valor);

  // input = so pinta (arrasto em curso). change = comita, e o change dispara
  // tanto ao soltar o mouse quanto ao usar o teclado.
  inp.addEventListener("pointerdown", () => arrastando.add(chave));
  inp.addEventListener("input", () => pintar(+inp.value));
  inp.addEventListener("change", () => {
    arrastando.delete(chave);
    aoSoltar && aoSoltar(+inp.value);
  });
  const soltar = () => arrastando.delete(chave);
  inp.addEventListener("pointerup", soltar);
  inp.addEventListener("pointercancel", soltar);
  window.addEventListener("pointerup", soltar);

  return {
    raiz,
    definir(v, { pendente = false, off = false } = {}) {
      if (arrastando.has(chave)) return; // nao puxa da mao de quem arrasta
      inp.disabled = off || v === null;
      if (v !== null && +inp.value !== v) inp.value = v;
      pintar(v);
      raiz.toggleAttribute("data-pendente", pendente);
      raiz.toggleAttribute("data-off", off || v === null);
    },
  };
}
