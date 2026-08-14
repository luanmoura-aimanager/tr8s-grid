#!/usr/bin/env python3
"""
apagar_luzes.py - apaga todos os LEDs dos Launchpad Mini MK3 conectados

Uso:
    python3 apagar_luzes.py          # apaga tudo e deixa em programmer mode
    python3 apagar_luzes.py --sair   # apaga e volta pro modo Session de fabrica

Independente do 'learn': nao le o layout salvo, nao precisa saber qual aparelho e
qual. Varre todas as saidas Launchpad por indice e apaga cada uma.

Por que ficar em programmer mode (padrao): ao sair dele o aparelho volta pro modo
Session, que acende a iluminacao propria dele. Programmer mode com tudo em zero e
o unico estado realmente escuro.
"""
import sys, time
import mido
import rtmidi

LP_MATCH = "Launchpad"
PROG_ON  = mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01])
PROG_OFF = mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x00])

# programmer mode: pads = nota linha*10+coluna, linha e coluna de 1 a 8
NOTAS_PAD = [l * 10 + c for l in range(1, 9) for c in range(1, 9)]
# fileira de funcao, coluna de cena e o logo
CCS = list(range(91, 99)) + [89, 79, 69, 59, 49, 39, 29, 19] + [99]


def saidas_launchpad():
    """[(indice, nome)] - por indice, porque dois aparelhos tem nome identico."""
    rt = rtmidi.MidiOut()
    try:
        return [(i, n) for i, n in enumerate(rt.get_ports())
                if LP_MATCH.lower() in n.lower()]
    finally:
        rt.delete()


def apagar(idx, sair=False):
    rt = rtmidi.MidiOut()
    rt.open_port(idx)
    try:
        rt.send_message(PROG_ON.bytes())
        time.sleep(0.05)
        for nota in NOTAS_PAD:
            rt.send_message([0x90, nota, 0])          # note_on velocity 0
        for cc in CCS:
            rt.send_message([0xB0, cc, 0])            # control_change value 0
        if sair:
            time.sleep(0.05)
            rt.send_message(PROG_OFF.bytes())
    finally:
        rt.close_port()
        rt.delete()


def main():
    sair = "--sair" in sys.argv
    portas = saidas_launchpad()
    if not portas:
        print("Nenhum Launchpad encontrado. Esta conectado?")
        return 1
    for idx, nome in portas:
        try:
            apagar(idx, sair)
            print(f"apagado  [{idx}] {nome}")
        except Exception as e:
            print(f"falhou   [{idx}] {nome}: {e}")
    print(f"\n{len(portas)} porta(s) varrida(s), "
          f"{len(NOTAS_PAD)} pads + {len(CCS)} botoes cada.")
    if sair:
        print("Aparelhos devolvidos ao modo Session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
