// dom.mjs - o minimo para montar e atualizar DOM sem framework.
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/** h("button.bt", {onclick, "aria-pressed":"true"}, "texto", filho) */
export function h(tag, props = {}, ...filhos) {
  const [nome, ...cls] = String(tag).split(".");
  const el = document.createElement(nome || "div");
  if (cls.length) el.className = cls.join(" ");
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function")
      el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.className += " " + v;
    else if (k === "texto") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    el.append(f.nodeType ? f : document.createTextNode(String(f)));
  }
  return el;
}

export function svg(tag, props = {}, ...filhos) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
  }
  filhos.flat().forEach((f) => f && el.append(f));
  return el;
}

/** Escreve so quando muda: metade do custo de render vem de evitar isso. */
export function texto(el, v) {
  const s = v === null || v === undefined ? "" : String(v);
  if (el.textContent !== s) el.textContent = s;
}
export function attr(el, k, v) {
  if (v === null || v === undefined || v === false) {
    if (el.hasAttribute(k)) el.removeAttribute(k);
  } else {
    const s = v === true ? "" : String(v);
    if (el.getAttribute(k) !== s) el.setAttribute(k, s);
  }
}
export function prop(el, k, v) {
  if (el.style.getPropertyValue(k) !== String(v)) el.style.setProperty(k, v);
}

/**
 * Reconcilia uma lista por chave, criando/atualizando/removendo o minimo.
 * O mapa fica num WeakMap, nao no dataset - dataset como banco de estado foi
 * fonte de bug na versao anterior.
 */
const mapas = new WeakMap();
export function reconciliar(pai, itens, chaveDe, criar, atualizar) {
  let mapa = mapas.get(pai);
  if (!mapa) mapas.set(pai, (mapa = new Map()));
  const vistos = new Set();
  itens.forEach((item, i) => {
    const k = chaveDe(item, i);
    vistos.add(k);
    let el = mapa.get(k);
    if (!el) {
      el = criar(item, i);
      mapa.set(k, el);
      pai.append(el);
    }
    atualizar && atualizar(el, item, i);
  });
  for (const [k, el] of mapa) {
    if (!vistos.has(k)) {
      el.remove();
      mapa.delete(k);
    }
  }
}
