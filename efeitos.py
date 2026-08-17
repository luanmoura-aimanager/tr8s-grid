#!/usr/bin/env python3
"""
efeitos.py - o que a TR-8S TEM (catalogo) e o que ja DESCOBRIMOS (mapa).

Duas metades bem diferentes, e a diferenca importa:

  CATALOGO - tirado do Reference (p. 24-37) e do TR-EDITOR. Sabemos o nome, a
    faixa, as opcoes e COMO CHEGAR NO CONTROLE PELO PAINEL. Nao sabemos o
    endereco SysEx de nenhum deles: a Roland nao documenta.

  MAPA - o offset de cada parametro, descoberto por observacao:
    - captura guiada no app (Motor.iniciar_captura_fx): o Luan mexe num
      controle do painel e o motor acha o byte que mudou;
    - sniff do TR-EDITOR (sessao M2 da REFERENCIA 7.2) -> PARAMS_FIXOS.
    O capturado vive em ~/.lp_tr8s_fx.json, fora do repo.

Por isso a interface mostra o painel inteiro mas so ACENDE o que esta no mapa:
knob que nao faz nada e mentira, e aqui mentira custa sessao de hardware.

DOIS BYTES: faixa 0-255 (e as bipolares -128..+127) nao cabe num byte MIDI de
7 bits. A maquina usa o truque do velocity (REFERENCIA 2.4): dois bytes em
nibbles, valor = (hi << 4) | lo. O manual entrega o centro dos bipolares em
128 ("If the setting of the parameter to be modified is 128 (the center
value)", p. 33).

NOME E CHAVE PERMANENTE: e o que fica gravado no ~/.lp_tr8s_fx.json. Renomear
um parametro ja capturado apaga trabalho de hardware que so o Luan, na frente
da maquina, consegue refazer. Convencao: "<painel> <tipo?> <param>", minusculo,
sem acento.
"""
import json
import os

ARQ_FX = os.path.expanduser("~/.lp_tr8s_fx.json")

# ─────────────────────────────────────────────────────────────
# ONDE CADA COISA MORA (sniff do TR-EDITOR, 15/08/2026)
#
# O kit nao e um bloco so: e uma familia de blocos sob 10 KK xx 00, onde
# KK = numero do kit menos 1 (o kit "003 TR-707" do Luan respondeu em 10 02).
# O TR-EDITOR le exatamente estes na abertura, com estes tamanhos - e ler o
# que o editor oficial le e a unica defesa barata contra a armadilha 3.1
# (RQ1 em endereco invalido mata a porta CTRL).
#
#   10 KK 00 00   16 + 105 B   nome do kit (16 ASCII) e comuns - level 0x10,
#                              GROUP master 0x11, COLOR por inst 0x42+i
#   10 KK 01 00        75 B    REVERB
#   10 KK 02 00        92 B    DELAY
#   10 KK 03 00   38 + 49 B    MASTER FX
#   10 KK 04 00        78 B    EXT IN (side chain 0x00, gain 0x04...)
#   10 KK 05 00        70 B    LFO
#   10 KK 06 00       115 B    CTRL (select global 0x00)
#   10 KK 07 00        12 B    OUTPUT, um byte por instrumento (BD=0x00)
#   10 KK 08 00        13 B    MUTE/choke, um byte por instrumento (BD=0x00)
#   10 KK 10..1A 00  53 + 48 B os 11 instrumentos, BD..RC, layout identico
#   10 KK 20..2A 00   7 + 50 B tone + INST FX dos 11 instrumentos
#
# offset_base: o segundo byte do endereco de bloco. 'por_inst' diz que o
# bloco tem uma copia por instrumento (soma o indice 0..10 ao offset_base).
BLOCOS = {
    "kit":    {"base": 0x00, "por_inst": False, "tam": 105},
    "reverb": {"base": 0x01, "por_inst": False, "tam": 75},
    "delay":  {"base": 0x02, "por_inst": False, "tam": 92},
    "mfx":    {"base": 0x03, "por_inst": False, "tam": 87},
    "extin":  {"base": 0x04, "por_inst": False, "tam": 78},
    "lfo":    {"base": 0x05, "por_inst": False, "tam": 70},
    "ctrl":   {"base": 0x06, "por_inst": False, "tam": 115},
    # OUTPUT e MUTE/choke: um byte por instrumento DENTRO de um bloco unico
    # (offset = indice do instrumento), como a COLOR - nao sao blocos por
    # instrumento como inst/ifx
    "output": {"base": 0x07, "por_inst": False, "tam": 12},
    "mute":   {"base": 0x08, "por_inst": False, "tam": 13},
    "inst":   {"base": 0x10, "por_inst": True,  "tam": 101},
    "ifx":    {"base": 0x20, "por_inst": True,  "tam": 57},
}

# ─────────────────────────────────────────────────────────────
# Vocabulario compacto para descrever parametro.
#   p(rot, max, bytes)          -> fader
#   p(rot, None, 1, opcoes=[])  -> lista
#   p(..., bipolar=True)        -> -128..+127 com centro em 128
# ─────────────────────────────────────────────────────────────
def p(rot, maximo=255, nbytes=2, opcoes=None, bipolar=False, unidade="",
      escala=None):
    d = {"rot": rot, "max": 255 if maximo is None else maximo,
         "bytes": nbytes, "opcoes": opcoes or [],
         "forma": "enum" if opcoes else "fader",
         "bipolar": bipolar, "unidade": unidade}
    # 'escala' = tabela byte -> o que o VISOR da maquina mostra, para o caso em
    # que a conta nao e linear nem centrada em 128 (o GAIN). So entra no dict
    # quando existe: ele viaja para a pagina no /dados.
    if escala:
        d["escala"] = escala
    return d


# ─────────────────────────────────────────────────────────────
# GAIN: a escala que o visor mostra, LIDA NO HARDWARE em 17/08/2026
#
#   byte 0   = -INF        byte 81 = 0.0 dB        byte 161 = +40.0 dB
#
# ou seja meio decibel por passo a partir do 81, e o byte 0 e um valor
# especial (-INF, silencio). Foi isto que fechou a pendencia da varredura de
# 15/08, que "parou em 161 e nao em 255" sem explicacao: 161 e o fim da faixa
# de verdade. Mandamos 255 de proposito e a maquina grampeou em 161 com o
# visor em +40.0 dB.
#
# Sem esta tabela a tela mostrava o desvio de 128 (o byte 81 aparecia como
# "-47" com a maquina dizendo 0.0 dB) - a conta de bipolar do resto do
# catalogo, que aqui nao vale.
GANHO_MAX = 161
GANHO_CENTRO = 81
def _ganho_rotulo(v):
    if v == 0:
        return "-INF"
    d = (v - GANHO_CENTRO) / 2
    # o visor mostra "0.0 dB" no centro, sem sinal - a tabela e para BATER com
    # ele, e um "+0.0" seria a unica linha em que ela nao bate
    return f"{d:.1f} dB" if d == 0 else f"{d:+.1f} dB"


GANHO_ESCALA = {v: _ganho_rotulo(v) for v in range(GANHO_MAX + 1)}

# ─────────────────────────────────────────────────────────────
# PAN: tambem lido no visor, 17/08/2026. As pontas sao L127 e R127, e o
# CENTER ocupa DOIS bytes (127 e 128) - e por isso que o desvio de 128
# errava por um: o visor dizia L9 onde a conta dava -10.
#
#   byte 0 = L127 ... byte 126 = L1 | 127 e 128 = CENTER | 129 = R1 ... 255 = R127
#
# Serve para "inst pan". O "extin pan" provavelmente e igual, mas isso e
# DEDUCAO: fica sem escala ate alguem ler o visor dele.
def _pan_rotulo(v):
    if v <= 126:
        return f"L{127 - v}"
    if v <= 128:
        return "CENTER"
    return f"R{v - 128}"


PAN_ESCALA = {v: _pan_rotulo(v) for v in range(256)}


DB = "dB"
FREQ_CUT_ALTA = ["630Hz", "800Hz", "1kHz", "1.25kHz", "1.6kHz", "2kHz",
                 "2.5kHz", "3.15kHz", "4kHz", "5kHz", "6.3kHz", "8kHz",
                 "10kHz", "12.5kHz", "FLAT"]
FREQ_CUT_BAIXA = ["FLAT", "20Hz", "25Hz", "31.5Hz", "40Hz", "50Hz", "63Hz",
                  "80Hz", "100Hz", "125Hz", "160Hz", "200Hz", "250Hz",
                  "315Hz", "400Hz", "500Hz", "630Hz", "800Hz"]
RATIO = ["1:1.00", "1:1.12", "1:1.25", "1:1.40", "1:1.60", "1:1.80", "1:2.00",
         "1:2.50", "1:3.20", "1:4.00", "1:5.60", "1:8.00", "1:16.0", "1:INF"]
KNEE = ["HARD"] + [f"SOFT{i}" for i in range(1, 10)]
# type e clipper do LPF/HPF vieram com DOIS bytes na captura, apesar de terem
# 3 e 2 opcoes - no MASTER FX o espacamento de 2 parece valer para tudo
TIPO_FILTRO = ["-24dB", "-18dB", "-12dB"]
SYNC_RATE = ["64.00", "48.00", "32.00", "24.00", "16.00", "12.00", "8.00",
             "6.00", "4.00", "3.00", "2.00", "1.50", "1.00", "0.75", "0.50",
             "0.25"]

# ── blocos que se repetem entre MASTER FX e INST FX ──
_FILTRO = [p("depth"), p("resonance"), p("type", 2, 2, TIPO_FILTRO),
           p("gain", 255, 2, None, True, DB),
           p("clipper", 1, 2, ["OFF", "ON"])]
_BOOST = [p("boost"), p("frequency"), p("gain", 255, 2, None, True, DB)]
_ISOLATOR = [p("balance"), p("low", 255, 2, None, False, DB),
             p("mid", 255, 2, None, False, DB),
             p("high", 255, 2, None, False, DB)]
_TRANSIENT = [p("envdepth"), p("attack", 255, 2, None, True),
              p("release", 255, 2, None, True)]
_COMPRESSOR = [p("balance"), p("attack"), p("release"),
               p("threshold", 255, 2, None, False, DB),
               p("gain", 255, 2, None, True, DB),
               p("ratio", None, 1, RATIO), p("knee", None, 1, KNEE)]
_DRIVE = [p("balance"), p("drive"), p("level"), p("hpfreq"), p("preeqfreq"),
          p("preeql", 255, 2, None, False, DB),
          p("preeqh", 255, 2, None, False, DB), p("posteqfreq"),
          p("posteql", 255, 2, None, False, DB),
          p("posteqh", 255, 2, None, False, DB)]
_DIST = [p("balance"), p("drive"), p("tone"), p("level")]
_CRUSHER = [p("balance"), p("samplerate"), p("filter")]
# A ORDEM AQUI VIROU DADO, nao so rotulo: no MASTER FX o offset de cada
# parametro sai da POSICAO dele na lista (0x27 + 2*i). Esta e a ordem do
# PAINEL do TR-EDITOR, que foi a que se confirmou no LPF/HPF - e nela o
# temposync vem DEPOIS, nao em segundo como o manual lista.
_MOD = [p("balance"), p("rate"), p("depth"), p("resonance"), p("manual")]
_TEMPOSYNC = p("temposync", None, 1, ["OFF", "ON"])

# ─────────────────────────────────────────────────────────────
# Os tipos de cada familia (Reference p. 24-37)
# ─────────────────────────────────────────────────────────────
TIPOS_REVERB = ["AMBI", "ROOM", "HALL1", "HALL2", "PLATE", "MOD", "HA-DOU"]
TIPOS_DELAY = ["DLY", "PAN", "TAPE ECHO", "PITCH SHFT"]
TIPOS_MFX = ["HPF", "LPF", "LPF/HPF", "H BOOST", "L BOOST", "L/H BOOST",
             "ISOLATOR", "TRANSIENT", "TRANSIENT2", "COMPRESSOR", "DRIVE",
             "OVERDRIVE", "DISTORTION", "FUZZ", "CRUSHER", "PHASER",
             "FLANGER", "SBF", "NOISE", "FATTENER", "VINYL SIM"]
TIPOS_IFX = ["THRU", "HPF", "LPF", "LPF/HPF", "H BOOST", "L BOOST",
             "L/H BOOST", "ISOLATOR", "TRANSIENT", "COMPRESSOR", "DRIVE",
             "COMP+DRV", "CRUSHER", "SATURATOR", "FREQ SHIFT", "RING MOD",
             "SPREAD"]

_MFX_POR_TIPO = {
    "HPF": _FILTRO, "LPF": _FILTRO, "LPF/HPF": _FILTRO,
    "H BOOST": _BOOST, "L BOOST": _BOOST, "L/H BOOST": _BOOST,
    "ISOLATOR": _ISOLATOR, "TRANSIENT": _TRANSIENT,
    "TRANSIENT2": _TRANSIENT + [
        p("q", None, 1, ["0.125", "0.25", "0.5", "1.0", "2.0", "4.0", "8.0",
                         "16.0"]),
        p("hp level", 255, 2, None, False, DB),
        p("bp level", 255, 2, None, False, DB),
        p("lp level", 255, 2, None, False, DB),
        p("bypass", 255, 2, None, False, DB)],
    "COMPRESSOR": _COMPRESSOR, "DRIVE": _DRIVE,
    "OVERDRIVE": _DIST, "DISTORTION": _DIST, "FUZZ": _DIST,
    "CRUSHER": _CRUSHER,
    "PHASER": _MOD + [p("type", None, 1, ["4ST", "8ST", "12ST", "BI-PHASE"]),
                      _TEMPOSYNC],
    "FLANGER": _MOD + [p("locutf", None, 1, FREQ_CUT_BAIXA),
                       p("mode", None, 1, ["MONO", "STEREO"]), _TEMPOSYNC],
    "SBF": [p("balance"), p("bandintrvl"), p("bandwidth"),
            p("type", None, 1, [f"SBF{i}" for i in range(1, 7)]),
            p("gain", 255, 2, None, False, DB)],
    "NOISE": [p("color"), p("level", 255, 2, None, False, DB),
              p("direction", None, 1, ["UP", "DOWN"])],
    "FATTENER": [p("depth"), p("level")],
    "VINYL SIM": [p("compressor"), p("noise"), p("wow flut"), p("level")],
}

_IFX_POR_TIPO = {
    "THRU": [],
    "HPF": _FILTRO, "LPF": _FILTRO, "LPF/HPF": _FILTRO,
    "H BOOST": _BOOST, "L BOOST": _BOOST, "L/H BOOST": _BOOST,
    "ISOLATOR": _ISOLATOR, "TRANSIENT": _TRANSIENT,
    "COMPRESSOR": _COMPRESSOR, "DRIVE": _DRIVE,
    "COMP+DRV": [p("balance"), p("cmpbalance"), p("drvbalance"),
                 p("cmpattack"), p("cmprelease"),
                 p("cmpthre", 255, 2, None, False, DB),
                 p("cmpgain", 255, 2, None, True, DB),
                 p("cmpratio", None, 1, RATIO), p("cmpknee", None, 1, KNEE),
                 p("drvdrive"), p("drvlevel"), p("drvhpf"), p("drvpref"),
                 p("drvprel", 255, 2, None, False, DB),
                 p("drvpreh", 255, 2, None, False, DB), p("drvpstf"),
                 p("drvpstl", 255, 2, None, False, DB),
                 p("drvpsth", 255, 2, None, False, DB)],
    "CRUSHER": _CRUSHER,
    "SATURATOR": [p("pretype", None, 1, ["THRU", "LPF", "HPF", "LSV", "HSV"]),
                  p("prefreq", 255, 2, None, False, "Hz"),
                  p("pregain", 255, 2, None, True, DB),
                  p("drive", 255, 2, None, False, DB),
                  p("post1type", None, 1, ["THRU", "LPF", "HPF", "LSV", "HSV"]),
                  p("post1freq", 255, 2, None, False, "Hz"),
                  p("post1gain", 255, 2, None, True, DB),
                  p("post2type", None, 1, ["THRU", "LPF", "HPF", "LSV", "HSV"]),
                  p("post2freq", 255, 2, None, False, "Hz"),
                  p("post2gain", 255, 2, None, True, DB),
                  p("post3type", None, 1, ["THRU", "LPF", "HPF", "BPF", "PKG"]),
                  p("post3freq", 255, 2, None, False, "Hz"),
                  p("post3gain", 255, 2, None, True, DB), p("post3q"),
                  p("sense", 255, 2, None, False, DB),
                  p("postgain", 255, 2, None, True, DB),
                  p("balance"), p("level")],
    "FREQ SHIFT": [p("freq", 255, 2, None, True, "kHz"),
                   p("fine", 255, 2, None, True, "Hz"), p("balance")],
    "RING MOD": [p("freq", 255, 2, None, False, "Hz"),
                 p("fine", 255, 2, None, True, "Hz"), p("balance")],
    "SPREAD": [p("rate"), p("mode", None, 1, ["SHIFT", "RING"]), p("balance")],
}

_DELAY_POR_TIPO = {
    # h/l damp sao 1 byte ate 81 - medido em 15/08/2026, contra a deducao de
    # 2 bytes que o manual sugeria
    "DLY": [p("highcut", None, 1, FREQ_CUT_ALTA),
            p("h damp", 81, 1, None, False, DB),
            p("h dampf", None, 1, FREQ_CUT_ALTA[:-1]),
            p("l damp", 81, 1, None, False, DB),
            p("l dampf", None, 1, ["80Hz", "100Hz", "125Hz", "160Hz", "200Hz",
                                   "250Hz", "315Hz", "400Hz", "500Hz",
                                   "630Hz", "800Hz"])],
    "PAN": [p("tap time", 100, 1, None, False, "%")],
    "TAPE ECHO": [p("mode", None, 1, ["S", "M", "L", "S+M", "S+L", "M+L",
                                      "S+M+L"]),
                  p("bass", 30, 1, None, True, DB),   # medido: 1 byte, 0-30
                  p("treble", 30, 1, None, True, DB),  # medido: 1 byte, 0-30
                  p("pan s", 255, 2, None, True), p("pan m", 255, 2, None, True),
                  p("pan l", 255, 2, None, True), p("tape dist", 8, 1),
                  p("wf rate"), p("wf depth")],
    "PITCH SHFT": [p("coarse", 255, 2, None, True, "semi"),
                   p("fine", 255, 2, None, True, "cent")],
}

# ─────────────────────────────────────────────────────────────
# CTRL POR INSTRUMENTO - bloco 06, um byte por instrumento a partir de 0x01
# (BD=0x01, SD=0x02 - sequencial provado em 15/08/2026). Codigos 0..5 fixos:
#     0 OFF   1 Pan   2 ReverbSend   3 DelaySend   4 LFO Depth   5 InstFX
# Do 6 em diante sao PARAMETROS DE TONE num espaco de codigos GLOBAL e
# estavel: cada tone so mostra os que ele expoe, mas o codigo de cada nome
# nao muda. Medido em 15/08/2026 em dois kits: o LT do kit 089 (sample)
# percorreu 0-5 e depois 9-23 - o pulo 6/7/8 e exatamente Attack/Snappy/
# Color dos ACB do TR-707 (6 e 7 medidos direto; 8=Color fecha por
# eliminacao, unico nome restante da faixa). "Morph" (tones FM) segue sem
# codigo medido e fica fora do select ate ser medido. O offset 0x00 do
# bloco e o SELECT global ("kit ctrl select").
# A lista CTRL_FIXOS + CTRL_TONE_PARAMS alimenta o catalogo ("inst ctrl
# select", fileira CTRL da aba Efeitos): indice na lista == codigo.
CTRL_OFF_BASE = 0x01
CTRL_FIXOS = {0: "OFF", 1: "Pan", 2: "ReverbSend", 3: "DelaySend",
              4: "LFO Depth", 5: "InstFX"}
CTRL_TONE_PARAMS = {
    6: "Attack", 7: "Snappy", 8: "Color", 9: "Coarse", 10: "Rate",
    11: "Spread", 12: "BitReduce",
    # o visor mostra "Attack" nos codigos 6 e 13: o 6 foi medido em tone
    # ACB, o 13 na varredura do tone de SAMPLE do LT (vizinho de BitReduce
    # e HoldMode). Rotulo distinto SO na exibicao, para o select nao mentir.
    13: "Attack (sample)", 14: "HoldMode",
    15: "HoldTime", 16: "HoldStep", 17: "FltType", 18: "FltCutoff",
    19: "FltReso", 20: "FltEnvAtk", 21: "FltEnvDecay", 22: "FltEnvDepth",
    23: "FltVelo",
}

# ─────────────────────────────────────────────────────────────
# Os paineis da interface (a ordem espelha o fluxo de audio, p. 56:
# TONE -> INST FX -> LEVEL -> GAIN -> PAN -> sends -> MIX -> MASTER FX -> OUT)
# ─────────────────────────────────────────────────────────────
PAINEIS = [
    {"id": "inst", "rotulo": "INSTRUMENT", "escopo": "inst", "familia": "INST",
     "bloco": "inst",
     "gesto": "SHIFT + [INST]", "seletor": None, "tipos": [], "comuns": [
        # attack: o TR-EDITOR mostra numa coluna propria da aba INST; e
        # parametro do tone, entao nem todo tone o expoe no painel fisico
        p("tune", 255, 2, None, True), p("decay"), p("attack"), p("level"),
        # o gain para em 161 e fala em dB (GANHO_ESCALA, lido no visor em
        # 17/08/2026); bipolar aqui e so o desenho do arco, que cresce a
        # partir do 0.0 dB - o centro da faixa 0-161 cai justo nele
        p("gain", GANHO_MAX, 2, None, True, "", GANHO_ESCALA),
        p("pan", 255, 2, None, True, "", PAN_ESCALA),
        p("reverb send"), p("delay send"),
        # "Attack" so aparece no TR-EDITOR; o manual lista sete destinos
        p("lfo destino", None, 1, ["Tune", "Decay", "Level", "Pan",
                                   "ReverbSend", "DelaySend", "InstFX",
                                   "Attack"]),
        p("lfo depth", 255, 2, None, True),
        # o que o knob CTRL fisico da coluna controla; codigos = posicao na
        # lista (0-5 fixos + 6-23 parametros de tone, ver CTRL_FIXOS acima)
        # indice na lista == codigo. Montar por INDICE (e nao concatenando os
        # dois dicts) faz um KeyError alto se alguem reordenar ou tirar um
        # codigo - o silencio ali deslocaria todos os rotulos do select
        p("ctrl select", None, 1,
          [{**CTRL_FIXOS, **CTRL_TONE_PARAMS}[i] for i in range(24)])]},

    # 'amount' e o knob rotulado INST FX no TR-EDITOR (fica na coluna do
    # instrumento, mas escreve no bloco do INST FX - foi assim que se
    # descobriu que nao era o ATTACK, 15/08/2026).
    {"id": "ifx", "rotulo": "INST FX", "escopo": "inst", "familia": "IFX",
     "bloco": "ifx",
     "gesto": "SHIFT + [INST] -> InstFX", "seletor": "ifx tipo",
     "tipos": TIPOS_IFX, "comuns": [p("amount")],
     "por_tipo": _IFX_POR_TIPO},

    {"id": "reverb", "rotulo": "REVERB", "escopo": "kit", "familia": "REVERB",
     "bloco": "reverb",
     "gesto": "SHIFT + [KIT] -> REVERB", "seletor": "reverb tipo",
     "tipos": TIPOS_REVERB, "comuns": [
        p("level"), p("time"), p("predelay", 100, 1, None, False, "ms"),
        p("lowcut", None, 1, FREQ_CUT_BAIXA),
        p("highcut", None, 1, FREQ_CUT_ALTA), p("density", 10, 1)]},

    {"id": "delay", "rotulo": "DELAY", "escopo": "kit", "familia": "DELAY",
     "bloco": "delay",
     "gesto": "SHIFT + [KIT] -> DELAY", "seletor": "delay tipo",
     "tipos": TIPOS_DELAY, "comuns": [
        p("temposync", None, 1, ["OFF", "ON"]), p("level"), p("time"),
        p("feedback"), p("reverb send")], "por_tipo": _DELAY_POR_TIPO},

    {"id": "mfx", "rotulo": "MASTER FX", "escopo": "kit", "familia": "MFX",
     "bloco": "mfx",
     "gesto": "SHIFT + [KIT] -> MASTER FX", "seletor": "mfx tipo",
     "tipos": TIPOS_MFX, "comuns": [p("sw", None, 1, ["OFF", "ON"])],
     "por_tipo": _MFX_POR_TIPO},

    # bloco 05, achado em 15/08/2026 pelo gesto do RATE (10 02 05 01)
    {"id": "lfo", "rotulo": "LFO", "escopo": "kit", "familia": "LFO",
     "bloco": "lfo",
     "gesto": "SHIFT + [KIT] -> LFO", "seletor": None, "tipos": [], "comuns": [
        p("waveform", None, 1, ["SIN", "TRI", "SAW", "SQR", "S&H"]),
        p("temposync", None, 1, ["OFF", "ON"]), p("rate")]},

    # EXT IN - bloco 04, contiguo, medido knob a knob em 15/08/2026 a noite.
    # O side chain e o que faz o EXT IN "bombar" junto com um instrumento.
    {"id": "extin", "rotulo": "EXT IN", "escopo": "kit", "familia": "EXTIN",
     "bloco": "extin",
     "gesto": "SHIFT + [KIT] -> EXT IN", "seletor": None, "tipos": [],
     "comuns": [
        p("side chn source", None, 1,
          ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC",
           "?"]),
        p("side chn type", 7, 1),
        # MEDIDO em 17/08/2026: com o byte em 95, o visor mostrou +7.0 dB -
        # exatamente o que a escala do gain de instrumento previa ((95-81)/2).
        # A previsao foi feita ANTES da leitura, que e o que faz dela um teste.
        # Com a faixa 0-161 ja documentada, os dois pontos fecham a reta: e a
        # mesma tabela. (O "extin pan" continua sem escala - esse ninguem leu.)
        p("side chn depth"), p("gain", GANHO_MAX, 2, None, True, "",
                               GANHO_ESCALA),
        p("pan", 255, 2, None, True),
        p("reverb send"), p("delay send")]},

    {"id": "kit", "rotulo": "KIT", "escopo": "kit", "familia": "KIT",
     "bloco": "kit",
     "gesto": "SHIFT + [KIT]", "seletor": None, "tipos": [], "comuns": [
        p("level", 127, 1, None, False, DB),
        p("ctrl select", None, 1, ["OFF", "Pan", "ReverbSend", "DelaySend",
                                   "LFO Depth", "InstFX", "User"])]},
]


def _nome(painel, param, tipo=None):
    """A chave permanente. Muda-la apaga captura de hardware."""
    base = painel["id"]
    if tipo:
        base += " " + tipo.lower().replace("/", "").replace("+", "").replace(" ", "")
    return f"{base} {param['rot']}"


def _entrada(painel, param, tipo=None):
    e = dict(param)
    e["nome"] = _nome(painel, param, tipo)
    e["grupo"] = painel["rotulo"]
    e["painel"] = painel["id"]
    e["bloco"] = painel.get("bloco")
    e["escopo"] = painel["escopo"]
    e["tipo_fx"] = tipo
    e["min"] = 0
    e["dica"] = painel["gesto"] + (f" ({tipo})" if tipo else "") \
        + " -> " + param["rot"]
    return e


def _montar_catalogo():
    saida = []
    for painel in PAINEIS:
        if painel.get("seletor"):
            saida.append(_entrada(painel, p("tipo", None, 1, painel["tipos"])))
        for param in painel["comuns"]:
            saida.append(_entrada(painel, param))
        for tipo, params in (painel.get("por_tipo") or {}).items():
            for param in params:
                saida.append(_entrada(painel, param, tipo))
    return saida


CATALOGO = _montar_catalogo()
POR_NOME = {e["nome"]: e for e in CATALOGO}

# ─────────────────────────────────────────────────────────────
# PROVADO EM HARDWARE - sniff do TR-EDITOR, 15/08/2026 (REFERENCIA 7.2, M2).
#
# Cada linha saiu de UM gesto isolado do Luan no TR-EDITOR, com o MIDI Monitor
# em spy: mexer o controle de ponta a ponta e ver que endereco o editor
# escreve. Captura em capturas/*.mmon; reproduzivel com
#     python3 tr8s_sysex.py fx capturas/<arquivo>.mmon
#
# A faixa "medida" e o que o gesto de fato varreu. Onde ela bate com o manual
# (predelay 0-100, density 0-10) as duas fontes se confirmam; onde nao bate
# (gain parou em 161) vale o medido, e esta anotado.
#
# NAO RENOMEAR as chaves: elas sao o que fica gravado no ~/.lp_tr8s_fx.json.
PARAMS_FIXOS = {
    # --- REVERB: bloco 10 KK 01 00, painel inteiro fechado -----------
    # A ordem interna NAO e a do painel: TIME vem antes de LEVEL.
    "reverb tipo":     {"bloco": "reverb", "tipo": "kit",  "off": 0x00, "bytes": 1},
    "reverb time":     {"bloco": "reverb", "tipo": "kit",  "off": 0x01, "bytes": 2},
    "reverb level":    {"bloco": "reverb", "tipo": "kit",  "off": 0x03, "bytes": 2},
    "reverb predelay": {"bloco": "reverb", "tipo": "kit",  "off": 0x05, "bytes": 1},
    # dropdowns percorridos um a um (sniff 2b): codigo = posicao na lista
    "reverb lowcut":   {"bloco": "reverb", "tipo": "kit",  "off": 0x06,
                        "bytes": 1, "opcoes_do_catalogo": True},
    "reverb highcut":  {"bloco": "reverb", "tipo": "kit",  "off": 0x07,
                        "bytes": 1, "opcoes_do_catalogo": True},
    "reverb density":  {"bloco": "reverb", "tipo": "kit",  "off": 0x08, "bytes": 1},

    # --- DELAY: bloco 10 KK 02 00 -----------------------------------
    # Tres faixas medidas fecharam com listas do manual, o que confirma as
    # duas fontes de uma vez: highcut 0-14 = FREQ_CUT_ALTA (15 itens),
    # h dampf 0-13 = FREQ_CUT_ALTA sem o FLAT (14), l dampf 0-10 (11).
    # ao contrario do INST FX, aqui o codigo SEGUE a ordem do menu
    "delay tipo":        {"bloco": "delay", "tipo": "kit", "off": 0x00,
                          "bytes": 1, "opcoes": {
                              "0": "DLY", "1": "PAN", "2": "TAPE ECHO",
                              "3": "PITCH SHFT"}},
    "delay temposync":   {"bloco": "delay", "tipo": "kit", "off": 0x01,
                          "bytes": 1, "opcoes": {"0": "OFF", "1": "ON"}},
    "delay level":       {"bloco": "delay", "tipo": "kit", "off": 0x02, "bytes": 2},
    "delay time":        {"bloco": "delay", "tipo": "kit", "off": 0x04, "bytes": 2},
    "delay feedback":    {"bloco": "delay", "tipo": "kit", "off": 0x06, "bytes": 2},
    "delay dly highcut": {"bloco": "delay", "tipo": "kit", "off": 0x08, "bytes": 1},
    # h/l damp: o catalogo os deduzia com 2 bytes em dB; o gesto mostrou UM
    # byte indo ate 81. Vale o medido.
    "delay dly h damp":  {"bloco": "delay", "tipo": "kit", "off": 0x09, "bytes": 1},
    "delay dly h dampf": {"bloco": "delay", "tipo": "kit", "off": 0x0A,
                          "bytes": 1, "opcoes_do_catalogo": True},
    "delay dly l damp":  {"bloco": "delay", "tipo": "kit", "off": 0x0B, "bytes": 1},
    "delay dly l dampf": {"bloco": "delay", "tipo": "kit", "off": 0x0C,
                          "bytes": 1, "opcoes_do_catalogo": True},
    # o quanto do delay volta para o reverb (ultimo knob da fileira DELAY
    # SEND, depois do EXT IN). Longe dos outros: offset 0x1C.
    "delay reverb send": {"bloco": "delay", "tipo": "kit", "off": 0x1C, "bytes": 2},

    # Cada TIPO de delay tem area propria - aqui NAO vale a regra de regiao
    # compartilhada do MASTER FX/INST FX, e os tamanhos variam (bass e 1
    # byte, coarse e 2). Por isso os do TAPE ECHO ficam por medir.
    "delay pan tap time":    {"bloco": "delay", "tipo": "kit", "off": 0x0D,
                              "bytes": 1},
    # TAPE ECHO: contiguo de 0x0E a 0x1B, misturando 1 e 2 bytes
    "delay tapeecho mode":   {"bloco": "delay", "tipo": "kit", "off": 0x0E,
                              "bytes": 1, "opcoes": {
                                  "0": "S", "1": "M", "2": "L", "3": "S+M",
                                  "4": "S+L", "5": "M+L", "6": "S+M+L"}},
    "delay tapeecho bass":   {"bloco": "delay", "tipo": "kit", "off": 0x0F,
                              "bytes": 1},
    "delay tapeecho treble": {"bloco": "delay", "tipo": "kit", "off": 0x10,
                              "bytes": 1},
    "delay tapeecho pan s":  {"bloco": "delay", "tipo": "kit", "off": 0x11,
                              "bytes": 2},
    "delay tapeecho pan m":  {"bloco": "delay", "tipo": "kit", "off": 0x13,
                              "bytes": 2},
    "delay tapeecho pan l":  {"bloco": "delay", "tipo": "kit", "off": 0x15,
                              "bytes": 2},
    "delay tapeecho tape dist": {"bloco": "delay", "tipo": "kit", "off": 0x17,
                                 "bytes": 1},
    "delay tapeecho wf rate":   {"bloco": "delay", "tipo": "kit", "off": 0x18,
                                 "bytes": 2},
    "delay tapeecho wf depth":  {"bloco": "delay", "tipo": "kit", "off": 0x1A,
                                 "bytes": 2},
    "delay pitchshft coarse": {"bloco": "delay", "tipo": "kit", "off": 0x1E,
                               "bytes": 2},
    "delay pitchshft fine":  {"bloco": "delay", "tipo": "kit", "off": 0x20,
                              "bytes": 2},

    # --- MASTER FX: bloco 10 KK 03 00 -------------------------------
    # Codigos embaralhados de novo (a 1a opcao do menu, HPF, e o codigo 11).
    # Confirmado pelo dump do boot: estava 0x0C e o editor mostrava LPF/HPF.
    "mfx tipo":  {"bloco": "mfx", "tipo": "kit", "off": 0x00, "bytes": 1,
                  "opcoes": {
                      "0": "COMPRESSOR", "1": "DRIVE", "2": "OVERDRIVE",
                      "3": "DISTORTION", "4": "FUZZ", "5": "CRUSHER",
                      "6": "PHASER", "7": "FLANGER", "8": "TRANSIENT",
                      "9": "TRANSIENT2", "10": "LPF", "11": "HPF",
                      "12": "LPF/HPF", "13": "L BOOST", "14": "H BOOST",
                      "15": "L/H BOOST", "16": "ISOLATOR", "17": "SBF",
                      "18": "NOISE", "19": "FATTENER", "20": "VINYL SIM"}},
    "mfx sw":    {"bloco": "mfx", "tipo": "kit", "off": 0x01, "bytes": 1,
                  "opcoes": {"0": "OFF", "1": "ON"}},

    # Os parametros DO TIPO ATIVO comecam em 0x27 e andam de 2 em 2, na ordem
    # em que o TR-EDITOR os desenha. Medido para LPF/HPF; se a regra valer
    # para os outros 20 tipos, os ~150 restantes caem sem gesto - mas isso
    # ainda e HIPOTESE, entao so o LPF/HPF esta aqui.
    # Note que type e clipper sao 2 bytes apesar de terem 3 e 2 opcoes.
    "mfx lpfhpf depth":     {"bloco": "mfx", "tipo": "kit", "off": 0x27, "bytes": 2},
    "mfx lpfhpf resonance": {"bloco": "mfx", "tipo": "kit", "off": 0x29, "bytes": 2},
    "mfx lpfhpf type":      {"bloco": "mfx", "tipo": "kit", "off": 0x2B, "bytes": 2,
                             "opcoes": {"0": "-24dB", "1": "-18dB", "2": "-12dB"}},
    "mfx lpfhpf gain":      {"bloco": "mfx", "tipo": "kit", "off": 0x2D, "bytes": 2},
    "mfx lpfhpf clipper":   {"bloco": "mfx", "tipo": "kit", "off": 0x2F, "bytes": 2,
                             "opcoes": {"0": "OFF", "1": "ON"}},
    # os dois gestos que provaram que a regiao e compartilhada
    "mfx compressor balance":  {"bloco": "mfx", "tipo": "kit", "off": 0x27,
                                "bytes": 2},
    "mfx vinylsim compressor": {"bloco": "mfx", "tipo": "kit", "off": 0x27,
                                "bytes": 2},

    # Enums do MASTER FX percorridos um a um no sniff 2 (15/08/2026 a noite):
    # os seis cairam EXATAMENTE onde a regra 0x27+2i previa (seis provas
    # independentes da regra), e em todos o codigo segue a ordem da lista do
    # catalogo - 'opcoes_do_catalogo' manda o carregar() montar o mapa
    # numero->nome a partir dela, sem o "?" de nao verificado.
    "mfx compressor ratio": {"bloco": "mfx", "tipo": "kit", "off": 0x31,
                             "bytes": 2, "opcoes_do_catalogo": True},
    "mfx compressor knee":  {"bloco": "mfx", "tipo": "kit", "off": 0x33,
                             "bytes": 2, "opcoes_do_catalogo": True},
    "mfx phaser type":      {"bloco": "mfx", "tipo": "kit", "off": 0x31,
                             "bytes": 2, "opcoes_do_catalogo": True},
    "mfx flanger mode":     {"bloco": "mfx", "tipo": "kit", "off": 0x33,
                             "bytes": 2, "opcoes_do_catalogo": True},
    "mfx sbf type":         {"bloco": "mfx", "tipo": "kit", "off": 0x2D,
                             "bytes": 2, "opcoes_do_catalogo": True},
    "mfx noise direction":  {"bloco": "mfx", "tipo": "kit", "off": 0x2B,
                             "bytes": 2, "opcoes_do_catalogo": True},

    # --- EXT IN: bloco 10 KK 04 00, contiguo -------------------------
    # source 0-11 na ordem BD..RC (11 medido como ultimo; o rotulo do 11 nao
    # foi lido no visor). gain com a mesma escala 0-161 do gain de inst.
    "extin side chn source": {"bloco": "extin", "tipo": "kit", "off": 0x00,
                              "bytes": 1, "opcoes_do_catalogo": True},
    "extin side chn type":   {"bloco": "extin", "tipo": "kit", "off": 0x01,
                              "bytes": 1},
    "extin side chn depth":  {"bloco": "extin", "tipo": "kit", "off": 0x02,
                              "bytes": 2},
    "extin gain":            {"bloco": "extin", "tipo": "kit", "off": 0x04,
                              "bytes": 2},
    "extin pan":             {"bloco": "extin", "tipo": "kit", "off": 0x06,
                              "bytes": 2},
    "extin reverb send":     {"bloco": "extin", "tipo": "kit", "off": 0x08,
                              "bytes": 2},
    "extin delay send":      {"bloco": "extin", "tipo": "kit", "off": 0x0A,
                              "bytes": 2},

    # --- LFO do kit: bloco 10 KK 05 00 ------------------------------
    "lfo waveform":  {"bloco": "lfo", "tipo": "kit", "off": 0x00, "bytes": 1,
                      "opcoes": {"0": "SIN", "1": "TRI", "2": "SAW",
                                 "3": "SQR", "4": "S&H"}},
    "lfo rate":      {"bloco": "lfo", "tipo": "kit", "off": 0x01, "bytes": 2},
    "lfo temposync": {"bloco": "lfo", "tipo": "kit", "off": 0x03, "bytes": 1,
                      "opcoes": {"0": "OFF", "1": "ON"}},

    # --- KIT ---------------------------------------------------------
    # level e UM byte ate 127, nao dois como o catalogo deduzia
    "kit level":       {"bloco": "kit",  "tipo": "kit", "off": 0x10, "bytes": 1},
    # o CTRL mora em bloco proprio (06), nao no no do kit
    "kit ctrl select": {"bloco": "ctrl", "tipo": "kit", "off": 0x00, "bytes": 1,
                        "opcoes": {"0": "OFF", "1": "Pan", "2": "ReverbSend",
                                   "3": "DelaySend", "4": "LFO Depth",
                                   "5": "InstFX", "6": "User"}},
    # CTRL de CADA instrumento: bloco 06, offsets 0x01+i (sniff 15/08/2026,
    # capturas/ctrl-por-inst e ctrl-lt-codigos). "off_por_inst" marca o
    # terceiro caso de enderecamento que BLOCOS nao cobria: um byte por
    # instrumento DENTRO de um bloco de kit (COLOR 0x42+i, OUTPUT bloco 07 e
    # choke bloco 08 sao o mesmo padrao e podem usar a flag quando a
    # interface precisar). ATENCAO: a ESCRITA no bloco 06 nunca saiu da
    # nossa ponta - so o TR-EDITOR foi visto escrevendo la; o primeiro teste
    # e girar o CTRL fisico depois de trocar o destino e OUVIR.
    "inst ctrl select": {"bloco": "ctrl", "tipo": "inst",
                         "off": CTRL_OFF_BASE,
                         "bytes": 1, "off_por_inst": True,
                         "opcoes_do_catalogo": True},

    # --- INSTRUMENTO: bloco 10 KK 1I 00, um por instrumento ----------
    # Os 11 blocos (BD..RC) tem layout identico: mapear o BD mapeou todos.
    "inst tune":        {"bloco": "inst", "tipo": "inst", "off": 0x04, "bytes": 2},
    "inst decay":       {"bloco": "inst", "tipo": "inst", "off": 0x06, "bytes": 2},
    "inst level":       {"bloco": "inst", "tipo": "inst", "off": 0x08, "bytes": 2},
    "inst gain":        {"bloco": "inst", "tipo": "inst", "off": 0x0A, "bytes": 2},
    "inst pan":         {"bloco": "inst", "tipo": "inst", "off": 0x0C, "bytes": 2},
    "inst reverb send": {"bloco": "inst", "tipo": "inst", "off": 0x0E, "bytes": 2},
    "inst delay send":  {"bloco": "inst", "tipo": "inst", "off": 0x10, "bytes": 2},
    "inst lfo depth":   {"bloco": "inst", "tipo": "inst", "off": 0x14, "bytes": 2},
    # destinos 1..8 na ordem do menu; o 0 nao aparece no menu do editor
    # (provavelmente OFF, nao verificado). "Attack" nao estava no manual.
    "inst lfo destino": {"bloco": "inst", "tipo": "inst", "off": 0x13,
                         "bytes": 1, "opcoes": {
                             "1": "Tune", "2": "Decay", "3": "Level",
                             "4": "Pan", "5": "ReverbSend", "6": "DelaySend",
                             "7": "InstFX", "8": "Attack"}},
    # 0x35 = 53: o primeiro byte da SEGUNDA metade do bloco. O instrumento
    # tem 101 bytes contiguos e o TR-EDITOR le em dois pedacos (53 + 48).
    "inst attack":      {"bloco": "inst", "tipo": "inst", "off": 0x35, "bytes": 2},

    # --- INST FX -----------------------------------------------------
    # o knob rotulado "INST FX" no editor; mora no bloco do INST FX, nao no
    # do instrumento. Nao confundir com o ATTACK, que fica ao lado na tela.
    "ifx amount":       {"bloco": "ifx",  "tipo": "inst", "off": 0x09, "bytes": 2},
    # O CODIGO NAO SEGUE A ORDEM DO MENU. A 1a opcao do menu (THRU) e o
    # codigo 12; a 10a (COMPRESSOR) e o 0. Assumir "menu = codigo" trocaria o
    # efeito errado em 13 dos 17 casos. Conferido de dois lados: no dump do
    # boot o BD estava em 03 e o TR-EDITOR mostrava COMP+DRV.
    "ifx tipo":         {"bloco": "ifx",  "tipo": "inst", "off": 0x00,
                         "bytes": 1, "opcoes": {
                             "0": "COMPRESSOR", "1": "DRIVE", "2": "CRUSHER",
                             "3": "COMP+DRV", "4": "TRANSIENT", "5": "LPF",
                             "6": "HPF", "7": "LPF/HPF", "8": "L BOOST",
                             "9": "H BOOST", "10": "L/H BOOST",
                             "11": "ISOLATOR", "12": "THRU",
                             "13": "SATURATOR", "14": "FREQ SHIFT",
                             "15": "RING MOD", "16": "SPREAD"}},
}

# COLOR do instrumento: mora no bloco do KIT (10 KK 00 00), UM BYTE POR
# INSTRUMENTO a partir de 0x42 (BD=0x42, SD=0x43 - sequencial provado em
# 15/08/2026; o SD percorreu os codigos 0..11 na ordem do menu, entao
# RED=0, ORANGE=1, ...). E o unico parametro por-instrumento que vive num
# bloco de kit; o modelo BLOCOS nao cobre isso ainda, entao fica registrado
# aqui ate a interface precisar: offset = 0x42 + indice do instrumento.
COLOR_OFF_BASE = 0x42
# na ordem do menu do TR-EDITOR = ordem dos codigos (o SD percorreu 0..11)
CORES_INST = ["RED", "ORANGE", "YELLOW", "LIME", "GREEN", "SKYBLUE",
              "LIGHTBLUE", "BLUE", "PURPLE", "MAGENTA", "PINK", "WHITE"]

# ─────────────────────────────────────────────────────────────
# DERIVADOS DE UMA REGRA MEDIDA (nao de um gesto proprio)
#
# Os parametros do tipo ativo do MASTER FX ficam numa regiao unica que TODOS
# os 21 tipos reusam, a partir de 0x27, de 2 em 2, na ordem em que o
# TR-EDITOR desenha os controles. Medido em 15/08/2026:
#     LPF/HPF    depth->0x27  resonance->0x29  type->0x2B  gain->0x2D
#                clipper->0x2F
#     COMPRESSOR balance   -> 0x27
#     VINYL SIM  compressor-> 0x27
# COMPRESSOR e VINYL SIM foram escolhidos por serem os extremos da lista de
# codigos (0 e 20) e terem contagens diferentes de parametros: se a regra
# sobrevive aos dois, sobrevive aos 21.
#
# O que NAO esta provado e a ordem dentro de cada tipo - ela vem das imagens
# do painel. Por isso estas entradas ficam marcadas com "derivado": um gesto
# em qualquer tipo confirma ou derruba o bloco inteiro dele.
# O INST FX tem a MESMA arquitetura, com base 0x09 e um bloco por
# instrumento. Medido no BD trocando entre COMP+DRV (codigo 3), LPF (5) e
# SPREAD (16): o primeiro parametro dos tres caiu em 0x09.
#
# 0x09 e tambem onde escreve o knob rotulado "INST FX" na coluna do
# instrumento - ou seja, aquele knob E o primeiro parametro do tipo ativo,
# mostrado num segundo lugar. Por isso "ifx amount" e o primeiro do tipo
# convivem no mesmo offset: sao o mesmo controle, como no proprio TR-EDITOR.
BASE_TIPO = {"mfx": (0x27, "kit"), "ifx": (0x09, "inst")}


def _derivados_por_tipo():
    """Aplica a regra 'base + 2*posicao' aos tipos de MASTER FX e INST FX."""
    out = {}
    for pid, (base, escopo) in BASE_TIPO.items():
        pn = next(x for x in PAINEIS if x["id"] == pid)
        for tipo, params in (pn.get("por_tipo") or {}).items():
            for i, param in enumerate(params):
                nome = _nome(pn, param, tipo)
                if nome in PARAMS_FIXOS:        # medido vence derivado
                    continue
                out[nome] = {"bloco": pid, "tipo": escopo,
                             "off": base + 2 * i, "bytes": 2,
                             "derivado": True}
    return out


PARAMS_FIXOS.update(_derivados_por_tipo())

# Faixa que cada gesto varreu de fato. E DOCUMENTACAO: ninguem le este dict em
# tempo de execucao - quem manda no 'max' da tela e no clamp da escrita e o
# catalogo. Serve para conferir se o catalogo esta mentindo sobre a faixa. O gain e o unico que discordou do esperado.
FAIXAS_MEDIDAS = {
    "reverb time": (0, 255), "reverb level": (0, 255),
    "reverb predelay": (0, 100), "reverb density": (0, 10),
    "inst reverb send": (0, 255), "inst delay send": (0, 255),
    "inst level": (0, 255), "inst tune": (0, 255), "inst decay": (0, 255),
    "inst pan": (0, 255), "inst lfo depth": (0, 255),
    # 17/08/2026 fechou o porque: 161 e o fim da faixa DE VERDADE (+40.0 dB) e
    # o 0 e -INF. Ver GANHO_ESCALA no alto do arquivo
    "inst gain": (1, 161),   # parou em 161, nao em 255 - medido, nao deduzido
    "ifx amount": (0, 255),
}


def carregar():
    """Mapa completo: fixos + capturados, ja enriquecidos pelo catalogo."""
    mapa = dict(PARAMS_FIXOS)
    capturados = set()
    try:
        with open(ARQ_FX) as f:
            do_arquivo = json.load(f)
            capturados = set(do_arquivo)
            mapa.update(do_arquivo)
    except (OSError, ValueError):
        pass
    for nome, ent in mapa.items():
        # de onde veio a entrada: True = capturada no app (mora no
        # ~/.lp_tr8s_fx.json e o apagar() alcanca), False = fixa do sniff, imune.
        # A aba que listava por esta flag saiu em 17/08/2026; a marca fica
        # porque e a unica forma de a tela saber a procedencia de um offset
        ent["capturado"] = nome in capturados
        cat = POR_NOME.get(nome, {})
        # 'bloco' diz em QUAL bloco do kit o offset vive (BLOCOS). Entradas
        # capturadas antes de 15/08/2026 nao tem o campo; ai vale o do
        # catalogo, e so por ultimo o palpite pelo escopo.
        ent.setdefault("bloco", cat.get("bloco")
                       or ("inst" if ent.get("tipo") == "inst" else "kit"))
        ent.setdefault("bytes", cat.get("bytes", 1))
        ent.setdefault("forma", cat.get("forma", "fader"))
        ent.setdefault("grupo", cat.get("grupo", "OUTROS"))
        ent.setdefault("min", 0)
        ent.setdefault("max", cat.get("max", 255 if ent["bytes"] == 2 else 127))
        ent.setdefault("bipolar", cat.get("bipolar", False))
        # enums cuja ordem codigo=posicao foi VERIFICADA em hardware: as
        # opcoes vem da lista do catalogo, sem precisar anotar uma a uma
        if ent.get("opcoes_do_catalogo") and cat.get("opcoes"):
            ent.setdefault("opcoes",
                           {str(i): r for i, r in enumerate(cat["opcoes"])})
        ent.setdefault("opcoes", {})
        ent["sugestoes"] = cat.get("opcoes", [])
        ent["rot"] = cat.get("rot", nome)
        ent["painel"] = cat.get("painel")
        ent["tipo_fx"] = cat.get("tipo_fx")
    return mapa


def _ler_capturados():
    try:
        with open(ARQ_FX) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _salvar(capturados):
    with open(ARQ_FX, "w") as f:
        json.dump(capturados, f, indent=1, ensure_ascii=False)


def registrar(nome, tipo, off, nbytes=None, bloco=None):
    """Grava um parametro capturado. 'tipo' aqui e onde ele mora
    (kit|inst), nao o tipo de efeito; 'bloco' e qual dos blocos do kit
    (BLOCOS) - a captura guiada descobre isso sozinha."""
    assert tipo in ("kit", "inst")
    cat = POR_NOME.get(nome, {})
    capturados = _ler_capturados()
    antigo = capturados.get(nome, {})
    entrada = {"tipo": tipo, "off": int(off),
               "bloco": bloco or cat.get("bloco") or tipo,
               "bytes": int(nbytes or cat.get("bytes", 1)),
               "forma": cat.get("forma", "fader"),
               "grupo": cat.get("grupo", "OUTROS"),
               "min": 0,
               "max": cat.get("max", 255 if (nbytes or 1) == 2 else 127),
               "bipolar": cat.get("bipolar", False),
               # opcoes ja anotadas sobrevivem a uma recaptura de offset
               "opcoes": antigo.get("opcoes", {})}
    capturados[nome] = entrada
    _salvar(capturados)
    saida = dict(entrada)
    saida["sugestoes"] = cat.get("opcoes", [])
    saida["capturado"] = True   # acabou de entrar no arquivo - esquecivel
    return saida


def registrar_opcao(nome, valor, rotulo):
    """Associa um CODIGO lido da maquina ao rotulo que esta no visor."""
    capturados = _ler_capturados()
    if nome not in capturados:
        return None
    capturados[nome].setdefault("opcoes", {})[str(int(valor))] = rotulo
    _salvar(capturados)
    return capturados[nome]["opcoes"]


def apagar(nome):
    capturados = _ler_capturados()
    if nome not in capturados:
        return False
    del capturados[nome]
    _salvar(capturados)
    return True


def pendentes(mapa):
    return [e for e in CATALOGO if e["nome"] not in mapa]


def paineis_para_tela():
    """O catalogo organizado como a interface desenha."""
    saida = []
    for painel in PAINEIS:
        saida.append({
            "id": painel["id"], "rotulo": painel["rotulo"],
            "escopo": painel["escopo"], "gesto": painel["gesto"],
            "seletor": _nome(painel, p("tipo")) if painel.get("seletor") else None,
            "tipos": painel["tipos"],
            "comuns": [_entrada(painel, x)["nome"] for x in painel["comuns"]],
            "por_tipo": {t: [_entrada(painel, x, t)["nome"] for x in ps]
                         for t, ps in (painel.get("por_tipo") or {}).items()},
        })
    return saida


def rotulo_valor(ent, valor, nome=None):
    """Como mostrar um valor: rotulo do enum, com-sinal se bipolar, ou o cru.

    'nome' e opcional e serve para achar a escala do catalogo (o GAIN em dB):
    a tabela nao viaja dentro do mapa, que vai no /estado 4x por segundo."""
    if valor is None:
        return "—"
    if ent.get("forma") == "enum":
        return ent.get("opcoes", {}).get(str(valor), f"? ({valor})")
    esc = ent.get("escala") or POR_NOME.get(nome or "", {}).get("escala")
    if esc:
        return esc.get(valor, str(valor))
    if ent.get("bipolar"):
        return f"{valor - 128:+d}"
    return str(valor)


if __name__ == "__main__":
    nomes = [e["nome"] for e in CATALOGO]
    dup = {n for n in nomes if nomes.count(n) > 1}
    assert not dup, f"nomes duplicados: {sorted(dup)}"
    por_painel = {}
    for e in CATALOGO:
        por_painel[e["grupo"]] = por_painel.get(e["grupo"], 0) + 1
    print(f"{len(CATALOGO)} parametros no catalogo, nenhum nome duplicado")
    for g, n in por_painel.items():
        print(f"  {g:12} {n:4}")
    print(f"\n{len(paineis_para_tela())} paineis para a tela")
    print("exemplo de dica:", CATALOGO[0]["dica"])
