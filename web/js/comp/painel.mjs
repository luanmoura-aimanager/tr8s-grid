// comp/painel.mjs - a unidade visual da reforma 2: painel com cabecalho no
// estilo TR-EDITOR, e o campo rotulo-em-cima.
//
// Acucar sobre h() para as abas nao repetirem estrutura. O header aceita
// filhos extras (contador, chips) via a opcao `dir` - eles entram num grupo
// alinhado a direita.
import { h } from "../nucleo/dom.mjs";

/**
 * painel("REVERB", corpo...)              -> painel simples
 * painel("REVERB", {dir:[contador]}, ...) -> com grupo a direita no header
 */
export function painel(titulo, ...filhos) {
  let dir = null;
  // opcoes = objeto plano com {dir}. O teste exige NAO ser um Node: todo
  // elemento HTML tem uma propriedade nativa `dir` (direcao de texto), e a
  // primeira versao disto engolia o primeiro filho de qualquer painel por
  // confundi-lo com as opcoes.
  if (
    filhos.length &&
    filhos[0] &&
    !(filhos[0] instanceof Node) &&
    typeof filhos[0] === "object" &&
    "dir" in filhos[0]
  ) {
    dir = filhos.shift().dir;
  }
  const header = h("header", {}, titulo);
  if (dir) header.append(h("div.h-dir", {}, ...[].concat(dir)));
  return h("div.painel", {}, header, h("div.corpo", {}, ...filhos));
}

/** campo("KIT", botao) - rotulo micro uppercase em cima, controle embaixo */
export function campo(rotulo, controle) {
  return h("div.campo", {}, h("label", {}, rotulo), controle);
}

/** toggle("Auto kit", aoMudar, ligado?) - estado vive no aria-pressed */
export function toggle(rotulo, aoMudar, ligado = false) {
  const b = h(
    "button.toggle",
    { type: "button", "aria-pressed": ligado ? "true" : "false" },
    rotulo,
  );
  b.onclick = () => {
    const novo = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", novo ? "true" : "false");
    aoMudar(novo);
  };
  return b;
}
