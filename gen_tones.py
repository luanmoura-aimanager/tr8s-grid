#!/usr/bin/env python3
"""
gen_tones.py - gera o tones.py a partir da tabela do proprio TR-EDITOR.

POR QUE NAO SAI MAIS DO PDF
A primeira versao lia a "Preset INST Tone List" do PDF e supunha
id = posicao na lista. O PDF agrupa por CATEGORIA (todos os BD, depois todos
os SD...), e a maquina NAO numera assim - ela numera por maquina de origem,
com buracos. O erro so apareceu em hardware, em 15/08/2026: o Luan escolheu
"707 Bass1/2" (posicao 8 na lista do PDF) e a TR-8S carregou "808 High Tom".

A tabela certa estava dentro do TR-EDITOR o tempo todo:
    /Applications/Roland/TR Editor.app/Contents/Resources/Script/
        ToneDetailsConfigTable.dat
E um CSV com NUMBER, CATEGORY, TYPE, NAME e a maquina de origem.

    id SysEx = NUMBER - 1

Provado contra 22 tone ids lidos da propria maquina (os 11 instrumentos do
kit 001 TR-808 e os 11 do kit 003 TR-707): 22/22. Ver REFERENCIA 2.9.

    python3 gen_tones.py            gera o tones.py
    python3 gen_tones.py --conferir so valida, nao escreve
"""
import csv
import io
import os
import sys

FONTE = ("/Applications/Roland/TR Editor.app/Contents/Resources/Script/"
         "ToneDetailsConfigTable.dat")
COPIA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "capturas", "ToneDetailsConfigTable.dat")
SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tones.py")

# tone ids lidos da maquina, para o gerador se auto-conferir
CONFERENCIA = {
    "TR-808": [1, 5, 6, 7, 8, 15, 17, 21, 22, 23, 25],
    "TR-707": [42, 44, 46, 47, 48, 49, 51, 53, 54, 55, 56],
}

CABECALHO = '''"""
tones.py - a lista de tones da TR-8S, gerada por gen_tones.py.

NAO EDITAR NA MAO.

Fonte: ToneDetailsConfigTable.dat, de dentro do TR-EDITOR. O id de SysEx e o
NUMBER da tabela MENOS UM - provado contra os 22 tone ids lidos dos kits
TR-808 e TR-707 da maquina do Luan (REFERENCIA 2.9).

Os ids NAO sao contiguos: a Roland deixa buracos entre as familias. Por isso
isto e uma lista de tuplas com o id dentro, e nao uma lista indexada por
posicao - foi confundir as duas coisas que carregou o tone errado em
15/08/2026.

    (id, categoria, nome, tipo, maquina)
"""

'''


def ler():
    caminho = FONTE if os.path.exists(FONTE) else COPIA
    if not os.path.exists(caminho):
        print(f"(!) nao achei a tabela nem em {FONTE}\n    nem em {COPIA}")
        return None, None
    with open(caminho, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(io.StringIO(f.read())))
    saida = []
    for l in linhas:
        try:
            num = int(l["NUMBER"])
        except (KeyError, ValueError):
            continue
        saida.append((num - 1, l["CATEGORY"].strip(), l["NAME"].strip(),
                      l["TYPE"].strip(), (l.get("DESCRIPTION1") or "").strip()))
    return sorted(saida), caminho


def conferir(tones):
    porid = {t[0]: t for t in tones}
    tudo_ok = True
    for maquina, ids in CONFERENCIA.items():
        erros = [i for i in ids
                 if not (porid.get(i) and porid[i][4] == maquina)]
        ok = len(ids) - len(erros)
        print(f"  {maquina}: {ok}/{len(ids)} tone ids batem com a maquina")
        if erros:
            tudo_ok = False
            for i in erros:
                e = porid.get(i)
                print(f"    (!) id {i} -> {e[2] if e else 'inexistente'} "
                      f"({e[4] if e else '?'})")
    return tudo_ok


def escrever(tones):
    with open(SAIDA, "w") as f:
        f.write(CABECALHO)
        f.write("TONES = [\n")
        for t in tones:
            f.write(f"    ({t[0]}, {t[1]!r}, {t[2]!r}, {t[3]!r}, {t[4]!r}),\n")
        f.write("]\n\n")
        f.write("POR_ID = {t[0]: t for t in TONES}\n\n\n")
        f.write("def nome(tone_id):\n")
        f.write('    """Nome do tone, ou None se o id nao existe."""\n')
        f.write("    t = POR_ID.get(tone_id)\n")
        f.write("    return t[2] if t else None\n")
    print(f"escrito: {SAIDA}  ({len(tones)} tones)")


if __name__ == "__main__":
    tones, caminho = ler()
    if not tones:
        sys.exit(1)
    print(f"lido de {caminho}: {len(tones)} tones, "
          f"ids {tones[0][0]}..{tones[-1][0]}")
    ok = conferir(tones)
    if not ok:
        print("(!) a conferencia falhou - NAO vou escrever com a regra errada")
        sys.exit(1)
    if "--conferir" in sys.argv:
        sys.exit(0)
    os.makedirs(os.path.dirname(COPIA), exist_ok=True)
    if caminho == FONTE:
        import shutil
        shutil.copy2(FONTE, COPIA)
        print(f"copia guardada em {COPIA}")
    escrever(tones)
