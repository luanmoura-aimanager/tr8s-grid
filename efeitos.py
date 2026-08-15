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
# Vocabulario compacto para descrever parametro.
#   p(rot, max, bytes)          -> fader
#   p(rot, None, 1, opcoes=[])  -> lista
#   p(..., bipolar=True)        -> -128..+127 com centro em 128
# ─────────────────────────────────────────────────────────────
def p(rot, maximo=255, nbytes=2, opcoes=None, bipolar=False, unidade=""):
    return {"rot": rot, "max": 255 if maximo is None else maximo,
            "bytes": nbytes, "opcoes": opcoes or [],
            "forma": "enum" if opcoes else "fader",
            "bipolar": bipolar, "unidade": unidade}


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
TIPO_FILTRO = ["-24dB", "-18dB", "-12dB"]
SYNC_RATE = ["64.00", "48.00", "32.00", "24.00", "16.00", "12.00", "8.00",
             "6.00", "4.00", "3.00", "2.00", "1.50", "1.00", "0.75", "0.50",
             "0.25"]

# ── blocos que se repetem entre MASTER FX e INST FX ──
_FILTRO = [p("depth"), p("resonance"), p("type", None, 1, TIPO_FILTRO),
           p("gain", 255, 2, None, True, DB),
           p("clipper", None, 1, ["OFF", "ON"])]
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
_MOD = [p("balance"), p("temposync", None, 1, ["OFF", "ON"]), p("rate"),
        p("depth"), p("resonance"), p("manual")]

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
    "PHASER": _MOD + [p("type", None, 1, ["4ST", "8ST", "12ST", "BI-PHASE"])],
    "FLANGER": _MOD + [p("locutf", None, 1, FREQ_CUT_BAIXA),
                       p("mode", None, 1, ["MONO", "STEREO"])],
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
    "DLY": [p("highcut", None, 1, FREQ_CUT_ALTA),
            p("h damp", 255, 2, None, False, DB),
            p("h dampf", None, 1, FREQ_CUT_ALTA[:-1]),
            p("l damp", 255, 2, None, False, DB),
            p("l dampf", None, 1, ["80Hz", "100Hz", "125Hz", "160Hz", "200Hz",
                                   "250Hz", "315Hz", "400Hz", "500Hz",
                                   "630Hz", "800Hz"])],
    "PAN": [p("tap time", 100, 1, None, False, "%")],
    "TAPE ECHO": [p("mode", None, 1, ["S", "M", "L", "S+M", "S+L", "M+L",
                                      "S+M+L"]),
                  p("bass", 255, 2, None, True, DB),
                  p("treble", 255, 2, None, True, DB),
                  p("pan s", 255, 2, None, True), p("pan m", 255, 2, None, True),
                  p("pan l", 255, 2, None, True), p("tape dist", 8, 1),
                  p("wf rate"), p("wf depth")],
    "PITCH SHFT": [p("coarse", 255, 2, None, True, "semi"),
                   p("fine", 255, 2, None, True, "cent")],
}

# ─────────────────────────────────────────────────────────────
# Os paineis da interface (a ordem espelha o fluxo de audio, p. 56:
# TONE -> INST FX -> LEVEL -> GAIN -> PAN -> sends -> MIX -> MASTER FX -> OUT)
# ─────────────────────────────────────────────────────────────
PAINEIS = [
    {"id": "inst", "rotulo": "INSTRUMENT", "escopo": "inst", "familia": "INST",
     "gesto": "SHIFT + [INST]", "seletor": None, "tipos": [], "comuns": [
        p("tune", 255, 2, None, True), p("decay"), p("level"),
        p("gain", 255, 2, None, True, DB), p("pan", 255, 2, None, True),
        p("reverb send"), p("delay send"),
        p("lfo destino", None, 1, ["Tune", "Decay", "Level", "Pan",
                                   "ReverbSend", "DelaySend", "InstFX"]),
        p("lfo depth", 255, 2, None, True)]},

    {"id": "ifx", "rotulo": "INST FX", "escopo": "inst", "familia": "IFX",
     "gesto": "SHIFT + [INST] -> InstFX", "seletor": "ifx tipo",
     "tipos": TIPOS_IFX, "comuns": [], "por_tipo": _IFX_POR_TIPO},

    {"id": "reverb", "rotulo": "REVERB", "escopo": "kit", "familia": "REVERB",
     "gesto": "SHIFT + [KIT] -> REVERB", "seletor": "reverb tipo",
     "tipos": TIPOS_REVERB, "comuns": [
        p("level"), p("time"), p("predelay", 100, 1, None, False, "ms"),
        p("lowcut", None, 1, FREQ_CUT_BAIXA),
        p("highcut", None, 1, FREQ_CUT_ALTA), p("density", 10, 1)]},

    {"id": "delay", "rotulo": "DELAY", "escopo": "kit", "familia": "DELAY",
     "gesto": "SHIFT + [KIT] -> DELAY", "seletor": "delay tipo",
     "tipos": TIPOS_DELAY, "comuns": [
        p("temposync", None, 1, ["OFF", "ON"]), p("level"), p("time"),
        p("feedback"), p("reverb send")], "por_tipo": _DELAY_POR_TIPO},

    {"id": "mfx", "rotulo": "MASTER FX", "escopo": "kit", "familia": "MFX",
     "gesto": "SHIFT + [KIT] -> MASTER FX", "seletor": "mfx tipo",
     "tipos": TIPOS_MFX, "comuns": [p("sw", None, 1, ["OFF", "ON"])],
     "por_tipo": _MFX_POR_TIPO},

    {"id": "lfo", "rotulo": "LFO", "escopo": "kit", "familia": "LFO",
     "gesto": "SHIFT + [KIT] -> LFO", "seletor": None, "tipos": [], "comuns": [
        p("waveform", None, 1, ["SIN", "TRI", "SAW", "SQR", "S&H"]),
        p("temposync", None, 1, ["OFF", "ON"]), p("rate")]},

    {"id": "kit", "rotulo": "KIT", "escopo": "kit", "familia": "KIT",
     "gesto": "SHIFT + [KIT]", "seletor": None, "tipos": [], "comuns": [
        p("level", 255, 2, None, False, DB),
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

# Entradas provadas por sniff do TR-EDITOR (sessao M2), com data e captura de
# origem no comentario. Vazio ate a primeira sessao.
PARAMS_FIXOS = {}


def carregar():
    """Mapa completo: fixos + capturados, ja enriquecidos pelo catalogo."""
    mapa = dict(PARAMS_FIXOS)
    try:
        with open(ARQ_FX) as f:
            mapa.update(json.load(f))
    except (OSError, ValueError):
        pass
    for nome, ent in mapa.items():
        cat = POR_NOME.get(nome, {})
        ent.setdefault("bytes", cat.get("bytes", 1))
        ent.setdefault("forma", cat.get("forma", "fader"))
        ent.setdefault("grupo", cat.get("grupo", "OUTROS"))
        ent.setdefault("min", 0)
        ent.setdefault("max", cat.get("max", 255 if ent["bytes"] == 2 else 127))
        ent.setdefault("bipolar", cat.get("bipolar", False))
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


def registrar(nome, tipo, off, nbytes=None):
    """Grava um parametro capturado. 'tipo' aqui e onde ele mora
    (kit|inst), nao o tipo de efeito."""
    assert tipo in ("kit", "inst")
    cat = POR_NOME.get(nome, {})
    capturados = _ler_capturados()
    antigo = capturados.get(nome, {})
    entrada = {"tipo": tipo, "off": int(off),
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


def rotulo_valor(ent, valor):
    """Como mostrar um valor: rotulo do enum, com-sinal se bipolar, ou o cru."""
    if valor is None:
        return "—"
    if ent.get("forma") == "enum":
        return ent.get("opcoes", {}).get(str(valor), f"? ({valor})")
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
