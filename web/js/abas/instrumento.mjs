// abas/instrumento.mjs - o gesto INST do TR-EDITOR: fileira BD-RC sempre
// visivel, e a lista de tones da categoria.
import { h, $, texto, attr } from "../nucleo/dom.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

const CAT_INST = {
  0: "BD",
  1: "SD",
  2: "TOM",
  3: "TOM",
  4: "TOM",
  5: "RS",
  6: "HC",
  7: "CH_OH",
  8: "CH_OH",
  9: "CC_RC",
  10: "CC_RC",
};
let inst = 0,
  selCat,
  corpo,
  elAtual,
  tbody,
  escolhido = null,
  catMontada = "";

export default {
  id: "instrumento",
  rotulo: "Instrumento",

  montar(raiz, D) {
    const tabs = h("div.inst-tabs");
    D.instrumentos.forEach((n, i) => {
      const b = h(
        "button.bt",
        {
          type: "button",
          "data-i": i,
          "aria-pressed": i === 0 ? "true" : "false",
        },
        n,
      );
      b.onclick = () => {
        inst = i;
        [...tabs.children].forEach((x) =>
          attr(x, "aria-pressed", +x.dataset.i === i ? "true" : "false"),
        );
        selCat.value = CAT_INST[i];
        montarTones(D);
      };
      tabs.append(b);
    });

    selCat = h("select", { "aria-label": "categoria de tone" });
    [...new Set(D.tones.map((t) => t.cat))].forEach((c) =>
      selCat.append(new Option(c, c)),
    );
    selCat.value = CAT_INST[0];
    selCat.onchange = () => montarTones(D);

    const bReler = h("button.bt.bt-peq", { type: "button" }, "Reler kit");
    bReler.onclick = () => agir({ acao: "ler_kit" });
    const bAplicar = h("button.bt", { type: "button" }, "Trocar o tone");
    bAplicar.onclick = () => {
      if (escolhido === null) {
        toast("escolha um tone na lista");
        return;
      }
      agir({ acao: "tone", inst, tone_id: escolhido });
    };

    elAtual = h("p.dica", {}, "—");
    tbody = h("tbody");
    corpo = h(
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
            h("th", {}, "id"),
            h("th", {}, "nome"),
            h("th", {}, "tipo"),
          ),
        ),
        tbody,
      ),
    );

    raiz.append(
      h("div.linha", {}, tabs),
      h("div.linha", {}, h("label", {}, "categoria"), selCat, bReler, bAplicar),
      elAtual,
      h(
        "p.aviso",
        {},
        "id → nome é HIPÓTESE (posição na Preset Tone List); " +
          "a escrita nunca foi testada — toque o pad e confira o som e o visor. " +
          "CTRL e INST FX ainda não foram decodificados.",
      ),
      corpo,
    );
    montarTones(D);
  },

  atualizar(e, D) {
    const tid = (e.tone_ids || [])[inst];
    const t = tid == null ? null : D.tones.find((x) => x.id === tid);
    texto(
      elAtual,
      `kit “${e.kit_nome || "?"}” · ${D.instrumentos[inst]}: ` +
        (tid == null
          ? "tone ainda não lido"
          : `id ${tid} = ` +
            (t
              ? `${t.nome} (${t.cat} ${t.tipo})`
              : "fora da lista de presets (sample?)")),
    );
  },
};

function montarTones(D) {
  const cat = selCat.value;
  if (catMontada === cat) return;
  catMontada = cat;
  escolhido = null;
  tbody.replaceChildren();
  D.tones
    .filter((t) => t.cat === cat)
    .forEach((t) => {
      const tr = h(
        "tr",
        {},
        h("td.mono", {}, t.id),
        h("td", {}, t.nome),
        h("td", {}, t.tipo),
      );
      tr.onclick = () => {
        escolhido = t.id;
        [...tbody.children].forEach((x) => attr(x, "aria-selected", "false"));
        attr(tr, "aria-selected", "true");
      };
      tr.ondblclick = () => agir({ acao: "tone", inst, tone_id: t.id });
      tbody.append(tr);
    });
}
