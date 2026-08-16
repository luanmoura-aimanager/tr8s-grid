// abas/fx.mjs - REVERB, DELAY, MASTER FX, INST FX e INSTRUMENT, como no
// TR-EDITOR.
//
// A diferenca honesta: la todos os knobs funcionam porque a Roland escreveu o
// editor. Aqui NENHUM offset e documentado - cada knob nasce FANTASMA (arco
// tracejado, valor "—") e so acende quando o offset entra no mapa, por captura
// no painel ou pelo sniff do TR-EDITOR. O contador "3/12 mapeados" de cada
// painel e, literalmente, o placar da engenharia reversa.
import { h, $, texto, attr, prop } from "../nucleo/dom.mjs";
import { knob } from "../comp/knob.mjs";
import { rotuloValor } from "../nucleo/formato.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

let raizEl,
  D_,
  instSel = 0,
  paineis = [];
const controles = new Map(); // nome -> {tipo:"knob"|"enum", ...}

export default {
  id: "fx",
  rotulo: "Efeitos",

  montar(raiz, D) {
    raizEl = raiz;
    D_ = D;

    // fileira BD-RC: vale para os paineis por instrumento (INST e INST FX)
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
        instSel = i;
        [...tabs.children].forEach((x) =>
          attr(x, "aria-pressed", +x.dataset.i === i ? "true" : "false"),
        );
      };
      tabs.append(b);
    });

    raiz.append(
      caminhoAudio(),
      h("div.linha", {}, h("label", {}, "instrumento (painéis INST)"), tabs),
      h(
        "p.aviso",
        {},
        "Nenhum offset de efeito é documentado pela Roland: " +
          "knob apagado = ainda não descoberto. Clique nele para capturar pelo " +
          "painel, ou faça a sessão de sniff do TR-EDITOR para destravar " +
          "vários de uma vez.",
      ),
    );

    (D.paineis_fx || []).forEach((pn) => raiz.append(montarPainel(pn, D)));
  },

  atualizar(e, D) {
    const mapa = e.mapa_fx || {},
      fx = e.fx || {};
    ultimoMapa = mapa;
    paineis.forEach((pn) => {
      // seletor de tipo do painel (REVERB tipo, MFX tipo...)
      let tipoAtual = null;
      if (pn.def.seletor) {
        const ent = mapa[pn.def.seletor];
        const v = ent ? fx[pn.def.seletor] : null;
        tipoAtual =
          ent && v != null ? (ent.opcoes || {})[String(v)] || null : null;
        pn.chips.forEach((b) => {
          attr(
            b,
            "aria-pressed",
            b.dataset.tipo === (tipoAtual || pn.visivel) ? "true" : "false",
          );
          attr(b, "data-confirmado", tipoAtual === b.dataset.tipo ? "" : null);
        });
      }
      // mostra o bloco do tipo escolhido (ou do que a maquina diz)
      const alvo = tipoAtual || pn.visivel;
      Object.entries(pn.blocos).forEach(([t, el]) => {
        el.hidden = t !== alvo;
      });

      // progresso
      const nomes = pn.nomesDe(alvo);
      const feitos = nomes.filter((n) => n in mapa).length;
      texto(pn.contador, `${feitos}/${nomes.length} mapeados`);
      prop(pn.barra, "--p", nomes.length ? feitos / nomes.length : 0);
    });

    // valores e estado fantasma de cada controle
    for (const [nome, c] of controles) {
      const ent = mapa[nome];
      const bruto = fx[nome];
      const v = Array.isArray(bruto) ? bruto[instSel] : bruto;
      if (c.tipo === "knob") {
        c.knob.definir(ent ? (v === undefined ? null : v) : null, {
          fantasma: !ent,
        });
        if (ent && !c.acendeu) {
          c.acendeu = true;
          c.knob.acender();
        }
      } else {
        // Opcoes ANOTADAS (codigo lido da maquina + rotulo do visor) valem
        // mais que as do manual, porque codigo nem sempre segue a ordem do
        // menu: o INST FX tem a 1a opcao no codigo 12 e a 10a no codigo 0.
        // Sem anotacao, usa a lista do manual como PRESUMIDA e diz isso com
        // um "?" - melhor um seletor util e honesto que um vazio.
        const anot = (ent && ent.opcoes) || {};
        const presumido =
          !Object.keys(anot).length && ent && (ent.sugestoes || []).length;
        const opts = presumido
          ? Object.fromEntries(ent.sugestoes.map((r, i) => [i, r + " ?"]))
          : anot;
        const chave =
          (presumido ? "p:" : "a:") + Object.keys(opts).sort().join(",");
        if (c.chaveOpcoes !== chave) {
          c.chaveOpcoes = chave;
          c.sel.replaceChildren();
          if (!Object.keys(opts).length) {
            c.sel.append(
              new Option(ent ? "(nenhuma opção anotada)" : "(não mapeado)", ""),
            );
          }
          Object.entries(opts)
            .sort((a, b) => a[0] - b[0])
            .forEach(([cod, rot]) => c.sel.append(new Option(rot, cod)));
          c.sel.title = presumido
            ? "ordem presumida do manual — confira no visor da TR-8S"
            : "";
        }
        c.sel.disabled = !ent;
        if (v != null && c.sel.value !== String(v)) c.sel.value = String(v);
        attr(c.raiz, "data-fantasma", ent ? null : "");
      }
    }
  },
};

function montarPainel(pn, D) {
  const chips = [];
  const blocos = {};
  const contador = h("span.dica");
  const barra = h("div.barra", {}, h("i"));
  const corpoComuns = h("div.knobs");
  pn.comuns.forEach((nome) => corpoComuns.append(controle(nome, D)));

  const cabecalho = h("div.linha", {}, h("h3", {}, pn.rotulo), contador, barra);

  const chipsCx = h("div.chips");
  (pn.tipos || []).forEach((t) => {
    const b = h("button.bt.bt-peq", { type: "button", "data-tipo": t }, t);
    b.onclick = () => {
      estado.visivel = t;
      // trocar o tipo na maquina so vale se o seletor ja foi mapeado e a
      // opcao anotada; senao e so navegacao visual
      const nome = pn.seletor;
      const ent = (ultimoMapa || {})[nome];
      const cod =
        ent && Object.entries(ent.opcoes || {}).find(([, r]) => r === t);
      if (cod)
        agir({
          acao: "fx",
          nome,
          valor: +cod[0],
          inst: pn.escopo === "kit" ? null : instSel,
        });
      else
        toast(
          `mostrando ${t} — para trocar de verdade, mapeie "${nome}" ` +
            "e anote as opções",
        );
      atualizarVisivel();
    };
    chips.push(b);
    chipsCx.append(b);
    const bloco = h("div.knobs", { hidden: true });
    (pn.por_tipo[t] || []).forEach((nome) => bloco.append(controle(nome, D)));
    blocos[t] = bloco;
  });

  const estado = {
    def: pn,
    chips,
    blocos,
    contador,
    barra,
    visivel: (pn.tipos || [])[0] || null,
    nomesDe: (t) => [
      ...pn.comuns,
      ...(t && pn.por_tipo[t] ? pn.por_tipo[t] : []),
    ],
  };
  paineis.push(estado);
  function atualizarVisivel() {
    Object.entries(blocos).forEach(([t, el]) => {
      el.hidden = t !== estado.visivel;
    });
  }

  const cx = h(
    "div.secao.cartao",
    {},
    cabecalho,
    pn.seletor ? h("div.linha", {}, h("label", {}, "tipo"), chipsCx) : null,
    corpoComuns,
    ...Object.values(blocos),
  );
  if (pn.escopo === "inst") {
    cabecalho.append(h("span.chip", {}, "por instrumento"));
  }
  atualizarVisivel();
  return cx;
}

let ultimoMapa = {};

function controle(nome, D) {
  const cat = (D.catalogo_fx || []).find((c) => c.nome === nome) || {};
  if (cat.forma === "enum") {
    const sel = h("select", { "aria-label": nome, disabled: true });
    const raiz = h(
      "div.linha",
      { "data-dica": cat.dica || nome },
      h("label", {}, cat.rot || nome),
      sel,
    );
    sel.onchange = () => {
      const ent = (ultimoMapa || {})[nome];
      if (!ent || !sel.value) return;
      agir({
        acao: "fx",
        nome,
        valor: +sel.value,
        inst: cat.escopo === "kit" ? null : instSel,
      });
    };
    raiz.addEventListener("click", () => {
      if (!(ultimoMapa || {})[nome]) capturar(nome, cat);
    });
    controles.set(nome, { tipo: "enum", sel, raiz });
    return raiz;
  }
  const k = knob({
    rotulo: cat.rot || nome,
    min: 0,
    max: cat.max || 255,
    chave: nome,
    bipolar: !!cat.bipolar,
    dica: cat.dica || "",
    formatar: (v) =>
      rotuloValor({ ...cat, opcoes: {} }, v) +
      (cat.unidade ? " " + cat.unidade : ""),
    fantasma: true,
    aoCapturar: () => capturar(nome, cat),
    aoSoltar: (v) =>
      agir({
        acao: "fx",
        nome,
        valor: v,
        inst: cat.escopo === "kit" ? null : instSel,
      }),
  });
  controles.set(nome, { tipo: "knob", knob: k });
  return k.raiz;
}

function capturar(nome, cat) {
  toast(
    `capturando “${nome}” — no painel: ${cat.dica || "?"}` +
      (cat.bytes === 2 ? " · gire de ponta a ponta" : ""),
    { ttl: 9000 },
  );
  agir({ acao: "capturar", nome });
}

// guarda o mapa para os handlers (evita passar estado por closure velha)
export function guardarMapa(mapa) {
  ultimoMapa = mapa || {};
}

/** o caminho do sinal (Reference p.56) - explica por que cada painel existe */
function caminhoAudio() {
  const etapas = [
    "TONE",
    "INST FX",
    "LEVEL",
    "GAIN",
    "PAN",
    "SENDS",
    "MIX",
    "MASTER FX",
    "OUT",
  ];
  const cx = h("div.linha", { style: { gap: "4px", marginBottom: "8px" } });
  etapas.forEach((e, i) => {
    cx.append(h("span.chip", {}, e));
    if (i < etapas.length - 1) cx.append(h("span.dica", {}, "→"));
  });
  return h("div", {}, h("h3", {}, "caminho do sinal"), cx);
}
