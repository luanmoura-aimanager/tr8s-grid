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
  elPads,
  padCels = [],
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
      b.onclick = () => agir({ acao: "exec", tipo: "variacao", arg: n });
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
      ),
    );

    // ── espelho dos LEDs (o que os Launchpads mostram, com a ondinha) ──
    elPads = h("div.pads");
    for (let i = 0; i < 128; i++) {
      const c = h("i");
      padCels.push(c);
      elPads.append(c);
    }

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
              "abre velocity/sub step/alternate/probability",
          ),
        ),
        elFerr,
      ),
      h(
        "div.secao",
        {},
        h("h3", {}, "espelho dos LEDs"),
        h(
          "p.dica",
          {},
          "o que está nos Launchpad agora — 8 linhas, já roladas, " +
            "com o playhead. No standby mostra a ondinha.",
        ),
        elPads,
      ),
    );
    grade.marcarLinha(linhaSel);
  },

  atualizar(e, D) {
    ultimoEstado = e;
    grade.pintar(e, pendentes);

    // variacoes: aberta (borda) e a que soa (ponto verde)
    [...elVars.children].forEach((b) => {
      const v = +b.dataset.v;
      attr(b, "data-aberta", v === e.variacao ? "" : null);
      attr(b, "data-tocando", v === e.variacao_tocando ? "" : null);
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

    // espelho dos LEDs: pads ja vem com a cor resolvida pelo motor
    const pads = e.pads;
    for (let l = 0; l < 8; l++) {
      for (let c = 0; c < 16; c++) {
        const cor = pads ? pads[l][c] : null;
        const hex =
          cor === null || cor === undefined
            ? "#1a1a1a"
            : Array.isArray(cor)
              ? `rgb(${Math.min(255, cor[0] * 2)},${Math.min(255, cor[1] * 2)},${Math.min(255, cor[2] * 2)})`
              : (D.paleta_idx && D.paleta_idx[cor]) || corIndice(cor);
        const cel = padCels[l * 16 + c];
        if (cel.dataset.h !== hex) {
          cel.dataset.h = hex;
          cel.style.background = hex;
        }
      }
    }
  },
};

// espelho de PALETA_HEX do lp_tr8s.py, para os indices que o grid usa
const IDX = {
  0: "#1a1a1a",
  1: "#3a3a3a",
  3: "#ffffff",
  5: "#ff3b30",
  7: "#5c1512",
  9: "#ff9500",
  11: "#5c3a0f",
  13: "#ffe600",
  21: "#33d17a",
  23: "#14532d",
  45: "#3b82f6",
  49: "#a855f7",
};
const corIndice = (i) => IDX[i] || "#1a1a1a";

// ── menu do step ─────────────────────────────────────────
// O ultimo estado, guardado so para o menu: sem ele os chips nasciam todos
// iguais e nao dava para saber em que velocity/modo/probability o step ja
// estava - o menu perguntava sem nunca responder.
let ultimoEstado = null;
let menuAberto = null;
function fecharMenu() {
  if (menuAberto) {
    menuAberto.remove();
    menuAberto = null;
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
        [100, 90, 80, 70, 60, 50, 40, 30, 20, 10].map((p) => [p + "%", p]),
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
  setTimeout(() => {
    document.addEventListener("pointerdown", umaVez, { once: true });
    document.addEventListener("keydown", esc);
  }, 0);
  function umaVez(ev) {
    if (!menu.contains(ev.target)) fecharMenu();
  }
  function esc(ev) {
    if (ev.key === "Escape") {
      fecharMenu();
      document.removeEventListener("keydown", esc);
    }
  }
}
