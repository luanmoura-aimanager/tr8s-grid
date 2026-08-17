#!/usr/bin/env python3
"""
instalar_hooks.py - liga os hooks de git versionados deste repositorio.

Os hooks moram em `.githooks/` (versionado) em vez de `.git/hooks/` (que nao vai
para o repositorio, entao um clone novo nasceria sem eles). O `core.hooksPath` e
config LOCAL do clone: por isso este script precisa rodar uma vez por clone, e
por isso ele nao pode ser um hook.

    python3 instalar_hooks.py            liga
    python3 instalar_hooks.py --estado   diz se estao ligados
    python3 instalar_hooks.py --remover   desliga

O que fica ligado:
  pre-commit  recusa commit direto na main
  pre-push    roda `python3 testes.py`; falhou, nao empurra
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA = ".githooks"
HOOKS = ("pre-commit", "pre-push")


def _git(*args):
    return subprocess.run(["git", "-C", AQUI, *args],
                          capture_output=True, text=True)


def estado():
    r = _git("config", "--get", "core.hooksPath")
    atual = r.stdout.strip()
    if atual == PASTA:
        print(f"hooks LIGADOS (core.hooksPath = {atual})")
        for h in HOOKS:
            caminho = os.path.join(AQUI, PASTA, h)
            if not os.path.exists(caminho):
                nota = "(!) nao existe"
            elif not os.access(caminho, os.X_OK):
                nota = "(!) sem permissao de execucao"
            else:
                nota = "ok"
            print(f"  {h:12} {nota}")
        return 0
    print(f"hooks DESLIGADOS (core.hooksPath = {atual or 'nao definido'})")
    print("Ligue com: python3 instalar_hooks.py")
    return 1


def instalar():
    faltando = [h for h in HOOKS
                if not os.path.exists(os.path.join(AQUI, PASTA, h))]
    if faltando:
        print(f"(!) nao achei em {PASTA}/: {', '.join(faltando)}")
        return 1
    for h in HOOKS:                      # o modo nao sobrevive a todo clone
        os.chmod(os.path.join(AQUI, PASTA, h), 0o755)
    r = _git("config", "core.hooksPath", PASTA)
    if r.returncode:
        print(f"(!) git config falhou: {r.stderr.strip()}")
        return 1
    print(f"hooks ligados: {PASTA}/{', '.join(HOOKS)}")
    print("  pre-commit  recusa commit direto na main")
    print("  pre-push    roda os testes de mesa")
    print("Escapar de um deles, quando voce sabe: --no-verify")
    return 0


def remover():
    _git("config", "--unset", "core.hooksPath")
    print("hooks desligados (core.hooksPath removido)")
    return 0


if __name__ == "__main__":
    if "--estado" in sys.argv:
        sys.exit(estado())
    if "--remover" in sys.argv:
        sys.exit(remover())
    sys.exit(instalar())
