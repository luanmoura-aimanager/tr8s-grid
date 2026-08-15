#!/usr/bin/env python3
"""
gen_tones.py - extrai a Preset INST Tone List do PDF da Roland e gera tones.py.

Uso:  python3 gen_tones.py          (precisa do TR-8S_PresetToneList_eng04_W.pdf
                                     na pasta e do fitz/PyMuPDF no PYTHONPATH)

O PDF nao tem coluna de numero. A HIPOTESE de id (registrada em tones.py e na
REFERENCIA 2.9) e que o id do tone e a posicao nesta lista, porque o mapa do
ARIA diz que os tones de usuario ocupam 624-1023 - sobrando o comeco para os
presets, e a Roland lista na ordem do indice em toda documentacao dela. Se a
sessao de hardware mostrar offset (0-based vs 1-based ou buracos), o ajuste e
um numero so: BASE_ID em tones.py.

Tres linhas do PDF vem quebradas pelo extrator de texto (nome colado no tipo,
nome partido em duas linhas, rodape de copyright); o parser trata as tres.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz

PDF = "TR-8S_PresetToneList_eng04_W.pdf"
TIPOS = {"ACB", "FM", "SAMPLE"}
LIXO = {"Category", "Name", "Type"}


def extrair():
    d = fitz.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), PDF))
    toks = []
    for p in d:
        for linha in p.get_text().splitlines():
            t = linha.strip()
            if (not t or t in LIXO or t.isdigit()
                    or "Preset INST Tone List" in t or "ROLAND" in t):
                continue
            toks.append(t)

    tones, i = [], 0
    while i < len(toks):
        cat = toks[i]
        # caso normal: cat / nome / tipo em tres tokens
        if i + 2 < len(toks) and toks[i+2] in TIPOS:
            tones.append((cat, toks[i+1].rstrip(), toks[i+2]))
            i += 3
            continue
        # nome com o tipo colado na mesma linha ("... OHC ACB")
        m = re.match(r"(.+)\s+(ACB|FM|SAMPLE)$", toks[i+1] if i + 1 < len(toks)
                     else "")
        if m:
            tones.append((cat, m.group(1).rstrip(), m.group(2)))
            i += 2
            continue
        # nome partido em duas linhas ("727OpHiConga/" + "MHC" + "ACB")
        if i + 3 < len(toks) and toks[i+3] in TIPOS:
            tones.append((cat, (toks[i+1] + toks[i+2]).rstrip(), toks[i+3]))
            i += 4
            continue
        raise SystemExit(f"token fora do padrao na posicao {i}: {toks[i:i+4]}")
    return tones


def escrever(tones):
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "tones.py")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write('"""\n'
                "tones.py - Preset INST Tone List da TR-8S (Ver.3.00), "
                "gerado por gen_tones.py.\n\n"
                "NAO EDITAR NA MAO - regenerar com python3 gen_tones.py.\n\n"
                "ID = BASE_ID + posicao na lista. E HIPOTESE (REFERENCIA 2.9):\n"
                "o PDF nao numera; a base veio de o ARIA reservar 624-1023 aos\n"
                "tones de usuario. A sessao de hardware confirma ou corrige -\n"
                "se houver offset, mexer SO em BASE_ID.\n"
                '"""\n\n'
                "BASE_ID = 0     # hipotese: primeiro preset = id 0\n\n"
                "TONES = [\n")
        for cat, nome, tipo in tones:
            f.write(f"    ({cat!r}, {nome!r}, {tipo!r}),\n")
        f.write("]\n\n\n"
                "def tone_id(pos):\n"
                "    return BASE_ID + pos\n\n\n"
                "def nome_do_id(tid):\n"
                '    """Nome pela hipotese de id, ou None se fora da lista."""\n'
                "    pos = tid - BASE_ID\n"
                "    if 0 <= pos < len(TONES):\n"
                "        cat, nome, tipo = TONES[pos]\n"
                "        return f\"{nome} ({cat} {tipo})\"\n"
                "    return None\n\n\n"
                "def por_categoria():\n"
                "    grupos = {}\n"
                "    for pos, (cat, nome, tipo) in enumerate(TONES):\n"
                "        grupos.setdefault(cat, []).append((pos, nome, tipo))\n"
                "    return grupos\n")
    return caminho


if __name__ == "__main__":
    tones = extrair()
    cats = {}
    for c, _, _ in tones:
        cats[c] = cats.get(c, 0) + 1
    caminho = escrever(tones)
    print(f"{len(tones)} tones em {len(cats)} categorias -> {caminho}")
    print("categorias:", ", ".join(f"{c}({n})" for c, n in cats.items()))
