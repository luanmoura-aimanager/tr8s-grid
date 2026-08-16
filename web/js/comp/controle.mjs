// controle.mjs - o protocolo de arrasto/commit que TODO controle usa.
//
// Corrige quatro defeitos da versao anterior:
//  1. `arrastando` era um booleano global: se o pointerup se perdesse (soltar
//     fora da janela, drag cancelado pelo SO), a tela inteira parava de
//     sincronizar PARA SEMPRE, em silencio. Agora e um Set por chave, com
//     setPointerCapture + lostpointercapture, e uma rede de seguranca em
//     window.pointerup/blur.
//  2. pointercancel COMITAVA o valor - cancelar escrevia na TR-8S. Agora
//     aborta e devolve o valor inicial.
//  3. teclado nao comitava nada (so pointerup comitava): mover com as setas
//     mexia o numero na tela e nao mandava nada para a maquina.
//  4. o valor pulava de volta (snap-back) porque a maquina so e relida a cada
//     1,5 s. Agora o valor local vale por um prazo - ver store.otimista.
import { arrastando } from "../nucleo/store.mjs";

export function ligarControle(el, { chave, ler, pintar, comitar }) {
  let inicial = null;
  let ativo = false;

  function comeco(v) {
    inicial = v;
    ativo = true;
    arrastando.add(chave);
  }
  function fim(comita, v) {
    if (!ativo) return;
    ativo = false;
    arrastando.delete(chave);
    if (comita) comitar(v);
    else pintar(inicial); // pointercancel: desfaz, nao escreve
  }

  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    el.setPointerCapture(e.pointerId);
    comeco(ler());
    e.preventDefault();
  });
  el.addEventListener("pointercancel", () => fim(false));
  el.addEventListener("lostpointercapture", () => fim(true, ler()));
  el.addEventListener("pointerup", () => fim(true, ler()));

  // rede de seguranca: se o pointerup escapar, ninguem fica preso
  window.addEventListener("pointerup", () => {
    if (ativo) fim(true, ler());
  });
  window.addEventListener("blur", () => {
    if (ativo) fim(true, ler());
  });

  return {
    arrastandoAgora: () => ativo,
    comecoManual: comeco,
    fimManual: fim,
  };
}

/** Arrasto vertical em pixels -> passos de valor (para knobs). */
export function arrastoVertical(el, { ao, curso = 200 }) {
  let y0 = 0,
    v0 = 0,
    on = false;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    on = true;
    y0 = e.clientY;
    v0 = ao.ler();
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (!on) return;
    const fino = e.shiftKey ? 0.25 : 1; // Shift = ajuste fino
    const d = ((y0 - e.clientY) / curso) * (ao.max - ao.min) * fino;
    ao.pintar(Math.round(Math.max(ao.min, Math.min(ao.max, v0 + d))));
  });
  const soltar = () => {
    on = false;
  };
  el.addEventListener("pointerup", soltar);
  el.addEventListener("pointercancel", soltar);
}
