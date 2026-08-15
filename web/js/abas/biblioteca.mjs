// abas/biblioteca.mjs - patterns classicos por estilo, com preview.
import { h, texto, attr } from "../nucleo/dom.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

let escolhido = null,
  elNome,
  elInfo,
  elObs,
  elPrev,
  elAlvo,
  bEscrever;
let armado = 0,
  ultimo = {};

export default {
  id: "biblioteca",
  rotulo: "Biblioteca",

  montar(raiz, D) {
    const tbody = h("tbody");
    let estilo = null;
    D.biblioteca.forEach((p) => {
      if (p.estilo !== estilo) {
        estilo = p.estilo;
        tbody.append(h("tr.grupo", {}, h("td", { colspan: 2 }, estilo)));
      }
      const tr = h(
        "tr",
        {},
        h("td", {}, p.nome),
        h("td.mono", {}, p.bpm + " bpm"),
      );
      tr.onclick = () => {
        escolhido = p;
        [...tbody.children].forEach((x) => attr(x, "aria-selected", "false"));
        attr(tr, "aria-selected", "true");
        texto(elNome, p.nome);
        texto(elInfo, `${p.estilo} · ${p.bpm} bpm · kit sugerido: ${p.kit}`);
        texto(elObs, p.obs || "");
        preview(p, D);
      };
      tbody.append(tr);
    });

    elNome = h("h2", {}, "escolha um pattern");
    elInfo = h("p.dica");
    elObs = h("p.aviso");
    elPrev = h("div.prev");
    elAlvo = h("p.dica");
    bEscrever = h(
      "button.bt.bt-perigo",
      { type: "button" },
      "Escrever na TR-8S",
    );
    bEscrever.onclick = () => escrever();
    const bDesfazer = h(
      "button.bt",
      { type: "button" },
      "Desfazer última escrita",
    );
    bDesfazer.onclick = () => agir({ acao: "desfazer" });

    raiz.append(
      h(
        "div.duas",
        {},
        h("div.lista", {}, h("table", {}, tbody)),
        h(
          "div",
          {},
          elNome,
          elInfo,
          elObs,
          elPrev,
          h("div.linha", {}, bEscrever, bDesfazer),
          elAlvo,
        ),
      ),
    );
  },

  atualizar(e) {
    ultimo = e;
    attr(bEscrever, "aria-disabled", e.carregado ? null : "true");
  },
};

function escrever() {
  if (!escolhido) {
    toast("escolha um pattern na lista");
    return;
  }
  const agora = Date.now();
  if (agora - armado > 2000) {
    armado = agora;
    bEscrever.setAttribute("data-armado", "");
    bEscrever.style.setProperty("--ms", "2000ms");
    texto(bEscrever, "Clique de novo (2 s)");
    texto(
      elAlvo,
      `vai sobrescrever a variação ${ultimo.variacao_nome || "?"}` +
        (ultimo.variacao_tocando === ultimo.variacao
          ? " — que está TOCANDO agora"
          : "") +
        ". O Desfazer volta o que estava.",
    );
    setTimeout(() => {
      if (Date.now() - armado >= 2000) {
        bEscrever.removeAttribute("data-armado");
        texto(bEscrever, "Escrever na TR-8S");
        texto(elAlvo, "");
      }
    }, 2000);
    return;
  }
  armado = 0;
  bEscrever.removeAttribute("data-armado");
  texto(bEscrever, "Escrever na TR-8S");
  texto(elAlvo, "");
  agir({ acao: "biblioteca", id: escolhido.id });
}

function preview(p, D) {
  elPrev.replaceChildren();
  D.instrumentos.forEach((n) => {
    const linha = p.grade[n];
    if (!linha || !linha.some((c) => c.v)) return;
    const g = h("div.g");
    for (let s = 0; s < 16; s++) {
      const c = linha[s],
        i = h("i");
      if (s >= (p.last_var || 16)) i.style.background = "var(--c-fora)";
      else if (c.v) {
        i.style.background = c.s
          ? c.s === 1
            ? "var(--c-flam)"
            : "var(--c-sub)"
          : c.v >= 80
            ? "var(--c-nota)"
            : "var(--c-nota_fraca)";
        if (c.p < 100) i.style.opacity = 0.35 + c.p / 160;
      }
      g.append(i);
    }
    elPrev.append(h("div.l", {}, h("span.n", {}, n), g));
  });
  if (p.accent) {
    const g = h("div.g");
    for (let s = 0; s < 16; s++) {
      const i = h("i");
      if (p.accent & (1 << s)) i.style.background = "var(--c-acc)";
      g.append(i);
    }
    elPrev.append(h("div.l", {}, h("span.n", {}, "ACC"), g));
  }
}
