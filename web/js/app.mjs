// app.mjs - monta a pagina, liga o laco de estado e troca de aba.
//
// Cada aba monta uma vez e SO a aba visivel e atualizada. A versao anterior
// remontava paineis de FX a cada 250 ms mesmo com a aba fechada.
import { $, h, texto, attr, prop } from "./nucleo/dom.mjs";
import { pegarToken, getJSON, acao, sair, lacoEstado } from "./nucleo/rede.mjs";
import { D, S, definirDados, aplicarEstado, assinar } from "./nucleo/store.mjs";
import { aplicarPaleta } from "./nucleo/paleta.mjs";
import { nomePattern } from "./nucleo/formato.mjs";
import { toast, erro } from "./comp/toast.mjs";
import { ligarDica } from "./comp/tooltip.mjs";

import pattern from "./abas/pattern.mjs";
import fx from "./abas/fx.mjs";
import mixer from "./abas/mixer.mjs";
import instrumento from "./abas/instrumento.mjs";
import grooves from "./abas/grooves.mjs";
import estocastica from "./abas/estocastica.mjs";

const ABAS = [pattern, fx, mixer, instrumento, grooves, estocastica];

// Biblioteca e Chain viraram a aba Grooves (reforma 2): quem tinha uma das
// duas salva volta na fusao, nao na primeira aba
if (["biblioteca", "chain"].includes(localStorage.getItem("aba")))
  localStorage.setItem("aba", "grooves");
// A aba AVANCADO saiu em 17/08/2026 ("o programa tem que ficar mais simples"):
// o WRITE mudou para a aba Pattern, o log continua no rodape e no arquivo, e a
// captura guiada saiu do ar com o catalogo 253/253 mapeado - ela volta do git
// se um parametro novo aparecer. Quem estava nela cai no Pattern.
if (localStorage.getItem("aba") === "avancado")
  localStorage.setItem("aba", "pattern");
let atual = null;

/** acao() com toast automatico no erro - ninguem clica no escuro. */
export async function agir(corpo) {
  const r = await acao(corpo);
  if (!r.ok) erro(r.erro);
  return r.ok;
}

// ── modos ────────────────────────────────────────────────
const MODOS = [
  { id: "on", rot: "ON", cor: "on", modo: "on" },
  { id: "off", rot: "off", cor: "off", modo: "off" },
  { id: "chuva", rot: "standby", cor: "sb", modo: "standby", estilo: "chuva" },
  {
    id: "amb",
    rot: "ambiente",
    cor: "sb",
    modo: "standby",
    estilo: "ambiente",
  },
];

function montarTopo() {
  const modos = $("#modos");
  MODOS.forEach((m) => {
    const b = h(
      "button.bt",
      {
        type: "button",
        "data-cor": m.cor,
        "data-id": m.id,
        "aria-pressed": "false",
      },
      m.rot,
    );
    b.onclick = () =>
      agir({ acao: "modo", modo: m.modo, estilo: m.estilo || null });
    modos.append(b);
  });
  const leds = $("#leds");
  [
    ["ctrl", "TR-8S"],
    ["lp", "Launchpad"],
    ["clock", "clock"],
  ].forEach(([id, rot]) => {
    leds.append(
      h(
        "div.led-rot",
        {},
        h("span.led", { id: "led-" + id, role: "img", "aria-label": rot }),
        rot,
      ),
    );
  });
  $("#b-recal").onclick = () => agir({ acao: "externa", op: "recalibrar" });
  $("#b-blackout").onclick = () => agir({ acao: "externa", op: "blackout" });
  $("#b-sair").onclick = async () => {
    await sair();
    texto($("#msg"), "encerrado — pode fechar esta aba");
  };
  $("#b-densidade").onclick = () => {
    const r = document.documentElement;
    const novo =
      r.dataset.densidade === "compacto" ? "confortavel" : "compacto";
    r.dataset.densidade = novo;
    localStorage.setItem("densidade", novo);
  };
  document.documentElement.dataset.densidade =
    localStorage.getItem("densidade") || "confortavel";
}

// ── abas ─────────────────────────────────────────────────
function montarAbas() {
  const nav = $("#abas"),
    paineis = $("#paineis");
  ABAS.forEach((aba, i) => {
    const b = h(
      "button",
      {
        type: "button",
        role: "tab",
        id: "tab-" + aba.id,
        "aria-controls": "p-" + aba.id,
        "aria-selected": "false",
        tabindex: -1,
      },
      aba.rotulo,
    );
    b.onclick = () => trocar(aba.id);
    nav.append(b);
    const p = h("section.aba", {
      id: "p-" + aba.id,
      role: "tabpanel",
      "aria-labelledby": "tab-" + aba.id,
      tabindex: 0,
      hidden: true,
    });
    paineis.append(p);
    try {
      aba.montar(p, D);
    } catch (e) {
      console.error(aba.id, e);
      p.append(
        h(
          "div.fita",
          { "data-tipo": "erro" },
          "esta aba falhou ao montar: " + e.message,
        ),
      );
    }
  });
  // setas do teclado navegam entre abas (padrao ARIA)
  nav.addEventListener("keydown", (e) => {
    const i = ABAS.findIndex((a) => a.id === atual);
    if (e.key === "ArrowRight") trocar(ABAS[(i + 1) % ABAS.length].id, true);
    else if (e.key === "ArrowLeft")
      trocar(ABAS[(i - 1 + ABAS.length) % ABAS.length].id, true);
    else if (e.key === "Home") trocar(ABAS[0].id, true);
    else if (e.key === "End") trocar(ABAS[ABAS.length - 1].id, true);
    else return;
    e.preventDefault();
  });
  trocar(localStorage.getItem("aba") || ABAS[0].id);
}

function trocar(id, focar) {
  if (!ABAS.some((a) => a.id === id)) id = ABAS[0].id;
  const antes = ABAS.find((a) => a.id === atual);
  if (antes && antes.aoSair) antes.aoSair();
  atual = id;
  localStorage.setItem("aba", id);
  ABAS.forEach((a) => {
    const tab = $("#tab-" + a.id),
      painel = $("#p-" + a.id);
    const sel = a.id === id;
    attr(tab, "aria-selected", sel ? "true" : "false");
    attr(tab, "tabindex", sel ? 0 : -1);
    painel.hidden = !sel;
    if (sel && focar) tab.focus();
  });
  // o realce desliza por transform, sem tocar no layout
  const tab = $("#tab-" + id),
    nav = $("#abas");
  prop(nav, "--aba-x", tab.offsetLeft - nav.offsetLeft + "px");
  prop(nav, "--aba-w", tab.offsetWidth + "px");
  const aba = ABAS.find((a) => a.id === id);
  if (aba.aoEntrar) aba.aoEntrar();
  if (S && Object.keys(S).length) pintar(S, D);
}

// ── pintura do chrome ────────────────────────────────────
let ultimoLog = 0;

// A acao "reler" (Motor.recarregar: rele em que pattern a maquina esta e as 11
// linhas, com duas tentativas cada) existia no servidor sem NENHUM botao na
// pagina. Quando uma leitura falha, a escrita fica bloqueada e a unica saida
// era esperar o tick se curar sozinho ou reiniciar o app - achado na sessao de
// hardware de 17/08/2026, com tres linhas nao lidas na tela.
const btRelerTudo = h(
  "button.bt.bt-peq",
  {
    type: "button",
    style: { marginLeft: "8px" },
    "data-dica": "rele o pattern inteiro da maquina e destrava a escrita",
  },
  "Reler tudo",
);
btRelerTudo.onclick = () => agir({ acao: "reler" });

// "maquina ocupada" e um estado que PISCA: o motor fica indisponivel por
// fracoes de segundo a cada releitura. Mostrar isso na fita fazia a fita
// aparecer e sumir varias vezes por segundo, e como a fita esta no fluxo,
// a pagina inteira subia e descia junto. Agora: (a) so conta como ocupado
// depois de PACIENCIA ms seguidos, e (b) vira chip, e a linha de chips tem
// altura reservada no CSS - entra e sai sem mover nada.
const PACIENCIA = 2000;
let ocupadoDesde = 0;
function ocupadoDeVerdade(fresco) {
  if (fresco !== false) {
    ocupadoDesde = 0;
    return false;
  }
  if (!ocupadoDesde) ocupadoDesde = performance.now();
  return performance.now() - ocupadoDesde > PACIENCIA;
}
function pintar(e, dados) {
  const seg = (id, v, vazio) => {
    const el = $(id);
    texto(el.querySelector(".seg-val"), v);
    attr(el, "data-vazio", vazio ? "1" : null);
  };
  // Display numerico de largura FIXA. Reservar espaco no CSS (min-width em ch)
  // nao bastou: o .seg tem letter-spacing, entao dois digitos ocupam mais que
  // 2ch e o "8" virando "16" ainda empurrava a barra 16 vezes por compasso.
  // Aqui os digitos que faltam entram como zeros a esquerda pintados da cor do
  // fundo: ocupam o lugar exato e nao se veem. Ideia do Luan, 16/08/2026.
  const segNum = (id, v, vazio, largura) => {
    const el = $(id);
    const val = el.querySelector(".seg-val");
    const s = String(v);
    const falta = Math.max(0, largura - s.length);
    val.replaceChildren();
    if (falta)
      val.append(
        h("span.zero-fantasma", { "aria-hidden": "true" }, "0".repeat(falta)),
      );
    val.append(document.createTextNode(s));
    attr(el, "data-vazio", vazio ? "1" : null);
  };
  seg("#d-ptn", nomePattern(e.pattern_atual), e.pattern_atual == null);
  seg(
    "#d-kit",
    e.kit_nome || (e.kit_atual == null ? "—" : e.kit_atual + 1),
    !e.kit_nome && e.kit_atual == null,
  );
  // BPM medido do MIDI clock (24 ppq): a TR-8S manda clock mesmo parada,
  // entao ele aparece sempre que o cabo esta la. Escrever BPM nao existe.
  segNum("#d-bpm", e.bpm != null ? e.bpm.toFixed(1) : "—", e.bpm == null, 5);
  // "toca" e "edita" sao coisas DIFERENTES (o visor diz 2-04B enquanto o
  // grid edita a A) - a barra mostra as duas. "?" = varias variacoes
  // habilitadas e o byte da que toca ainda nao foi decodificado.
  const toca =
    e.variacao_tocando_nome ||
    ((e.vars_habilitadas || []).length > 1 ? "?" : null);
  seg("#d-var", toca || "—", !toca);
  seg("#d-vedit", e.variacao_nome || "—", !e.variacao_nome);
  segNum(
    "#d-step",
    e.tocando && e.passo >= 0 ? String(e.passo + 1) : "—",
    !(e.tocando && e.passo >= 0),
    2,
  );

  // SCALE (17/08/2026): so aparece quando o pattern NAO esta em semicolcheia,
  // porque e exatamente quando o playhead anda em outra velocidade - deixar
  // isso invisivel foi o que fez o grid "andar em metade do tempo" sem
  // ninguem saber por que
  const segScale = $("#d-scale");
  const scale = e.scale && e.scale !== "16th" ? e.scale : null;
  segScale.hidden = !scale;
  if (scale) texto(segScale.querySelector(".seg-val"), scale);

  attr($("#led-ctrl"), "data-estado", e.tem_tr8s ? "on" : "off");
  attr($("#led-lp"), "data-estado", e.tem_lp ? "on" : "off");
  attr($("#led-clock"), "data-estado", e.tem_clock ? "on" : "off");
  attr($("#led-clock"), "data-pulsa", e.tocando ? "1" : null);

  MODOS.forEach((m) => {
    const b = $(`#modos .bt[data-id="${m.id}"]`);
    const on =
      e.modo_geral === m.modo && (!m.estilo || m.estilo === e.estilo_standby);
    attr(b, "aria-pressed", on ? "true" : "false");
  });

  // chips: mudos, cache invalido, ALT, CLEAR armado
  const chips = $("#chips-estado");
  const quer = [];
  (e.mudo || []).forEach((m, i) => {
    if (m)
      quer.push([
        "mudo-" + i,
        "chip chip-mudo",
        (dados.instrumentos[i] || "?") + " mudo",
      ]);
  });
  (e.cache_invalido || []).forEach((i) =>
    quer.push(["inv-" + i, "chip", "⚠ " + dados.instrumentos[i] + " não lido"]),
  );
  if (e.alt) quer.push(["alt", "chip", "ALT ligado"]);
  if (e.armado) quer.push(["arm", "chip", "CLEAR armado"]);
  if (e.polirritmia) quer.push(["poli", "chip", "polirritmia"]);
  if (ocupadoDeVerdade(e.fresco))
    quer.push(["ocup", "chip", "lendo a máquina…"]);
  const chave = quer.map((q) => q[0] + q[2]).join("|");
  if (chips.dataset.chave !== chave) {
    chips.dataset.chave = chave;
    chips.replaceChildren(
      ...quer.map(([, cls, txt]) =>
        h("span", { class: cls, "data-on": "1" }, txt),
      ),
    );
  }

  // fita: estados que explicam por que a tela pode estar "errada"
  const fita = $("#fita");
  let aviso = null;
  if (!e.ligado)
    aviso = ["", "motor desligado — clique ON para o app falar com a TR-8S"];
  else if (e.modo_geral !== "on")
    aviso = ["", "fora do modo ON: a TR-8S não é tocada"];
  else if (!e.carregado) aviso = ["", "lendo a máquina…"];
  // vem antes do cache_invalido: e o problema mais grave que a tela pode ter -
  // o grid inteiro mostrando outro pattern, nao uma linha que falhou
  else if (e.espelho_suspeito)
    aviso = [
      "erro",
      "o playhead não para de divergir do que a máquina toca — escrita " +
        "bloqueada por precaução. Se o TR-EDITOR (ou outro programa MIDI) " +
        "estiver aberto, feche: os dois disputam a porta CTRL e as leituras " +
        "saem trocadas. Some sozinho depois de 1 min sem divergência",
    ];
  else if ((e.cache_invalido || []).length)
    aviso = [
      "erro",
      "leitura falhou em alguma linha: o que aparece pode estar errado, e a escrita nela está bloqueada",
      true, // este e o unico aviso que uma releitura resolve
    ];
  // a variacao que toca nao existe em no SysEx nenhum: e contada a partir do
  // clock, e sem um start nao ha de onde ancorar a conta.
  //
  // O stop/play vem primeiro porque e o unico caminho PROVADO e sem pressa de
  // tempo: a maquina recomeca pela variacao mais baixa habilitada (16/08/2026).
  // O LED verde do painel tambem indica a que toca, mas a janela e de um
  // compasso - 2,8 s a 86 bpm - entao Shift-clicar nela e apertado
  else if (e.var_incerta)
    aviso = [
      "",
      "não sei qual variação está tocando (várias habilitadas e a máquina já " +
        "estava rodando) — dê stop/play na TR-8S, ou Shift-clique na variação " +
        "cujo LED verde estiver aceso no painel. (Duplo clique também resolve, " +
        "mas fixa uma variação só e desliga o rodízio.)",
    ];
  if (aviso) {
    fita.hidden = false;
    attr(fita, "data-tipo", aviso[0] || null);
    // reescreve so quando a mensagem muda: a fita roda 4x/s e o botao de
    // releitura mora dentro dela (texto() apagaria o botao todo quadro)
    if (fita.dataset.msg !== aviso[1]) {
      fita.dataset.msg = aviso[1];
      fita.replaceChildren(document.createTextNode(aviso[1]));
      if (aviso[2]) fita.append(btRelerTudo);
    }
  } else fita.hidden = true;

  const log = e.log || [];
  if (log.length && log.length !== ultimoLog) {
    ultimoLog = log.length;
    texto($("#msg"), log[log.length - 1]);
  }

  const aba = ABAS.find((a) => a.id === atual);
  if (aba && aba.atualizar) {
    try {
      aba.atualizar(e, dados);
    } catch (err) {
      console.error(aba.id, err);
    }
  }
}

// ── boot ─────────────────────────────────────────────────
async function iniciar() {
  try {
    await pegarToken();
    definirDados(await getJSON("/dados", 5000));
  } catch (e) {
    document.body.prepend(
      h(
        "div.fita",
        { "data-tipo": "erro" },
        "não consegui falar com o servidor: " +
          e.message +
          " — feche esta aba e abra o app pelo ícone do Desktop.",
      ),
    );
    return; // sem dados nao se comeca o laco
  }
  aplicarPaleta(D.cores);
  texto($("#build"), "build " + D.build);
  montarTopo();
  montarAbas();
  ligarDica();
  assinar(pintar);
  lacoEstado({
    aoEstado: aplicarEstado,
    aoFalhar: (err, ms) => {
      const f = $("#fita");
      f.hidden = false;
      attr(f, "data-tipo", "erro");
      texto(
        f,
        `sem contato com o servidor — nova tentativa em ${Math.round(ms / 1000)}s`,
      );
      // este caminho escreve na tarja por fora do pintar(): zerar o cache do
      // texto, senao a mensagem de "sem contato" ficaria colada na tela quando
      // o contato voltasse com o MESMO aviso de antes ativo
      delete f.dataset.msg;
    },
    aoVoltar: () => toast("contato restabelecido", { tipo: "ok" }),
  });
}
iniciar();
