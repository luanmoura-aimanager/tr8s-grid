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
    # core.hooksPath substitui o diretorio de hooks INTEIRO: o que estiver em
    # .git/hooks (git-lfs, ferramenta de editor, hook de outra ferramenta) para
    # de rodar a partir daqui. Avisar e o minimo - apontado na revisao de
    # 17/08/2026
    atual = _git("config", "--get", "core.hooksPath").stdout.strip()
    if atual and atual != PASTA:
        print(f"(!) core.hooksPath ja apontava para '{atual}' - vou "
              f"substituir por '{PASTA}'")
    proprios = [h for h in os.listdir(os.path.join(AQUI, ".git", "hooks"))
                if not h.endswith(".sample")] if os.path.isdir(
                    os.path.join(AQUI, ".git", "hooks")) else []
    if proprios:
        print(f"(!) ha hooks em .git/hooks que PARAM de rodar agora: "
              f"{', '.join(sorted(proprios))}")
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
    """Desliga. Confere de verdade em vez de anunciar sucesso no escuro.

    O `--unset` sai com 5 quando a chave nao existe, e o escopo LOCAL nao
    alcanca um core.hooksPath definido em --global ou --system: nos dois casos
    a versao anterior imprimia "removido" e o usuario saia achando que tinha
    desligado. Apontado na revisao de 17/08/2026."""
    r = _git("config", "--unset", "core.hooksPath")
    if r.returncode == 5:
        print("core.hooksPath ja nao estava definido neste clone")
    elif r.returncode:
        print(f"(!) git config --unset falhou: {r.stderr.strip()}")
        return 1
    restante = _git("config", "--get", "core.hooksPath").stdout.strip()
    if restante:
        print(f"(!) ainda ha core.hooksPath = {restante} (vem de --global ou "
              "--system; o --unset local nao alcanca)")
        return 1
    print("hooks desligados (core.hooksPath removido)")
    return 0


if __name__ == "__main__":
    if "--estado" in sys.argv:
        sys.exit(estado())
    if "--remover" in sys.argv:
        sys.exit(remover())
    sys.exit(instalar())
