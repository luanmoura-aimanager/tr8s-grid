// formato.mjs - traducoes de valor para texto. Espelho de efeitos.rotulo_valor.
const BANCOS = "ABCDEFGH";

/** 0-127 -> "B3". Trata null e fora de faixa: "pattern undefined1" ja
 *  apareceu na tela por causa de um indice sem guarda. */
export function nomePattern(p) {
  if (p === null || p === undefined || p < 0 || p > 127) return "—";
  return BANCOS[Math.floor(p / 16)] + ((p % 16) + 1);
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
