// tooltip.mjs - um elemento so, compartilhado por todo [data-dica].
// Aparece no hover E no foco por teclado (title= nativo nunca aparece no foco).
import { h, texto } from "../nucleo/dom.mjs";

let cx = null;

function mostrar(alvo) {
  const txt = alvo.getAttribute("data-dica");
  if (!txt) return;
  if (!cx) {
    cx = h("div", { id: "dica", role: "tooltip" });
    document.body.append(cx);
  }
  texto(cx, txt);
  cx.setAttribute("data-on", "");
  const r = alvo.getBoundingClientRect();
  const c = cx.getBoundingClientRect();
  let x = r.left + r.width / 2 - c.width / 2;
  x = Math.max(8, Math.min(window.innerWidth - c.width - 8, x));
  const acima = r.top > c.height + 12;
  cx.style.left = x + "px";
  cx.style.top = (acima ? r.top - c.height - 8 : r.bottom + 8) + "px";
}
function esconder() {
  if (cx) cx.removeAttribute("data-on");
}

export function ligarDica() {
  document.addEventListener("pointerover", (e) => {
    const alvo = e.target.closest && e.target.closest("[data-dica]");
    if (alvo) mostrar(alvo);
    else esconder();
  });
  document.addEventListener("focusin", (e) => {
    const alvo = e.target.closest && e.target.closest("[data-dica]");
    if (alvo) mostrar(alvo);
    else esconder();
  });
  document.addEventListener("focusout", esconder);
  window.addEventListener("scroll", esconder, true);
}
