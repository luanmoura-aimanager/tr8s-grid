#!/usr/bin/env python3
"""
apc_tr8s.py - grid fisico na APC40 mkII escrevendo steps na TR-8S via SysEx

Requisitos:
    pip3 install mido python-rtmidi

Comandos:
    python3 apc_tr8s.py ports              # lista portas MIDI
    python3 apc_tr8s.py learn              # descobre o layout dos pads
    python3 apc_tr8s.py dump               # le os blocos da TR-8S e mostra os bytes
    python3 apc_tr8s.py test               # prova se a ESCRITA funciona
    python3 apc_tr8s.py run                # o grid ao vivo

IMPORTANTE: os valores em CONFIG_A_CONFIRMAR sao hipotese ate o diff do SEND.
Rode 'dump' e o diff antes de confiar no 'run'.
"""
import sys, time, json, os
import mido

# ─────────────────────────────────────────────────────────────
# Portas (ajuste se os nomes mudarem)
# ─────────────────────────────────────────────────────────────
APC_MATCH   = "APC40"
TR8S_MATCH  = "CTRL"          # a porta "TR-8S TR-8S CTRL"

# ─────────────────────────────────────────────────────────────
# SysEx TR-8S  (confirmado pela captura do MIDI Monitor)
# ─────────────────────────────────────────────────────────────
HDR      = [0x41, 0x10, 0x00, 0x00, 0x00, 0x45]   # Roland / devID / model TR-8S
RQ1, DT1 = 0x11, 0x12

def roland_checksum(payload):
    """payload = endereco + dados. Confirmado contra as capturas."""
    return (128 - sum(payload) % 128) % 128

def dt1(addr, data):
    body = list(addr) + list(data)
    return mido.Message('sysex', data=HDR + [DT1] + body + [roland_checksum(body)])

def rq1(addr, size):
    """size em 4 bytes de 7 bits."""
    sz = [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
    body = list(addr) + sz
    return mido.Message('sysex', data=HDR + [RQ1] + body + [roland_checksum(body)])

# ─────────────────────────────────────────────────────────────
# Layout do step - CONFIRMADO pelo dump de 08/08/2026
#
#   128 bytes = 16 steps x 8 bytes
#   bytes 6 e 7 = VELOCITY em nibbles (b6 = nibble alto, b7 = baixo)
#   velocity 0 = step desligado ; 1-127 = ligado com essa dinamica
#   ex.: 05 00 -> 0x50 = 80 (normal) ; 03 02 -> 0x32 = 50 (weak beat)
#   bytes 0-5 = ainda nao identificados (sub step, flam, probability, alt)
# ─────────────────────────────────────────────────────────────
VARIACAO      = 0x01   # 0x01=A ... 0x08=H  (0x09/0x0A = fills 1/2)
BLOCO_STEPS   = 0x08
BYTES_P_STEP  = 8
VEL_HI, VEL_LO = 6, 7
VEL_FORTE     = 80     # mesmo default do TR-EDITOR
VEL_FRACA     = 50     # weak beat

# byte 5 = tipo do step (confirmado na captura do TR-EDITOR)
SUB_BYTE = 5
MODOS = [("NORMAL", 0x00), ("FLAM", 0x01), ("SUB 1/2", 0x02),
         ("SUB 1/3", 0x03), ("SUB 1/4", 0x04)]

# instrumentos: indice do sub-bloco dentro da variacao
INSTRUMENTOS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC"]

def addr_bloco(inst_idx):
    return (0x20, VARIACAO, inst_idx, BLOCO_STEPS)

def addr_soma(addr, offset):
    """Soma com carry de 7 bits (enderecamento Roland)."""
    a = list(addr)
    for i in range(3, -1, -1):
        v = a[i] + (offset & 0x7F)
        offset >>= 7
        a[i] = v & 0x7F
        offset += v >> 7
    return tuple(a)

def addr_step(inst_idx, step):
    """Endereco dos 8 bytes de um step. Confirmado na captura do TR-EDITOR."""
    return addr_soma(addr_bloco(inst_idx), step * BYTES_P_STEP)

def addr_accent():
    """Mascara de 16 bits do ACCENT, em 4 nibbles."""
    return (0x20, VARIACAO, 0x00, 0x00)

def mascara_para_nibbles(m):
    return [(m >> 12) & 0x0F, (m >> 8) & 0x0F, (m >> 4) & 0x0F, m & 0x0F]

def nibbles_para_mascara(n):
    return (n[0] << 12) | (n[1] << 8) | (n[2] << 4) | n[3]

# ─────────────────────────────────────────────────────────────
# APC40 mkII
# ─────────────────────────────────────────────────────────────
APC_INIT = mido.Message('sysex',
    data=[0x47, 0x7F, 0x29, 0x60, 0x00, 0x04, 0x41, 0x00, 0x00, 0x00])
# 0x41 = Ableton Live Mode (LEDs controlados pelo host).
# Se os LEDs nao responderem, teste 0x40 (Generic) ou 0x42.

COR_OFF, COR_ON, COR_FRACA = 0, 5, 6      # apagado / vermelho / vermelho escuro
COR_SUB, COR_SUB_FRACA     = 9, 10        # laranja / laranja escuro (flam e sub step)
COR_ACC = 13                              # amarelo, so pra linha do ACCENT
SCENE_NOTAS = [0x52, 0x53, 0x54, 0x55, 0x56]   # SCENE LAUNCH 1-5 = os 5 modos
LINHAS_INST = 4                           # linhas 1-4 = instrumentos, linha 5 = ACC
CLIP_STOP   = 0x34                        # nota dos CLIP STOP; canal 0-7 = variacao A-H
VARIACOES   = "ABCDEFGH"
LAYOUT_FILE = os.path.expanduser("~/.apc_tr8s_layout.json")


def achar_porta(lista, trecho):
    for nome in lista:
        if trecho.lower() in nome.lower():
            return nome
    return None


def cmd_ports():
    print("ENTRADAS:")
    for n in mido.get_input_names():
        print("  ", n)
    print("\nSAIDAS:")
    for n in mido.get_output_names():
        print("  ", n)


def cmd_learn():
    """Descobre o mapeamento fisico dos pads a partir de 3 toques."""
    apc_in = achar_porta(mido.get_input_names(), APC_MATCH)
    if not apc_in:
        print("APC40 nao encontrada. Rode 'ports'."); return
    pedidos = [
        "Aperte o pad do CANTO SUPERIOR ESQUERDO do grid 8x5",
        "Aperte o pad IMEDIATAMENTE A DIREITA dele",
        "Aperte o pad IMEDIATAMENTE ABAIXO do primeiro",
    ]
    notas = []
    with mido.open_input(apc_in) as port:
        for texto in pedidos:
            print(f"\n>> {texto}")
            for msg in port:
                if msg.type == 'note_on' and msg.velocity > 0 and msg.note <= 0x27:
                    print(f"   nota {msg.note} (0x{msg.note:02X}), canal {msg.channel}")
                    notas.append(msg.note)
                    break
    origem = notas[0]
    passo_col = notas[1] - notas[0]
    passo_lin = notas[2] - notas[0]
    layout = dict(origem=origem, passo_col=passo_col, passo_lin=passo_lin)
    with open(LAYOUT_FILE, "w") as f:
        json.dump(layout, f)
    print(f"\nLayout salvo: origem={origem}, +coluna={passo_col}, +linha={passo_lin}")
    print("\nGrid resultante (linha x coluna -> nota):")
    for l in range(5):
        print("  ", " ".join(f"{origem + l*passo_lin + c*passo_col:3}" for c in range(8)))


def carregar_layout():
    if not os.path.exists(LAYOUT_FILE):
        print("Rode 'learn' primeiro."); sys.exit(1)
    with open(LAYOUT_FILE) as f:
        return json.load(f)


def nota_de(layout, linha, coluna):
    return layout["origem"] + linha * layout["passo_lin"] + coluna * layout["passo_col"]


# ─────────────────────────────────────────────────────────────
# Leitura do estado atual da TR-8S
# ─────────────────────────────────────────────────────────────
def ler_bloco(tr_in, tr_out, addr, tamanho=128, timeout=2.0):
    tr_out.send(rq1(addr, tamanho))
    limite = time.time() + timeout
    while time.time() < limite:
        for msg in tr_in.iter_pending():
            if msg.type != 'sysex':
                continue
            d = list(msg.data)
            if len(d) < 12 or d[:6] != HDR or d[6] != DT1:
                continue
            if tuple(d[7:11]) == tuple(addr):
                return d[11:-1]          # dados sem checksum
        time.sleep(0.005)
    return None


def cmd_dump():
    tr_in_n  = achar_porta(mido.get_input_names(), TR8S_MATCH)
    tr_out_n = achar_porta(mido.get_output_names(), TR8S_MATCH)
    if not (tr_in_n and tr_out_n):
        print("Porta TR-8S CTRL nao encontrada. Rode 'ports'."); return
    with mido.open_input(tr_in_n) as tin, mido.open_output(tr_out_n) as tout:
        for i, nome in enumerate(INSTRUMENTOS):
            dados = ler_bloco(tin, tout, addr_bloco(i))
            if dados is None:
                print(f"{nome}: sem resposta"); continue
            print(f"\n{nome}  (addr {' '.join(f'{x:02X}' for x in addr_bloco(i))}, {len(dados)}B)")
            for s in range(16):
                grupo = dados[s*BYTES_P_STEP:(s+1)*BYTES_P_STEP]
                print(f"   step {s+1:2}: " + " ".join(f"{b:02X}" for b in grupo))


def cmd_test():
    """Escreve BD step 1 com velocity 80 e le de volta. Prova a escrita."""
    tr_in_n  = achar_porta(mido.get_input_names(), TR8S_MATCH)
    tr_out_n = achar_porta(mido.get_output_names(), TR8S_MATCH)
    if not (tr_in_n and tr_out_n):
        print("Porta TR-8S CTRL nao encontrada."); return
    addr = addr_bloco(0)   # BD
    with mido.open_input(tr_in_n) as tin, mido.open_output(tr_out_n) as tout:
        antes = ler_bloco(tin, tout, addr)
        if antes is None:
            print("Sem resposta ao RQ1. A TR-8S esta ligada e o TR-EDITOR fechado?")
            return
        print(f"ANTES  step 1: " + " ".join(f"{b:02X}" for b in antes[:8]))

        novo = list(antes)
        atual = (novo[VEL_HI] << 4) | novo[VEL_LO]
        alvo = 0 if atual else VEL_FORTE
        novo[VEL_HI] = (alvo >> 4) & 0x0F
        novo[VEL_LO] = alvo & 0x0F
        print(f"Escrevendo velocity {alvo} no BD step 1...")
        tout.send(dt1(addr, novo))
        time.sleep(0.3)

        depois = ler_bloco(tin, tout, addr)
        if depois is None:
            print("Sem resposta na releitura."); return
        print(f"DEPOIS step 1: " + " ".join(f"{b:02X}" for b in depois[:8]))

        if depois[:8] == novo[:8]:
            print("\n>>> ESCRITA CONFIRMADA. Olhe o painel da TR-8S (TR-REC, BD).")
        elif depois[:8] == antes[:8]:
            print("\n>>> A TR-8S IGNOROU o DT1. Precisamos capturar um SEND do")
            print("    TR-EDITOR pra ver se ha handshake antes da escrita.")
        else:
            print("\n>>> Mudou, mas nao pro valor esperado. Ver bytes acima.")


# ─────────────────────────────────────────────────────────────
# O grid ao vivo
# ─────────────────────────────────────────────────────────────
def cmd_run():
    global VARIACAO
    layout = carregar_layout()
    apc_in_n  = achar_porta(mido.get_input_names(), APC_MATCH)
    apc_out_n = achar_porta(mido.get_output_names(), APC_MATCH)
    tr_in_n   = achar_porta(mido.get_input_names(), TR8S_MATCH)
    tr_out_n  = achar_porta(mido.get_output_names(), TR8S_MATCH)
    if not all([apc_in_n, apc_out_n, tr_in_n, tr_out_n]):
        print("Faltou alguma porta. Rode 'ports'."); return

    with mido.open_input(apc_in_n) as apc_in, \
         mido.open_output(apc_out_n) as apc_out, \
         mido.open_input(tr_in_n) as tr_in, \
         mido.open_output(tr_out_n) as tr_out:

        apc_out.send(APC_INIT)
        time.sleep(0.3)
        for n in range(0x28):                       # limpa os 40 pads
            apc_out.send(mido.Message('note_on', channel=0, note=n, velocity=0))
        time.sleep(0.1)

        pagina = 0          # 0 = steps 1-8, 1 = steps 9-16
        base_inst = 0       # primeira linha visivel (0=BD)
        shift = False       # SHIFT segurado = grava weak beat
        modo = 0            # indice em MODOS

        # cache local dos blocos: o botao altera 1 byte e reenvia o bloco inteiro
        cache = {}
        acc = [0]

        def recarregar():
            for i in range(len(INSTRUMENTOS)):
                cache[i] = ler_bloco(tr_in, tr_out, addr_bloco(i)) or [0] * 128
            cab = ler_bloco(tr_in, tr_out, addr_accent(), 8) or [0] * 8
            acc[0] = nibbles_para_mascara(cab[:4])

        recarregar()
        print(f"Variacao {VARIACOES[VARIACAO-1]} carregada. ACCENT = 0x{acc[0]:04X}")

        def ler_sub(inst, step):
            return cache[inst][step * BYTES_P_STEP + SUB_BYTE]

        def ler_vel(inst, step):
            b = step * BYTES_P_STEP
            return (cache[inst][b + VEL_HI] << 4) | cache[inst][b + VEL_LO]

        def escrever_vel(inst, step, vel):
            b = step * BYTES_P_STEP
            cache[inst][b + VEL_HI] = (vel >> 4) & 0x0F
            cache[inst][b + VEL_LO] = vel & 0x0F

        def pintar():
            for linha in range(5):
                for col in range(8):
                    step = pagina * 8 + col
                    nota = nota_de(layout, linha, col)
                    if linha == 4:                       # linha de baixo = ACCENT
                        cor = COR_ACC if acc[0] & (1 << step) else COR_OFF
                    else:
                        inst = base_inst + linha
                        if inst >= len(INSTRUMENTOS):
                            cor = COR_OFF
                        else:
                            v, sub = ler_vel(inst, step), ler_sub(inst, step)
                            if v == 0:
                                cor = COR_OFF
                            elif sub:
                                cor = COR_SUB_FRACA if v <= 64 else COR_SUB
                            else:
                                cor = COR_FRACA if v <= 64 else COR_ON
                    apc_out.send(mido.Message('note_on', channel=0,
                                              note=nota, velocity=cor))

        def alternar_acc(step):
            acc[0] ^= (1 << step)
            tr_out.send(dt1(addr_accent(), mascara_para_nibbles(acc[0])))
            estado = "ON " if acc[0] & (1 << step) else "OFF"
            print(f"ACC step {step+1:2} -> {estado}   (mascara 0x{acc[0]:04X})")

        def pintar_variacao():
            for i in range(8):
                apc_out.send(mido.Message('note_on', channel=i, note=CLIP_STOP,
                                          velocity=1 if i == VARIACAO - 1 else 0))

        def pintar_modos():
            for i, nota in enumerate(SCENE_NOTAS):
                apc_out.send(mido.Message('note_on', channel=0, note=nota,
                                          velocity=3 if i == modo else 0))

        def alternar(inst, step, fraco=False):
            """Sem shift: off <-> forte. Com shift: off <-> fraco.
            O tipo (normal/flam/sub) vem do modo escolhido nos SCENE LAUNCH."""
            b = step * BYTES_P_STEP
            atual = ler_vel(inst, step)
            alvo  = 0 if atual else (VEL_FRACA if fraco else VEL_FORTE)
            escrever_vel(inst, step, alvo)
            cache[inst][b + SUB_BYTE] = 0 if alvo == 0 else MODOS[modo][1]
            tr_out.send(dt1(addr_step(inst, step), cache[inst][b:b + BYTES_P_STEP]))
            if alvo == 0:
                desc = "OFF"
            else:
                desc = f"vel {alvo}" + ("" if modo == 0 else f" + {MODOS[modo][0]}")
            print(f"{INSTRUMENTOS[inst]:3} step {step+1:2} -> {desc}")

        pintar()
        pintar_modos()
        pintar_variacao()
        print(f"Pronto. Steps {pagina*8+1}-{pagina*8+8} | linhas a partir de "
              f"{INSTRUMENTOS[base_inst]}\n"
              "  pad          = liga/desliga forte (vel 80)\n"
              "  SHIFT + pad  = liga/desliga fraco (vel 50)\n"
              "  linha 5      = ACCENT (liga/desliga, sem dinamica)\n"
              "  SCENE 1-5    = NORMAL / FLAM / SUB 1-2 / 1-3 / 1-4\n"
              "  CLIP STOP1-8 = variacao A-H\n"
              "  UP / DOWN    = rola os instrumentos\n"
              "  LEFT / RIGHT = alterna steps 1-8 / 9-16\n"
              "  Ctrl+C       = sair")

        for msg in apc_in:
            if msg.type in ('note_on', 'note_off') and msg.note == 0x62:   # SHIFT
                shift = (msg.type == 'note_on' and msg.velocity > 0)
                continue
            if msg.type != 'note_on' or msg.velocity == 0:
                continue
            n = msg.note
            if n == 0x5E:                       # UP
                base_inst = max(0, base_inst - 1); pintar(); continue
            if n == 0x5F:                       # DOWN
                base_inst = min(len(INSTRUMENTOS) - LINHAS_INST, base_inst + 1); pintar(); continue
            if n in (0x60, 0x61):               # RIGHT / LEFT
                pagina = 1 - pagina; pintar()
                print(f"steps {pagina*8+1}-{pagina*8+8}"); continue
            if n == CLIP_STOP:                  # CLIP STOP 1-8 = variacao A-H
                VARIACAO = msg.channel + 1
                recarregar(); pintar(); pintar_variacao()
                print(f"variacao {VARIACOES[VARIACAO-1]}  "
                      f"(selecione a mesma na TR-8S pra ouvir)")
                continue
            if n in SCENE_NOTAS:                # SCENE LAUNCH = modo de escrita
                modo = SCENE_NOTAS.index(n); pintar_modos()
                print(f"modo: {MODOS[modo][0]}"); continue
            # pads do grid
            for linha in range(5):
                for col in range(8):
                    if nota_de(layout, linha, col) == n:
                        step = pagina * 8 + col
                        if linha == 4:
                            alternar_acc(step)
                        else:
                            inst = base_inst + linha
                            if inst < len(INSTRUMENTOS):
                                alternar(inst, step, fraco=shift)
                        pintar()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"ports": cmd_ports, "learn": cmd_learn, "dump": cmd_dump,
     "test": cmd_test, "run": cmd_run}.get(cmd, lambda: print(__doc__))()
