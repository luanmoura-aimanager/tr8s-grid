#!/usr/bin/env python3
"""
instalar_agente.py - deixa o servidor sempre no ar, para o app da Dock abrir
sozinho.

POR QUE ISTO EXISTE
O "Adicionar a Dock" do Safari cria um app que abre uma URL. Se ninguem
subiu o servidor, a janela abre no vazio - foi o que aconteceu. O .app do
Desktop resolve, mas ai sao dois cliques em dois lugares.

POR QUE E SEGURO DEIXAR NO AR
O servidor NAO abre porta MIDI nenhuma sozinho: o Motor (que segura os dois
Launchpad e a porta CTRL) so nasce quando alguem aperta ON na tela. Com o
motor desligado, este processo e so um servidor HTTP parado em 127.0.0.1,
gastando ~20 MB. O TR-EDITOR continua abrindo normalmente - basta o motor
estar em off, como ja e preciso hoje.

POR QUE ELE RODA UMA COPIA, E NAO O CODIGO DO PROJETO
O projeto vive em ~/Documents, e o macOS (TCC) NAO deixa um LaunchAgent ler
nada de la: a primeira versao deste script apontou para o servidor.py do
projeto e o log so dizia "Operation not permitted". Por isso o instalador
copia os scripts para ~/Library/Application Support/tr8s-grid/, onde o
launchd chega sem pedir permissao a ninguem.

Consequencia pratica, a mesma do .app: DEPOIS DE EDITAR o codigo, rodar
este script de novo. Ele copia por cima e reinicia o agente.

    python3 instalar_agente.py            instala (ou atualiza) e liga
    python3 instalar_agente.py --remover  desliga e desinstala
    python3 instalar_agente.py --estado   diz se esta rodando
"""
import os
import shutil
import subprocess
import sys
import time

ROTULO = "com.luanmoura.tr8s-grid"
AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.expanduser("~/Library/Application Support/tr8s-grid")
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{ROTULO}.plist")
LOG = os.path.expanduser("~/Library/Logs/tr8s-grid-agente.log")
PYTHONPATH = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")

# os mesmos do criar_app.py, mais o diretorio web/
ARQUIVOS = ("servidor.py", "pagina.html", "lp_tr8s.py", "apagar_luzes.py",
            "biblioteca.py", "ferramentas.py", "tones.py", "efeitos.py")


def copiar():
    os.makedirs(DESTINO, exist_ok=True)
    for nome in ARQUIVOS:
        orig = os.path.join(AQUI, nome)
        if os.path.exists(orig):
            shutil.copy2(orig, os.path.join(DESTINO, nome))
    web_orig, web_dest = os.path.join(AQUI, "web"), os.path.join(DESTINO, "web")
    if os.path.isdir(web_orig):
        shutil.rmtree(web_dest, ignore_errors=True)
        shutil.copytree(web_orig, web_dest)
    return os.path.join(DESTINO, "servidor.py")

MODELO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{rotulo}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
    <string>--sem-abrir</string>
  </array>
  <key>WorkingDirectory</key><string>{aqui}</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>{pypath}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
"""


def _uid():
    return os.getuid()


def instalar():
    if not os.path.exists(os.path.join(AQUI, "servidor.py")):
        print(f"(!) nao achei o servidor.py em {AQUI}")
        return 1
    alvo = copiar()
    print(f"scripts copiados para {DESTINO}")
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "w") as f:
        f.write(MODELO.format(rotulo=ROTULO, python=sys.executable,
                              script=alvo, aqui=DESTINO, pypath=PYTHONPATH,
                              log=LOG))
    # bootout antes: se ja estava carregado, recarrega com a versao nova.
    # O bootout retorna ANTES de o processo antigo morrer, e o bootstrap em
    # cima disso falha com "Input/output error" - dai o retry com pausa
    # (aconteceu de verdade em 16/08/2026 e deixou o agente desinstalado).
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{ROTULO}"],
                   capture_output=True)
    r = None
    for tentativa in range(5):
        time.sleep(1.0 if tentativa else 0.5)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{_uid()}", PLIST],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    if r is None or r.returncode:
        print(f"(!) launchctl bootstrap falhou: {r.stderr.strip()}")
        return 1
    print(f"agente instalado: {PLIST}")
    print(f"log: {LOG}")
    print("o servidor sobe agora e a cada login. O app da Dock ja funciona.")
    print("motor desligado = nenhuma porta MIDI ocupada (TR-EDITOR livre).")
    print("ATENCAO: ele roda a COPIA. Depois de editar, rode este script "
          "de novo.")
    return 0


def remover():
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{ROTULO}"],
                   capture_output=True)
    try:
        os.remove(PLIST)
    except OSError:
        pass
    print("agente removido. O icone do Desktop continua funcionando.")
    return 0


def estado():
    r = subprocess.run(["launchctl", "print", f"gui/{_uid()}/{ROTULO}"],
                       capture_output=True, text=True)
    if r.returncode:
        print("agente NAO instalado")
        return 1
    for linha in r.stdout.splitlines():
        if any(k in linha for k in ("state =", "pid =", "last exit")):
            print("  " + linha.strip())
    return 0


if __name__ == "__main__":
    if "--remover" in sys.argv:
        sys.exit(remover())
    if "--estado" in sys.argv:
        sys.exit(estado())
    sys.exit(instalar())
