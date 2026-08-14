#!/usr/bin/env python3
"""
tr8s_sysex.py - parser e diff de capturas SysEx da TR-8S (MIDI Monitor)

Uso:
    python3 tr8s_sysex.py parse  get_vazio.txt
    python3 tr8s_sysex.py diff   send_vazio.txt send_bd1.txt

Espera o texto colado do MIDI Monitor (Cmd+A, Cmd+C, colar em .txt).
"""
import re, sys
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


def load(path, keep_alive=False):
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


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "parse":
        cmd_parse(sys.argv[2])
    elif sys.argv[1] == "diff" and len(sys.argv) >= 4:
        cmd_diff(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
