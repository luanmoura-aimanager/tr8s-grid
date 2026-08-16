// rede.mjs - conversa com o servidor local.
//
// Tres coisas que a versao anterior nao tinha e custaram caro:
//  1. TIMEOUT. O motor segura o lock por ~2 s quando rele a maquina; sem
//     AbortController a promessa pendurava e o laco de polling morria calado.
//  2. ERRO VISIVEL. acao() ignorava response.ok, entao "ligue o modo ON" e
//     "cache invalido, escrita abortada" nunca chegavam na tela.
//  3. BACKOFF. Com o servidor fora do ar a pagina metralhava pedidos a cada
//     250 ms para sempre, e nao se recuperava sozinha quando ele voltava.

let TOKEN = "";

export async function pegarToken() {
  // o cookie de sessao (SameSite=Strict, HttpOnly) autoriza esta chamada.
  // outro site nao consegue: o cookie nao viaja e a resposta nao tem CORS.
  const r = await fetch("/token");
  if (!r.ok) throw new Error("sem sessao (abra pelo atalho do app)");
  TOKEN = (await r.json()).token;
  sessionStorage.removeItem(RECARGA); // deu certo: libera a rede de seguranca
  history.replaceState(null, "", "/"); // tira o ?t= da barra do navegador
  return TOKEN;
}

const RECARGA = "tr8s-recarregou";
let recuperando = null;

/**
 * O servidor sorteia um TOKEN novo a cada boot. Entao reiniciar o servidor -
 * um `instalar_agente.py`, um reboot, o app sendo reaberto - deixa a pagina
 * aberta com credencial velha, e TODO clique vira 403 "origem nao autorizada".
 * A pagina reconectava o polling (que e GET e nao usa token) e dizia "contato
 * restabelecido", entao parecia viva enquanto nada funcionava.
 *
 * Aconteceu de verdade em 16/08/2026 e so um F5 manual resolvia - sem que a
 * mensagem dissesse isso. Agora a pagina repega o token sozinha; se o cookie
 * tambem venceu (so o GET / reemite), recarrega UMA vez.
 */
async function recuperarSessao() {
  if (!recuperando) {
    recuperando = (async () => {
      try {
        await pegarToken();
        return true;
      } catch (e) {
        if (!sessionStorage.getItem(RECARGA)) {
          // uma vez so: com o servidor fora do ar isto viraria laco de reload
          sessionStorage.setItem(RECARGA, "1");
          location.reload();
        }
        return false;
      } finally {
        recuperando = null;
      }
    })();
  }
  return recuperando;
}

export async function getJSON(rota, ms = 1200) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(rota, { signal: ctl.signal });
    if (!r.ok) throw new Error(`${rota}: HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

/** Manda uma acao. Devolve {ok, erro}. Nunca lanca - quem chama decide. */
export async function acao(corpo, ms = 4000, jaTentou = false) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch("/acao", {
      method: "POST",
      signal: ctl.signal,
      headers: { "Content-Type": "application/json", "X-TR8S-Token": TOKEN },
      body: JSON.stringify(corpo),
    });
    if (r.ok) return { ok: true };
    // 403 = o servidor reiniciou e o token mudou. Repega e repete UMA vez;
    // a acao nao chegou a rodar, entao repetir nao duplica nada
    if (r.status === 403 && !jaTentou && (await recuperarSessao()))
      return acao(corpo, ms, true);
    let erro = `HTTP ${r.status}`;
    try {
      erro = (await r.json()).erro || erro;
    } catch (e) {}
    return { ok: false, erro };
  } catch (e) {
    return {
      ok: false,
      erro:
        e.name === "AbortError"
          ? "o servidor demorou demais"
          : "sem contato com o servidor",
    };
  } finally {
    clearTimeout(t);
  }
}

export async function sair(jaTentou = false) {
  // mesmo tratamento de 403 do acao(): sem ele, o botao Sair era justamente o
  // unico que continuava quebrado depois de o servidor reiniciar - respondia
  // 403, caia no catch vazio, e a pessoa clicava achando que travou
  try {
    const r = await fetch("/sair", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TR8S-Token": TOKEN },
      body: "{}",
    });
    if (r.status === 403 && !jaTentou && (await recuperarSessao()))
      return sair(true);
  } catch (e) {}
}

/**
 * Laco de estado. Rapido com a aba a vista, lento em segundo plano, e com
 * recuo progressivo quando o servidor some.
 */
export function lacoEstado({ aoEstado, aoFalhar, aoVoltar }) {
  let atraso = 250,
    falhas = 0,
    parado = false;
  const RAPIDO = 250,
    LENTO = 2000,
    TETO = 4000;

  async function passo() {
    if (parado) return;
    try {
      const e = await getJSON("/estado");
      if (falhas) {
        falhas = 0;
        aoVoltar && aoVoltar();
      }
      atraso = document.hidden ? LENTO : RAPIDO;
      aoEstado(e);
    } catch (err) {
      falhas++;
      // recuo com jitter, para nao sincronizar rajadas de tentativa
      atraso =
        Math.min(TETO, 250 * 2 ** Math.min(falhas, 4)) + Math.random() * 150;
      aoFalhar && aoFalhar(err, Math.round(atraso));
    }
    setTimeout(passo, atraso);
  }

  // voltar para a aba acorda na hora, sem esperar o ciclo lento terminar
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !falhas) {
      atraso = RAPIDO;
    }
  });
  passo();
  return {
    parar() {
      parado = true;
    },
  };
}
