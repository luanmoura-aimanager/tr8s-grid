// abas/mixer.mjs - probability por instrumento + os parametros ja mapeados +
// a ferramenta de captura.
//
// E a sala de maquinas da engenharia reversa: nenhum offset de FX e
// documentado, entao cada controle aqui existe porque alguem (o Luan, no
// painel) o revelou. O que ainda nao foi revelado aparece na lista de captura,
// com o gesto do painel ao lado - nunca como um knob que finge funcionar.
import { h, $, texto, attr, reconciliar } from "../nucleo/dom.mjs";
import { fader } from "../comp/fader.mjs";
import { knob } from "../comp/knob.mjs";
import { rotuloValor } from "../nucleo/formato.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

let faderProb = [],
  elFx,
  elCat,
  selCat,
  dicaCat,
  bCapturar,
  selEnum,
  selRot,
  selInst,
  montados = "",
  controles = new Map();

export default {
  id: "mixer",
  rotulo: "Mixer & FX",

  montar(raiz, D) {
    // ── probability por instrumento ──
    const fila = h("div.fila-inst", {}, h("div.rot-fila", {}, "PROB %"));
    D.instrumentos.forEach((nome, i) => {
      const f = fader({
        rotulo: nome,
        min: 10,
        max: 100,
        chave: "prob" + i,
        aoSoltar: (v) => agir({ acao: "prob_inst", inst: i, pct: v }),
      });
      faderProb.push(f);
      fila.append(f.raiz);
    });

    elFx = h("div");

    // ── captura ──
    selCat = h("select", { id: "sel-cat", "aria-label": "parâmetro a mapear" });
    selCat.onchange = () => pintarDica(D);
    dicaCat = h("p.aviso");
    bCapturar = h("button.bt", { type: "button" }, "Capturar");
    bCapturar.onclick = () => {
      if (ultimoEstado && ultimoEstado.captura_fx)
        agir({ acao: "cancelar_captura" });
      else if (selCat.value) agir({ acao: "capturar", nome: selCat.value });
      else toast("escolha um parâmetro na lista");
    };
    selEnum = h("select", { "aria-label": "parâmetro de lista" });
    selEnum.onchange = () => pintarSugestoes(D);
    selRot = h("select", { "aria-label": "opção que está no visor" });
    const bAnotar = h("button.bt.bt-peq", { type: "button" }, "Anotar");
    bAnotar.onclick = () => {
      const nome = selEnum.value;
      if (!nome) {
        toast("capture um parâmetro de lista primeiro");
        return;
      }
      const ent = (ultimoEstado.mapa_fx || {})[nome] || {};
      agir({
        acao: "anotar_opcao",
        nome,
        rotulo: selRot.value,
        inst: ent.tipo === "kit" ? null : +selInst.value,
      });
    };
    selInst = h("select", { "aria-label": "instrumento das listas" });
    D.instrumentos.forEach((n, i) => selInst.append(new Option(n, i)));
    const bReler = h("button.bt.bt-peq", { type: "button" }, "Reler valores");
    bReler.onclick = () => agir({ acao: "ler_fx" });

    elCat = h(
      "div.cartao",
      {},
      h("h3", {}, "mapear parâmetro novo"),
      h(
        "p.dica",
        {},
        "A Roland não documenta nenhum offset de efeito. " +
          "Escolha o parâmetro, clique Capturar e mexa SÓ nesse controle no " +
          "painel da TR-8S — o app acha o byte que mudou. Nos de 2 bytes, " +
          "gire de ponta a ponta.",
      ),
      h("div.linha", {}, selCat, bCapturar),
      dicaCat,
      h(
        "div.linha",
        {},
        h("label", {}, "anotar opção de lista"),
        selEnum,
        selRot,
        bAnotar,
      ),
      h(
        "div.linha",
        {},
        h("label", {}, "instrumento das listas"),
        selInst,
        bReler,
      ),
    );

    raiz.append(
      h(
        "div.secao",
        {},
        h("h3", {}, "probability por instrumento"),
        h(
          "p.dica",
          {},
          "solta o fader e escreve em todos os steps ligados do " +
            "instrumento; “—” quer dizer que os steps têm valores diferentes",
        ),
        fila,
      ),
      h("div.secao", {}, h("h3", {}, "parâmetros mapeados"), elFx),
      elCat,
    );
  },

  atualizar(e, D) {
    ultimoEstado = e;
    (e.probs_inst || []).forEach(
      (p, i) =>
        faderProb[i] &&
        faderProb[i].definir(p === null ? null : p, { off: p === null }),
    );
    montarMapeados(e, D);
    montarCatalogo(e, D);
    texto(bCapturar, e.captura_fx ? `Cancelar “${e.captura_fx}”` : "Capturar");
    attr(bCapturar, "aria-pressed", e.captura_fx ? "true" : "false");
  },
};

let ultimoEstado = {};

function montarMapeados(e, D) {
  const mapa = e.mapa_fx || {};
  const chave = JSON.stringify(Object.keys(mapa).sort());
  if (chave !== montados) {
    montados = chave;
    controles.clear();
    elFx.replaceChildren();
    const nomes = Object.keys(mapa).sort();
    if (!nomes.length) {
      elFx.append(
        h(
          "p.vazio",
          {},
          "nada mapeado ainda — use a caixa abaixo, " +
            "ou faça a sessão de sniff do TR-EDITOR para destravar vários de uma vez",
        ),
      );
    }
    const grupos = {};
    nomes.forEach((n) => (grupos[mapa[n].grupo || "OUTROS"] ||= []).push(n));
    Object.keys(grupos)
      .sort()
      .forEach((g) => {
        const cx = h("div.secao", {}, h("h3", {}, g));
        grupos[g].forEach((nome) => cx.append(linhaParam(nome, mapa[nome], D)));
        elFx.append(cx);
      });
  }
  // valores
  const fx = e.fx || {};
  for (const [nome, ctl] of controles) {
    const ent = mapa[nome];
    if (!ent) continue;
    const v = fx[nome];
    if (ent.forma === "enum") {
      const val = Array.isArray(v) ? v[+selInst.value] : v;
      const rot = (ent.opcoes || {})[String(val)] || "";
      if (ctl.el.value !== rot) ctl.el.value = rot;
    } else if (ent.tipo === "inst") {
      (Array.isArray(v) ? v : []).forEach(
        (vi, i) =>
          ctl.faders[i] && ctl.faders[i].definir(vi === undefined ? null : vi),
      );
    } else if (ctl.knob) {
      ctl.knob.definir(v === undefined ? null : v);
    }
  }
}

function linhaParam(nome, ent, D) {
  const fmt = (v) => rotuloValor(ent, v);
  if (ent.forma === "enum") {
    const sel = h("select", { "aria-label": nome });
    const ops = ent.opcoes || {};
    if (!Object.keys(ops).length)
      sel.append(new Option("(nenhuma opção anotada)", ""));
    Object.entries(ops)
      .sort((a, b) => a[0] - b[0])
      .forEach(([cod, rot]) => sel.append(new Option(rot, rot)));
    sel.onchange = () => {
      const cod = Object.entries(ops).find(([, r]) => r === sel.value);
      if (cod)
        agir({
          acao: "fx",
          nome,
          valor: +cod[0],
          inst: ent.tipo === "kit" ? null : +selInst.value,
        });
    };
    controles.set(nome, { el: sel });
    return h(
      "div.linha",
      {},
      h("label", {}, nome),
      sel,
      ent.tipo === "inst"
        ? h("span.dica", {}, "(do instrumento escolhido)")
        : null,
      botaoEsquecer(nome),
    );
  }
  if (ent.tipo === "inst") {
    const fila = h("div.fila-inst", {}, h("div.rot-fila", {}, nome));
    const faders = D.instrumentos.map((n, i) => {
      const f = fader({
        rotulo: n,
        min: ent.min,
        max: ent.max,
        chave: nome + i,
        formatar: fmt,
        aoSoltar: (v) => agir({ acao: "fx", nome, valor: v, inst: i }),
      });
      fila.append(f.raiz);
      return f;
    });
    fila.append(botaoEsquecer(nome));
    controles.set(nome, { faders });
    return fila;
  }
  const k = knob({
    rotulo: nome,
    min: ent.min,
    max: ent.max,
    chave: nome,
    bipolar: !!ent.bipolar,
    formatar: fmt,
    aoSoltar: (v) => agir({ acao: "fx", nome, valor: v, inst: null }),
  });
  controles.set(nome, { knob: k });
  return h("div.linha", {}, k.raiz, botaoEsquecer(nome));
}

function botaoEsquecer(nome) {
  const b = h(
    "button.bt.bt-peq",
    { type: "button", "data-dica": "tira do mapa para recapturar do zero" },
    "esquecer",
  );
  b.onclick = () => agir({ acao: "esquecer_fx", nome });
  return b;
}

function montarCatalogo(e, D) {
  const mapa = e.mapa_fx || {};
  const faltam = (D.catalogo_fx || []).filter((p) => !(p.nome in mapa));
  const chave = faltam.map((p) => p.nome).join("|");
  if (selCat.dataset.chave !== chave) {
    selCat.dataset.chave = chave;
    selCat.replaceChildren();
    faltam.forEach((p) =>
      selCat.append(new Option(`${p.grupo} · ${p.nome}`, p.nome)),
    );
    pintarDica(D);
  }
  const enums = Object.entries(mapa)
    .filter(([, x]) => x.forma === "enum")
    .map(([n]) => n);
  if (selEnum.dataset.chave !== enums.join("|")) {
    selEnum.dataset.chave = enums.join("|");
    selEnum.replaceChildren();
    enums.forEach((n) => selEnum.append(new Option(n, n)));
    pintarSugestoes(D);
  }
}

function pintarDica(D) {
  const p = (D.catalogo_fx || []).find((x) => x.nome === selCat.value);
  texto(
    dicaCat,
    p
      ? `no painel: ${p.dica}` +
          (p.bytes === 2 ? " · 2 bytes: gire de ponta a ponta" : "") +
          (p.forma === "enum"
            ? " · é uma LISTA: capture e depois anote as opções"
            : "")
      : "",
  );
}
function pintarSugestoes(D) {
  const cat = (D.catalogo_fx || []).find((x) => x.nome === selEnum.value);
  selRot.replaceChildren();
  ((cat && cat.opcoes) || []).forEach((o) => selRot.append(new Option(o, o)));
  if (!selRot.options.length) selRot.append(new Option("(sem sugestão)", ""));
}
