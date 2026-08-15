// toast.mjs - o canal de feedback que faltava.
// Antes, erro de acao virava uma linha de log em 11px no rodape (quando
// virava): "ligue o modo ON", "cache invalido - escrita abortada" e os 403 do
// servidor morriam calados.
import { h } from "../nucleo/dom.mjs";

let cx = null;
const ultimo = { txt: "", el: null, n: 0, t: 0 };

function caixa() {
  if (!cx) {
    cx = h("div", { id: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(cx);
  }
  return cx;
}

export function toast(txt, { tipo = "info", ttl = 4200 } = {}) {
  const agora = performance.now();
  // repetido em sequencia vira "x3" em vez de empilhar cinco caixinhas iguais
  if (ultimo.el && ultimo.txt === txt && agora - ultimo.t < 6000) {
    ultimo.n++;
    ultimo.t = agora;
    ultimo.el.querySelector(".vezes").textContent = ` ×${ultimo.n}`;
    return ultimo.el;
  }
  const el = h("div.toast", { "data-tipo": tipo }, txt, h("span.vezes"));
  caixa().append(el);
  Object.assign(ultimo, { txt, el, n: 1, t: agora });
  setTimeout(() => {
    el.setAttribute("data-saindo", "");
    setTimeout(() => {
      el.remove();
      if (ultimo.el === el) ultimo.el = null;
    }, 200);
  }, ttl);
  return el;
}

export const erro = (t) => toast(t, { tipo: "erro", ttl: 6000 });
export const ok = (t) => toast(t, { tipo: "ok" });
export const aviso = (t) => toast(t, { tipo: "aviso" });
