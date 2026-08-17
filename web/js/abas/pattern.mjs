// abas/pattern.mjs - o grid completo, no espirito da aba PATTERN do TR-EDITOR.
//
// Nao e duplicata do Launchpad: mostra as 13 linhas de uma vez (o fisico cabe 8
// e rola) e mostra a PROBABILITY, que o hardware nao tem como exibir.
import { h, $, texto, attr, prop } from "../nucleo/dom.mjs";
import { gradeSteps } from "../comp/grade-steps.mjs";
import { agir } from "../app.mjs";
import { toast } from "../comp/toast.mjs";

let grade,
  elVars,
  elFerr,
  linhaSel = 1;
const pendentes = new Set(); // "l,s" enviados, aguardando a maquina
let ultimoArmado = 0;

function chip(rot, aoClicar, props = {}) {
  return h("button.bt", { type: "button", ...props }, rot);
}

export default {
  id: "pattern",
  rotulo: "Pattern",

  montar(raiz, D) {
    // ── coluna das variacoes ──
    elVars = h("div.vars");
    D.variacoes.forEach((v, i) => {
      const n = i + 1;
      const b = chip(v.replace("Fill ", "F"), null, {
        "data-v": n,
        class: n > 8 ? "fill" : "",
      });
      // clique = ABRIR no grid pra editar (o playhead some, porque o que soa
      // e outra variacao). Duplo clique = pedir que ela TOQUE, na virada.
      // Sao coisas diferentes de proposito: editar uma variacao enquanto
      // outra soa e o recurso mais valioso do projeto (REFERENCIA 2.3.2).
      // O duplo clique tem que cancelar o simples, senao abriria o grid junto
      let tSimples = null;
      // liga/desliga no rodizio, sem zerar as outras - o caminho de volta,
      // ja que o duplo clique deixa UMA habilitada e mata o A->B->C.
      // Clique direito, nao Alt-clique: o teclado do Mac nao tem tecla "Alt"
      // escrita (e a Option), e o resto do app ja oferece as duas formas
      b.oncontextmenu = (ev) => {
        ev.preventDefault();
        clearTimeout(tSimples);
        agir({ acao: "ciclo_variacao", var: n });
      };
      b.onclick = (ev) => {
        clearTimeout(tSimples);
        if (ev.altKey) {
          agir({ acao: "ciclo_variacao", var: n });
          return;
        }
        if (ev.shiftKey) {
          // "e ESTA que esta no visor": ancora a conta da variacao. Quem sobe
          // o app com a maquina ja rodando nunca recebe um start, e sem start
          // nao ha como deduzir qual toca - so o olho do Luan sabe
          agir({ acao: "ancorar_variacao", var: n });
          return;
        }
        tSimples = setTimeout(
          () => agir({ acao: "exec", tipo: "variacao", arg: n }),
          220,
        );
      };
      b.ondblclick = () => {
        clearTimeout(tSimples);
        agir({ acao: "tocar_variacao", var: n });
      };
      elVars.append(b);
    });

    // ── grade ──
    grade = gradeSteps({
      instrumentos: D.instrumentos,
      aoClicarCelula: (l, s, { fraco }) => {
        // linha 0 = ACC; o Motor.alternar_editor ja trata isso pelo indice
        const inst = l === 0 ? D.instrumentos.length : l - 1;
        const k = `${l},${s}`;
        pendentes.add(k);
        setTimeout(() => pendentes.delete(k), 2500);
        agir({ acao: "editor_toggle", inst, step: s, fraco: !!fraco }).then(
          (ok) => {
            if (!ok) pendentes.delete(k);
          },
        );
      },
      aoClicarRotulo: (l) => {
        linhaSel = l;
        grade.marcarLinha(l);
      },
      aoMenuCelula: (l, s, cel) => abrirMenu(l, s, cel, D),
    });

    // ── ferramentas ──
    elFerr = h("div.ferr");
    const grupo = (titulo, ...filhos) =>
      h("div.grupo", {}, h("h3", {}, titulo), ...filhos);

    const velChips = h("div.chips");
    D.velocidades.forEach((v, i) => {
      const b = chip(String(v), null, { "data-vel": i });
      b.onclick = () => agir({ acao: "exec", tipo: "velocidade", arg: i });
      velChips.append(b);
    });
    const modoChips = h("div.chips");
    D.modos_step.forEach((m, i) => {
      const b = chip(m.replace("SUB ", ""), null, { "data-modo": i });
      b.onclick = () => agir({ acao: "exec", tipo: "modo", arg: i });
      modoChips.append(b);
    });
    const bAlt = chip("ALTERNATE", null, { id: "b-alt" });
    bAlt.onclick = () => agir({ acao: "exec", tipo: "alt" });
    const bAcc = chip("mostrar ACC no grid", null, { id: "b-acc" });
    bAcc.onclick = () => agir({ acao: "exec", tipo: "acc" });
    const bCopiar = chip("COPY", null);
    bCopiar.onclick = () => agir({ acao: "exec", tipo: "copiar" });
    const bColar = chip("PASTE", null, { id: "b-colar" });
    bColar.onclick = () => agir({ acao: "exec", tipo: "colar" });
    const bClearInst = chip("CLEAR linha", null);
    bClearInst.onclick = () => {
      agir({ acao: "exec", tipo: "limpar_inst" });
      toast("CLEAR armado: clique num step da linha que quer limpar");
    };
    const bClearVar = chip("CLEAR variação", null, { class: "bt-perigo" });
    bClearVar.onclick = () => {
      const agora = Date.now();
      if (agora - ultimoArmado > 2000) {
        ultimoArmado = agora;
        bClearVar.setAttribute("data-armado", "");
        bClearVar.style.setProperty("--ms", "2000ms");
        texto(bClearVar, "apagar tudo? (2s)");
        setTimeout(() => {
          bClearVar.removeAttribute("data-armado");
          texto(bClearVar, "CLEAR variação");
        }, 2000);
        return;
      }
      ultimoArmado = 0;
      bClearVar.removeAttribute("data-armado");
      texto(bClearVar, "CLEAR variação");
      agir({ acao: "exec", tipo: "limpar_var" });
      agir({ acao: "exec", tipo: "limpar_var" }); // o motor pede 2x pra valer
    };

    // WRITE veio da aba Avancado quando ela foi removida (17/08/2026): salvar
    // o pattern e gesto de pattern, e este e o lugar dele. Dois cliques em 2 s,
    // como o CLEAR variacao - escrever na memoria da maquina nao se desfaz
    let armadoWrite = 0;
    const bWrite = chip("WRITE (salvar)", null, { class: "bt-perigo" });
    bWrite.onclick = () => {
      const agora = Date.now();
      if (agora - armadoWrite > 2000) {
        armadoWrite = agora;
        bWrite.setAttribute("data-armado", "");
        bWrite.style.setProperty("--ms", "2000ms");
        texto(bWrite, "clique de novo (2s)");
        setTimeout(() => {
          bWrite.removeAttribute("data-armado");
          texto(bWrite, "WRITE (salvar)");
        }, 2000);
        return;
      }
      armadoWrite = 0;
      bWrite.removeAttribute("data-armado");
      texto(bWrite, "WRITE (salvar)");
      agir({ acao: "util", op: "write" });
    };

    const selLastVar = h("select", {
      id: "last-var",
      "aria-label": "last step da variação",
    });
    for (let i = 1; i <= 16; i++) selLastVar.append(new Option(i, i));
    selLastVar.onchange = () =>
      agir({ acao: "last_var", valor: +selLastVar.value });

    const selLastTrack = h("select", {
      id: "last-track",
      "aria-label": "last step da linha",
    });
    selLastTrack.append(new Option("—", ""));
    for (let i = 1; i <= 16; i++) selLastTrack.append(new Option(i, i));
    selLastTrack.onchange = () => {
      if (linhaSel === 0) {
        toast("escolha uma linha de instrumento");
        return;
      }
      agir({
        acao: "last_track",
        inst: linhaSel - 1,
        valor: selLastTrack.value === "" ? null : +selLastTrack.value,
      });
    };

    // janela dos Launchpads: os mesmos INST UP/DOWN dos pads, agora na tela
    const bCima = h(
      "button.bt.bt-peq",
      { type: "button", id: "b-rolar-cima", title: "INST UP" },
      "▲",
    );
    bCima.onclick = () => agir({ acao: "exec", tipo: "rolar", arg: -1 });
    const bBaixo = h(
      "button.bt.bt-peq",
      { type: "button", id: "b-rolar-baixo", title: "INST DOWN" },
      "▼",
    );
    bBaixo.onclick = () => agir({ acao: "exec", tipo: "rolar", arg: 1 });

    // quantas linhas cada toque anda. 3 por padrao porque e o que falta: sao
    // 11 instrumentos numa janela de 8, entao um toque so leva de BD-CH a
    // MT-RC e o resto aparece inteiro. Vale para os pads do Launchpad tambem
    const selPasso = h("select", {
      id: "passo-inst",
      "aria-label": "linhas por toque do INST UP/DOWN",
    });
    // o teto vem do servidor (PASSO_INST_MAX); 8 e so o palpite ate o
    // primeiro estado chegar. Fixar 8 aqui deixava a tela oferecer valores que
    // o servidor grampeia, e o campo ficava se reescrevendo a cada quadro
    for (let i = 1; i <= 8; i++) selPasso.append(new Option(i, i));
    selPasso.onchange = () =>
      agir({ acao: "passo_inst", valor: +selPasso.value });

    elFerr.append(
      grupo("velocity", velChips),
      grupo("modo do step", modoChips, bAlt),
      grupo(
        "last step",
        h("div.linha", {}, h("label", {}, "variação"), selLastVar),
        h("div.linha", {}, h("label", {}, "linha"), selLastTrack),
      ),
      grupo(
        "edição",
        h("div.chips", {}, bCopiar, bColar),
        bClearInst,
        bClearVar,
        bAcc,
        bWrite,
        h(
          "p.dica",
          {},
          "o WRITE grava o pattern na memória da máquina — o teste de verdade " +
            "é religar a TR-8S depois",
        ),
      ),
      grupo(
        "janela dos Launchpads",
        h(
          "div.linha",
          {},
          bCima,
          bBaixo,
          h("span.mono.dica", { id: "rot-janela" }, "—"),
        ),
        h("div.linha", {}, h("label", {}, "linhas por toque"), selPasso),
      ),
    );

    raiz.append(
      h(
        "div.pattern",
        {},
        elVars,
        h(
          "div",
          {},
          h("div.grade-cx", {}, grade.raiz),
          h(
            "p.dica",
            {},
            "clique liga/desliga · Shift-clique grava fraco · " +
              "arraste para pintar vários · clique direito (ou Alt-clique) " +
              "abre velocity/sub step/alternate/probability · a moldura " +
              "verde é a janela dos Launchpads · nas variações: clique abre " +
              "para editar, duplo clique faz tocar na virada (só ela), " +
              "clique direito liga/desliga no rodízio A→B→C",
          ),
        ),
        elFerr,
      ),
    );
    grade.marcarLinha(linhaSel);
  },

  atualizar(e, D) {
    ultimoEstado = e;
    grade.pintar(e, pendentes);

    // variacoes: aberta (borda), a que soa (ponto verde) e a pedida (piscando
    // ate a virada). O ponto verde so aparece quando a conta esta ANCORADA -
    // sem ancora nao sabemos qual toca, e inventar seria pior que nao dizer
    [...elVars.children].forEach((b) => {
      const v = +b.dataset.v;
      attr(b, "data-aberta", v === e.variacao ? "" : null);
      attr(b, "data-tocando", v === e.variacao_tocando ? "" : null);
      attr(b, "data-pedida", v === e.var_pedida ? "" : null);
    });

    [...elFerr.querySelectorAll("[data-vel]")].forEach((b) =>
      attr(b, "aria-pressed", +b.dataset.vel === e.vel_idx ? "true" : "false"),
    );
    [...elFerr.querySelectorAll("[data-modo]")].forEach((b) =>
      attr(
        b,
        "aria-pressed",
        +b.dataset.modo === e.modo_idx ? "true" : "false",
      ),
    );
    attr($("#b-alt"), "aria-pressed", e.alt ? "true" : "false");
    attr($("#b-acc"), "aria-pressed", e.mostrar_acc ? "true" : "false");
    attr($("#b-colar"), "aria-disabled", e.copia_cheia ? null : "true");

    const lv = $("#last-var");
    if (document.activeElement !== lv && e.last_var)
      lv.value = String(e.last_var);
    const lt = $("#last-track");
    if (document.activeElement !== lt && linhaSel > 0) {
      const v = (e.last_track || [])[linhaSel - 1];
      lt.value = v && v < 16 ? String(v) : "";
    }

    // janela dos Launchpads: a moldura verde sobre o proprio grid substitui
    // o antigo "espelho dos LEDs". Usa e.janela (lista de INDICES, criada
    // para isto) - a primeira versao mapeava e.visiveis, que e uma STRING
    // de log, e o .map explodia calado e a moldura nunca nascia (16/08).
    // +1 porque a linha 0 do grid e a ACC
    const idx = (e.janela || []).map((i) => i + 1);
    // a moldura para no last step da variacao: alem dele os steps nao tocam
    grade.marcarJanela(idx, e.last_var || 16);
    const rotJanela = $("#rot-janela");
    if (rotJanela && idx.length) {
      texto(
        rotJanela,
        `${D.instrumentos[idx[0] - 1]}–${D.instrumentos[idx[idx.length - 1] - 1]}`,
      );
    }
    const emCima = e.base_inst === 0;
    const emBaixo = idx.length && idx[idx.length - 1] === D.instrumentos.length;
    attr($("#b-rolar-cima"), "aria-disabled", emCima ? "true" : null);
    attr($("#b-rolar-baixo"), "aria-disabled", emBaixo ? "true" : null);
    const selP = $("#passo-inst");
    if (selP) {
      const teto = e.passo_inst_max || 8;
      if (selP.options.length !== teto) {
        selP.replaceChildren();
        for (let i = 1; i <= teto; i++) selP.append(new Option(i, i));
      }
      if (e.passo_inst && +selP.value !== e.passo_inst)
        selP.value = String(e.passo_inst);
    }
  },
};

// ── menu do step ─────────────────────────────────────────
// O ultimo estado, guardado so para o menu: sem ele os chips nasciam todos
// iguais e nao dava para saber em que velocity/modo/probability o step ja
// estava - o menu perguntava sem nunca responder.
let ultimoEstado = null;
let menuAberto = null;
let desligarFecho = null; // remove os listeners de "clique fora"/Esc

// Os listeners de fechar TEM que morrer junto com o menu. A versao anterior
// registrava um pointerdown {once:true} por menu e nunca o removia: o
// listener orfao do menu ANTERIOR nao reconhecia o menu novo e o fechava no
// pointerdown - antes de o clique completar. Resultado: a partir do segundo
// menu, nenhum chip funcionava (velocity, modo, probability, nada).
function fecharMenu() {
  if (menuAberto) {
    menuAberto.remove();
    menuAberto = null;
  }
  if (desligarFecho) {
    desligarFecho();
    desligarFecho = null;
  }
}

function abrirMenu(l, s, cel, D) {
  fecharMenu();
  if (l === 0) return; // ACC e liga/desliga, sem parametro
  const inst = l - 1;
  const r = cel.getBoundingClientRect();
  const linha = (rot, filhos) => h("div", {}, h("h4", {}, rot), filhos);

  // valores que a maquina diz que este step tem agora
  const E = ultimoEstado || {};
  const vAtual = ((E.pattern || [])[inst] || [])[s];
  const subAtual = ((E.subs || [])[inst] || [])[s];
  const probAtual = ((E.probs || [])[inst] || [])[s];

  const chips = (itens, aoEscolher, atual) => {
    const cx = h("div.chips");
    itens.forEach(([rot, val]) => {
      const b = h(
        "button.bt.bt-peq",
        {
          type: "button",
          "aria-pressed": val === atual ? "true" : "false",
        },
        rot,
      );
      b.onclick = () => {
        aoEscolher(val);
        fecharMenu();
      };
      cx.append(b);
    });
    return cx;
  };

  const menu = h(
    "div.menu-step",
    { role: "dialog", "aria-label": "editar step" },
    h("h4", {}, `${D.instrumentos[inst]} · step ${s + 1}`),
    linha(
      "velocity",
      chips(
        D.velocidades.map((v) => [String(v), v]),
        (v) => agir({ acao: "step_set", inst, step: s, vel: v }),
        vAtual,
      ),
    ),
    linha(
      "modo",
      chips(
        D.modos_step.map((m, i) => [m.replace("SUB ", ""), i]),
        (i) => agir({ acao: "step_set", inst, step: s, vel: 80, sub: i }),
        subAtual,
      ),
    ),
    linha(
      "probability",
      chips(
        // 0% existe (sniff 15/08): o step fica gravado mas nunca toca
        [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0].map((p) => [p + "%", p]),
        (p) => agir({ acao: "prob_step", inst, step: s, pct: p }),
        probAtual,
      ),
    ),
    h(
      "div.linha",
      {},
      (() => {
        const b = h("button.bt.bt-peq", { type: "button" }, "ALTERNATE");
        b.onclick = () => {
          agir({ acao: "step_set", inst, step: s, vel: 80, alt: true });
          fecharMenu();
        };
        return b;
      })(),
      (() => {
        const b = h(
          "button.bt.bt-peq.bt-perigo",
          { type: "button" },
          "limpar step",
        );
        b.onclick = () => {
          agir({ acao: "step_set", inst, step: s, vel: 0 });
          fecharMenu();
        };
        return b;
      })(),
    ),
  );

  document.body.append(menu);
  const m = menu.getBoundingClientRect();
  menu.style.left =
    Math.max(
      8,
      Math.min(window.innerWidth - m.width - 8, r.left - m.width / 2),
    ) + "px";
  menu.style.top =
    (r.bottom + m.height + 8 < window.innerHeight
      ? r.bottom + 6
      : r.top - m.height - 6) + "px";
  menuAberto = menu;
  function fora(ev) {
    if (!menu.contains(ev.target)) fecharMenu();
  }
  function esc(ev) {
    if (ev.key === "Escape") fecharMenu();
  }
  desligarFecho = () => {
    document.removeEventListener("pointerdown", fora);
    document.removeEventListener("keydown", esc);
  };
  // adiado um tique para o pointerdown que ABRIU o menu nao fecha-lo
  setTimeout(() => {
    if (menuAberto === menu) {
      document.addEventListener("pointerdown", fora);
      document.addEventListener("keydown", esc);
    }
  }, 0);
}
