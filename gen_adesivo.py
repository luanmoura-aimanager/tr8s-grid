#!/usr/bin/env python3
"""
gen_adesivo.py - gera adesivo.pdf: 32 etiquetas coloridas em TAMANHO REAL pra
colar EM CIMA dos botoes de borda dos dois Launchpad Mini MK3. Uma pagina so.

    python3 gen_adesivo.py

Imprima em A4 adesivo com escala 100% ("tamanho real" / "sem ajustar a pagina").
Confira a regua de 100 mm antes de recortar - se nao bater, a impressora
reescalou e nada vai encaixar.

POR QUE ETIQUETA SOLTA, E NAO UMA TIRA COM FUROS
    No Mini MK3 os botoes de borda sao QUADRADOS de ~15 mm, nao redondos. E a
    etiqueta vai POR CIMA do botao, nao ao lado dele. Isso derruba toda a
    dependencia da geometria do bezel: nao importa o passo entre botoes nem a
    distancia ate a borda, so o tamanho do botao. Cada quadradinho e recortado e
    colado sozinho.

POR QUE FILEIRAS, E NAO O DESENHO DOS DOIS APARELHOS
    Colocar as etiquetas em L ao redor de dois grids 8x8 daria 342 mm de largura
    - nao cabe em A4. Entao a folha traz as etiquetas em fileiras (que e o que se
    recorta) e, embaixo, um MAPA esquematico fora de escala mostrando onde cada
    fileira vai. O mapa nao precisa de escala: as etiquetas ja sao recortadas
    uma a uma.
"""
import sys
import fitz

# ── medidas, em mm ────────────────────────────────────────────
BOTAO = 15.0     # lado do botao no Mini MK3 (~1,5 cm, medido no aparelho)
# A etiqueta sai menor que o botao pra nao sobrar aba. Era 0.7 (etiqueta de
# 14.3 mm) e foi pra 1.7 em 14/08/2026, depois de colar as primeiras: 13.3 mm
# assenta melhor. O ajuste e AQUI e nao no BOTAO - aquele numero e o aparelho
# medido, um fato; este e a nossa margem, uma escolha.
FOLGA = 1.7
LADO  = BOTAO - FOLGA
# Cantos VIVOS, sem raio. Tinham 2 mm de arredondamento imitando o botao, mas o
# que se recorta e um quadrado - o canto redondo so dava trabalho de tesoura e
# deixava uma sobra branca visivel na quina depois de colado (14/08/2026).
VAO   = 4.5      # branco entre etiquetas, pra ter onde passar a tesoura

MM = 72 / 25.4
A4_L, A4_A = 210.0, 297.0

# Compensacao de impressora que se recusa a imprimir em 100%.
#     python3 gen_adesivo.py --medido 93
# significa "a regua de 100 mm saiu com 93 mm na minha impressora": tudo e
# desenhado 100/93 maior, pra que o encolhimento devolva o tamanho certo.
#
# Isto e REMENDO, nao conserta. 93% e a cara de "Scale to Fit" no dialogo de
# impressao - tente Escala 100% / Tamanho real ANTES de usar isto, senao a folha
# fica presa a uma impressora e a um ajuste especificos.
ESCALA, MEDIDO = 1.0, None
if "--medido" in sys.argv:
    MEDIDO = float(sys.argv[sys.argv.index("--medido") + 1])
    ESCALA = 100.0 / MEDIDO

def mm(v): return v * MM * ESCALA

# Compensando, o desenho inteiro cresce e o A4 fica curto. Quem encolhe sao os
# VAOS - as etiquetas nunca, que sao a unica coisa que precisa de tamanho certo.
GAP_FILEIRA = 5.5 if ESCALA == 1.0 else 2.5    # entre uma fileira e a seguinte
CEL_MAPA    = 4.4 if ESCALA == 1.0 else 3.5    # celula do mapa esquematico
GAP_RODAPE  = 4.3 if ESCALA == 1.0 else 3.9    # entre linhas do rodape

# ── cores de impressao ────────────────────────────────────────
# Um grupo, uma cor. A versao anterior punha variacoes e fills no mesmo teal, e
# os modos e a velocity no mesmo roxo - dois grupos diferentes vestindo a mesma
# cor derrota o proposito de ter cor.
VAR_C  = (0.05, 0.40, 0.36)   # teal escuro   variacoes A-H
FILL_C = (0.02, 0.46, 0.21)   # verde         fill 1 / fill 2
ACC_C  = (0.56, 0.79, 0.24)   # verde claro   accent          (texto escuro)
INST_C = (0.11, 0.11, 0.13)   # quase preto   rolagem de instrumento
SOM_C  = (0.33, 0.15, 0.68)   # roxo          normal / flam / subs
VEL_C  = (0.24, 0.49, 0.83)   # azul          velocity
VELP_C = (0.05, 0.19, 0.52)   # azul escuro   velocity 80 e 50, os da maquina
LOTE_C = (0.68, 0.21, 0.04)   # laranja       clear / copy / paste / mute
RES_C  = (0.42, 0.42, 0.44)   # cinza         write, ainda sem funcao
BRANCO = (1, 1, 1)
TINTA  = (0.10, 0.09, 0.08)
FRACO  = (0.55, 0.53, 0.50)
CORTE  = (0.76, 0.74, 0.71)
GUIA   = (0.86, 0.85, 0.83)

# ── as quatro bordas, na ordem fisica ─────────────────────────
GRUPOS = [
    ("LEFT UNIT · top edge", "variations, left to right", "topo", "E",
     [(ch, VAR_C) for ch in "ABCDEFGH"]),
    ("LEFT UNIT · left edge", "top to bottom", "esq", "E",
     [("FILL\n1", FILL_C), ("FILL\n2", FILL_C),
      ("CLR\nINST", LOTE_C), ("CLR\nVAR", LOTE_C),
      ("HIDE\nMUTED", LOTE_C), ("ALT", SOM_C),
      ("COPY", LOTE_C), ("PASTE", LOTE_C)]),
    ("RIGHT UNIT · top edge", "left to right", "topo", "D",
     [("INST", INST_C, "cima"), ("INST", INST_C, "baixo"),
      ("NORM", SOM_C), ("FLAM", SOM_C),
      ("SUB\n1/2", SOM_C), ("SUB\n1/3", SOM_C),
      ("SUB\n1/4", SOM_C), ("ACCENT", ACC_C)]),
    ("RIGHT UNIT · right edge", "velocity, top to bottom", "dir", "D",
     [(str(v), VELP_C if v in (80, 50) else VEL_C)
      for v in (127, 110, 100, 80, 60, 50, 30, 10)]),
]

# Os dois niveis que a propria TR-8S usa: o ciclo do pad dela e strong -> weak ->
# off (Reference p. 45), com 80 e 50 (SysEx do TR-EDITOR, e o manual dele p. 8).
# Os outros seis so existem porque a maquina aceita velocity continua.
CANONICOS = {"80": "STRONG", "50": "WEAK"}

# Os cantos do logo nao sao botoes - viram cabecalho da borda que comeca ali.
TITULOS = [("VELOCITY", "baixo", "D"), ("VAR", "direita", "E")]

doc = fitz.open()
pg = doc.new_page(width=mm(A4_L), height=mm(A4_A))


def _por(x, y, larg, alt, txt, tam, cor, negrito, alinha):
    """insert_textbox DESCARTA o texto em silencio se a caixa for baixa demais -
    erra por 1 pt e a linha some da folha sem aviso. Aqui isso vira erro."""
    sobra = pg.insert_textbox(
        fitz.Rect(mm(x), mm(y), mm(x+larg), mm(y+alt)), txt, fontsize=tam,
        fontname="hebo" if negrito else "helv", color=cor, align=alinha)
    if sobra < 0:
        raise SystemExit(f"caixa baixa demais para {txt[:40]!r}: "
                         f"faltaram {-sobra:.1f} pt em {alt} mm")


def esq(x, y, larg, txt, tam=7.5, cor=TINTA, negrito=False, alt=None):
    # o fitz precisa de mais folga que a altura de linha nominal; 0.7 mm por pt
    # cobre com margem e evita ficar caçando o "faltaram 0.1 pt"
    _por(x, y, larg, alt or max(5.0, tam * 0.7), txt, tam, cor, negrito,
         fitz.TEXT_ALIGN_LEFT)


def etiqueta(x, y, rotulo, cor, nota=None, glifo=None):
    """Quadradinho colorido com o nome dentro, do tamanho do botao.

    'nota'  = legenda miudinha embaixo (STRONG 80 / WEAK 50, os dois niveis que a
              propria TR-8S usa - ver o cabecalho deste arquivo).
    'glifo' = triangulo no lugar da legenda, pra rolagem de instrumento."""
    tinta = tinta_para(cor)
    pg.draw_rect(fitz.Rect(mm(x), mm(y), mm(x+LADO), mm(y+LADO)),
                 color=None, fill=cor)
    linhas = rotulo.split("\n")
    if nota or glifo:                tam, dy = 8.2, 3.0
    elif len(linhas) > 1:            tam, dy = 7.0, 3.2
    elif len(linhas[0]) <= 3:        tam, dy = 10.0, 4.4
    elif len(linhas[0]) <= 5:        tam, dy = 8.0, 3.9
    else:                            tam, dy = 6.6, 3.6
    _por(x, y + dy, LADO, LADO, rotulo, tam, tinta, True, fitz.TEXT_ALIGN_CENTER)
    if nota:
        _por(x, y + 8.5, LADO, 5.2, nota, 5.6, tinta, True,
             fitz.TEXT_ALIGN_CENTER)
    elif glifo:
        triangulo(x + LADO/2, y + 10.3, 4.2, glifo, tinta)


def triangulo(cx, cy, base, direcao, cor):
    """So a ponta, sem haste. Desenhado em vetor porque a fonte base do PDF usa
    WinAnsiEncoding, que nao tem seta nenhuma - e embutir uma fonte inteira por
    causa de um glifo nao se paga."""
    b, h = base / 2, base * 0.80
    if direcao == "cima":     pts = [(cx-b, cy+h/2), (cx+b, cy+h/2), (cx, cy-h/2)]
    elif direcao == "baixo":  pts = [(cx-b, cy-h/2), (cx+b, cy-h/2), (cx, cy+h/2)]
    else:                     pts = [(cx-h/2, cy-b), (cx-h/2, cy+b), (cx+h/2, cy)]
    pg.draw_polyline([fitz.Point(mm(a), mm(c)) for a, c in pts + [pts[0]]],
                     color=cor, fill=cor, width=0.2)


def tinta_para(fundo):
    """Texto branco ou escuro, conforme o fundo. O verde claro do ACCENT nao tem
    contraste com branco - so escolher a cor a mao seria esquecer disso na
    proxima vez que a paleta mudasse."""
    lum = 0.2126*fundo[0] + 0.7152*fundo[1] + 0.0722*fundo[2]
    return TINTA if lum > 0.55 else BRANCO


def etiqueta_titulo(x, y, texto, direcao):
    """Etiqueta BRANCA pro canto do logo. O logo nao e botao, entao o quadradinho
    ali nao aciona nada - vira cabecalho da fileira/coluna que comeca ao lado."""
    pg.draw_rect(fitz.Rect(mm(x), mm(y), mm(x+LADO), mm(y+LADO)),
                 color=CORTE, fill=BRANCO, width=0.5)
    tam = 6.6 if len(texto) > 4 else 9.5
    _por(x, y + 3.2, LADO, 7.0, texto, tam, TINTA, True, fitz.TEXT_ALIGN_CENTER)
    triangulo(x + LADO/2, y + 10.2, 4.6, direcao, TINTA)


# ── cabecalho ─────────────────────────────────────────────────
esq(14.5, 11, 181, "TR-8S GRID  ·  EDGE BUTTON LABELS", tam=13, cor=TINTA,
    negrito=True)
for k, linha in enumerate([
        ("Print at 100% scale on adhesive A4. Cut along the dashed square and "
         "stick each label straight onto its button." if ESCALA == 1.0 else
         "Print on adhesive A4 with SCALE TO FIT (the usual default). Cut along "
         "the dashed square and stick each label onto its button."),
        f"Each label is {LADO:.1f} mm for a {BOTAO:.0f} mm button, so it sits "
        "inside the button face without an overhanging edge.",
        "The rows are in physical order. The map at the bottom shows where each "
        "row goes."]):
    esq(14.5, 18.5 + k * 4.4, 181, linha, tam=7.5, cor=FRACO)

if ESCALA != 1.0:
    # carimbo: sem isto, uma folha ja esticada reimpressa numa impressora
    # consertada sairia 7% grande e ninguem saberia por que
    esq(14.5, 31.4, 181,
        f"PRE-SCALED {ESCALA*100:.1f}% - a test print of the previous sheet "
        f"measured {MEDIDO:.0f} mm where it should read 100.",
        tam=7.5, cor=(0.70, 0.15, 0.10), negrito=True)
    esq(14.5, 35.4, 181,
        "So do NOT ask for 100% - leave Scale to Fit on. Always measure the ruler "
        "on the result: if it is not 100 mm, regenerate with the new reading.",
        tam=7.5, cor=(0.70, 0.15, 0.10))

RY = 34.0 if ESCALA == 1.0 else 43.0
pg.draw_line(fitz.Point(mm(14.5), mm(RY)), fitz.Point(mm(114.5), mm(RY)),
             color=TINTA, width=0.8)
for k in range(11):
    x = 14.5 + k * 10
    pg.draw_line(fitz.Point(mm(x), mm(RY)),
                 fitz.Point(mm(x), mm(RY - (3.0 if k % 5 == 0 else 1.8))),
                 color=TINTA, width=0.6)
esq(117, RY - 3.4, 90, "this line must measure exactly 100 mm", tam=7.5, cor=TINTA)

# ── as quatro fileiras: e isto que se recorta ─────────────────
LARG = 8 * LADO + 7 * VAO
X0 = (A4_L - LARG) / 2
y = 45.0 if ESCALA == 1.0 else 53.0
for n, (titulo, sentido, *_resto, itens) in enumerate(GRUPOS, 1):
    esq(X0 - 6.5, y + 0.6, 6.5, f"{n}", tam=10, cor=FRACO, negrito=True, alt=6.0)
    esq(X0, y, 120, titulo, tam=8.5, cor=TINTA, negrito=True)
    esq(X0, y + 4.2, 120, sentido, tam=7, cor=FRACO)
    y += 9.5
    m = FOLGA / 2
    for k, item in enumerate(itens):
        rotulo, cor = item[0], item[1]
        x = X0 + k * (LADO + VAO)
        etiqueta(x, y, rotulo, cor, nota=CANONICOS.get(rotulo),
                 glifo=item[2] if len(item) > 2 else None)
        pg.draw_rect(fitz.Rect(mm(x-m), mm(y-m), mm(x+LADO+m), mm(y+LADO+m)),
                     color=CORTE, width=0.3, dashes="[1.5 1.5] 0")
    y += LADO + GAP_FILEIRA

esq(X0 - 6.5, y + 0.6, 6.5, "5", tam=10, cor=FRACO, negrito=True, alt=6.0)
esq(X0, y, 130, "CORNER HEADERS · not buttons", tam=8.5, cor=TINTA, negrito=True)
esq(X0, y + 4.2, 130,
    "the logo corners: VELOCITY on the right unit, VAR on the left", tam=7,
    cor=FRACO)
y += 9.5
m = FOLGA / 2
for k, (texto, direcao, _dev) in enumerate(TITULOS):
    x = X0 + k * (LADO + VAO)
    etiqueta_titulo(x, y, texto, direcao)
    pg.draw_rect(fitz.Rect(mm(x-m), mm(y-m), mm(x+LADO+m), mm(y+LADO+m)),
                 color=CORTE, width=0.3, dashes="[1.5 1.5] 0")
y += LADO + 7.0

# ── o mapa: fora de escala, so pra saber onde cada fileira vai ──
esq(14.5, y, 181, "WHERE EACH ROW GOES", tam=8.5, cor=TINTA, negrito=True)
esq(14.5, y + 4.2, 181,
    "Not to scale - each label is cut out separately, so only its own size "
    "matters. Both units seen from above, as they sit on the desk.",
    tam=7, cor=FRACO)
y += 14.0

CEL, MINI = CEL_MAPA, CEL_MAPA - 0.6          # celula do mapa e lado da etiqueta em miniatura
LARG_AP = 9 * CEL
GAP_AP = 14.0
MX = (A4_L - (2 * LARG_AP + GAP_AP)) / 2

for ap, (nome, logo_esq) in enumerate((("LEFT · rotated 90° CCW", True),
                                       ("RIGHT · normal", False))):
    ox = MX + ap * (LARG_AP + GAP_AP)
    esq(ox, y - 4.6, LARG_AP + 10, nome, tam=7, cor=TINTA, negrito=True)
    pg.draw_rect(fitz.Rect(mm(ox), mm(y), mm(ox+LARG_AP), mm(y+LARG_AP)),
                 color=GUIA, width=0.7)
    # os 8x8 pads, do lado oposto ao canto do logo
    cols = range(1, 9) if logo_esq else range(0, 8)
    for r in range(1, 9):
        for c in cols:
            px, py = ox + c*CEL + 0.7, y + r*CEL + 0.7
            pg.draw_rect(fitz.Rect(mm(px), mm(py), mm(px+CEL-1.4), mm(py+CEL-1.4)),
                         color=GUIA, width=0.4)
    # as etiquetas, na posicao fisica, em miniatura
    for n, (_t, _s, borda, dev, itens) in enumerate(GRUPOS, 1):
        if dev != ("E" if logo_esq else "D"):
            continue
        for k, item in enumerate(itens):
            cor = item[1]
            if borda == "topo":
                cx = ox + (k + (1 if logo_esq else 0)) * CEL
                cy = y
            elif borda == "esq":
                cx, cy = ox, y + (k + 1) * CEL
            else:
                cx, cy = ox + 8 * CEL, y + (k + 1) * CEL
            pg.draw_rect(fitz.Rect(mm(cx+0.4), mm(cy+0.4),
                                   mm(cx+0.4+MINI), mm(cy+0.4+MINI)),
                         color=None, fill=cor)
        # numero da fileira, encostado na borda que ela ocupa
        if borda == "topo":
            lx, ly = ox + LARG_AP + 1.5, y + 0.6
        elif borda == "esq":
            lx, ly = ox - 5.0, y + LARG_AP - 6.0
        else:
            lx, ly = ox + LARG_AP + 1.5, y + LARG_AP - 6.0
        esq(lx, ly, 6, f"{n}", tam=8, cor=FRACO, negrito=True, alt=5.5)
    # o canto do logo: nao e botao, leva a etiqueta branca de cabecalho
    lcx = ox if logo_esq else ox + 8 * CEL
    pg.draw_rect(fitz.Rect(mm(lcx+0.4), mm(y+0.4), mm(lcx+0.4+MINI), mm(y+0.4+MINI)),
                 color=TINTA, fill=BRANCO, width=0.5)
    esq(lcx + 0.6, y + 1.4, MINI, "5", tam=4.5, cor=TINTA, negrito=True, alt=3.5)

y += LARG_AP + 3.0

# ── rodape ────────────────────────────────────────────────────
for k, linha in enumerate([
        "Colour key:  teal = variations   ·   green = fills   ·   light green = "
        "accent   ·   black = instrument scroll",
        "purple = step type   ·   blue = velocity, dark blue = the two the "
        "machine itself uses   ·   orange = batch edits",
        "HIDE MUTED toggles: rows muted on the TR-8S drop out of the grid, or come "
        "back in purple (notes) and blue (flam/sub). Muting itself is the panel button.",
        "ALT arms the alternate sound: the next pads record in pink. It only "
        "sounds on the 20 tones with a / in the name.",
        "HIDE MUTED + ALT together bring the pads back from the off mode.",
        "The corner logos are LEDs, not buttons. Their white labels (row 5) are "
        "headers for the edge next to them. Instrument scrolling: right unit only."]):
    esq(14.5, y + k * GAP_RODAPE, 181, linha, tam=7.5, alt=10.0,
        cor=TINTA if k == 0 else FRACO)

# a pagina nao pode transbordar em silencio: com --medido o desenho cresce e o
# que sair do A4 simplesmente sumiria da folha impressa
usada = (y + 5 * GAP_RODAPE) * ESCALA
if usada > A4_A - 8:
    raise SystemExit(f"conteudo estourou o A4: {usada:.0f} mm de {A4_A:.0f}. "
                     f"Reduza os vaos ou o mapa antes de usar --medido {100/ESCALA:.0f}.")

saida = "/Users/luanmoura/Documents/Claude/Projects/tr8s-grid/adesivo.pdf"
doc.save(saida)
print(f"escrito: {saida}  (1 pagina)")
print(f"{sum(len(g[-1]) for g in GRUPOS)} etiquetas de botao + {len(TITULOS)} de cabecalho, {LADO:.1f} mm (botao de {BOTAO:.0f} mm)")
print(f"altura usada: {usada:.0f} de {A4_A:.0f} mm"
      f"{'' if ESCALA == 1 else f'  (escala {ESCALA:.4f})'}")
