// store.mjs - o estado da tela.
//
// A maquina e a autoridade; a tela e espelho. O unico estado que vive aqui e o
// OVERLAY OTIMISTA: quando voce solta um fader, o valor local vale por um
// tempo, senao o proximo quadro (que pode trazer leitura de ate 1,5 s atras)
// puxaria o controle de volta e pareceria que a tela ignorou o gesto.
//
// Regra: o local vence ate a maquina confirmar OU ate PRAZO passar. Estourando
// o prazo com a maquina ainda discordando, volta o valor dela e avisa - foi a
// TR-8S que nao aceitou, e isso e informacao, nao ruido.

export const D = {}; // dados estaticos (congelado no boot)
export let S = {}; // ultimo estado do servidor

const PRAZO = 3500; // dois ciclos de releitura do motor
const local = new Map(); // chave -> {valor, t}
export const arrastando = new Set(); // chaves em uso agora (nao sobrescrever)

const ouvintes = new Set();
let agendado = false;

export function assinar(fn) {
  ouvintes.add(fn);
  return () => ouvintes.delete(fn);
}

export function definirDados(d) {
  Object.assign(D, d);
}

export function aplicarEstado(novo) {
  S = novo;
  // limpa overlays que a maquina ja confirmou ou que expiraram
  const agora = performance.now();
  for (const [chave, o] of local) {
    if (agora - o.t > PRAZO) {
      local.delete(chave);
      if (o.aoExpirar) o.aoExpirar();
    }
  }
  agendarRender();
}

let devendoRender = false;

document.addEventListener("visibilitychange", () => {
  // voltar para a aba tem que repintar na hora: sem isto a tela mostrava o
  // quadro velho ate o proximo estado chegar - ate 2 s no modo lento
  if (!document.hidden && devendoRender) agendarRender();
});

function agendarRender() {
  if (document.hidden) {
    devendoRender = true;
    return;
  }
  if (agendado) return;
  agendado = true;
  requestAnimationFrame(() => {
    agendado = false;
    devendoRender = false;
    for (const fn of ouvintes) {
      try {
        fn(S, D);
      } catch (e) {
        console.error(e);
      }
    }
  });
}
export { agendarRender };

/** Marca um valor como "eu acabei de mandar; segura ai". */
export function otimista(chave, valor, aoExpirar) {
  local.set(chave, { valor, t: performance.now(), aoExpirar });
}
export function largar(chave) {
  local.delete(chave);
}

/** Valor que a tela deve mostrar: o meu recente, ou o da maquina. */
export function efetivo(chave, doServidor) {
  const o = local.get(chave);
  if (!o) return doServidor;
  if (o.valor === doServidor) {
    local.delete(chave);
    return doServidor;
  }
  return o.valor;
}
export function pendente(chave) {
  return local.has(chave);
}
