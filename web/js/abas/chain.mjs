// abas/chain.mjs - encadeia patterns/variacoes.
import { h, texto, attr } from "../nucleo/dom.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

const MODOS = [
  ["reescrita", "biblioteca (reescrita — funciona hoje)"],
  ["variacao", "variação A-H (requer sessão C)"],
  ["pattern", "pattern da máquina (requer sessão B)"],
  ["pc", "program change (requer sessão B)"],
];
let selModo,
  selAlvo,
  inReps,
  tbody,
  elEstado,
  entradas = [];

export default {
  id: "chain",
  rotulo: "Chain",

  montar(raiz, D) {
    selModo = h("select", { "aria-label": "modo do chain" });
    MODOS.forEach(([v, r]) => selModo.append(new Option(r, v)));
    selModo.onchange = () => {
      if (
        entradas.length &&
        !confirm("trocar de modo limpa a lista montada. Continuar?")
      ) {
        selModo.value = selModo.dataset.antes;
        return;
      }
      entradas = [];
      alvos(D);
      desenhar();
    };
    selAlvo = h("select", { "aria-label": "entrada" });
    inReps = h("input", {
      type: "number",
      min: 1,
      max: 16,
      value: 2,
      style: { width: "72px" },
      "aria-label": "repetições",
    });
    const bAdd = h("button.bt", { type: "button" }, "Adicionar");
    bAdd.onclick = () => {
      if (!selAlvo.value) return;
      entradas.push({
        alvo: selModo.value === "reescrita" ? selAlvo.value : +selAlvo.value,
        rotulo: selAlvo.options[selAlvo.selectedIndex].text,
        reps: Math.max(1, +inReps.value || 1),
      });
      desenhar();
    };
    tbody = h("tbody");
    elEstado = h("span.dica", {}, "chain desarmado");
    const bArmar = h("button.bt", { type: "button" }, "Armar");
    bArmar.onclick = () => {
      if (!entradas.length) {
        toast("adicione entradas primeiro");
        return;
      }
      agir({
        acao: "chain_armar",
        modo: selModo.value,
        entradas: entradas.map((e) => ({ alvo: e.alvo, reps: e.reps })),
      });
    };
    const bParar = h("button.bt", { type: "button" }, "Parar");
    bParar.onclick = () => agir({ acao: "chain_parar" });

    raiz.append(
      h(
        "div.linha",
        {},
        h("label", {}, "modo"),
        selModo,
        selAlvo,
        h("label", {}, "repetições"),
        inReps,
        bAdd,
      ),
      h("p.dica", {}, "no modo variação: A–H · nos modos pattern/PC: A1..H16"),
      h(
        "div.lista",
        {},
        h(
          "table",
          {},
          h(
            "thead",
            {},
            h(
              "tr",
              {},
              h("th", {}, "entrada"),
              h("th", {}, "reps"),
              h("th", {}, ""),
            ),
          ),
          tbody,
        ),
      ),
      h("div.linha", {}, bArmar, bParar, elEstado),
    );
    alvos(D);
    desenhar();
  },

  atualizar(e) {
    const c = e.chain;
    texto(
      elEstado,
      !c
        ? "chain desarmado"
        : `${c.ativo ? "ATIVO" : "parado"} · ${c.posicao + 1}/${c.total}` +
            ` · faltam ${c.reps_restantes} ciclos`,
    );
  },
};

function alvos(D) {
  selModo.dataset.antes = selModo.value;
  selAlvo.replaceChildren();
  const m = selModo.value;
  if (m === "reescrita") {
    D.biblioteca.forEach((p) => selAlvo.append(new Option(p.nome, p.id)));
  } else if (m === "variacao") {
    "ABCDEFGH"
      .split("")
      .forEach((v, i) => selAlvo.append(new Option(v, i + 1)));
  } else {
    for (const b of "ABCDEFGH") {
      for (let n = 1; n <= 16; n++) {
        selAlvo.append(new Option(b + n, "ABCDEFGH".indexOf(b) * 16 + n - 1));
      }
    }
  }
}

function desenhar() {
  tbody.replaceChildren();
  if (!entradas.length) {
    tbody.append(
      h(
        "tr",
        {},
        h(
          "td.vazio",
          { colspan: 3 },
          "nenhuma entrada — escolha acima e clique Adicionar",
        ),
      ),
    );
    return;
  }
  entradas.forEach((e, i) => {
    const b = h("button.bt.bt-peq", { type: "button" }, "remover");
    b.onclick = () => {
      entradas.splice(i, 1);
      desenhar();
    };
    tbody.append(
      h(
        "tr",
        {},
        h("td", {}, e.rotulo),
        h("td.mono", {}, e.reps),
        h("td", {}, b),
      ),
    );
  });
}
