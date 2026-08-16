// paleta.mjs - as cores do pattern vem do PYTHON, nao do CSS.
//
// A mesma tabela que pinta os LEDs do Launchpad (lp_tr8s.paleta_da_tela) vira
// custom property aqui. Assim a cor de um step na tela e no aparelho nunca
// divergem - foi o que comecou a acontecer quando a janela Tk tinha a propria
// copia da paleta.
export function aplicarPaleta(cores) {
  const r = document.documentElement;
  for (const [nome, hex] of Object.entries(cores || {})) {
    r.style.setProperty("--c-" + nome, hex);
  }
}
