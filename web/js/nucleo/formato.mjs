// formato.mjs - traducoes de valor para texto. Espelho de efeitos.rotulo_valor.

/** 0-127 -> "2-05", COMO O VISOR: banco e NUMERO (1-8); letra e variacao.
 *  A tela ja mostrou "B5" e confundiu o Luan - "nem existe pattern B"
 *  (16/08). Trata null e fora de faixa. */
export function nomePattern(p) {
  if (p === null || p === undefined || p < 0 || p > 127) return "—";
  return Math.floor(p / 16) + 1 + "-" + String((p % 16) + 1).padStart(2, "0");
}

export function intOu(v, padrao = 0) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : padrao;
}

/** Como mostrar o valor de um parametro de FX (enum, bipolar ou cru). */
export function rotuloValor(ent, valor) {
  if (valor === null || valor === undefined) return "—";
  if (!ent) return String(valor);
  if (ent.forma === "enum") {
    return (ent.opcoes || {})[String(valor)] || `? (${valor})`;
  }
  if (ent.escala && ent.escala[valor] !== undefined) return ent.escala[valor];
  // bipolar guarda 0-255 com centro em 128 (Reference p.33)
  if (ent.bipolar) return (valor - 128 >= 0 ? "+" : "") + (valor - 128);
  return String(valor);
}

export function pct(v, min, max) {
  if (max === min) return 0;
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}
