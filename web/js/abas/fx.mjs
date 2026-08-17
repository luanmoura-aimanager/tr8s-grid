// abas/fx.mjs - REVERB, DELAY, MASTER FX, INST FX e INSTRUMENT, como no
// TR-EDITOR.
//
// A diferenca honesta: la todos os knobs funcionam porque a Roland escreveu o
// editor. Aqui NENHUM offset e documentado - cada knob nasce FANTASMA (arco
// tracejado, valor "—") e so acende quando o offset entra no mapa, por captura
// no painel ou pelo sniff do TR-EDITOR. O contador "3/12 mapeados" de cada
// painel e, literalmente, o placar da engenharia reversa.
import { h, texto, attr, prop } from "../nucleo/dom.mjs";
import { knob } from "../comp/knob.mjs";
import { painel, campo } from "../comp/painel.mjs";
import { secaoColapsavel } from "../comp/secao.mjs";
import { rotuloValor, faixaDoCatalogo } from "../nucleo/formato.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

// ultimoE guarda o ultimo quadro do polling: e o que deixa a troca de
// instrumento repintar na hora, sem esperar o proximo GET /estado
let instSel = 0,
  ultimoE = null,
  paineis = [];
const controles = new Map(); // nome -> {tipo:"knob"|"enum", ...}

export default {
  id: "fx",
  rotulo: "Efeitos",

  montar(raiz, D) {
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
        // repinta com o ultimo estado na hora: sem isso a troca de
        // instrumento so aparecia no proximo quadro do polling (ate 250 ms)
        if (ultimoE) pintarEstado(ultimoE);
      };
      tabs.append(b);
    });

    // POR INSTRUMENTO x MASTER/KIT: a separacao que faltava. Os paineis de
    // escopo "inst" (INSTRUMENT, INST FX) entram no primeiro grupo junto
    // com o SENDS e o CTRL; os de kit no segundo, e DOBRAM: sao seis
    // paineis compridos com um ou dois em uso por vez - REVERB e DELAY
    // nascem abertos, o resto fechado (o estado persiste por secao).
    const porInst = [];
    const master = [];
    (D.paineis_fx || []).forEach((pn) => {
      if (pn.escopo === "inst") porInst.push(montarPainel(pn, D));
      else
        master.push(
          montarPainel(pn, D, {
            colapsavel: true,
            aberto: pn.id === "reverb" || pn.id === "delay",
          }),
        );
    });

    raiz.append(
      caminhoAudio(),
      painel(
        "Por instrumento",
        { dir: [tabs] },
        montarSends(D),
        montarCtrl(D),
        ...porInst,
      ),
      painel("Master / Kit", ...master),
    );
  },

  atualizar(e) {
    ultimoE = e;
    pintarEstado(e);
  },
};

function pintarEstado(e) {
  const mapa = e.mapa_fx || {},
    fx = e.fx || {};
  ultimoMapa = mapa;

  // sends: um knob por instrumento, direto dos arrays do estado
  for (const [nome, ks] of Object.entries(sendsKnobs)) {
    const vals = fx[nome];
    ks.forEach((k, i) =>
      k.definir(Array.isArray(vals) ? (vals[i] ?? null) : null),
    );
  }
  // fileira CTRL: opcoes do mapa (uma vez), valores dos arrays de 11
  pintarCtrl(mapa, fx);
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
        } else {
          // placeholder na frente: sem ele o select mostrava a PRIMEIRA opcao
          // ("OFF", "Tune") quando o valor ainda nao foi lido - dizia que a
          // maquina esta num destino que ninguem leu. Mesmo "—" da fileira
          // CTRL e dos knobs.
          c.sel.append(new Option("—", ""));
        }
        Object.entries(opts)
          .sort((a, b) => a[0] - b[0])
          .forEach(([cod, rot]) => c.sel.append(new Option(rot, cod)));
        c.sel.title = presumido
          ? "ordem presumida do manual — confira no visor da TR-8S"
          : "";
      }
      c.sel.disabled = !ent;
      // valor nulo volta ao "—": o motor desligado (ou bloco ainda nao lido)
      // nao pode parecer uma leitura
      const alvoSel = v == null ? "" : String(v);
      if (c.sel.value !== alvoSel) c.sel.value = alvoSel;
      attr(c.raiz, "data-fantasma", ent ? null : "");
    }
  }
}

function montarPainel(pn, D, op = {}) {
  const chips = [];
  const blocos = {};
  const contador = h("span.dica");
  const barra = h("div.barra", {}, h("i"));
  const corpoComuns = h("div.knobs");
  pn.comuns.forEach((nome) => corpoComuns.append(controle(nome, D)));

  // painel com cabecalho (reforma 2): contador e barra moram no header -
  // ou no summary, quando o painel dobra (op.colapsavel)
  const hDir = h("div.h-dir", {}, contador, barra);

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

  if (pn.escopo === "inst") {
    hDir.append(h("span.chip", {}, "por instrumento"));
  }
  const corpo = [
    pn.seletor ? h("div.linha", {}, h("label", {}, "tipo"), chipsCx) : null,
    corpoComuns,
    ...Object.values(blocos),
  ];
  atualizarVisivel();
  // Master/Kit dobra: o cabecalho (titulo + contador/barra) vira o summary,
  // entao o placar de mapeados continua visivel mesmo com a secao fechada
  if (op.colapsavel)
    return secaoColapsavel({
      id: "fx-" + pn.id,
      cabecalho: [pn.rotulo, hDir],
      corpo,
      aberto: !!op.aberto,
    });
  return h(
    "div.painel",
    {},
    h("header", {}, pn.rotulo, hDir),
    h("div.corpo", {}, ...corpo),
  );
}

let ultimoMapa = {};

// ── SENDS: fileiras de 11 knobs, um por instrumento ────────
// Como no TR-EDITOR: reverb send e delay send lado a lado para o kit todo.
// Fora do Map `controles` (que resolve pelo instrumento selecionado): aqui
// cada knob e um instrumento fixo, e fx["inst reverb send"] ja chega do
// motor como array de 11. Offsets provados em hardware - sem fantasma.
const sendsKnobs = {
  "inst reverb send": [],
  "inst delay send": [],
  // pedido de 17/08/2026: o LFO DEPTH de cada instrumento na mesma forma dos
  // sends. E bipolar (centro em 128) e o catalogo e quem diz isso
  "inst lfo depth": [],
};

function montarSends(D) {
  const fileira = (nome, rotulo) => {
    const cx = h("div.fila-inst", {}, h("div.rot-fila", {}, rotulo));
    D.instrumentos.forEach((n, i) => {
      const k = knob({
        rotulo: n,
        ...faixaDoCatalogo(D, nome),
        chave: `${nome}:${i}`,
        aoSoltar: (v) => agir({ acao: "fx", nome, valor: v, inst: i }),
      });
      sendsKnobs[nome].push(k);
      cx.append(k.raiz);
    });
    return cx;
  };
  return painel(
    "Sends e LFO",
    fileira("inst reverb send", "REVERB"),
    fileira("inst delay send", "DELAY"),
    fileira("inst lfo depth", "LFO DEPTH"),
    h(
      "p.dica",
      {},
      "o LFO tem UM destino por instrumento (Tune, Decay, Level, Pan…) — ele " +
        "fica no painel INSTRUMENT, que segue o seletor BD…RC lá em cima",
    ),
  );
}

// ── CTRL: fileira de dropdowns estilo TR-EDITOR ────────────
// O que o knob CTRL fisico de cada coluna controla. Offsets provados por
// sniff (bloco 06, um byte em 0x01+i), mas a ESCRITA pela nossa ponta ainda
// nao foi ouvida em hardware - a primeira troca merece girar o knob e ouvir.
// Como nos Sends, cada select e um instrumento FIXO por posicao (nao segue o
// seletor BD..RC do topo); os valores chegam como array de 11.
const ctrlSels = [];
let ctrlKitSel = null,
  ctrlFila = null,
  ctrlOpcoes = "";

function montarCtrl(D) {
  ctrlKitSel = h("select", { "aria-label": "modo do knob CTRL (kit)" });
  ctrlKitSel.onchange = () => {
    if (ctrlKitSel.value === "") return;
    agir({
      acao: "fx",
      nome: "kit ctrl select",
      valor: +ctrlKitSel.value,
      inst: null,
    });
  };
  ctrlFila = h(
    "div.fila-inst.fila-ctrl",
    {
      "data-dica":
        "códigos 6+ são parâmetros do tone — cada tone expõe só alguns, " +
        "e o visor da TR-8S é quem confirma. Morph (tones FM) ainda não " +
        "tem código medido e fica de fora",
    },
    h("div.rot-fila", {}, "CTRL"),
  );
  D.instrumentos.forEach((n, i) => {
    const sel = h("select", { "aria-label": "CTRL do " + n });
    sel.onchange = () => {
      if (sel.value === "") return;
      agir({
        acao: "fx",
        nome: "inst ctrl select",
        valor: +sel.value,
        inst: i,
      });
    };
    ctrlSels.push(sel);
    ctrlFila.append(campo(n, sel));
  });
  return painel(
    "CTRL",
    h(
      "div.linha",
      {},
      h("label", {}, "modo do knob CTRL (kit)"),
      ctrlKitSel,
      h(
        "span.dica",
        {},
        "a fileira por instrumento só vale com o modo em User — " +
          "leitura do manual, não protocolo medido",
      ),
    ),
    ctrlFila,
  );
}

function pintarCtrl(mapa, fx) {
  if (!ctrlKitSel) return;
  const entI = mapa["inst ctrl select"];
  const entK = mapa["kit ctrl select"];
  // opcoes sao estaticas (PARAMS_FIXOS): materializa uma vez quando chegam
  const chave = entI
    ? Object.keys(entI.opcoes || {}).length +
      "|" +
      Object.keys((entK && entK.opcoes) || {}).length
    : "";
  if (chave && ctrlOpcoes !== chave) {
    ctrlOpcoes = chave;
    const encher = (sel, opcoes, agrupar) => {
      sel.replaceChildren(new Option("—", ""));
      // Os codigos 0-5 existem em QUALQUER instrumento (efeitos.CTRL_FIXOS);
      // do 6 em diante sao parametros de TONE, e cada tone expoe so alguns -
      // o BD nao tem Snappy, o SD nao tem Color. Nao existe tabela
      // tone -> parametros em lugar nenhum (o ToneDetailsConfigTable.dat da
      // Roland so traz numero/categoria/tipo/nome), entao a lista nao tem
      // como filtrar; o que ela pode fazer e nao MENTIR que tudo serve.
      const grupos = agrupar
        ? {
            "sempre disponíveis": (c) => +c < 6,
            "do tone — só se este tone tiver": (c) => +c >= 6,
          }
        : { "": () => true };
      Object.entries(grupos).forEach(([rotulo, filtro]) => {
        const alvo = rotulo
          ? sel.appendChild(h("optgroup", { label: rotulo }))
          : sel;
        Object.entries(opcoes)
          .filter(([cod]) => filtro(cod))
          .sort((a, b) => a[0] - b[0])
          .forEach(([cod, rot]) => alvo.append(new Option(rot, cod)));
      });
    };
    ctrlSels.forEach((sel) => encher(sel, entI.opcoes || {}, true));
    encher(ctrlKitSel, (entK && entK.opcoes) || {}, false);
  }
  // codigo que a maquina reporta e a lista nao tem (Morph dos tones FM, e
  // qualquer codigo acima do 23 que ainda nao foi medido): sem isto o select
  // caia calado no "—", e a tela dizia "nao lido" onde o visor da maquina
  // mostra um destino de verdade. Mesmo criterio do "?" das opcoes presumidas.
  const garantirOpcao = (sel, alvo) => {
    if (alvo && !sel.querySelector(`option[value="${alvo}"]`))
      sel.append(new Option(`código ${alvo} ?`, alvo));
  };
  const vals = fx["inst ctrl select"];
  ctrlSels.forEach((sel, i) => {
    const v = Array.isArray(vals) ? vals[i] : null;
    const alvo = v == null ? "" : String(v);
    garantirOpcao(sel, alvo);
    if (sel.value !== alvo) sel.value = alvo;
  });
  const vg = fx["kit ctrl select"];
  const alvoG = vg == null ? "" : String(vg);
  garantirOpcao(ctrlKitSel, alvoG);
  if (ctrlKitSel.value !== alvoG) ctrlKitSel.value = alvoG;
  // fora do modo User (6) o por-instrumento nao esta valendo: atenua a
  // fileira, mas deixa operavel - trocar fora do User so armazena o valor
  attr(ctrlFila, "data-atenuado", vg != null && +vg !== 6 ? "" : null);
}

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
      if (!(ultimoMapa || {})[nome]) semMapa(nome);
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
    aoCapturar: () => semMapa(nome),
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

// Clicar num controle FANTASMA abria a captura guiada. O painel que a cancelava
// morreu com a aba Avancado (17/08/2026), e captura sem cancelamento fica presa
// relendo os 26 blocos de FX a cada 0,35 s ate reiniciar o app - caro demais
// para um clique acidental na janela entre o montar() e o primeiro /estado, em
// que todo knob nasce fantasma. Hoje o clique so explica o que aconteceu.
function semMapa(nome) {
  toast(
    `“${nome}” não está no mapa: o offset dele nunca foi descoberto, então ` +
      "este controle não escreve nada. A captura guiada saiu na reforma 3 " +
      "(o catálogo está todo mapeado) e volta do git se precisar.",
    { ttl: 9000 },
  );
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
