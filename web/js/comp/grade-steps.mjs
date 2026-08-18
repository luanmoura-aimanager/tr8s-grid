// grade-steps.mjs - a grade 13x16, espelho da aba PATTERN do TR-EDITOR.
//
// PINTURA SEM RECRIAR DOM: as 208 celulas nascem uma vez. A cada quadro
// calcula-se um inteiro que empacota tudo que afeta a pintura (tipo, prob,
// pendente) e compara com um Int32Array de cache. Igual -> nao toca no DOM.
// Parado, o custo por quadro sao 208 comparacoes de inteiro.
//
// PLAYHEAD: um unico elemento movido por transform. Repintar 176 celulas a
// cada step (4x por segundo a 120 bpm) derruba qualquer navegador.
//
// A REGRA DE COR e a de Motor.cor_do_step()/cor_base() em lp_tr8s.py:
//     mudo > ALT > flam > sub > nota,  VEL_LIMIAR=64,  fora do last step.
// As cores vem do Python (--c-*), da mesma tabela que pinta os LEDs.
import { h, attr, prop, texto } from "../nucleo/dom.mjs";

const LIMIAR = 64; // VEL_LIMIAR do lp_tr8s.py
const SUB_FLAM = 1;

// tipo -> nome da classe usada no CSS
const TIPOS = [
  "vazio",
  "nota",
  "nota-f",
  "flam",
  "flam-f",
  "sub",
  "sub-f",
  "alt",
  "alt-f",
  "acc",
  "mudo",
  "mudo-f",
  "fora",
  "invalido",
];

function tipoDaCelula({ vel, sub, alt, mudo, fora, invalido, acc, ehAcc }) {
  if (invalido) return 13;
  if (fora) return 12;
  if (ehAcc) return acc ? 9 : 0;
  if (!vel) return 0;
  const forte = vel > LIMIAR;
  if (mudo) return forte ? 10 : 11;
  if (alt) return forte ? 7 : 8;
  if (sub === SUB_FLAM) return forte ? 3 : 4;
  if (sub) return forte ? 5 : 6;
  return forte ? 1 : 2;
}

export function gradeSteps({
  instrumentos,
  aoClicarCelula,
  aoClicarRotulo,
  aoMenuCelula,
}) {
  const LINHAS = instrumentos.length + 1; // + ACC
  const raiz = h("div.grade", { role: "grid", "aria-label": "pattern" });
  const celulas = new Array(LINHAS * 16);
  const rotulos = new Array(LINHAS);
  const cache = new Int32Array(LINHAS * 16).fill(-1);

  // regua de numeros
  raiz.append(h("div"));
  for (let s = 0; s < 16; s++) {
    raiz.append(h("div.num", { "data-tempo": s % 4 === 0 ? "" : null }, s + 1));
  }

  // A ACC desceu para o FIM da tela (pedido de 17/08/2026: o olho procura os
  // instrumentos, e o accent atravessado no topo empurrava o BD pra baixo).
  // Ela continua sendo a LINHA LOGICA 0 - data-l, os indices de celulas[] e
  // rotulos[] e o "+1 da ACC" de quem chama a marcarJanela nao mudam; o que
  // muda e so a ordem de insercao no grid. A folga acima dela e CSS
  // (margin-top no data-l="0").
  const nomes = ["ACC", ...instrumentos];
  const ordemVisual = [...instrumentos.map((_, i) => i + 1), 0];
  ordemVisual.forEach((l) => {
    const nome = nomes[l];
    const rot = h(
      "button.rot",
      { type: "button", "data-l": l, title: l === 0 ? "accent" : nome },
      h("span", {}, nome),
      h("small", {}, ""),
    );
    rot.addEventListener("click", () => aoClicarRotulo && aoClicarRotulo(l));
    rotulos[l] = rot;
    raiz.append(rot);
    for (let s = 0; s < 16; s++) {
      const c = h("button.cel", {
        type: "button",
        "data-l": l,
        "data-s": s,
        "data-tempo": s % 4 === 0 ? "" : null,
        "aria-label": `${nome} step ${s + 1}`,
      });
      celulas[l * 16 + s] = c;
      raiz.append(c);
    }
  });

  const playhead = h("div.playhead", { hidden: true });
  raiz.append(playhead);

  // moldura da janela dos Launchpads: 8 linhas sobre o proprio grid, no
  // lugar do antigo "espelho dos LEDs". Elemento unico movido por CSS vars.
  const janela = h("div.janela-lp", { hidden: true });
  raiz.append(janela);
  let janelaChave = "";

  // ultimoStep = last step da variacao (1..16). A moldura para nele, e nao na
  // coluna 16: com uma variacao de 12 steps ela avancava sobre os steps 13-16,
  // que estao fora do pattern e aparecem apagados - dava a impressao de que o
  // playhead ia ate o 13. O grid dos Launchpads continua tendo 16 colunas
  // fisicas; o que a moldura marca e a area que de fato toca.
  function marcarJanela(indices, ultimoStep = 16) {
    // linhas nao contiguas (esconder_mudos tirou uma do meio): a moldura
    // mentiria, entao ela some e a marca vai para os rotulos das linhas
    const contigua =
      indices.length > 0 &&
      indices[indices.length - 1] - indices[0] === indices.length - 1;
    janela.hidden = !contigua;
    if (contigua) {
      // Mede AS PROPRIAS CELULAS das esquinas (primeira da primeira linha,
      // ultima da ultima) e cobre exatamente esse retangulo. Tentativas
      // anteriores: somar alturas (erro acumulado), item do grid CSS
      // (deslocava as celulas auto-posicionadas - piorou tudo). Celula de
      // esquina nao tem como mentir. Os indices ja sao linhas do grid
      // (o +1 da ACC veio de quem chamou).
      const col = Math.min(15, Math.max(0, ultimoStep - 1));
      const primeira = celulas[indices[0] * 16];
      const ultima = celulas[indices[indices.length - 1] * 16 + col];
      const m = 3; // folga para a borda nao encostar nas celulas
      janela.style.top = primeira.offsetTop - m + "px";
      janela.style.left = primeira.offsetLeft - m + "px";
      janela.style.width =
        ultima.offsetLeft +
        ultima.offsetWidth -
        primeira.offsetLeft +
        2 * m +
        "px";
      janela.style.height =
        ultima.offsetTop +
        ultima.offsetHeight -
        primeira.offsetTop +
        2 * m +
        "px";
    }
    const chave = indices.join(",");
    if (chave === janelaChave) return;
    janelaChave = chave;
    rotulos.forEach((r, l) =>
      attr(r, "data-lp", indices.includes(l) && !contigua ? "" : null),
    );
  }

  // ── playhead que pinta as NOTAS da coluna ─────────────────
  // Verde cheio onde tem nota, verde fraco onde nao - como os pads. Le o
  // data-c que a pintura ja calculou (nao duplica a regra de cores nem toca
  // no cache Int32Array; data-play e camada de TRANSPORTE por cima da cor
  // de conteudo, e a celula volta ao normal quando a coluna passa).
  let colunaPintada = -1;

  function pintarColuna(p) {
    if (p === colunaPintada) return;
    limparColuna();
    colunaPintada = p;
    if (p < 0) return;
    for (let l = 0; l < LINHAS; l++) {
      const c = celulas[l * 16 + p];
      const t = c.dataset.c;
      if (t === "fora" || t === "invalido") continue;
      attr(c, "data-play", t && t !== "vazio" ? "f" : "o");
    }
  }

  function limparColuna() {
    if (colunaPintada < 0) return;
    for (let l = 0; l < LINHAS; l++)
      attr(celulas[l * 16 + colunaPintada], "data-play", null);
    colunaPintada = -1;
  }

  // ── playhead que anda sozinho entre dois quadros ──────────
  // O Launchpad e pintado no instante em que o clock chega; a tela so
  // saberia no proximo /estado, e a 120 bpm um step dura 125 ms contra 250 ms
  // de polling - dai o "verde um passo atrasado" que o Luan viu, com o pad
  // certo e a tela errada.
  //
  // Em vez de pedir estado mais vezes (o motor gera o estado sob lock, e
  // apertar isso competiria com o tick), a tela MEDE quanto dura um step: a
  // cada passo novo, o intervalo desde o anterior entra numa media que
  // amortece jitter de rede. Entre um quadro e outro ela avanca sozinha.
  //
  // Ela nunca avanca mais de um step alem do ultimo confirmado: se a maquina
  // parar ou virar a volta, o pior caso e ficar um step adiantada por uma
  // fracao de segundo - e o quadro seguinte corrige. Adivinhar mais do que
  // isso daria um playhead fluido e mentiroso.
  // O ciclo e o LAST STEP da variacao, nao 16. Enquanto isto foi 16 fixo, uma
  // variacao de 12 steps fazia o relogio adivinhar o step 13 (que nao existe) e
  // depois cair no 2 em vez do 1 - o servidor confirmava o step 1, mas o
  // relogio ja tinha disparado o passo seguinte. Era o "playhead maluco" de
  // 16/08/2026, e nao estava no motor: o motor sempre mandou 0..11.
  // QUANTO a tela pode andar sozinha antes de uma confirmacao do servidor.
  // A versao anterior adivinhava UM step e parava. Isso bastava enquanto o
  // step era mais longo que o polling; num step CURTO (scale 32nd, ou BPM
  // alto) cada quadro de /estado cobre varios steps, e o playhead: pulava
  // steps, travava no ultimo e reaparecia atrasado - os tres sintomas que o
  // Luan relatou em 17/08/2026, a 40 bpm em 32nd, onde o step dura 187 ms
  // contra 250 ms de polling.
  //
  // O limite e em TEMPO, nao em numero de steps: step longo continua ganhando
  // uma adivinhacao so, step curto ganha quantas couberem. Se a maquina parar,
  // o pior caso e ~2 steps fantasmas ate o quadro seguinte dizer que parou.
  const ADIVINHACAO_MS = 600;

  let passoReal = -1,
    tPasso = 0,
    durStep = 0,
    timer = 0,
    ciclo = 16,
    adivinhados = 0;

  function pararRelogio() {
    if (timer) {
      clearTimeout(timer);
      timer = 0;
    }
    passoReal = -1;
    adivinhados = 0;
    limparColuna();
  }

  // agenda a PROXIMA adivinhacao e, quando ela acontece, agenda a seguinte -
  // e assim a tela acompanha step curto sem depender do polling
  function agendarAdivinhacao() {
    if (timer) {
      clearTimeout(timer);
      timer = 0;
    }
    if (!durStep || passoReal < 0) return;
    const n = adivinhados + 1;
    if (durStep * n > ADIVINHACAO_MS) return; // longe demais: espera o servidor
    const falta = durStep * n - (performance.now() - tPasso);
    timer = setTimeout(
      () => {
        timer = 0;
        if (passoReal < 0) return;
        adivinhados = n;
        const p = (passoReal + n) % ciclo;
        prop(playhead, "--p", p);
        pintarColuna(p);
        agendarAdivinhacao();
      },
      Math.max(10, falta),
    );
  }

  function marcarPasso(p) {
    if (p !== passoReal) {
      const agora = performance.now();
      if (passoReal >= 0 && tPasso) {
        const dt =
          (agora - tPasso) / Math.max(1, (p - passoReal + ciclo) % ciclo);
        // 30..2000 ms cobre de 500 bpm a 8 bpm; fora disso e engasgo de rede
        if (dt > 30 && dt < 2000) {
          durStep = durStep ? durStep * 0.7 + dt * 0.3 : dt;
          // o respiro do fill (CSS) dura UM COMPASSO. Quem sabe quanto isso
          // vale em ms e este relogio, que mede o step de verdade - assim o
          // respiro fecha na virada em qualquer BPM e qualquer scale, sem
          // ninguem escrever numero nenhum no CSS
          prop(raiz, "--compasso", Math.round(durStep * ciclo) + "ms");
        }
      }
      passoReal = p;
      tPasso = agora;
      adivinhados = 0;
      prop(playhead, "--p", p);
      pintarColuna(p);
    }
    agendarAdivinhacao();
  }

  // ── um unico listener para as 208 celulas ──
  let pintandoArrasto = null; // {ligar:bool} decidido pela primeira celula
  raiz.addEventListener("pointerdown", (e) => {
    const c = e.target.closest(".cel");
    if (!c) return;
    const l = +c.dataset.l,
      s = +c.dataset.s;
    // botao direito: so NAO pintar - o menu vem uma vez so, no contextmenu
    // (abrir aqui tambem criava o menu em dobro a cada clique direito)
    if (e.button === 2) return;
    if (e.altKey) {
      aoMenuCelula && aoMenuCelula(l, s, c);
      return;
    }
    pintandoArrasto = { feitas: new Set([`${l},${s}`]) };
    aoClicarCelula && aoClicarCelula(l, s, { fraco: e.shiftKey });
  });
  raiz.addEventListener("pointerover", (e) => {
    if (!pintandoArrasto) return;
    const c = e.target.closest(".cel");
    if (!c) return;
    const k = `${c.dataset.l},${c.dataset.s}`;
    if (pintandoArrasto.feitas.has(k)) return; // uma acao por celula
    pintandoArrasto.feitas.add(k);
    aoClicarCelula &&
      aoClicarCelula(+c.dataset.l, +c.dataset.s, { fraco: e.shiftKey });
  });
  const soltar = () => {
    pintandoArrasto = null;
  };
  window.addEventListener("pointerup", soltar);
  window.addEventListener("pointercancel", soltar);
  raiz.addEventListener("contextmenu", (e) => {
    const c = e.target.closest(".cel");
    if (c) {
      e.preventDefault();
      aoMenuCelula && aoMenuCelula(+c.dataset.l, +c.dataset.s, c);
    }
  });

  return {
    raiz,
    /** e[chave] cru do /estado; pendentes = Set("l,s") aguardando a maquina */
    pintar(e, pendentes = new Set()) {
      const ptn = e.pattern || {},
        subs = e.subs || {},
        alts = e.alts || {};
      const probs = e.probs || {},
        mudo = e.mudo || [];
      const invalidos = new Set(e.cache_invalido || []);
      const lastVar = e.last_var || 16,
        lastTrack = e.last_track || [];
      const carregado = !!e.carregado;

      for (let l = 0; l < LINHAS; l++) {
        const ehAcc = l === 0;
        const i = l - 1;
        const lim = ehAcc ? lastVar : Math.min(lastVar, lastTrack[i] || 16);
        const vels = ehAcc ? null : ptn[i] || [];
        const sub = ehAcc ? null : subs[i] || [];
        const alt = ehAcc ? null : alts[i] || [];
        const pr = ehAcc ? null : probs[i] || [];
        const invalido = !ehAcc && invalidos.has(i);
        const mudoAqui = !ehAcc && !!mudo[i];

        // rotulo: mudo riscado, linha com leitura falhada em vermelho
        const rot = rotulos[l];
        attr(rot, "data-mudo", mudoAqui ? "" : null);
        attr(rot, "data-invalido", invalido ? "" : null);
        texto(
          rot.lastChild,
          !ehAcc && lastTrack[i] && lastTrack[i] < 16
            ? String(lastTrack[i])
            : "",
        );

        for (let s = 0; s < 16; s++) {
          const idx = l * 16 + s;
          const t = !carregado
            ? 0
            : tipoDaCelula({
                vel: vels ? vels[s] : 0,
                sub: sub ? sub[s] : 0,
                alt: alt ? alt[s] : 0,
                mudo: mudoAqui,
                fora: s >= lim,
                invalido,
                acc: ehAcc && e.acc & (1 << s),
                ehAcc,
              });
          const p = !ehAcc && pr && vels && vels[s] && pr[s] < 100 ? pr[s] : 0;
          const pend = pendentes.has(`${l},${s}`) ? 1 : 0;
          const codigo = (t << 9) | (p << 1) | pend;
          if (cache[idx] === codigo) continue; // nada mudou: nao toca
          cache[idx] = codigo;
          const c = celulas[idx];
          attr(c, "data-c", TIPOS[t]);
          if (p) {
            attr(c, "data-prob", "");
            prop(c, "--prob", p / 100);
          } else attr(c, "data-prob", null);
          attr(c, "data-pendente", pend ? "" : null);
        }
      }

      // playhead: so quando a maquina toca E o grid esta na variacao que soa.
      // O ciclo do relogio local acompanha o last step da variacao - sem isto
      // ele adivinhava steps que o pattern nem tem (ver comentario la em cima)
      ciclo = Math.min(16, Math.max(1, e.last_var || 16));
      const mostra = e.tocando && e.playhead_visivel && e.passo >= 0;
      playhead.hidden = !mostra;
      if (mostra) marcarPasso(e.passo);
      else pararRelogio();
      // o repintado acima pode ter trocado o data-c de celulas sob o
      // playhead: refaz a camada de transporte por cima
      if (colunaPintada >= 0) {
        const p = colunaPintada;
        colunaPintada = -1;
        pintarColuna(p);
      }
    },
    marcarLinha(l) {
      rotulos.forEach((r, k) => attr(r, "data-sel", k === l ? "" : null));
    },
    marcarJanela,
  };
}
