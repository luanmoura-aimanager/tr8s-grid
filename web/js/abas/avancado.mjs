// abas/avancado.mjs - o bloco utility do mapa oficial da Roland + o log.
// NADA disto foi testado nesta maquina: cada botao e uma mini-sessao.
import { h, texto } from "../nucleo/dom.mjs";
import { agir } from "../app.mjs";

let logbox,
  ultimoN = 0,
  inVisor;

export default {
  id: "avancado",
  rotulo: "Avançado",

  montar(raiz) {
    const bt = (rot, op, cls = "") => {
      const b = h("button.bt" + cls, { type: "button" }, rot);
      b.onclick = () => agir({ acao: "util", op, texto: inVisor.value });
      return b;
    };
    inVisor = h("input", {
      type: "text",
      value: "TR-8S GRID",
      maxlength: 32,
      style: { width: "260px" },
      "aria-label": "texto do visor",
    });
    let armado = 0;
    const bWrite = h(
      "button.bt.bt-perigo",
      { type: "button" },
      "WRITE (salvar pattern)",
    );
    bWrite.onclick = () => {
      const agora = Date.now();
      if (agora - armado > 2000) {
        armado = agora;
        bWrite.setAttribute("data-armado", "");
        bWrite.style.setProperty("--ms", "2000ms");
        texto(bWrite, "Clique de novo (2 s)");
        setTimeout(() => {
          bWrite.removeAttribute("data-armado");
          texto(bWrite, "WRITE (salvar pattern)");
        }, 2000);
        return;
      }
      armado = 0;
      bWrite.removeAttribute("data-armado");
      texto(bWrite, "WRITE (salvar pattern)");
      agir({ acao: "util", op: "write" });
    };

    logbox = h("ol.lista", {
      style: {
        maxHeight: "220px",
        padding: "8px 24px",
        fontFamily: "var(--f-mono)",
        fontSize: "var(--t-min)",
      },
    });

    raiz.append(
      h(
        "p.aviso",
        {},
        "Comandos do mapa oficial da Roland (achados nas " +
          "capturas do ARIA). NENHUM foi testado nesta máquina: cada botão é " +
          "uma mini-sessão — observe a TR-8S e o resultado vai para a REFERENCIA.",
      ),
      h(
        "div.linha",
        {},
        bt("Está tocando?", "playing"),
        bt("Versão do firmware", "versao"),
      ),
      h("div.linha", {}, inVisor, bt("Escrever no visor", "visor")),
      h(
        "div.linha",
        {},
        bWrite,
        h(
          "span.dica",
          {},
          "grava o pattern atual na memória — o teste de " +
            "verdade é religar a máquina depois",
        ),
      ),
      h("div.secao", {}, h("h3", {}, "log"), logbox),
    );
  },

  atualizar(e) {
    // append incremental: reescrever a caixa a cada quadro destruia a selecao
    // e a posicao de rolagem do usuario 4x por segundo
    const log = e.log || [];
    if (log.length === ultimoN) return;
    const perto =
      logbox.scrollTop + logbox.clientHeight >= logbox.scrollHeight - 24;
    log.slice(ultimoN).forEach((l) => logbox.append(h("li", {}, l)));
    ultimoN = log.length;
    while (logbox.children.length > 200) logbox.firstChild.remove();
    if (perto) logbox.scrollTop = logbox.scrollHeight;
  },
};
