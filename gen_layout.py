#!/usr/bin/env python3
"""Gera layout.html - referencia visual do mapeamento dos dois Launchpad."""

# ── semantica de cor (3 acentos, significado fixo na pagina inteira) ──
# NIGHT MODE: os acentos usam as versoes claras. As versoes escuras do tema claro
# (#0f766e, #7a5af5, #c2410c) somem no fundo preto - nao voltar a elas sem trocar
# o fundo junto.
TEAL   = TEAL_L   = "#2dd4bf"   # navegacao: onde/o que voce edita
PURPLE = PURPLE_L = "#a78bfa"   # som: como o step vai soar
ORANGE = ORANGE_L = "#fb923c"   # lote: muda muitos steps de uma vez
TEAL_BG, PURPLE_BG, ORANGE_BG = "#0d2b27", "#1c1733", "#2e1a0c"

# cores de pad (aproximam a paleta Novation usada no script)
# A paleta dos steps ESPELHA o painel da TR-8S (REFERENCIA 5.3): nota vermelha,
# flam lilas, sub amarelo, ALT rosa. Sao os COR_* do lp_tr8s.py, que vao de
# 0-127; aqui em hex, dobrados.
P_OFF, P_TEMPO = "#3a3633", "#6b6560"
P_FORTE, P_FRACA = "#e8433f", "#8f2b28"
P_FLAM, P_FLAM_FRACA = "#c47cfe", "#442894"
P_SUB, P_SUB_FRACA = "#ffe000", "#584c00"
P_ALT, P_ALT_FRACA = "#ff3450", "#5c103a"
P_PLAY, P_PLAY_HIT = "#1c7a4a", "#35d07f"
P_ACC = "#007cfe"                       # azul vivido - a linha de ACCENT
P_FORA = "#0a0a0a"
# Linha mutada: cinza-azulado dessaturado, um par so. Sem matiz proprio de
# proposito - o que ela comunica e ausencia de som.
P_MUTE_FORTE, P_MUTE_FRACA = "#38445c", "#161c26"
SLAB, SLAB_EDGE = "#2a2724", "#4a443c"   # corpo do aparelho: mais claro que o fundo

# ── geometria ──
PAD, GAP = 24, 4
PITCH = PAD + GAP
GRIDW = 8 * PAD + 7 * GAP          # 220
R = 10                              # raio dos botoes redondos
OX = 120                            # deslocamento pra caber os rotulos da esquerda

L_BTN_CX = OX + 40
L_GX     = OX + 62
L_GX1    = L_GX + GRIDW
SLAB_GAP = 52          # o vao entre as slabs carrega os nomes dos instrumentos
R_SX     = L_GX1 + 8 + SLAB_GAP     # inicio da slab direita
R_GX     = R_SX + 8
R_GX1    = R_GX + GRIDW
R_BTN_CX = R_GX1 + 18
TOP_CY   = 36
GY       = 58
GY1      = GY + GRIDW

def col_cx(gx, i): return gx + PAD // 2 + i * PITCH
def row_cy(i):     return GY + PAD // 2 + i * PITCH

# ── conteudo dos botoes: (cc, rotulo, cor_clara) ──
TOPO_ESQ = [(cc, ch, TEAL_L) for cc, ch in
            zip([89, 79, 69, 59, 49, 39, 29, 19], "ABCDEFGH")]
BORDA_ESQ = [(98, "FILL 1", TEAL_L), (97, "FILL 2", TEAL_L),
             (96, "CLEAR inst", ORANGE_L), (95, "CLEAR variação", ORANGE_L),
             (94, "HIDE MUTED", ORANGE_L), (93, "ALT", PURPLE_L),
             (92, "copiar", ORANGE_L), (91, "colar", ORANGE_L)]
# rotulos curtos: o passo entre botoes e 28px, nome longo colide com o vizinho
TOPO_DIR = [(91, "INST▲", TEAL_L), (92, "INST▼", TEAL_L),
            (93, "NORM", PURPLE_L), (94, "FLAM", PURPLE_L),
            (95, "½", PURPLE_L), (96, "⅓", PURPLE_L),
            (97, "¼", PURPLE_L), (98, "ACC", TEAL_L)]
BORDA_DIR = [(cc, str(v), PURPLE_L) for cc, v in
             zip([89, 79, 69, 59, 49, 39, 29, 19],
                 [127, 110, 100, 80, 60, 50, 30, 10])]
# Os dois que a propria maquina usa: o ciclo do pad dela e strong -> weak -> off
VEL_FORTE, VEL_FRACA = "80", "50"

# ── pattern de exemplo: um dump real da maquina, com um last step e um mute
# aplicados por cima pra que o desenho sirva de legenda de todas as cores ──
LINHAS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH"]
FORTE = {"BD": [1, 7], "SD": [5, 13], "LT": [4, 7, 10, 12, 15],
         "MT": [1, 5, 9, 13], "HT": [3], "RS": [], "HC": [1],
         "CH": [1, 5, 9, 13]}
FRACA = {"CH": [3, 7, 11, 15]}
SUB   = {"LT": [12]}                    # um flam, pra aparecer o laranja
PLAYHEAD = 5                            # step em que o playhead esta
LAST    = 14                            # last step: 15 e 16 ficam fora
# LT esta mutado no exemplo de proposito: ele tem notas fortes E um flam, entao
# a figura mostra o roxo e o azul de uma vez, que e o par que a legenda explica
MUDO    = {"LT"}

def cor_pad(linha, step):
    nome = LINHAS[linha]
    forte = step in FORTE.get(nome, [])
    fraca = step in FRACA.get(nome, [])
    sub   = step in SUB.get(nome, [])
    mudo  = nome in MUDO
    # precedencia igual a do lp_tr8s.py: fora do last step vence tudo, e numa
    # linha muda o playhead nao aparece - o verde diria "esta soando agora"
    if step > LAST:
        return P_FORA
    if step == PLAYHEAD and not mudo:
        return P_PLAY_HIT if (forte or fraca) else P_PLAY
    if mudo and (forte or fraca):
        return P_MUTE_FRACA if fraca else P_MUTE_FORTE
    if mudo:
        return P_OFF                    # linha mutada perde a cabeca de tempo
    if sub:
        return P_SUB_FRACA if fraca else P_SUB
    if forte:
        return P_FORTE
    if fraca:
        return P_FRACA
    return P_TEMPO if (step - 1) % 4 == 0 else P_OFF

# ── montagem do SVG ──
s = []
def add(x): s.append(x)

def slab(x0, y0, x1, y1, titulo, sub):
    add(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="12" '
        f'fill="{SLAB}" stroke="{SLAB_EDGE}"/>')
    add(f'<text x="{(x0+x1)/2:.0f}" y="{y1+16}" text-anchor="middle" '
        f'class="slab-t">{titulo}</text>')
    add(f'<text x="{(x0+x1)/2:.0f}" y="{y1+29}" text-anchor="middle" '
        f'class="slab-s">{sub}</text>')

def botao(cx, cy, cc, cor):
    add(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{cor}" '
        f'stroke-width="2"/>')
    add(f'<text x="{cx}" y="{cy+3}" text-anchor="middle" class="cc">{cc}</text>')

def grade(gx, off):
    for l in range(8):
        for c in range(8):
            step = off + c + 1
            add(f'<rect x="{gx + c*PITCH}" y="{GY + l*PITCH}" width="{PAD}" '
                f'height="{PAD}" rx="4" fill="{cor_pad(l, step)}"/>')

L_SX0, L_SX1 = L_BTN_CX - R - 8, L_GX1 + 8
R_SX1 = R_BTN_CX + R + 8
SY0, SY1 = TOP_CY - R - 8, GY1 + 8

slab(L_SX0, SY0, L_SX1, SY1, "ESQUERDO", "girado 90° anti-horário · steps 1–8")
slab(R_SX, SY0, R_SX1, SY1, "DIREITO", "posição normal · steps 9–16")

grade(L_GX, 0)
grade(R_GX, 8)

# topo esquerdo (coluna de cena girada) — rotulo acima da slab
for i, (cc, rot, cor) in enumerate(TOPO_ESQ):
    cx = col_cx(L_GX, i)
    botao(cx, TOP_CY, cc, cor)
    add(f'<text x="{cx}" y="{SY0-6}" text-anchor="middle" class="lbl" '
        f'fill="{TEAL}">{rot}</text>')
# topo direito (fileira de funcao)
for i, (cc, rot, cor) in enumerate(TOPO_DIR):
    cx = col_cx(R_GX, i)
    botao(cx, TOP_CY, cc, cor)
    add(f'<text x="{cx}" y="{SY0-6}" text-anchor="middle" class="lbl" '
        f'fill="{PURPLE if cor == PURPLE_L else TEAL}">{rot}</text>')
# borda esquerda (fileira de funcao girada) — rotulo a esquerda da slab
for i, (cc, rot, cor) in enumerate(BORDA_ESQ):
    cy = row_cy(i)
    botao(L_BTN_CX, cy, cc, cor)
    add(f'<text x="{L_SX0-8}" y="{cy+4}" text-anchor="end" class="lbl" '
        f'fill="{ORANGE if cor == ORANGE_L else TEAL}">{rot}</text>')
# borda direita (coluna de cena) — rotulo a direita
for i, (cc, rot, cor) in enumerate(BORDA_DIR):
    cy = row_cy(i)
    botao(R_BTN_CX, cy, cc, cor)
    add(f'<text x="{R_SX1+8}" y="{cy+4}" class="lbl" fill="{PURPLE}">{rot}</text>')

# logos (CC 99). Ficam no canto onde a fileira de funcao encontra a coluna de
# cena: no aparelho normal isso e o canto superior DIREITO; girado 90° anti-horario
# esse mesmo canto vai parar no superior ESQUERDO.
# Eles NAO sao botoes - so LED. Nao ha chave embaixo (visto no hardware em
# 13/08/2026), entao nunca enviam nada. Ficam desenhados como marca apagada,
# porque o logo esquerdo ainda serve de indicador de "tem alguem mutado".
# No adesivo eles levam uma etiqueta BRANCA que serve de cabecalho da borda
# vizinha: VAR apontando pro lado no esquerdo, VELOCITY apontando pra baixo no
# direito.
for cx, rot in ((L_BTN_CX, "VAR ▸"), (R_BTN_CX, "VELOCITY ▾")):
    add(f'<rect x="{cx-R}" y="{TOP_CY-R}" width="{2*R}" height="{2*R}" rx="3" '
        f'fill="#e8e4dc" stroke="#8a837a"/>')
    add(f'<text x="{cx}" y="{SY0-6}" text-anchor="middle" class="lbl" '
        f'fill="#9a938a">{rot}</text>')

# nomes dos instrumentos no vao entre as slabs: as linhas sao as mesmas nos dois
# aparelhos, entao uma coluna so de rotulos serve para os dois
MEIO = L_SX1 + SLAB_GAP / 2
for l, nome in enumerate(LINHAS):
    add(f'<text x="{MEIO:.0f}" y="{row_cy(l)+4}" text-anchor="middle" '
        f'class="inst">{nome}</text>')

VB_W, VB_H = R_SX1 + 96, SY1 + 40
SVG = (f'<svg viewBox="0 0 {VB_W} {VB_H}" xmlns="http://www.w3.org/2000/svg" '
       f'role="img" aria-label="Layout dos dois Launchpad Mini MK3">'
       + "".join(s) + "</svg>")

# ── tabelas de referencia ──
def tabela(titulo, cor, linhas, nota=""):
    tr = "".join(f'<tr><td class="m">{cc}</td><td>{f}</td></tr>' for cc, f in linhas)
    n = f'<p class="nota">{nota}</p>' if nota else ""
    return (f'<div class="grp"><h4 style="color:{cor}">{titulo}</h4>'
            f'<table class="ref"><tbody>{tr}</tbody></table>{n}</div>')

T1 = tabela("Topo esquerdo — variações", TEAL,
            [(cc, f"variação {ch}") for cc, ch in
             zip([89, 79, 69, 59, 49, 39, 29, 19], "ABCDEFGH")],
            "Ordem A→H já sai correta da esquerda para a direita depois da rotação.")
T2 = tabela("Borda esquerda — de cima para baixo", ORANGE,
            [(98, "FILL 1 &nbsp;<span class='m'>0x09</span>"),
             (97, "FILL 2 &nbsp;<span class='m'>0x0A</span>"),
             (96, "CLEAR instrumento — arma, o próximo pad limpa a linha"),
             (95, "CLEAR variação — segundo toque em 2 s confirma"),
             (94, "<b>HIDE MUTED</b> — tira do grid as linhas mutadas na TR-8S; "
                  "apertando de novo elas voltam em roxo (notas) e azul (flam/sub)"),
             (93, "<b>ALT</b> — arma o som alternado; o próximo pad grava em rosa. Só soa nos tones com <code>/</code> no nome"),
             (92, "copiar variação para o buffer"),
             (91, "colar o buffer na variação atual")],
            "A fileira de função gira junto: de cima para baixo ela corre 98→91. "
            "As duas do meio eram as setas de rolagem, que faziam o mesmo que as "
            "do aparelho direito — viraram MUTE e WRITE quando se descobriu que os "
            "logos não são botões.")
T3 = tabela("Topo direito — da esquerda para a direita", PURPLE,
            [(91, "<b>INST UP</b> — sobe um instrumento"),
             (92, "<b>INST DN</b> — desce um instrumento"),
             (93, "modo NORMAL"), (94, "modo FLAM"), (95, "modo SUB 1/2"),
             (96, "modo SUB 1/3"), (97, "modo SUB 1/4"),
             (98, "ACCENT — mostra/oculta a linha de ACC")],
            "Os modos caem em ◀▶ por aritmética: sobraram 6 vagas para 5 modos "
            "depois das setas.")
T4 = tabela("Borda direita — velocity", PURPLE,
            [(cc, f"velocity {v}" +
              {80: " &nbsp;<b>forte</b> — o normal da máquina",
               50: " &nbsp;<b>fraca</b> — o weak beat da máquina"}.get(v, ""))
             for cc, v in zip([89, 79, 69, 59, 49, 39, 29, 19],
                              [127, 110, 100, 80, 60, 50, 30, 10])],
            "Substitui o antigo SHIFT binário. O nível aceso é o que o pad escreve. "
            "O ciclo do pad da própria TR-8S é <b>strong → weak → off</b> "
            "(Reference p. 45), e esses dois estados são justamente 80 e 50 — por "
            "isso eles acendem na cor que a nota deles vai ter no grid, e o resto "
            "da coluna fica cinza. Os outros seis níveis só existem porque a "
            "máquina aceita velocity contínua, que é o que o grid destrava.")
T5 = tabela("Logos — não são botões", "#6f6860",
            [(99, "esquerdo — adesivo <b>VAR ▸</b>; acende com linha escondida"),
             (99, "direito — adesivo <b>VELOCITY ▾</b>; apagado")],
            "O logo tem LED endereçável mas <b>não tem chave embaixo</b>: nunca "
            "envia nada. HIDE MUTED e WRITE moraram ali por um tempo, o que os deixava "
            "inalcançáveis — foram para as setas do aparelho esquerdo, a única "
            "função que estava duplicada no mapa. Rolagem de linha agora só no "
            "aparelho direito.")

def chip(cor, txt):
    return f'<span class="chip" style="--c:{cor}">{txt}</span>'

LEGENDA_PAD = "".join(
    f'<div class="lg"><span class="sw" style="background:{c}"></span>{t}</div>'
    for c, t in [(P_FORTE, "nota forte (velocity &gt; 64)"),
                 (P_FRACA, "nota fraca (velocity ≤ 64)"),
                 (P_FLAM, "<b>flam</b> — lilás, como na TR-8S"),
                 (P_FLAM_FRACA, "flam em velocity fraca"),
                 (P_SUB, "<b>sub step</b> 1/2, 1/3, 1/4 — amarelo"),
                 (P_SUB_FRACA, "sub step em velocity fraca"),
                 (P_ALT, "<b>ALT</b> (som alternado) — rosa"),
                 (P_ALT_FRACA, "ALT em velocity fraca"),
                 (P_ACC, "linha de <b>ACCENT</b>"),
                 (P_PLAY_HIT, "playhead sobre nota"),
                 (P_PLAY, "playhead sobre vazio"),
                 (P_TEMPO, "cabeça de tempo vazia (1, 5, 9, 13)"),
                 (P_MUTE_FORTE, "linha <b>mutada</b> na TR-8S"),
                 (P_MUTE_FRACA, "linha mutada, velocity fraca"),
                 (P_FORA, "step além do LAST STEP"),
                 (P_OFF, "apagado")])

HTML = f"""<!doctype html>
<!-- gerado por gen_layout.py -->
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Layout dos Launchpad — TR-8S Grid</title>
<style>
:root{{
  color-scheme:dark;
  --bg:#0e0d0c; --card:#181614; --ink:#ece8e2; --muted:#9a938a; --faint:#6f6860;
  --line:#2b2825; --line2:#3a3631;
  --nav:{TEAL};   --nav-bg:{TEAL_BG};   /* navegação: onde/o que você edita  */
  --som:{PURPLE}; --som-bg:{PURPLE_BG}; /* som: como o step vai soar          */
  --lote:{ORANGE};--lote-bg:{ORANGE_BG};/* lote: muda muitos steps de uma vez */
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:880px;margin:0 auto;padding:44px 20px 80px}}
h1{{font-size:26px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}}
.sub{{color:var(--muted);margin:0 0 26px;font-size:14px}}
.thesis{{font-size:17px;line-height:1.55;margin:0 0 30px;padding:16px 18px;
  background:var(--card);border:1px solid var(--line);border-radius:11px}}
h2{{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
  margin:38px 0 12px;font-weight:600}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:11px;
  padding:20px}}
svg{{width:100%;height:auto;display:block}}
.cc{{font:600 8px ui-monospace,Menlo,monospace;fill:#c9c3ba}}
.lbl{{font:600 9px -apple-system,sans-serif}}
.inst{{font:600 9px ui-monospace,Menlo,monospace;fill:var(--muted)}}
.slab-t{{font:700 9px -apple-system,sans-serif;fill:var(--ink);
  letter-spacing:.06em}}
.slab-s{{font:9px -apple-system,sans-serif;fill:var(--muted)}}
.cap{{color:var(--muted);font-size:13px;margin:14px 0 0;text-align:center}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 0;justify-content:center}}
.chip{{font:600 11px ui-monospace,Menlo,monospace;color:var(--c);
  background:color-mix(in srgb,var(--c) 16%,transparent);
  border:1px solid color-mix(in srgb,var(--c) 38%,transparent);
  padding:3px 9px;border-radius:20px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.grp{{background:var(--card);border:1px solid var(--line);border-radius:11px;
  padding:16px 18px}}
.grp h4{{margin:0 0 10px;font-size:12px;letter-spacing:.04em;text-transform:uppercase}}
table.ref{{width:100%;border-collapse:collapse;font-size:13.5px}}
table.ref td{{padding:4px 0;border-bottom:1px solid var(--line);vertical-align:top}}
table.ref tr:last-child td{{border-bottom:0}}
table.ref td:first-child{{width:34px;color:var(--faint)}}
.m{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}}
.nota{{margin:10px 0 0;font-size:12.5px;color:var(--muted);line-height:1.5}}
.legenda{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px 18px;
  margin-top:4px}}
.lg{{display:flex;align-items:center;gap:9px;font-size:13px}}
.sw{{width:15px;height:15px;border-radius:3px;flex:none;
  outline:1px solid rgba(255,255,255,.18)}}
.lens{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}}
.lens>div{{padding:13px 15px;border-radius:9px;font-size:13.5px;line-height:1.55}}
.biz{{background:var(--nav-bg);border:1px solid color-mix(in srgb,var(--nav) 22%,transparent)}}
.hood{{background:var(--som-bg);border:1px solid color-mix(in srgb,var(--som) 22%,transparent)}}
.lens h5{{margin:0 0 5px;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.07em}}
.biz h5{{color:var(--nav)}} .hood h5{{color:var(--som)}}
.io{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--muted);
  margin-top:12px}}
.io b{{color:var(--ink)}}
.falta{{background:var(--card);border:1px solid var(--line);border-radius:11px;
  padding:6px 18px}}
.falta table{{width:100%;border-collapse:collapse;font-size:13.5px}}
.falta td{{padding:9px 0;border-bottom:1px solid var(--line);vertical-align:top}}
.falta tr:last-child td{{border-bottom:0}}
.falta td:first-child{{width:120px;font-family:ui-monospace,Menlo,monospace;
  font-size:12.5px;color:var(--lote)}}
.payoff{{margin-top:34px;padding:20px 22px;border-radius:11px;
  background:var(--nav-bg);border:1px solid color-mix(in srgb,var(--nav) 26%,transparent)}}
.payoff h3{{margin:0 0 7px;font-size:15px;color:var(--nav)}}
.payoff p{{margin:0;font-size:14px;line-height:1.6}}
@media(max-width:680px){{
  .grid2,.legenda,.lens{{grid-template-columns:1fr}}
}}
</style>

<div class="wrap">
<h1>Layout dos dois Launchpad Mini MK3</h1>
<p class="sub">Controlador de grid escrevendo direto no sequenciador interno da TR-8S · 13/08/2026</p>

<p class="thesis">Dois Launchpad de 8×8 viram <b>um grid de 16 steps por 8 instrumentos</b>,
e os 32 botões de borda cobrem tudo que o protocolo SysEx já decodificado
permite — inclusive <b>editar uma variação enquanto outra toca</b>, o que a
TR-8S não faz sozinha.</p>

<div class="chips">
  {chip(TEAL,   'teal = navegação · onde você edita')}
  {chip(PURPLE, 'roxo = som · como o step soa')}
  {chip(ORANGE, 'laranja = lote · muda muitos steps')}
</div>

<h2>O desenho</h2>
<div class="card">
{SVG}
<p class="cap">Os números dentro dos círculos são os <span class="m">CC</span> que
cada botão manda. O aparelho esquerdo está girado 90° anti-horário, então a coluna
de cena dele foi parar no topo e a fileira de função na borda externa esquerda.
O grid mostra um pattern real, com o last step em 14 e o LT mutado na TR-8S, para servir de legenda de todas as cores. A linha mutada troca de família de cor: vermelho vira roxo, laranja vira azul, e a cabeça de tempo e o playhead somem.</p>
</div>

<h2>Legenda dos pads</h2>
<div class="card"><div class="legenda">{LEGENDA_PAD}</div></div>

<h2>Referência por grupo</h2>
<div class="grid2">{T1}{T2}{T3}{T4}{T5}</div>

<h2>A regra do toque</h2>
<div class="card">
<p style="margin:0">Com um seletor de velocity, liga/desliga binário não basta: trocar
o nível de um step existente exigiria apagar e repintar. O pad passou a
<b>comparar estado</b>.</p>
<div class="lens">
  <div class="biz"><h5>Para o negócio</h5>
    Você escolhe a intensidade e vai batendo. Pisar de novo no mesmo step com a
    <i>mesma</i> intensidade apaga; com outra intensidade, corrige sem apagar antes.
    Um gesto só, sem modo de edição.</div>
  <div class="hood"><h5>Sob o capô</h5>
    O pad compara <span class="m">(velocity, byte 5)</span> do cache com o alvo
    atual. Igual → escreve zero. Diferente → sobrescreve. O cache é autoritativo
    porque toda escrita nossa passa por ele.</div>
</div>
<p class="io">entra: <b>toque no pad</b> &nbsp;→&nbsp; sai: <b>1 DT1 de 8 bytes</b>
no endereço <span class="m">20 0V I 08</span> + step × 8</p>
</div>

<h2>O que ainda falta decodificar</h2>
<div class="falta"><table><tbody>
<tr><td>WRITE</td><td>Sem ele a TR-8S perde tudo ao desligar — escrevemos só no buffer
ativo. O botão existe no TR-EDITOR, então é sniffável. <b>Maior lacuna.</b></td></tr>
<tr><td>LAST STEP</td><td>Por instrumento. Também é o que faz o playhead
dessincronizar quando o pattern não tem 16 steps.</td></tr>
<tr><td>PROBABILITY</td><td>Um dos bytes 0–4 de cada step. O atalho
<span class="m">[P]</span>+pad do editor isola a mudança num step só.</td></tr>
<tr><td>ALTERNATE</td><td>Outro dos bytes 0–4. Atalho <span class="m">[A]</span>+pad.
Fecha o mapa do step.</td></tr>
<tr><td>TRG</td><td>O manual confirma que o INST SELECT vai até TRG, o que sustenta
o palpite de que o bloco <span class="m">20 0V 0B 08</span> é isso.</td></tr>
</tbody></table></div>

<div class="payoff">
<h3>Por que isso vale o trabalho</h3>
<p>A TR-8S não deixa você editar a variação B enquanto a A toca — no painel, você
edita o que está tocando. Escrevendo por SysEx, o script escreve onde quiser,
independente do que está selecionado na máquina. As oito variações mais os dois
fills viram um grid físico de 16×8 com velocity, flam e sub step ao alcance do
dedo, e a próxima parte já toca antes de você trocar para ela.</p>
</div>
</div>
"""

import pathlib
out = pathlib.Path("/Users/luanmoura/Documents/Claude/Projects/tr8s-grid/layout.html")
out.write_text(HTML, encoding="utf-8")
print(f"escrito: {out}  ({len(HTML)} bytes)")
print(f"viewBox: 0 0 {VB_W} {VB_H}")
print(f"botoes desenhados: "
      f"{len(TOPO_ESQ)+len(BORDA_ESQ)+len(TOPO_DIR)+len(BORDA_DIR)}"
      f"  (+2 logos, que sao so LED)")
print(f"pads desenhados  : {8*8*2}")
