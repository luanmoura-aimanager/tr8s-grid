// comp/secao.mjs - painel colapsavel: <details>/<summary> nativos vestidos
// com o visual do painel. Nasceu na reforma 3 para as abas longas (Efeitos)
// dobrarem o que nao esta em uso; aberto/fechado persiste por secao no
// localStorage.
//
// <details> da teclado e acessibilidade de graca, na mesma filosofia do
// fader (que e um <input type=range> girado). Sem animacao de altura: o
// atualizar() roda 4x/s e nao paga reflow de transicao. Os controles dentro
// de um details fechado continuam recebendo definir()/value= normalmente -
// atribuicao em DOM oculto e barata.
import { h } from "../nucleo/dom.mjs";

const chave = (id) => "secao:" + id;

/**
 * secaoColapsavel({id, cabecalho, corpo, aberto})
 *   id        chave de persistencia no localStorage
 *   cabecalho conteudo do summary (string ou nos: titulo, contador, barra)
 *   corpo     conteudo dobravel
 *   aberto    estado inicial na primeira visita (default false)
 */
export function secaoColapsavel({ id, cabecalho, corpo, aberto = false }) {
  const salvo = localStorage.getItem(chave(id));
  const det = h(
    "details.painel.colapsavel",
    { open: salvo === null ? aberto : salvo === "1" },
    h("summary", {}, ...[].concat(cabecalho)),
    h("div.corpo", {}, ...[].concat(corpo)),
  );
  det.addEventListener("toggle", () =>
    localStorage.setItem(chave(id), det.open ? "1" : "0"),
  );
  return det;
}
