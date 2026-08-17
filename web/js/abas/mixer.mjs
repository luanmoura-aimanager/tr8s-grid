// abas/mixer.mjs - a MESA: 11 canais (GAIN, PAN, sends, LEVEL, PROB, MUTE)
// e um canal MASTER, tudo num quadro so.
//
// Reforma 3: a versao anterior desta aba despejava os 252 parametros do
// mapa_fx em ordem alfabetica (uma fileira de 11 faders POR parametro) e
// duplicava a aba Efeitos inteira. O catalogo completo continua la, por
// painel e com so o tipo ativo visivel; aqui ficam os gestos de mixagem.
// A ferramenta de captura foi para a aba Avancado.
//
// Todos os offsets desta mesa sao provados (sniff M2, 15/08/2026). O MUTE e
// o unico que nao passa pelo definir_fx: ele escreve a mascara de
// performance (REFERENCIA 2.7) pela acao "mudo", e o estado vem de e.mudo.
// Sem otimismo local em nada: o poll de 250 ms reflete o que a maquina diz.
import { h, attr } from "../nucleo/dom.mjs";
import { painel } from "../comp/painel.mjs";
import { knob } from "../comp/knob.mjs";
import { fader } from "../comp/fader.mjs";
// faixa, bipolaridade e formato vem do CATALOGO (efeitos.py), nunca digitados
// aqui - foi o GAIN que mostrou o preco de repetir faixa na tela (17/08/2026)
import { faixaDoCatalogo as doCat } from "../nucleo/formato.mjs";
import { agir } from "../app.mjs";

const canais = []; // [{gain, pan, rvb, dly, level, prob, mute}]
let master = null; // {rvb, dly, kit, mfxSw, mfxTipo, chaveTipos}

export default {
  id: "mixer",
  rotulo: "Mixer",

  montar(raiz, D) {
    const mesa = h("div.mesa");

    D.instrumentos.forEach((n, i) => {
      const fx = (nome) => (v) => agir({ acao: "fx", nome, valor: v, inst: i });
      const c = {
        gain: knob({
          rotulo: "GAIN",
          ...doCat(D, "inst gain"),
          chave: "mx-gain:" + i,
          dica: "inst gain do " + n + " — 0.0 dB no meio, -INF no fim",
          aoSoltar: fx("inst gain"),
        }),
        pan: knob({
          rotulo: "PAN",
          ...doCat(D, "inst pan"),
          chave: "mx-pan:" + i,
          dica: "inst pan do " + n,
          aoSoltar: fx("inst pan"),
        }),
        rvb: knob({
          rotulo: "RVB",
          ...doCat(D, "inst reverb send"),
          chave: "mx-rvb:" + i,
          dica: "reverb send do " + n,
          aoSoltar: fx("inst reverb send"),
        }),
        dly: knob({
          rotulo: "DLY",
          ...doCat(D, "inst delay send"),
          chave: "mx-dly:" + i,
          dica: "delay send do " + n,
          aoSoltar: fx("inst delay send"),
        }),
        level: fader({
          rotulo: "LEVEL",
          ...doCat(D, "inst level"),
          chave: "mx-level:" + i,
          aoSoltar: fx("inst level"),
        }),
        prob: knob({
          rotulo: "PROB",
          min: 10,
          max: 100,
          chave: "mx-prob:" + i,
          formatar: (v) => v + "%",
          dica:
            "solta e escreve em todos os steps ligados do " +
            n +
            "; “—” = steps com probabilidades diferentes, ou nenhum step ligado",
          aoSoltar: (v) => agir({ acao: "prob_inst", inst: i, pct: v }),
        }),
        mute: h(
          "button.bt.bt-peq.bt-mute",
          {
            type: "button",
            "aria-pressed": "false",
            "data-dica": "muta o " + n + " na maquina (mascara de performance)",
          },
          "MUTE",
        ),
      };
      c.mute.onclick = () => agir({ acao: "mudo", inst: i });
      canais.push(c);
      mesa.append(
        h(
          "div.canal",
          {},
          h("div.canal-nome", {}, n),
          c.gain.raiz,
          c.pan.raiz,
          c.rvb.raiz,
          c.dly.raiz,
          c.level.raiz,
          c.prob.raiz,
          c.mute,
        ),
      );
    });

    // canal master: niveis de kit/reverb/delay + o MASTER FX de performance
    const fxk = (nome) => (v) =>
      agir({ acao: "fx", nome, valor: v, inst: null });
    master = {
      rvb: knob({
        rotulo: "RVB LVL",
        ...doCat(D, "reverb level"),
        chave: "mx-rvblvl",
        dica: "level do reverb do kit — em 0 os sends não soam",
        aoSoltar: fxk("reverb level"),
      }),
      dly: knob({
        rotulo: "DLY LVL",
        ...doCat(D, "delay level"),
        chave: "mx-dlylvl",
        dica: "level do delay do kit — em 0 os sends não soam",
        aoSoltar: fxk("delay level"),
      }),
      kit: fader({
        rotulo: "KIT LVL",
        ...doCat(D, "kit level"),
        // o catalogo marca dB neste, mas o visor da maquina nunca foi lido
        // aqui: melhor o numero cru do que uma unidade que ninguem conferiu
        formatar: String,
        chave: "mx-kitlvl",
        aoSoltar: fxk("kit level"),
      }),
      mfxSw: h(
        "button.bt.bt-peq.bt-mute",
        {
          type: "button",
          "aria-pressed": "false",
          "data-dica": "MASTER FX on/off",
        },
        "MFX",
      ),
      mfxTipo: h("select", { "aria-label": "tipo do MASTER FX" }),
      chaveTipos: "",
    };
    master.mfxSw.onclick = () => {
      const ligado = master.mfxSw.getAttribute("aria-pressed") === "true";
      agir({ acao: "fx", nome: "mfx sw", valor: ligado ? 0 : 1, inst: null });
    };
    master.mfxTipo.onchange = () => {
      if (master.mfxTipo.value === "") return;
      agir({
        acao: "fx",
        nome: "mfx tipo",
        valor: +master.mfxTipo.value,
        inst: null,
      });
    };
    // ordem pedida em 17/08: o MASTER FX em cima (e um botao, nao um knob -
    // liderar a coluna com ele evita o pulo de leitura), depois os dois niveis
    // de envio e, no pe, o fader do kit inteiro - que e o unico que mexe no
    // volume de TUDO, entao ganhou rotulo e dica proprios
    mesa.append(
      h(
        "div.canal.canal-master",
        {},
        h("div.canal-nome", {}, "MASTER"),
        h("div.linha", {}, master.mfxSw, master.mfxTipo),
        master.rvb.raiz,
        master.dly.raiz,
        h(
          "div.dica.dica-kit",
          { "data-dica": "o mesmo do SHIFT + [KIT] → LEVEL na máquina" },
          "volume do kit inteiro",
        ),
        master.kit.raiz,
      ),
    );

    // o motor rele os blocos de FX em rodizio (INTERVALO_FX), entao mexer no
    // painel da maquina chega aqui em alguns segundos; este botao e o atalho
    // para quem nao quer esperar a volta da fila
    const bReler = h(
      "button.bt.bt-peq",
      { type: "button", "data-dica": "rele os 26 blocos de efeito agora" },
      "Reler",
    );
    bReler.onclick = () => agir({ acao: "ler_fx" });

    raiz.append(
      painel(
        "Mesa",
        { dir: [bReler] },
        h(
          "p.dica",
          {},
          "level, gain, pan, sends, probability e mute dos 11 instrumentos — " +
            "o resto dos parâmetros mora na aba Efeitos",
        ),
        mesa,
      ),
    );
  },

  atualizar(e) {
    const fx = e.fx || {};
    const arr = (nome) => (Array.isArray(fx[nome]) ? fx[nome] : []);
    const g = arr("inst gain"),
      p = arr("inst pan"),
      r = arr("inst reverb send"),
      d = arr("inst delay send"),
      l = arr("inst level");
    const probs = e.probs_inst || [];
    const mudos = e.mudo || [];
    canais.forEach((c, i) => {
      c.gain.definir(g[i] ?? null);
      c.pan.definir(p[i] ?? null);
      c.rvb.definir(r[i] ?? null);
      c.dly.definir(d[i] ?? null);
      c.level.definir(l[i] ?? null);
      c.prob.definir(probs[i] ?? null);
      attr(c.mute, "aria-pressed", mudos[i] ? "true" : "false");
    });
    master.rvb.definir(fx["reverb level"] ?? null);
    master.dly.definir(fx["delay level"] ?? null);
    master.kit.definir(fx["kit level"] ?? null);
    attr(master.mfxSw, "aria-pressed", fx["mfx sw"] === 1 ? "true" : "false");
    // tipos do MASTER FX: opcoes anotadas do mapa, populadas so quando mudam
    const ent = (e.mapa_fx || {})["mfx tipo"];
    const opts = (ent && ent.opcoes) || {};
    const chave = Object.keys(opts).sort().join(",");
    if (chave && master.chaveTipos !== chave) {
      master.chaveTipos = chave;
      master.mfxTipo.replaceChildren(new Option("—", ""));
      Object.entries(opts)
        .sort((a, b) => a[0] - b[0])
        .forEach(([cod, rot]) => master.mfxTipo.append(new Option(rot, cod)));
    }
    const vt = fx["mfx tipo"];
    const alvo = vt == null ? "" : String(vt);
    if (master.mfxTipo.value !== alvo) master.mfxTipo.value = alvo;
  },
};
