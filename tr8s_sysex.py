#!/usr/bin/env python3
"""
tr8s_sysex.py - parser e diff de capturas SysEx da TR-8S (MIDI Monitor)

Uso:
    python3 tr8s_sysex.py parse  get_vazio.txt
    python3 tr8s_sysex.py diff   send_vazio.txt send_bd1.txt
    python3 tr8s_sysex.py fx     sniff_tr_editor.mmon

Aceita dois formatos:
  - texto colado do MIDI Monitor (Cmd+A, Cmd+C, colar em .txt)
  - o arquivo .mmon salvo pelo proprio MIDI Monitor (binary plist /
    NSKeyedArchiver) - e o formato das 4 capturas do repo TR-8S-SysEx,
    que guardam o trafego do site ARIA com o mapa oficial da Roland
"""
import plistlib, re, sys
from collections import OrderedDict

ROLAND_HDR = [0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x45]

# endereços de keep-alive (o editor pergunta "ainda tá aí?" a cada 3s)
KEEPALIVE = {(0x00, 0x03, 0x00, 0x3B), (0x00, 0x03, 0x00, 0x36)}

CMD = {0x11: "RQ1(ler)", 0x12: "DT1(escrever)"}


def checksum(addr, data):
    """Checksum Roland: 128 - (soma mod 128), mod 128."""
    return (128 - (sum(addr) + sum(data)) % 128) % 128


def parse_line(line):
    """Extrai uma mensagem SysEx de uma linha do log do MIDI Monitor."""
    m = re.search(r'((?:[0-9A-Fa-f]{2}\s+){10,}[0-9A-Fa-f]{2})', line)
    if not m:
        return None
    b = [int(x, 16) for x in m.group(1).split()]
    if b[:7] != ROLAND_HDR or b[-1] != 0xF7:
        return None
    direction = "TX" if "To " in line else "RX"
    cmd = b[7]
    addr = tuple(b[8:12])
    body = b[12:-2]           # dados (sem checksum e sem F7)
    chk = b[-2]
    ok = chk == checksum(addr, body)
    return dict(dir=direction, cmd=cmd, addr=addr, data=body, chk_ok=ok)


def load_mmon(path, keep_alive=False):
    """Le o .mmon do MIDI Monitor: plist externo com 'messageData', que e um
    NSKeyedArchiver; cada mensagem tem statusByte, data (payload SEM F0/F7,
    checksum incluso) e originatingEndpoint ('To ...' = TX, 'From ...' = RX).
    Formato conferido nas capturas do TR-8S-SysEx em 14/08/2026."""
    with open(path, "rb") as f:
        inner = plistlib.loads(plistlib.load(f)["messageData"])
    objs = inner["$objects"]

    def deref(u):
        return objs[u.data] if isinstance(u, plistlib.UID) else u

    msgs = []
    for o in objs:
        if not (isinstance(o, dict) and o.get("statusByte") == 0xF0):
            continue
        bruto = deref(o["data"])
        b = list(bruto["NS.data"] if isinstance(bruto, dict) else bruto)
        if b[:6] != ROLAND_HDR[1:] or len(b) < 12:
            continue                       # outro fabricante ou curta demais
        ep = deref(o.get("originatingEndpoint", ""))
        direction = "TX" if str(ep).startswith("To ") else "RX"
        addr = tuple(b[7:11])
        if not keep_alive and addr in KEEPALIVE:
            continue
        body, chk = b[11:-1], b[-1]
        msgs.append(dict(dir=direction, cmd=b[6], addr=addr, data=body,
                         chk_ok=chk == checksum(addr, body)))
    return msgs


def load(path, keep_alive=False):
    if path.lower().endswith(".mmon"):
        return load_mmon(path, keep_alive)
    msgs = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            msg = parse_line(line)
            if not msg:
                continue
            if not keep_alive and msg["addr"] in KEEPALIVE:
                continue
            msgs.append(msg)
    return msgs


def fmt_addr(a):
    return " ".join(f"{x:02X}" for x in a)


def cmd_parse(path):
    msgs = load(path)
    bad = sum(1 for m in msgs if not m["chk_ok"])
    print(f"{path}: {len(msgs)} mensagens (keep-alive removido), "
          f"{bad} com checksum inválido\n")
    for m in msgs:
        n = len(m["data"])
        preview = " ".join(f"{x:02X}" for x in m["data"][:12])
        flag = "" if m["chk_ok"] else "  <-- CHECKSUM RUIM"
        print(f"{m['dir']} {CMD.get(m['cmd'], hex(m['cmd'])):14} "
              f"addr {fmt_addr(m['addr'])}  {n:4}B  {preview}{'...' if n > 12 else ''}{flag}")


def index_by_addr(msgs, cmd=None):
    """Junta os dados por endereço (última ocorrência vence)."""
    out = OrderedDict()
    for m in msgs:
        if cmd and m["cmd"] != cmd:
            continue
        if not m["data"]:
            continue
        out[m["addr"]] = m["data"]
    return out


def cmd_diff(p1, p2):
    a = index_by_addr(load(p1))
    b = index_by_addr(load(p2))

    only_a = [k for k in a if k not in b]
    only_b = [k for k in b if k not in a]
    if only_a:
        print(f"Só em {p1}: {', '.join(fmt_addr(k) for k in only_a)}")
    if only_b:
        print(f"Só em {p2}: {', '.join(fmt_addr(k) for k in only_b)}")

    achou = False
    for addr in a:
        if addr not in b:
            continue
        d1, d2 = a[addr], b[addr]
        if d1 == d2:
            continue
        achou = True
        print(f"\n### addr {fmt_addr(addr)}  ({len(d1)} bytes)")
        for i, (x, y) in enumerate(zip(d1, d2)):
            if x == y:
                continue
            # 128 bytes = 16 steps x 8 bytes -> traduz offset em step/campo
            step, campo = divmod(i, 8)
            extra = f"   -> step {step+1:2}, byte {campo}" if len(d1) == 128 else ""
            print(f"  offset {i:4} (0x{i:03X}): {x:02X} -> {y:02X}{extra}")
        if len(d2) > len(d1):
            print(f"  (+{len(d2)-len(d1)} bytes extras no segundo arquivo)")

    if not achou:
        print("\nNenhuma diferença de dados entre endereços comuns.")


def cmd_fx(path):
    """Decodifica uma sessao de sniff do TR-EDITOR (REFERENCIA 7.2, M2).

    O editor manda um DT1 a cada mexida de knob. Mexendo UM controle por vez,
    a ordem cronologica das mudancas casa com a ordem em que voce mexeu - e
    cada linha aqui vira uma entrada de offset no efeitos.py.

    Agrupa por (endereco de bloco, offset) e mostra a faixa de valores vista:
    parametro de 2 bytes aparece como DOIS offsets vizinhos mexendo juntos."""
    msgs = [m for m in load(path) if m["cmd"] == 0x12]     # so escrita
    if not msgs:
        print("nenhum DT1 na captura (so RQ1?)"); return

    # o editor escreve o bloco inteiro as vezes; o que interessa e a MUDANCA
    anterior, eventos = {}, []
    for m in msgs:
        chave = m["addr"]
        antes = anterior.get(chave)
        if antes is not None and len(antes) == len(m["data"]):
            difs = [(i, a, b) for i, (a, b) in enumerate(zip(antes, m["data"]))
                    if a != b]
            if difs and len(difs) <= 4:
                eventos.append((chave, difs))
        elif len(m["data"]) <= 4:
            # escrita curta: o proprio endereco ja aponta o offset
            eventos.append((chave, [(0, None, m["data"][0])]))
        anterior[chave] = list(m["data"])

    if not eventos:
        print(f"{len(msgs)} DT1, mas nenhuma MUDANCA de valor detectada.\n"
              "Dica: limpe o MIDI Monitor DEPOIS que o TR-EDITOR terminar de "
              "ler a maquina, senao a leitura inicial domina a captura.")
        return

    print(f"{len(msgs)} DT1, {len(eventos)} mudancas, na ordem em que voce "
          "mexeu:\n")
    print(f"{'#':>3}  {'endereco':<12} {'offset':>6}  valor")
    for n, (addr, difs) in enumerate(eventos, 1):
        offs = ", ".join(str(o) for o, _, _ in difs)
        vals = ", ".join(f"{b:02X}" for _, _, b in difs)
        marca = "  (2 bytes)" if len(difs) == 2 and \
            difs[1][0] == difs[0][0] + 1 else ""
        print(f"{n:>3}  {fmt_addr(addr):<12} {offs:>6}  {vals}{marca}")

    print("\nAgora me mande esta saida junto com a lista do que voce mexeu, "
          "na mesma ordem.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "parse":
        cmd_parse(sys.argv[2])
    elif sys.argv[1] == "fx":
        cmd_fx(sys.argv[2])
    elif sys.argv[1] == "diff" and len(sys.argv) >= 4:
        cmd_diff(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
