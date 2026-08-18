#!/usr/bin/env python3
"""
lp_tr8s.py - dois Launchpad Mini MK3 como grid 16x8 escrevendo na TR-8S via SysEx

Requisitos:
    mido + python-rtmidi ja instalados em ~/Library/Python/3.9/
    (NAO usar --break-system-packages: o pip 3.9 e 21.2.4 e nao suporta)

Comandos (nesta ordem, na primeira vez):
    python3 lp_tr8s.py ports     # lista as portas MIDI com indice
    python3 lp_tr8s.py learn     # descobre esquerdo/direito e a rotacao de cada um
    python3 lp_tr8s.py probe     # imprime tudo que chega (pra conferir os botoes)
    python3 lp_tr8s.py colors    # mostra a paleta de cores nos pads
    python3 lp_tr8s.py dump      # le o pattern atual da TR-8S
    python3 lp_tr8s.py run       # o grid ao vivo
    python3 lp_tr8s.py standby [ambiente]   # so as ondas; nao precisa da TR-8S

Engenharia reversa do que ainda falta no protocolo:
    python3 lp_tr8s.py sniff             # escuta SysEx na porta CTRL
    python3 lp_tr8s.py escutar           # escuta TUDO na porta comum (notas, CC)
    python3 lp_tr8s.py varrer  mapa.json # que enderecos a maquina reconhece
    python3 lp_tr8s.py snap  base.json [--amplo mapa.json]
    python3 lp_tr8s.py snapdiff a.json b.json

    O roteiro de captura do MUTE:
      varrer mapa.json
      snap m0.json  --amplo mapa.json          # base
      snap m0b.json --amplo mapa.json          # sem tocar em nada
      snapdiff m0.json m0b.json                # <- piso de ruido, faca sempre
      (segurar [MUTE] + [BD])
      snap m1.json  --amplo mapa.json
      snapdiff m0.json m1.json

Protocolo da TR-8S decifrado empiricamente em 08/08/2026.

PORTAS POR INDICE, NAO POR NOME
    Dois Launchpad Mini MK3 expoem quatro portas com nomes IDENTICOS. O mido nao
    consegue enderecar as duas segundas:
      - mido.get_devices() deduplica por nome  (backends/rtmidi.py: 'if name not
        in devices'), entao get_input_names() devolve 3 portas em vez de 5;
      - mido.open_input(nome) faz port_names.index(nome), que sempre casa com a
        PRIMEIRA ocorrencia - as duas portas DAW abririam o mesmo aparelho.
    Por isso este arquivo enumera e abre tudo via rtmidi cru, por indice, e usa
    mido apenas para montar/parsear mensagens. Verificado em 13/08/2026: as 4
    entradas abrem simultaneamente.
"""
import sys, time, json, os, math, random, threading, queue, collections
import mido
import rtmidi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import efeitos

APC_TIMEOUT = 2.0
LAYOUT_FILE = os.path.expanduser("~/.lp_tr8s_layout.json")
ESTADO_FILE = os.path.expanduser("~/.lp_tr8s_estado.json")

# ─────────────────────────────────────────────────────────────
# SysEx TR-8S (confirmado contra capturas do TR-EDITOR)
# ─────────────────────────────────────────────────────────────
HDR      = [0x41, 0x10, 0x00, 0x00, 0x00, 0x45]   # Roland / devID / model TR-8S
RQ1, DT1 = 0x11, 0x12
TR8S_MATCH = "CTRL"                                # porta "TR-8S TR-8S CTRL"

def roland_checksum(payload):
    return (128 - sum(payload) % 128) % 128

def dt1(addr, data):
    body = list(addr) + list(data)
    return mido.Message('sysex', data=HDR + [DT1] + body + [roland_checksum(body)])

def rq1(addr, size):
    sz = [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
    body = list(addr) + sz
    return mido.Message('sysex', data=HDR + [RQ1] + body + [roland_checksum(body)])

# layout do step: 128 bytes = 16 steps x 8 bytes
#   byte 5     = tipo (00 normal, 01 flam, 02 sub 1/2, 03 sub 1/3, 04 sub 1/4)
#   bytes 6,7  = velocity em nibbles (0 = step desligado)
BYTES_P_STEP = 8
ALT_BYTE     = 4
SUB_BYTE     = 5
SUB_FLAM     = 1      # byte 5: 1 = flam; 2, 3, 4 = sub step 1/2, 1/3, 1/4
VEL_HI, VEL_LO = 6, 7

# PROBABILITY do step = byte 3 (REFERENCIA 2.4). Decodificada por leitura em tres
# pontos: 50% -> 05, 90% -> 01, 20% -> 08. A formula linear abaixo cobre os tres;
# se o painel tiver valores fora da escala de 10, a sessao de calibracao
# (cmd_prob_watch) transforma isto numa tabela. 100% = 0x00.
PROB_BYTE = 3

# PROVADO em 15/08/2026 (sniff M2b): o TR-EDITOR escreve a probability no
# byte 3 do step, no MESMO endereco que o grid usa, com byte = (100-pct)/10 -
# o gesto varreu 0..10 monotonico, ida e volta. O 10 e novidade: 0%, um step
# que NUNCA toca (a formula antiga capava em 9 achando que o piso era 10%).
def prob_para_byte(pct):
    return max(0, min(10, (100 - int(pct)) // 10))

def byte_para_prob(b):
    return 100 - 10 * max(0, min(10, b))

# ALTERNATE: o valor e 0x08, nao 0x01 (REFERENCIA 2.4). Por que o bit 3, ninguem
# sabe - provavelmente ha outras flags no mesmo byte. Guardado como VALOR, nao
# como numero de bit, pra nao fingir que entendemos o resto do byte.
ALT_LIGADO = 0x08
VEL_LIMIAR   = 64     # <= isso o pad pinta na cor escura ("fraco")

# Niveis do seletor de velocity (coluna de cena do DIREITO, topo -> base).
# O TR-EDITOR oferece 10-100, 110, 120 e 127 por atalho (manual p. 8).
VELOCIDADES = [127, 110, 100, 80, 60, 50, 30, 10]
VEL_PADRAO  = 3       # indice de 80

# Os dois niveis que a PROPRIA TR-8S usa. O ciclo do pad dela e strong -> weak ->
# off (Reference p. 45), e os valores saem de tres fontes que batem: o SysEx
# capturado do TR-EDITOR (05 00 = 80, 03 02 = 50), o manual do editor p. 8
# ("velocity value of 50" no atalho de weak beat), e o proprio ciclo do painel.
# Os outros seis niveis so existem porque a maquina aceita velocity continua -
# e exatamente o que o grid destrava. Por isso estes dois ganham cor propria.
VEL_FORTE, VEL_FRACA = 80, 50

MODOS = [("NORMAL", 0x00), ("FLAM", 0x01), ("SUB 1/2", 0x02),
         ("SUB 1/3", 0x03), ("SUB 1/4", 0x04)]
INSTRUMENTOS = ["BD","SD","LT","MT","HT","RS","HC","CH","OH","CC","RC"]

# 0x01..0x08 = A..H, 0x09 = Fill 1, 0x0A = Fill 2 (REFERENCIA 2.3).
# Fills confirmados em hardware em 13/08/2026 (escrita ouvida na caixa).
VARIACOES = ["A", "B", "C", "D", "E", "F", "G", "H", "Fill 1", "Fill 2"]

VARIACAO = 0x01

def addr_soma(addr, offset):
    """Soma com carry de 7 bits (enderecamento Roland)."""
    a = list(addr)
    for i in range(3, -1, -1):
        v = a[i] + (offset & 0x7F)
        offset >>= 7
        a[i] = v & 0x7F
        offset += v >> 7
    return tuple(a)


# ── LEITURA do pattern: regiao 24 5x, achada em 16/08/2026 ────────────
#
# O `20 xx` acima NAO devolve o pattern que a maquina toca. Ele devolve sempre
# o mesmo conteudo, para qualquer pattern - trocar no painel ou remotamente nao
# mexe nele (medido: 1-01 e 3-06 devolveram bytes identicos). Foi a causa do
# "grid nao espelha o que toca", aberto desde 15/08.
#
# O sniff do GET do TR-EDITOR mostrou que ele le OUTRA regiao, `24 5x`, com a
# mesma forma: 24 50 = cabecalho, 24 51..24 5A = as 10 variacoes (A-H + os dois
# Fill In), terceiro byte = instrumento, quarto = 0x08. Ou seja, e o `20 0V`
# deslocado: 0x20 -> 0x24 e o segundo byte somado de 0x50.
#
# Conferido contra o painel (pattern 3-06 var A, BD so no step 1, last 12):
#
#             20 01 ii 08        24 51 ii 08     painel
#   BD        [1, 10, 13]        [1]             [1]
#   last A-H  [16, 16, ...]      [12, 12, ...]   12
#   nome      '----'             '32bars Trap'   -
#
# A ESCRITA vai no MESMO lugar - provado em 16/08/2026 com um segundo sniff.
# Ligando o step 2 do BD no TR-EDITOR saiu UMA mensagem:
#
#   DT1  24 51 00 10   data=[0, 0, 0, 0, 0, 0, 5, 0]
#
# 24 51 = variacao A, 00 = BD, 0x10 = 0x08 + 1*8 = step 2; e os nibbles 5 e 0
# sao a velocity 80 que o editor mostrava. Bate byte a byte com addr_step().
#
# Ou seja, o `20 xx` estava errado nas DUAS pontas. Escrever nele nunca chegou
# a mudar a maquina - o que parecia "sincronizar ao clicar" era so o grid
# atualizando o proprio cache local.
# O `24 5x` acima e uma FOTOGRAFIA: era onde morava o pattern 3-06, o que
# estava carregado durante aquele sniff. A regra geral, achada em 16/08/2026
# na mesma captura, e que o segundo byte vale `pattern * 16 + variacao` - e
# 3-06 e o indice 37, entao 37*16 + 1 = 593 = 4*128 + 81, ou seja o byte 0
# sobe para 0x24 e o byte 1 fica 0x51. Bate exatamente com o que foi visto.
#
# Confirmado lendo quatro patterns na maquina, incluindo os que transbordam o
# carry de 7 bits para o byte 0:
#
#   pattern   0 (1-01)  20 01 00 08   nome '----'
#   pattern   4 (1-05)  20 41 00 08   nome 'SambaWork'
#   pattern  43 (3-12)  25 31 00 08   nome 'Loafing'
#   pattern 127 (8-16)  2F 71 00 08   nome '----'
#
# E verificado em hardware pelo Luan com o gesto do relato original: trocar de
# pattern no painel passou a mudar o grid.
#
# Cada (pattern, variacao) ocupa VAO_VARIACAO do offset de 28 bits. O
# `pattern` e OBRIGATORIO de proposito: um default silencioso e o bug de novo,
# so que ancorado noutro pattern - melhor o Python reclamar.
REGIAO_PATTERN = (0x20, 0x00, 0x00, 0x00)
VAO_VARIACAO   = 128 * 128        # 16384 bytes de espaco de endereco

def addr_variacao(pattern, var):
    """Base da variacao `var` (0 = no do pattern, 1-8 = A-H, 9-10 = fills)."""
    return addr_soma(REGIAO_PATTERN, (pattern * 16 + var) * VAO_VARIACAO)

def addr_no_pattern(pattern):
    return addr_variacao(pattern, 0)

def addr_bloco_rd(inst, var, pattern):
    return addr_soma(addr_variacao(pattern, var), inst * 128 + 8)

def addr_step_rd(inst, s, var, pattern):
    return addr_soma(addr_bloco_rd(inst, var, pattern), s * BYTES_P_STEP)

def addr_accent_rd(var, pattern):
    return addr_variacao(pattern, var)
# NIVEL DE KIT - estrutura levantada no sniff do TR-EDITOR (15/08/2026).
#
# O segundo byte e o NUMERO DO KIT, nao um zero fixo: o kit "003 TR-707" do
# Luan respondeu em 10 02 xx 00. Ate 15/08 estas funcoes fixavam 0x00, ou
# seja, liam sempre o kit 001 - plausivel o bastante para ninguem notar.
#
# O terceiro byte escolhe o bloco (ver efeitos.BLOCOS):
#   00 nome/comuns   01 REVERB   02 DELAY   03 MASTER FX
#   10+i instrumento i (BD..RC)  20+i tone e INST FX do instrumento i
def addr_kit_nome(kit=0):         return (0x10, kit & 0x7F, 0x00, 0x00)
def addr_kit_tone(inst, kit=0):   return (0x10, kit & 0x7F, 0x10 + inst, 0x00)
def addr_kit_param(inst, kit=0):  return (0x10, kit & 0x7F, 0x20 + inst, 0x00)

def addr_fx(bloco, kit=0, inst=None):
    """Endereco base de um bloco de efeito do kit (efeitos.BLOCOS)."""
    b = efeitos.BLOCOS[bloco]
    terceiro = b["base"] + (inst or 0 if b["por_inst"] else 0)
    return (0x10, kit & 0x7F, terceiro & 0x7F, 0x00)

# Nivel de PATTERN, decodificado em 13/08/2026 com snap/snapdiff (REFERENCIA 2.3.1).
# Os dois LAST STEP moram na mesma tabela de 20 bytes e sao 0-based: o valor 0x0F
# e 16 steps. As variacoes A-H tem slot; os dois Fill In nao - onde eles guardam
# o comprimento continua desconhecido.
# O no do pattern ZERO (1-01). Nome explicito de proposito: com o nome
# generico anterior ele parecia 'o no do pattern' e era chamado como tal -
# foi assim que a mascara de variacao acabou sendo escrita no 1-01. Serve
# so de endereco de liveness, que precisa existir sempre e nao pode
# depender de saber onde a maquina esta. Para o pattern corrente e
# addr_no_pattern(p).
ADDR_PATTERN_ZERO   = (0x20, 0x00, 0x00, 0x00)
OFF_VAR_TOCANDO = 63   # 63-66: mascara de 4 nibbles, bit i = variacao i+1
OFF_LAST_VAR   = 67    # +0 = A ... +7 = H
OFF_LAST_TRACK = 75    # +0 = BD ... +10 = RC, +11 = TRG

# SCALE do pattern - PROVADA em 17/08/2026 por snapdiff com ida e volta:
# 32nd -> 16th mudou este byte de 03 para 02, e 16th -> 32nd o devolveu para
# 03, sem mais nada mudar no snapshot inteiro.
#
# A ordem dos codigos e a mesma lista do Reference (`8th(T)`, `16th(T)`,
# `16th`, `32nd`): dai 2 = 16th e 3 = 32nd, MEDIDOS. Os codigos 0 e 1 sao
# DEDUZIDOS da mesma lista - ninguem pos a maquina em triplet ainda.
#
# Quantos pulsos de MIDI clock (24 por seminima) cada step dura: e daqui que
# vem a correcao do playhead que andava em METADE da velocidade da maquina
# num pattern em 32nd (3-10, relatado em 17/08).
# AUTO FILL IN - o INTERVALO, no no do pattern. Provado em 17/08/2026 por
# snapdiff com tres pontos, dois deles as pontas da lista:
#     knob 32 -> 0x00      knob 8 -> 0x03      knob 2 -> 0x05
# O byte e o INDICE da posicao do knob, nao o numero: a lista fisica e
# 32/16/12/8/4/2 e nao tem OFF (ligar/desligar e um botao separado).
#
# Mora no NO DO PATTERN, entao o intervalo e propriedade de CADA PATTERN, nao
# uma configuracao global - trocar de pattern troca o intervalo do fill.
#
# ATENCAO: o que o numero do knob CONTA continua desconhecido. Com o knob em 2,
# o fill medido entrou a cada QUATRO voltas de 16 steps (11,15 s a 86 bpm), nao
# a cada duas. A medicao esta na REFERENCIA; a interpretacao nao.
OFF_AUTO_FILL = 0x7F
AUTO_FILL_VALORES = [32, 16, 12, 8, 4, 2]

OFF_SCALE = 0x16
PULSOS_POR_SCALE = {0: 8,   # 8th(T)  - colcheia de tercina: 24/3   (deduzido)
                    1: 4,   # 16th(T) - semicolcheia de tercina    (deduzido)
                    2: 6,   # 16th    - o padrao                   (medido)
                    3: 3}   # 32nd    - o dobro de velocidade      (medido)
NOME_SCALE = {0: "8th(T)", 1: "16th(T)", 2: "16th", 3: "32nd"}

# VARIACAO QUE ESTA TOCANDO - decodificada em 14/08/2026 (REFERENCIA 2.3.2).
#
# Mascara de 16 bits em 4 nibbles, o MESMO formato do ACCENT (2.5) e do MUTE
# (2.7) - terceiro campo da maquina nesse padrao. Bit 0 = A ... bit 7 = H.
#
# Mora imediatamente ANTES da tabela de last steps das variacoes (67-74), o que
# fecha a leitura daquele bloco: 63-66 dizem qual toca, 67-74 dizem o tamanho de
# cada uma.
#
# Trocar de variacao NAO emite Program Change - escutado por 14 s na porta comum,
# so clock. Ler este endereco e o unico caminho.

# Somam sobre addr_no_pattern(pattern), o cabecalho do pattern CORRENTE - o
# mesmo de onde o ler_last_steps le. Ja apontaram para o `20 00` fixo, e
# entao mexer no [LAST] pela tela nao chegava na maquina: o valor voltava
# sozinho na releitura seguinte, sem erro nenhum aparecendo.
def addr_last_var(var, pattern):
    return addr_soma(addr_no_pattern(pattern), OFF_LAST_VAR + var - 1)
def addr_last_track(inst, pattern):
    return addr_soma(addr_no_pattern(pattern), OFF_LAST_TRACK + inst)

# MUTE DE TRACK - decodificado em 14/08/2026 (REFERENCIA 5.3).
#
# Mora numa regiao de SISTEMA, nao no pattern nem no kit: por isso o snap dos ~50
# enderecos conhecidos nao via nada, por mais que se mutasse. Nao e salvo com o
# pattern, o que bate com ele ser estado de performance.
#
# O formato e o MESMO do ACCENT (2.5): mascara de 16 bits em 4 nibbles, bit i =
# instrumento i, BD=0 ... RC=10. Confirmado em quatro estados, incluindo um que
# cruza a fronteira de nibble (CH+OH+CC+RC = 0x0780 -> nibbles 0 7 8 0).
#
# Leitura E escrita confirmadas em hardware. A escrita silencia de verdade - foi
# ouvida na caixa, nao so relida. Isso derruba a premissa da secao 10 da
# REFERENCIA, que renomeou MUTE para HIDE por acreditar que silenciar era
# impossivel; o que era impossivel era pelo CC de LEVEL.
ADDR_PERF = (0x01, 0x00, 0x00, 0x00)   # regiao de performance
ADDR_MUTE = ADDR_PERF                  # nome antigo, mantido por clareza no uso
OFF_MUTE  = 12        # 12,13,14,15 = os 4 nibbles

# STEP ATUAL DO SEQUENCIADOR - decodificado em 14/08/2026, no mesmo bloco.
# Anda 0..15 e da a volta; congela quando a maquina para. Ele apareceu como
# "ruido que muda sozinho" num diff de mute e quase foi descartado como tal.
#
# Serve para uma coisa que o MIDI clock nao resolve: a TR-8S manda clock
# MESMO PARADA (medido: 138 pulsos em 4 s com o transporte parado), entao
# "chegou clock" nao prova que ela esta tocando. So o start/continue prova - e
# quem sobe o grid com a maquina ja rodando nunca recebe um start, e ficava sem
# playhead ate parar e tocar de novo. Este byte responde a pergunta direto.
OFF_STEP_ATUAL = 7

# FILL IN EM ANDAMENTO - decodificado em 17/08/2026 com um watch da regiao de
# performance (930 leituras, 17 fills). 1 = a maquina esta tocando um fill,
# 0 = pattern normal.
#
# A assinatura nao deixa duvida: acende e apaga SEMPRE na virada do compasso
# (step 15 -> 0), dura exatamente um compasso no automatico (2,74 a 2,94 s
# medidos, contra 2,79 s teoricos de 16 steps a 86 bpm) e, no fill MANUAL,
# acende no instante do aperto (foi visto no step 6) e apaga na mesma virada.
#
# E o unico caminho para saber que a maquina saiu do pattern: a mascara de
# variacao habilitada (63-66) so reporta A-H e nunca os dois Fill In (2.3.2),
# e o watch confirmou que NENHUM byte da performance reporta qual variacao
# toca. Sem isto, o grid seguia desenhando o playhead sobre uma variacao que
# nao estava soando.

# TROCA REMOTA DE KIT E PATTERN - do mapa oficial da Roland embutido no site
# ARIA (TR-8S-SysEx/js/Tr8s/Tr8sData.js, base64) e visto em capturas reais:
#   offset 0 = kit atual, 1 = pattern atual, 2 = proximo pattern (1 byte,
#   0-127 = banco A-H x 16, 0-based). DT1 de 1 byte em endereco valido.
# NUNCA exercitado na NOSSA maquina - so usar via cmd_pattern ate a sessao de
# hardware provar (e registrar o resultado na REFERENCIA).
OFF_KIT_ATUAL     = 0
OFF_PATTERN_ATUAL = 1
OFF_PATTERN_PROX  = 2

# TEMPO - achado com cmd_tempo_watch em 16/08/2026, o Luan girando o knob de
# ponta a ponta: tempo x 10 em TRES NIBBLES nos offsets 0x3A-0x3C do perf.
# Conferido nas pontas: 05 07 08 = 0x578 = 1400 = 140.0 (o visor dizia
# ~139.7) e 0B 0B 08 = 0xBB8 = 3000 = 300.0 (o teto do knob). Faixa
# 40.0-300.0. LEITURA provada; escrita e a mesma hipotese ja confirmada nos
# vizinhos (kit no 0, pattern no 1/2).
OFF_FILL = 0x09

# TEMPO. Mora no NO DO PATTERN, quatro nibbles a partir do offset 0x10, e a
# regiao de performance (0x3A) e ESPELHO - escrever no espelho nao muda nada.
# O TR-EDITOR faz exatamente uma mensagem por mudanca:
#     DT1  20 00 00 10   00 03 05 0D     (0x35D = 861 = 86.1 BPM)
# Sniff de 17/08/2026: 40 mensagens subindo de 1 em 1, de 86.0 a 90.0, todas
# nesse endereco e nada mais junto.
#
# Sequencia completa de 17/08/2026, porque o caminho importa mais que o
# resultado:
#   1. 3 nibbles em 0x3A            -> recusado: a leitura de volta nem mudou
#   2. os mesmos 3 no no do pattern -> recusado tambem
#   3. a mascara de MUTE, no mesmo minuto -> aceitou e restaurou. Prova de que
#      a porta, o dt1 e o caminho de escrita estavam bons - sem isso, "recusou"
#      poderia ser o nosso script nao mandando nada
#   4. 4 nibbles em 0x39            -> a leitura de volta FOI para 120.0
#   5. e o visor continuou em 86, e o CLOCK MEDIDO continuou em 85.8 BPM
#
# O passo 5 e a licao: a maquina ACEITA o valor no espelho de SysEx e NAO o
# aplica. Round-trip de leitura nao prova efeito - e exatamente o que o
# definir_fx ja logava ("o ouvido confirma, nao o round-trip"), agora com um
# caso concreto. Quem for reabrir isto: o TR-EDITOR MUDA o tempo, entao existe
# caminho; o proximo passo e sniffar o que ele manda (sessao M2).
OFF_TEMPO_NO = 0x10   # no do pattern: e AQUI que se escreve (4 nibbles)
OFF_TEMPO = 0x3A      # performance: espelho, serve para LER

# perf offset 0x40: alterna 0/1 a cada volta MESMO com A->B->C ciclando
# (watch de 16/08) - e paridade de compasso ou algo do genero, NAO a
# variacao tocando. Registrado para ninguem confundir de novo.
OFF_PARIDADE = 0x40

def addr_mute():            return addr_soma(ADDR_PERF, OFF_MUTE)

# BLOCO UTILITY (50 00 00 xx) - do mesmo mapa oficial do ARIA. Semantica
# diferente de tudo que o projeto conhecia: a PERGUNTA e a RESPOSTA sao ambas
# DT1 no mesmo endereco (nao e RQ1/DT1). Visto no fio nas capturas; NUNCA
# exercitado na nossa maquina - toda chamada avisa isso no log.
UTIL_WRITE_PATTERN = 0x01   # data = [id >> 7, id & 0x7F]; grava na memoria
UTIL_WRITE_KIT     = 0x02
UTIL_PLAYING       = 0x10   # resposta: 1 byte, 0 = parada
UTIL_DISPLAY       = 0x12   # data = 32 chars ASCII; escreve no visor
UTIL_VERSION       = 0x13   # resposta: 8 chars ("1.13"...)
UTIL_UID           = 0x14

def nome_pattern(n):
    """Como o VISOR mostra: banco 1-8, pattern 1-16 -> "2-05".
    A letra e VARIACAO, nao banco - a tela ja confundiu as duas (16/08)."""
    return f"{n // 16 + 1}-{n % 16 + 1:02d}"


def addr_util(sub):         return (0x50, 0x00, 0x00, sub)

def ler_util(tr_in, tr_out, sub, data=(0,), timeout=1.0):
    """Consulta utility: manda DT1 e espera o DT1 de volta no mesmo endereco.

    Nao e RQ1 em endereco desconhecido - e endereco da tabela oficial e o
    veneno da 3.1 e especificamente RQ1 invalido. Ainda assim, primeira vez
    em hardware proprio: observar a maquina."""
    alvo = addr_util(sub)
    tr_out.send(dt1(alvo, list(data)))
    limite = time.time() + timeout
    while time.time() < limite:
        for msg in tr_in.iter_pending():
            if msg.type != 'sysex':
                continue
            d = list(msg.data)
            if len(d) < 12 or d[:6] != HDR or d[6] != DT1:
                continue
            if tuple(d[7:11]) == alvo:
                return d[11:-1]
        time.sleep(0.005)
    return None

# CCs de LEVEL por instrumento, da implementation chart. Guardados como
# documentacao, NAO em uso.
#
# NAO FUNCIONAM: testado em 13/08/2026 com a maquina tocando, USBMidiThru ON,
# canal 10 - a caixa nao silenciou, e nenhum dos ~50 enderecos legiveis se
# mexeu. A chart marca estes CCs como "recognized"; a maquina discorda. O mais
# provavel e que o FADER FISICO seja a autoridade, e um CC nao move fader.
# Segunda vez no mesmo dia que a chart nao descreve a maquina - a primeira foi
# ela marcar System Exclusive "x" (secao 5.1).
# Nao tentar de novo sem uma razao nova.
CC_LEVEL = {"BD": 24, "SD": 29, "LT": 48, "MT": 51, "HT": 54, "RS": 57,
            "HC": 60, "CH": 63, "OH": 82, "CC": 85, "RC": 88}
CANAL_TR8S = 9        # canal 10 na contagem de 1, o default de fabrica

def mascara_para_nibbles(m):
    return [(m >> 12) & 0x0F, (m >> 8) & 0x0F, (m >> 4) & 0x0F, m & 0x0F]
def nibbles_para_mascara(n):
    return (n[0] << 12) | (n[1] << 8) | (n[2] << 4) | n[3]

# ─────────────────────────────────────────────────────────────
# Launchpad Mini MK3
# ─────────────────────────────────────────────────────────────
LP_MATCH = "Launchpad"
PROG_ON  = mido.Message('sysex', data=[0x00,0x20,0x29,0x02,0x0D,0x0E,0x01])
PROG_OFF = mido.Message('sysex', data=[0x00,0x20,0x29,0x02,0x0D,0x0E,0x00])

# ─────────────────────────────────────────────────────────────
# PALETA DOS STEPS - espelha as cores do painel da propria TR-8S
#
# Decisao de 14/08/2026, do Luan: a maquina ja pinta cada tipo de step com uma
# cor, e o grid usava outras por acaso historico (flam e sub eram os dois
# laranja, porque nasceram do mesmo byte). Espelhar tira uma traducao mental de
# quem olha os dois aparelhos ao mesmo tempo.
#
#   na TR-8S          no grid
#   ---------------   ------------------------------------------
#   nota              vermelho          COR_FORTE / COR_FRACA
#   flam              lilas             COR_FLAM  / COR_FLAM_FRACA
#   sub step          amarelo           COR_SUB   / COR_SUB_FRACA
#   ALT               rosa              COR_ALT_FORTE / COR_ALT_FRACA
#
# FLAM e SUB agora sao familias DIFERENTES, e nao eram: os dois moram no byte 5
# (1 = flam, 2-4 = sub 1/2, 1/3, 1/4), e o codigo antigo tratava "byte 5 != 0"
# como uma coisa so. Ver cor_base().
#
# O par claro/escuro de cada familia continua sendo forte/fraca pelo VEL_LIMIAR.
# ALT nao ganha variante de flam nem de sub: o matiz ja esta carregando o ALT, e
# empilhar mais um eixo daria doze cores que ninguem distingue num LED de 15 mm.
# ─────────────────────────────────────────────────────────────
COR_OFF        = 0    # apagado
COR_FORTE      = 5    # vermelho
COR_FRACA      = 7    # vermelho escuro
# O lilas nasceu em (98, 62, 127) e ficou lavado: aquilo e quase o #C77DFF, o tom
# mais claro e leitoso de um roxo. O que faz parecer roxo de verdade e o verde
# BAIXO contra o azul - na paleta de referencia a razao verde/azul fica entre
# 0.15 e 0.35, e ali estava em 0.49. Estes sao o #7B2CBF e o #3C096C levados ao
# brilho maximo do LED.
COR_FLAM       = (82, 29, 127)   # roxo
COR_FLAM_FRACA = (30, 6, 54)
COR_SUB        = (127, 112, 0)   # amarelo
COR_SUB_FRACA  = (44, 38, 0)
COR_ALT_FORTE  = (127, 26, 80)   # rosa
COR_ALT_FRACA  = (46, 8, 29)
COR_ACC        = (0, 62, 127)    # azul vivido - a linha de ACCENT
COR_ATIVO      = 3    # branco  (modo selecionado)
COR_VAR        = 45   # azul    (variacao selecionada)
COR_PLAY       = 23   # verde escuro - playhead sobre step vazio
COR_PLAY_HIT   = 21   # verde        - playhead sobre step ligado
COR_TEMPO      = 1    # branco fraco - cabeca de tempo vazia (steps 1,5,9,13)
STEPS_TEMPO    = 4    # marca 1 step a cada 4
COR_FILL       = 49   # roxo    - fill 1/2 ativo
COR_CLEAR      = 7    # vermelho escuro - CLEAR em repouso
COR_ARMADO     = 5    # vermelho        - CLEAR armado
COR_COPIA      = 9    # laranja - COPY (colar so acende com buffer cheio)
COR_SETA       = 1    # cinza escuro - seta de rolagem disponivel
COR_VEL_OFF    = 1    # cinza escuro - nivel sem correspondente na maquina
COR_ALT        = 13   # amarelo - ALT armado (a mesma cor que a nota ALT tem no grid)

# Cores em TUPLA (r,g,b) de 0-127 vao pelo SysEx de LED, nao pela paleta - a
# paleta indexada nao chega perto do escuro que estas precisam.
COR_FORA = (3, 3, 3)      # step alem do LAST STEP: "esse step nao existe"

# LINHA MUTADA NA TR-8S: cinza-azulado bem dessaturado.
#
# A primeira versao trocava a familia de cor (roxo pra nota, azul pro flam), e
# funcionou - ate as familias acabarem. Com nota, flam, sub e ALT espelhando o
# vermelho, lilas, amarelo e rosa da maquina, nao sobrou matiz livre.
#
# Dessaturar e melhor que mais um matiz, e nao e so falta de opcao: uma linha
# muda nao esta fazendo som nenhum, e ausencia de cor diz isso melhor do que
# qualquer cor nova diria. Aqui o ritmo continua legivel pelo desenho, sem
# competir com as linhas que soam.
#
# Um par so, forte e fraca: nao distingue flam de sub. Numa linha que nao soa, o
# tipo do som que ela nao esta fazendo e detalhe - e quatro cinzas ninguem
# separaria de longe.
COR_MUDA_FORTE = (28, 34, 46)
COR_MUDA_FRACA = (11, 14, 19)
COR_MUDA_BOTAO = (34, 42, 56)   # o botao e o logo, quando ha alguem mutado

# ─────────────────────────────────────────────────────────────
# Traducao das cores para hex, para a TELA (pagina web).
#
# Mora aqui, e nao na tela, de proposito: a cor de um step no navegador e a cor
# do LED do Launchpad tem que sair da MESMA fonte, senao as duas versoes do
# grid divergem com o tempo - foi o que comecou a acontecer quando a janela Tk
# tinha a propria copia da paleta.
#
# Cor int = indice da paleta Novation (o caminho barato, via note_on);
# cor tupla = (r,g,b) de 0-127, o SysEx de LED. So os indices que o grid usa.
# ─────────────────────────────────────────────────────────────
PALETA_HEX = {0: "#1a1a1a", 1: "#3a3a3a", 3: "#ffffff", 5: "#ff3b30",
              7: "#5c1512", 9: "#ff9500", 11: "#5c3a0f", 13: "#ffe600",
              21: "#33d17a", 23: "#14532d", 45: "#3b82f6", 49: "#a855f7"}


def cor_hex(cor):
    """Cor do motor (indice da paleta ou tupla RGB 0-127) -> hex do CSS."""
    if isinstance(cor, tuple):
        r, g, b = (min(255, int(c * 2)) for c in cor)
        return f"#{r:02x}{g:02x}{b:02x}"
    return PALETA_HEX.get(cor, "#1a1a1a")


def paleta_da_tela():
    """As cores do pattern, com os nomes que o CSS usa (--c-nota etc.).

    A precedencia que a tela precisa respeitar e a de cor_do_step():
    mudo > ALT > flam/sub > nota, com VEL_LIMIAR separando forte de fraca."""
    return {
        "nota": cor_hex(COR_FORTE), "nota_fraca": cor_hex(COR_FRACA),
        "flam": cor_hex(COR_FLAM), "flam_fraca": cor_hex(COR_FLAM_FRACA),
        "sub": cor_hex(COR_SUB), "sub_fraca": cor_hex(COR_SUB_FRACA),
        "alt": cor_hex(COR_ALT_FORTE), "alt_fraca": cor_hex(COR_ALT_FRACA),
        "acc": cor_hex(COR_ACC),
        "muda": cor_hex(COR_MUDA_FORTE), "muda_fraca": cor_hex(COR_MUDA_FRACA),
        "play": cor_hex(COR_PLAY_HIT), "play_vazio": cor_hex(COR_PLAY),
        "tempo": cor_hex(COR_TEMPO), "fora": cor_hex(COR_FORA),
        "vazio": "#26221e",
    }

# ─────────────────────────────────────────────────────────────
# LUZ DA BORDA - pedido do Luan em 14/08/2026: o adesivo colado nos botoes de
# borda fica ilegivel com o LED aceso embaixo. Toda cor de borda passa por
# cor_borda() e sai escurecida por um fator unico; 0.0 apaga tudo. Estados
# ativos/armados usam um piso um pouco maior para continuarem distinguiveis de
# perto sem ofuscar o adesivo.
#
# A paleta indexada nao escurece, entao a borda vai SEMPRE pelo SysEx RGB - por
# isso o mapa abaixo traduz cada indice usado na borda para um RGB de brilho
# cheio antes de aplicar o fator. Indices repetidos (SETA/VEL_OFF = 1,
# ARMADO/FORTE = 5, CLEAR/FRACA = 7) dividem a mesma entrada de proposito.
# ─────────────────────────────────────────────────────────────
BRILHO_BORDA       = 0.10   # botoes em repouso; calibrar no olho com o adesivo
BRILHO_BORDA_ATIVO = 0.25   # estado ativo/armado (variacao atual, CLEAR armado)

RGB_BORDA = {
    COR_OFF:     (0, 0, 0),
    COR_ATIVO:   (127, 127, 127),   # branco
    COR_VAR:     (0, 40, 127),      # azul
    COR_FILL:    (90, 0, 127),      # roxo
    COR_CLEAR:   (70, 0, 0),        # vermelho escuro
    COR_ARMADO:  (127, 0, 0),       # vermelho
    COR_COPIA:   (127, 60, 0),      # laranja
    COR_SETA:    (70, 70, 70),      # cinza
    COR_ALT:     (127, 110, 0),     # amarelo
}

# AMPLITUDE DO RESPIRO do fill: quanto a nota chega a escurecer no fundo da
# curva. 0.45 = some quase pela metade e volta. E o unico numero de calibragem
# no olho aqui - se ficar agressivo, sobe; se ficar invisivel, desce.
RESPIRO_FUNDO = 0.45


def respirar(cor, fator):
    """Escurece uma cor do GRID por um fator 0-1, devolvendo RGB 0-127.

    Precisa passar por RGB porque indice de paleta nao escurece: o Launchpad
    so tem aquele tom. O PALETA_HEX ja traduz todo indice do grid, e o
    cor_hex() faz a conversao inversa (RGB 0-127 -> hex dobrando), entao aqui e
    so desfazer. Mesma ideia do cor_borda(), que faz isto para os botoes.

    RESSALVA: o PALETA_HEX e a tabela da TELA - e a nossa aproximacao de como o
    indice N aparece no pad, nao uma medicao do aparelho. Com fator 1.0 a cor
    sai "cheia", mas ja nao e mais o indice: se a aproximacao for grosseira, o
    tom pode mudar no instante em que o fill comeca. O Luan olhou em 18/08/2026
    e aprovou; se um dia aparecer diferenca de tom, o conserto e uma tabela RGB
    propria para o grid, medida no aparelho, como o RGB_BORDA ja e para os
    botoes."""
    if isinstance(cor, tuple):
        rgb = cor
    else:
        h = PALETA_HEX.get(cor)
        if not h:
            return cor                   # cor que nao sei escurecer sai intacta
        rgb = tuple(int(h[i:i + 2], 16) // 2 for i in (1, 3, 5))
    f = max(0.0, min(1.0, fator))
    return tuple(max(0, min(127, int(round(c * f)))) for c in rgb)


def cor_borda(cor, ativo=False):
    """Escurece uma cor de botao de borda. Aceita indice de paleta ou (r,g,b)."""
    rgb = cor if isinstance(cor, tuple) else RGB_BORDA.get(cor, (70, 70, 70))
    f = BRILHO_BORDA_ATIVO if ativo else BRILHO_BORDA
    if f <= 0:
        return (0, 0, 0)
    return tuple(max(0, min(127, int(round(c * f)))) for c in rgb)
# Ondinha do modo off: o toque no pad usa estes valores fixos, e e o unico
# comportamento de onda que ja foi exercitado em hardware. Nao mexer sem motivo.
ONDA_VEL     = 9.0    # celulas por segundo
ONDA_LARGURA = 2.2    # espessura do anel, em celulas
ONDA_ALCANCE = 15.0   # celulas ate morrer (a diagonal do 16x8 e ~17)
ONDA_FPS     = 30

# Modo standby: as mesmas ondas, mas nascendo sozinhas. Cada estilo e so uma
# tabela de faixas (min, max) sorteadas por onda - acertar o gosto depois e
# mexer em numero, nao em codigo. O render nao sabe que estilos existem.
ESTILO_CHUVA, ESTILO_AMBIENTE = "chuva", "ambiente"
STANDBY_ESTILOS = {
    # chuva: variacao larga, uma onda a cada meio segundo mais ou menos
    ESTILO_CHUVA:    {"intervalo": (0.35, 1.10), "vel": (6.0, 13.0),
                      "larg": (1.4, 3.0), "alc": (9.0, 17.0),
                      "brilho": 1.00, "fps": 30},
    # ambiente: grandes, raras, lentas e fracas - respiracao, nao chuva. O fps
    # menor nao e economia de estilo, e de trafego: metade dos quadros por hora.
    ESTILO_AMBIENTE: {"intervalo": (2.50, 5.00), "vel": (1.6, 3.2),
                      "larg": (3.5, 6.0), "alc": (14.0, 20.0),
                      "brilho": 0.45, "fps": 15},
}

# MIDI clock: 24 pulsos por seminima -> 6 pulsos por semicolcheia (1 step)
PULSOS_P_STEP  = 6
SEGUIR_CLOCK   = True   # False desliga o playhead

# Track mais curto que a variacao roda no PROPRIO comprimento: com o BD em 10 numa
# variacao de 16, no step 11 ele ja voltou pro 1 enquanto os outros seguem em 11 -
# a coluna verde deixa de ser coluna. Observado na maquina pelo Luan em 13/08/2026.
#
# O que a observacao NAO distingue: quando a variacao da a volta, o track curto
# reinicia junto ou continua de onde parou? False = continua (a fase anda e leva
# varios compassos pra fechar, polirritmia de verdade). True = reinicia todo
# compasso, e o padrao se repete igual. Uma escuta de tres compassos decide.
TRACK_REINICIA_NA_VARIACAO = False

# De quanto em quanto tempo reler os last steps da maquina. Sem isso o grid so
# saberia deles ao ligar e ao trocar de variacao, e mexer no [LAST] do painel
# nunca chegaria na tela - foi exatamente o que aconteceu em 13/08/2026.
INTERVALO_RELEITURA = 1.5

# De quanto em quanto tempo REARMAR a fila dos 26 blocos de efeito. Ela sai
# poucos blocos por ciclo (Motor.FX_POR_CICLO), entao uma volta completa leva
# alguns segundos - isto aqui e so o intervalo entre uma volta e a proxima.
# Sem esse rodizio, mexer no painel da maquina em qualquer parametro de FX
# nunca aparecia na tela (achado na sessao de 17/08/2026).
INTERVALO_FX = 2.0

# De quantos steps de divergencia o playhead e puxado de volta pro step que a
# maquina diz estar tocando (ver Motor._ressincronizar). None desliga a correcao
# e volta a confiar so na contagem de clock.
TOLERANCIA_SYNC = 1

# Prazo de validade do passo_maquina, em segundos. Ele nasce de um round-trip
# de SysEx e e gravado no ler_mudos(), mas so consumido pelo _ressincronizar
# depois do ler_kit, da fila de FX e do rodizio de releitura - um recarregar
# saudavel ja custa ~1 s, e a 86 bpm um step dura 0,17 s. Corrigir a fase por
# um alvo velho faz o playhead tremer sozinho, sem nenhum pulso ter se perdido.
VALIDADE_PASSO = 0.15

# Acima de quantos steps de correcao a ancora do ciclo de variacoes e SOLTA.
# Um desvio desse tamanho nao e latencia de medicao: e pulso de clock perdido
# de verdade. A fase da pra consertar pelo step que a maquina informa; QUAL
# variacao esta tocando, nao - e a regra da casa e "?" em vez de errado.
SALTO_SOLTA_ANCORA = 3

# Quantas correcoes grandes, dentro de quantos segundos, denunciam que o no
# 20 xx nao corresponde ao pattern que a maquina toca (Motor._conferir_espelho).
# Medido em 16/08/2026 com o espelho errado: ~5 por minuto, sem parar. Com o
# espelho certo o resync mal dispara, entao 4 numa janela de 60 s nao acontece
# por acaso - e o preco de um falso positivo e so a escrita ficar bloqueada
# ate a proxima releitura limpa.
JANELA_ESPELHO = 60.0
SALTOS_P_SUSPEITA = 4
# ... mas uma RAJADA nao conta como quatro. Ligar o modo ON dispara recarregar,
# ler_kit e ler_fx em sequencia; o playhead sai de fase durante essas leituras e
# o resync corrige varias vezes em poucos segundos - o que enchia a cota e
# acusava espelho errado numa partida perfeitamente normal (visto em 16/08).
# Contando no maximo um salto a cada 8 s, a rajada de partida vale 1 e o
# problema cronico (medido: ~5 por minuto, sem parar) continua sendo pego.
INTERVALO_MIN_SALTO = 8.0

# Quantas leituras seguidas precisam apontar o MESMO SENTIDO de erro antes de o
# playhead ser corrigido. Ver Motor._ressincronizar: o alvo vem da maquina com
# atraso variavel, e medindo 103 amostras o erro aparente cobriu -5..+6 de forma
# uniforme. Exigir tres do mesmo sinal separa deriva real de ruido de medicao.
ERROS_P_CORRIGIR = 3

# Ajuste fino do playhead, em PULSOS de clock (6 pulsos = 1 step). Positivo
# adianta o grid, negativo atrasa. Existe porque sobra uma latencia que nao da
# pra medir de dentro: o LED do Launchpad acende alguns milissegundos depois do
# comando sair daqui, e o som sai da TR-8S por um caminho proprio.
#
# CALIBRADO NO OLHO em 14/08/2026, com a maquina a 120 bpm: 0 ficava atrasado,
# 2 melhorou, 3 passou do ponto. Cada pulso vale ~21 ms nesse andamento.
#
# Duas ressalvas antes de mexer:
#  - o valor e em PULSOS, entao ele acompanha o andamento sozinho; o que ele NAO
#    acompanha e a latencia fisica, que e fixa em ms. Em BPM muito diferente de
#    120 vale reconferir no olho.
#  - so faz sentido corrigir offset CONSTANTE. Se o playhead for se afastando ao
#    longo dos compassos, o problema e outro, e quem cuida disso e o
#    _ressincronizar - aumentar este numero so disfarcaria a deriva.
AJUSTE_PLAYHEAD = 2

# Quantas linhas o INST UP/DOWN anda por toque (nos Launchpad e na tela).
#
# 3 por padrao porque e o que faltava: sao 11 instrumentos e a janela mostra 8,
# entao de BD-CH um unico toque leva a MT-RC e o resto (OH, CC, RC) aparece
# inteiro. Com passo 1 era preciso tocar tres vezes pra ver a ultima linha.
# Passo 1 continua disponivel pra quem quiser deslizar de um em um.
PASSO_INST_PADRAO = 3
PASSO_INST_MAX = 8

# Botoes, por CC. Em programmer mode:
#   fileira de funcao (▲▼◀▶ Session Drums Keys User) = CC 91..98
#   coluna de cena (>)                                = CC 89,79,69,59,49,39,29,19
FUNC_CCS  = [91, 92, 93, 94, 95, 96, 97, 98]
CENA_CCS  = [89, 79, 69, 59, 49, 39, 29, 19]
LOGO_CC   = 99            # reservado para o WRITE, quando for decodificado

# ACCENT comeca fora do grid: 8 linhas de instrumento, a de baixo e o CH.
# Vira toggle em execucao pelo botao ACC (CC 98 do direito).
MOSTRAR_ACC = False
LINHA_ACC_POS = 7         # se a linha de ACC existir, e sempre a de baixo

# ─────────────────────────────────────────────────────────────
# Mapa fisico dos botoes -> acao
#
# O aparelho ESQUERDO esta girado 90 graus anti-horario, entao:
#   - a coluna de cena vai para o TOPO,  esq->dir na ordem de CENA_CCS
#   - a fileira de funcao vai para a BORDA ESQUERDA, e de cima para baixo
#     ela corre 98 97 96 95 94 93 92 91 (ordem INVERSA de FUNC_CCS)
#   - as setas giram junto: ▶ (94) passa a apontar para CIMA e ◀ (93) para
#     BAIXO, com o 94 fisicamente acima do 93
# O DIREITO esta na posicao normal: funcao no TOPO, cena na BORDA DIREITA.
#
# Confira com 'probe' antes de confiar - isto foi derivado da geometria.
# ─────────────────────────────────────────────────────────────
BOTOES = {}
for _i, _cc in enumerate(CENA_CCS):
    BOTOES[("E", _cc)] = ("variacao", _i + 1)     # topo esquerdo: A..H
    BOTOES[("D", _cc)] = ("velocidade", _i)       # borda direita: 127..10
for _cc, _acao in ((98, ("variacao", 0x09)),      # FILL 1
                   (97, ("variacao", 0x0A)),      # FILL 2
                   (96, ("limpar_inst", None)),
                   (95, ("limpar_var", None)),
                   (94, ("oculto", None)),        # ESCONDER MUTADOS (era a seta ▶)
                   (93, ("alt", None)),           # ALT (era a seta ◀)
                   (92, ("copiar", None)),
                   (91, ("colar", None))):
    BOTOES[("E", _cc)] = _acao                    # borda esquerda
for _cc, _acao in ((91, ("rolar", -1)),           # ▲
                   (92, ("rolar", +1)),           # ▼
                   (93, ("modo", 0)), (94, ("modo", 1)), (95, ("modo", 2)),
                   (96, ("modo", 3)), (97, ("modo", 4)),
                   (98, ("acc", None))):
    BOTOES[("D", _cc)] = _acao                    # topo direito
del _i, _cc, _acao

# Os LOGOS (CC 99) NAO sao botoes - so LED. Verificado no hardware em 13/08/2026:
# nao ha chave embaixo, entao eles nunca enviam nada. MUTE e WRITE moraram ali por
# um tempo, o que os deixava inalcancaveis. Foram pras setas do aparelho esquerdo,
# que eram a unica funcao DUPLICADA do mapa (as do direito fazem o mesmo). O logo
# esquerdo continua util como indicador passivo de "tem alguem mutado".
ESCAPE_CHORD = (94, 93)   # HIDE MUTED + ALT: fora do ON, os dois juntos voltam


# ─────────────────────────────────────────────────────────────
# LEDs do Launchpad
#
# Cor int  = indice da paleta, via note_on (o caminho barato de sempre).
# Cor tupla = (r,g,b) de 0-127, via SysEx de LED:
#     F0 00 20 29 02 0D 03 <spec> [<spec> ...] F7
#     spec estatico = 00 <indice> <cor>      spec RGB = 03 <indice> <r> <g> <b>
# Varios specs cabem numa mensagem so, o que a ondinha usa pra mandar o quadro
# inteiro de uma vez em vez de 128 mensagens.
# ─────────────────────────────────────────────────────────────
LED_SYSEX = [0x00, 0x20, 0x29, 0x02, 0x0D, 0x03]

def _spec_cor(nota, cor):
    if isinstance(cor, tuple):
        r, g, b = cor
        return [0x03, nota, int(r) & 0x7F, int(g) & 0x7F, int(b) & 0x7F]
    return [0x00, nota, int(cor) & 0x7F]

def enviar_cor(out, nota, cor):
    if isinstance(cor, tuple):
        out.send(mido.Message('sysex', data=LED_SYSEX + _spec_cor(nota, cor)))
    else:
        out.send(mido.Message('note_on', channel=0, note=nota, velocity=cor))

def enviar_cores(out, pares):
    """[(nota, cor)] num SysEx so."""
    if not pares: return
    dados = []
    for nota, cor in pares:
        dados += _spec_cor(nota, cor)
    out.send(mido.Message('sysex', data=LED_SYSEX + dados))


# ─────────────────────────────────────────────────────────────
# Camada de portas: rtmidi cru, endereçado por INDICE
# (o mido colapsa nomes duplicados - ver docstring do topo)
# ─────────────────────────────────────────────────────────────
class EntradaMIDI:
    """Entrada aberta por indice. Expoe a mesma interface que a do mido.

    MODO CALLBACK (16/08/2026), usado na porta de clock. Por padrao o rtmidi
    guarda o que chega numa fila de 1024 mensagens e DESCARTA em silencio o
    que passar disso - o aviso 'MidiInCore: message queue limit reached!!' sai
    no stderr, fora do log do app (657 deles no log de 15/08). Como a variacao
    que toca e derivada da CONTAGEM de pulsos, cada pulso descartado virava
    erro permanente.

    A 86 bpm a TR-8S manda ~34 mensagens/s, entao 1024 e meia hora de folga -
    exceto que o tick para de drenar durante as leituras longas (recarregar,
    ler_kit), e com a porta CTRL muda isso passa de 30 s.

    Medido nesta maquina, fila de 2 mensagens e ninguem drenando por 3 s:
      - polling: 1 mensagem entregue, ~100 avisos no stderr
      - callback: 104 entregues, zero avisos
    O callback so faz append num deque ilimitado, entao nao ha o que estourar.
    (set_error_callback NAO resolve: nao e chamado para este aviso - ele sai de
    um cerr cru dentro do CoreMIDI. Testado: 0 chamadas.)"""

    def __init__(self, idx, nome=None, ignorar_sense=True, callback=False):
        self._rt = rtmidi.MidiIn()
        self._rt.open_port(idx)
        # mesma config do mido: NAO ignorar sysex nem timing (clock), so active sense.
        # sem isso o playhead nao conta clock e o dump da TR-8S nunca responde.
        #
        # ignorar_sense=False so serve ao 'escutar': na porta comum o active sensing
        # e o unico sinal que a maquina manda o tempo todo, parada ou tocando, entao
        # e ele que prova que o listener nao esta surdo.
        self._rt.ignore_types(False, False, ignorar_sense)
        self._parser = mido.Parser()
        self.idx, self.name = idx, nome or "?"
        self._buf = None
        if callback:
            # deque: append de um lado e popleft do outro sao atomicos sob o
            # GIL, entao a thread do CoreMIDI e a do motor nao brigam
            self._buf = collections.deque()
            self._rt.set_callback(lambda par, d=None: self._buf.append(par[0]))

    def iter_pending(self):
        if self._buf is not None:
            while self._buf:
                self._parser.feed(self._buf.popleft())
        else:
            while True:
                r = self._rt.get_message()
                if r is None:
                    break
                self._parser.feed(r[0])
        return list(self._parser)          # lista, nao generator: drenar e seguro

    def close(self):
        try:
            if self._buf is not None:
                self._rt.cancel_callback()
            self._rt.close_port(); self._rt.delete()
        except Exception: pass

    def __enter__(self): return self
    def __exit__(self, *e): self.close()


class SaidaMIDI:
    """Saida aberta por indice."""
    def __init__(self, idx, nome=None):
        self._rt = rtmidi.MidiOut()
        self._rt.open_port(idx)
        self.idx, self.name = idx, nome or "?"

    def send(self, msg):
        self._rt.send_message(msg.bytes())

    def close(self):
        try: self._rt.close_port(); self._rt.delete()
        except Exception: pass

    def __enter__(self): return self
    def __exit__(self, *e): self.close()


def listar_portas(entradas=True):
    """Todas as portas como [(indice, nome)] - sem deduplicar."""
    rt = rtmidi.MidiIn() if entradas else rtmidi.MidiOut()
    try:
        return list(enumerate(rt.get_ports()))
    finally:
        rt.delete()


def achar_portas(trecho, entradas=True):
    """[(indice, nome)] das portas cujo nome contem 'trecho'."""
    return [(i, n) for i, n in listar_portas(entradas)
            if trecho.lower() in n.lower()]


def cmd_ports():
    for rotulo, ent in (("ENTRADAS", True), ("SAIDAS", False)):
        portas = listar_portas(ent)
        vistos = {}
        for _, n in portas:
            vistos[n] = vistos.get(n, 0) + 1
        print(f"{rotulo}:")
        for i, n in portas:
            dup = "   <- nome duplicado" if vistos[n] > 1 else ""
            print(f"   [{i}] {n}{dup}")
        print()
    n_mido = len(mido.get_input_names()), len(mido.get_output_names())
    n_real = len(listar_portas(True)), len(listar_portas(False))
    if n_mido != n_real:
        print(f"(mido enxerga {n_mido[0]} in / {n_mido[1]} out por deduplicar nomes; "
              f"o real e {n_real[0]} / {n_real[1]}. Este script usa os indices reais.)")


def _programmer_mode(ligar=True):
    """Manda o SysEx de programmer mode pra todas as saidas Launchpad."""
    msg = PROG_ON if ligar else PROG_OFF
    for i, _ in achar_portas(LP_MATCH, entradas=False):
        try:
            with SaidaMIDI(i) as p:
                p.send(msg)
        except Exception:
            pass
    time.sleep(0.3)


def _esperar_pad(portas):
    """Espera um note_on de qualquer porta. Retorna (indice_porta, nota)."""
    while True:
        for idx, p in portas.items():
            for msg in p.iter_pending():
                if msg.type == 'note_on' and msg.velocity > 0:
                    return idx, msg.note
        time.sleep(0.005)


def _acender_tudo(out_idx, origem, passo_col, passo_lin, cor):
    """Pinta os 64 pads de um aparelho - usado pra confirmar identidade visual."""
    with SaidaMIDI(out_idx) as out:
        for l in range(8):
            for s in range(8):
                out.send(mido.Message('note_on', channel=0,
                                      note=origem + l*passo_lin + s*passo_col,
                                      velocity=cor))


def _confirmar_saida(lado, candidatos, palpite, geo):
    """Nomes duplicados nao distinguem aparelho: confirma acendendo o grid."""
    ordem = [palpite] + [c for c in candidatos if c != palpite]
    for out_idx in ordem:
        try:
            _acender_tudo(out_idx, geo["origem"], geo["passo_col"],
                          geo["passo_lin"], COR_VAR)
        except Exception as e:
            print(f"   [{out_idx}] nao abriu ({e})"); continue
        r = input(f"   O aparelho {lado.upper()} acendeu de azul? [s/n] ").strip().lower()
        _acender_tudo(out_idx, geo["origem"], geo["passo_col"],
                      geo["passo_lin"], COR_OFF)
        if r.startswith("s"):
            return out_idx
    print(f"   (!) nenhum candidato confirmado; ficando com [{palpite}]")
    return palpite


def cmd_learn():
    _programmer_mode(True)
    entradas = achar_portas(LP_MATCH)
    saidas   = achar_portas(LP_MATCH, entradas=False)
    if not entradas:
        print("Nenhum Launchpad encontrado. Rode 'ports'."); return
    if len(entradas) < 4:
        print(f"(!) so {len(entradas)} entradas Launchpad - esperado 4 (2 aparelhos "
              f"x DAW/MIDI). Confira 'ports'.")

    portas = {i: EntradaMIDI(i, n) for i, n in entradas}
    cfg, usadas = {}, set()
    try:
        for lado in ("esquerdo", "direito"):
            print(f"\n=== LAUNCHPAD {lado.upper()} ===")
            pedidos = [
                "pad do CANTO SUPERIOR ESQUERDO deste aparelho",
                "pad IMEDIATAMENTE A DIREITA dele",
                "pad IMEDIATAMENTE ABAIXO do primeiro",
            ]
            notas, porta = [], None
            for texto in pedidos:
                while True:                          # repete ate vir do aparelho certo
                    print(f">> Aperte o {texto}")
                    for p in portas.values():
                        p.iter_pending()             # limpa fila
                    idx, nota = _esperar_pad(portas)
                    if porta is not None and idx != porta:
                        print(f"   (!) veio da porta [{idx}], nao da [{porta}] - "
                              f"aperte no MESMO aparelho")
                        time.sleep(0.35); continue
                    if porta is None and idx in usadas:
                        print(f"   (!) a porta [{idx}] ja foi usada no outro lado - "
                              f"aperte no OUTRO aparelho")
                        time.sleep(0.35); continue
                    porta = idx
                    print(f"   nota {nota}  porta [{idx}] {portas[idx].name}")
                    notas.append(nota)
                    time.sleep(0.35)
                    break
            usadas.add(porta)
            cfg[lado] = dict(in_idx=porta, in_nome=portas[porta].name,
                             origem=notas[0],
                             passo_col=notas[1] - notas[0],
                             passo_lin=notas[2] - notas[0])
    finally:
        for p in portas.values(): p.close()

    # Saida correspondente: nomes sao identicos, entao pareia por POSICAO ordinal
    # entre as portas Launchpad (a k-esima entrada e a k-esima saida do mesmo
    # aparelho) e confirma visualmente, porque a ordem nao e garantida.
    idx_in = [i for i, _ in entradas]
    idx_out = [i for i, _ in saidas]
    print("\nConfirmando qual saida e qual aparelho (nomes sao identicos):")
    for lado in cfg:
        pos = idx_in.index(cfg[lado]["in_idx"])
        palpite = idx_out[pos] if pos < len(idx_out) else idx_out[0]
        escolhido = _confirmar_saida(lado, idx_out, palpite, cfg[lado])
        cfg[lado]["out_idx"] = escolhido
        cfg[lado]["out_nome"] = dict(saidas)[escolhido]

    if cfg["esquerdo"]["out_idx"] == cfg["direito"]["out_idx"]:
        print("\n(!) os dois lados ficaram com a MESMA saida - rode 'learn' de novo.")

    # O que de fato identifica o aparelho e a POSICAO dele entre os Launchpad -
    # o indice global muda toda vez que outro aparelho MIDI entra ou sai (foi o
    # bug de 16/08: a interface de audio desligada derrubava o app inteiro).
    # O snapshot continua salvo, mas so como diagnostico e para migrar layouts
    # antigos; quem manda agora e o ordinal.
    nomes_in  = [n for _, n in listar_portas(True)]
    nomes_out = [n for _, n in listar_portas(False)]
    g_in, g_out = _grupo_lp(nomes_in), _grupo_lp(nomes_out)
    for lado in ("esquerdo", "direito"):
        if cfg[lado]["in_idx"] in g_in:
            cfg[lado]["in_ord"] = g_in.index(cfg[lado]["in_idx"])
        if cfg[lado]["out_idx"] in g_out:
            cfg[lado]["out_ord"] = g_out.index(cfg[lado]["out_idx"])
    cfg["_portas_in"]  = nomes_in
    cfg["_portas_out"] = nomes_out

    with open(LAYOUT_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

    print("\nLayout salvo:")
    for lado in ("esquerdo", "direito"):
        c = cfg[lado]
        print(f"  {lado:9} origem={c['origem']:3}  +coluna={c['passo_col']:+3}  "
              f"+linha={c['passo_lin']:+3}")
        print(f"            in  [{c['in_idx']}] {c['in_nome']}")
        print(f"            out [{c['out_idx']}] {c['out_nome']}")
        for l in range(8):
            print("            " + " ".join(
                f"{c['origem'] + l*c['passo_lin'] + s*c['passo_col']:3}" for s in range(8)))


def _grupo_lp(nomes):
    """Indices das portas Launchpad, na ordem em que o CoreMIDI as lista."""
    return [i for i, n in enumerate(nomes) if LP_MATCH.lower() in n.lower()]


def resolver_layout(cfg, portas_in, portas_out):
    """Reconfere o layout salvo contra a enumeracao de agora.

    Devolve (cfg_resolvido, [mensagens]) ou (None, [motivos]).

    POR QUE ISTO EXISTE (16/08/2026). A guarda anterior comparava a lista
    INTEIRA de nomes de porta por igualdade. Como o indice do CoreMIDI e
    posicional, desligar a interface de audio - que nem faz parte do projeto -
    empurrava tudo uma casa e derrubava o app com "Aperte Recalibrar". E
    recalibrar era a acao ERRADA: refazia o learn sem a interface, e religa-la
    quebrava de novo, no sentido inverso. Um ciclo vicioso.

    O que de fato importa e o GRUPO Launchpad: se ele esta igual (mesmo
    tamanho, mesma sequencia de nomes), a k-esima porta Launchpad continua
    sendo o mesmo aparelho, esteja ela no indice 4 ou no 6. Qualquer coisa
    fora do grupo pode ir e vir a vontade.

    LIMITE HONESTO: os dois Mini MK3 tem nome IDENTICO, entao o ordinal e a
    unica forma de distingui-los sem o learn. Se o CoreMIDI trocar os dois de
    posicao entre si, isto aceita e o grid sai espelhado. A guarda antiga
    tambem nao pegava esse caso (a lista de nomes ficaria identica), entao nao
    e regressao - mas e o motivo de o 'learn' confirmar acendendo o aparelho,
    e a unica prova continua sendo o olho."""
    msgs = []
    if "porta_in" in cfg.get("esquerdo", {}):
        return None, ["layout no formato antigo (portas por nome) - rode 'learn'"]

    g_atual_in, g_atual_out = _grupo_lp(portas_in), _grupo_lp(portas_out)
    snap_in, snap_out = cfg.get("_portas_in"), cfg.get("_portas_out")

    for rot, snap, atual, g_atual in (("entrada", snap_in, portas_in, g_atual_in),
                                      ("saida", snap_out, portas_out, g_atual_out)):
        if snap is None:
            continue
        g_snap = _grupo_lp(snap)
        if len(g_snap) != len(g_atual):
            return None, [f"o conjunto de Launchpad mudou na {rot}: o learn viu "
                          f"{len(g_snap)} portas, agora ha {len(g_atual)}. "
                          "Rode 'learn' de novo."]
        if [snap[i] for i in g_snap] != [atual[i] for i in g_atual]:
            return None, [f"a ordem das portas Launchpad mudou na {rot}. "
                          "Rode 'learn' de novo."]

    novo = json.loads(json.dumps(cfg))          # copia funda, nao mexe no salvo
    for lado in ("esquerdo", "direito"):
        c = novo.get(lado)
        if not c:
            return None, [f"layout sem o lado {lado} - rode 'learn'"]
        for chave, ordch, grupo, snap in (("in_idx", "in_ord", g_atual_in, snap_in),
                                          ("out_idx", "out_ord", g_atual_out, snap_out)):
            ordinal = c.get(ordch)
            if ordinal is None:
                # layout anterior a 16/08: o ordinal se deduz do snapshot
                if snap is None:
                    return None, ["layout velho demais (sem ordinal e sem "
                                  "snapshot de portas) - rode 'learn' de novo"]
                g_snap = _grupo_lp(snap)
                if c[chave] not in g_snap:
                    return None, [f"o {chave} salvo do {lado} nao era uma porta "
                                  "Launchpad - rode 'learn' de novo"]
                ordinal = g_snap.index(c[chave])
            if ordinal >= len(grupo):
                return None, [f"nao ha porta Launchpad numero {ordinal + 1} - "
                              "rode 'learn' de novo"]
            antes = c[chave]
            c[chave], c[ordch] = grupo[ordinal], ordinal
            if antes != c[chave]:
                msgs.append(f"porta do {lado} deslocada desde o learn: "
                            f"{chave} [{antes}] -> [{c[chave]}]")

    if novo["esquerdo"]["out_idx"] == novo["direito"]["out_idx"]:
        return None, ["os dois lados cairam na MESMA saida - rode 'learn'"]
    if msgs:
        msgs.append("(algum aparelho MIDI entrou ou saiu; reresolvi pelo nome "
                    "e pela posicao entre os Launchpad, sem precisar recalibrar)")
    return novo, msgs


def carregar_layout_resolvido(caminho=LAYOUT_FILE):
    """(cfg, mensagens) do layout em disco, ja reresolvido. cfg=None se recusado."""
    if not os.path.exists(caminho):
        return None, ["nenhum layout salvo - rode 'learn' (ou aperte Recalibrar)"]
    try:
        with open(caminho) as f:
            cfg = json.load(f)
    except Exception as e:
        return None, [f"layout ilegivel: {e}"]
    return resolver_layout(cfg, [n for _, n in listar_portas(True)],
                           [n for _, n in listar_portas(False)])


def carregar_layout():
    cfg, msgs = carregar_layout_resolvido()
    for m in msgs:
        print(("(!) " if cfg is None else "    ") + m)
    if cfg is None:
        sys.exit(1)
    return cfg


def cmd_probe():
    """Imprime tudo que chega - use pra descobrir os CCs dos botoes."""
    _programmer_mode(True)
    portas = {i: EntradaMIDI(i, n) for i, n in achar_portas(LP_MATCH)}
    if not portas:
        print("Nenhum Launchpad encontrado. Rode 'ports'."); return
    print("Aperte qualquer botao. Ctrl+C pra sair.\n")
    try:
        while True:
            for idx, p in portas.items():
                for msg in p.iter_pending():
                    if msg.type in ('note_on', 'control_change'):
                        if getattr(msg, 'velocity', 1) == 0: continue
                        if getattr(msg, 'value', 1) == 0: continue
                        curto = p.name.split("Launchpad")[-1].strip()[:24]
                        print(f"[{idx}] {curto:26} {msg}")
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        for p in portas.values(): p.close()


def cmd_colors():
    """Acende a paleta: indices 0-63 no esquerdo, 64-127 no direito."""
    _programmer_mode(True)
    cfg = carregar_layout()
    for base, lado in ((0, "esquerdo"), (64, "direito")):
        c = cfg[lado]
        with SaidaMIDI(c["out_idx"], c["out_nome"]) as out:
            for l in range(8):
                for s in range(8):
                    nota = c["origem"] + l*c["passo_lin"] + s*c["passo_col"]
                    out.send(mido.Message('note_on', channel=0, note=nota,
                                          velocity=base + l*8 + s))
    print("Esquerdo = indices 0-63 (linha a linha), direito = 64-127.")
    print("Anote os que gostar e troque as constantes COR_* no topo do arquivo.")


# ─────────────────────────────────────────────────────────────
# TR-8S: leitura
# ─────────────────────────────────────────────────────────────
def ler_bloco(tr_in, tr_out, addr, tamanho=128, timeout=APC_TIMEOUT):
    tr_out.send(rq1(addr, tamanho))
    limite = time.time() + timeout
    while time.time() < limite:
        for msg in tr_in.iter_pending():
            if msg.type != 'sysex': continue
            d = list(msg.data)
            if len(d) < 12 or d[:6] != HDR or d[6] != DT1: continue
            if tuple(d[7:11]) == tuple(addr):
                return d[11:-1]
        time.sleep(0.005)
    return None


def pattern_corrente(tr_in, tr_out):
    """Indice do pattern que a maquina tem carregado, ou None.

    Todo endereco da regiao de pattern depende dele (segundo byte =
    pattern*16 + variacao). Quem monta endereco sem perguntar isto observa um
    pattern que nao e o que esta tocando."""
    d = ler_bloco(tr_in, tr_out, ADDR_PERF, 128, timeout=SNAP_TIMEOUT)
    return d[OFF_PATTERN_ATUAL] if d and len(d) > OFF_PATTERN_ATUAL else None


def _portas_tr8s():
    """(indice_in, indice_out) da porta CTRL, ou (None, None)."""
    i = achar_portas(TR8S_MATCH)
    o = achar_portas(TR8S_MATCH, entradas=False)
    return (i[0] if i else None), (o[0] if o else None)


def _porta_comum(entradas=True):
    """A porta 'TR-8S' comum (nao a CTRL): manda o MIDI clock e recebe os CCs."""
    cands = [(i, n) for i, n in achar_portas("TR-8S", entradas)
             if "CTRL" not in n.upper()]
    return cands[0] if cands else None


def _porta_clock():
    return _porta_comum(True)


def cmd_dump():
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    with EntradaMIDI(*tin) as tin, SaidaMIDI(*tout) as tout:
        p = pattern_corrente(tin, tout)
        if p is None:
            print("(!) nao consegui ler o pattern corrente."); return
        print(f"pattern {nome_pattern(p)}, variacao {VARIACOES[VARIACAO-1]}\n")
        cab = ler_bloco(tin, tout, addr_accent_rd(VARIACAO, p), 8)
        if cab:
            print(f"ACCENT = 0x{nibbles_para_mascara(cab[:4]):04X}\n")
        for i, nome in enumerate(INSTRUMENTOS):
            d = ler_bloco(tin, tout, addr_bloco_rd(i, VARIACAO, p))
            if d is None:
                print(f"{nome}: sem resposta"); continue
            ligados = []
            for s in range(16):
                b = s * BYTES_P_STEP
                v = (d[b+VEL_HI] << 4) | d[b+VEL_LO]
                if v:
                    t = MODOS[d[b+SUB_BYTE]][0] if d[b+SUB_BYTE] < len(MODOS) else "?"
                    ligados.append(f"{s+1}({v}{'' if t=='NORMAL' else '/'+t})")
            print(f"{nome}: " + (" ".join(ligados) if ligados else "-"))


# ─────────────────────────────────────────────────────────────
# Engenharia reversa: snapshot do estado e escuta passiva
#
# Dois metodos, porque nenhum sozinho ve tudo:
#
#   snap/snapdiff  le a maquina com RQ1 antes e depois de um gesto no painel e
#                  compara. Ve qualquer coisa que seja ESTADO guardado no pattern
#                  ou no kit. Nao ve comandos (WRITE), que nao deixam rastro.
#
#   sniff          escuta o que a TR-8S TRANSMITE. Ve comandos, se ela os
#                  transmitir. ATENCAO: nao e substituto do MIDI Monitor - o
#                  rtmidi so enxerga a saida da maquina, nunca o que o TR-EDITOR
#                  manda PARA ela (o MIDI Monitor consegue porque usa a API
#                  privada de espionagem do CoreMIDI, que o rtmidi nao expoe).
#                  Ainda assim vale: o editor se mantem sincronizado quando voce
#                  mexe no painel, entao a maquina provavelmente transmite DT1
#                  dos gestos do painel. Se transmitir, [WRITE] apertado no
#                  PAINEL cai aqui e nao precisamos do editor pra nada.
# ─────────────────────────────────────────────────────────────
SNAP_TIMEOUT = 0.4        # a maquina responde em ~20 ms; endereco invalido cala


def _addrs_do_snapshot(var, pattern, incluir_kit=True, incluir_motion=False):
    """[(rotulo, endereco, tamanho)] dos enderecos CONHECIDOS. Ver REFERENCIA 2.3.

    Sao ~50, e todos moram no pattern ou no kit. Isso basta para o que ja foi
    decodificado, mas e cego para estado de PERFORMANCE - o mute, por exemplo, que
    o manual em lugar nenhum diz ser salvo no pattern. Para esses casos existe o
    'varrer', cujo resultado entra aqui pelo snap --amplo."""
    base = addr_variacao(pattern, var)
    alvos = [(f"var {var:02X} cabecalho", base, 8)]

    # 20 0V hh 08: instrumento I comeca no offset I*128+8, entao hh = I.
    # 0x00-0x0A sao os 11 instrumentos, 0x0B e o TRG (11*128+8 = 1416), e
    # 0x0C-0x18 sao blocos que nunca foram lidos.
    for hh in range(0x00, 0x19):
        if hh < len(INSTRUMENTOS):   rotulo = f"var {var:02X} {INSTRUMENTOS[hh]}"
        elif hh == 0x0B:             rotulo = f"var {var:02X} TRG?"
        else:                        rotulo = f"var {var:02X} bloco {hh:02X}?"
        alvos.append((rotulo, addr_soma(base, hh * 128 + 8), 128))

    if incluir_motion:
        alvos.append((f"var {var:02X} motion",
                      addr_soma(base, 0x19 * 128 + 8), 1664))

    # variacao 0x00 = o NO DO PATTERN (nome, last steps, kitReference). Ja nao
    # e palpite: e onde o TR-EDITOR le o cabecalho, 193 bytes.
    alvos.append(("no do pattern", addr_no_pattern(pattern), 193))

    # A REGIAO DE PERFORMANCE, que o snapshot ignorava - e por isso ele era
    # "cego para estado de performance". Nao e leitura nova nem arriscada: e
    # exatamente a que o tick faz a cada 1,5 s (mute, step atual, tempo).
    # Sem ela, um snapdiff nao enxerga QUAL VARIACAO TOCA, o AUTO FILL IN nem
    # o tempo - tres coisas que a sessao de 17/08/2026 precisou e nao tinha.
    alvos.append(("performance", ADDR_PERF, 128))

    if incluir_kit:
        alvos.append(("kit nome", (0x10, 0x00, 0x00, 0x00), 16))
        for i, nome in enumerate(INSTRUMENTOS):
            alvos.append((f"kit tone {nome}",  (0x10, 0x00, 0x10 + i, 0x00), 128))
        for i, nome in enumerate(INSTRUMENTOS):
            alvos.append((f"kit param {nome}", (0x10, 0x00, 0x20 + i, 0x00), 128))
    return alvos


def _chave(addr):
    return " ".join(f"{x:02X}" for x in addr)


def _alvos_da_varredura(caminho):
    """Le o JSON do 'varrer' e devolve os alvos que responderam."""
    try:
        with open(caminho) as f:
            j = json.load(f)
    except Exception as e:
        print(f"(!) nao consegui ler {caminho}: {e}"); return []
    return [(a["rotulo"], tuple(a["addr"]), a["tam"]) for a in j.get("achados", [])]


def cmd_snap(argv):
    posicionais = [a for a in argv if not a.startswith("-")]
    destino = posicionais[0] if posicionais else None
    if not destino:
        print("Uso: snap <arquivo.json> [--var N|todas] [--motion] [--sem-kit] "
              "[--amplo <varredura.json>]")
        return
    incluir_kit    = "--sem-kit" not in argv
    incluir_motion = "--motion" in argv

    vars_ = [VARIACAO]
    if "--var" in argv:
        v = argv[argv.index("--var") + 1]
        vars_ = list(range(1, 11)) if v.startswith("t") else [int(v)]

    # --amplo: acrescenta tudo que o 'varrer' achou. Sem isso o snapdiff continua
    # cego fora dos ~50 conhecidos, e um mute que more em 00 03 passaria batido
    # como se nao existisse - que e exatamente a conclusao errada a se tirar.
    extras = []
    if "--amplo" in argv:
        i = argv.index("--amplo") + 1
        caminho = argv[i] if i < len(argv) and not argv[i].startswith("-") else None
        if not caminho:
            print("--amplo precisa do arquivo do 'varrer'. "
                  "Rode: varrer varredura.json"); return
        extras = _alvos_da_varredura(caminho)
        if not extras:
            print(f"(!) {caminho} nao tem nenhum endereco. Rode o 'varrer' primeiro.")
            return
        print(f"--amplo: +{len(extras)} enderecos de {caminho}")

    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada. A TR-8S esta ligada?"); return

    # o snapshot precisa saber QUAL pattern esta carregado: os enderecos da
    # regiao de pattern dependem dele, e um snap do pattern errado vira "fato"
    # na REFERENCIA sem ninguem desconfiar
    with EntradaMIDI(*tin) as _ti, SaidaMIDI(*tout) as _to:
        pattern = pattern_corrente(_ti, _to)
    if pattern is None:
        print("(!) nao consegui ler o pattern corrente; sem isso o snapshot "
              "leria outro pattern."); return
    print(f"pattern carregado: {nome_pattern(pattern)}")

    alvos = []
    for v in vars_:
        alvos += _addrs_do_snapshot(v, pattern, incluir_kit,
                                    incluir_motion)
    # os conhecidos vao primeiro: a deduplicacao abaixo guarda a PRIMEIRA ocorrencia,
    # e num empate a leitura conhecida (com rotulo e tamanho certos) vale mais que a
    # sonda de 1 byte que a varredura deixou no mesmo endereco
    alvos += extras
    # varias variacoes repetem os enderecos de kit e de pattern; le uma vez so
    vistos, unicos = set(), []
    for rotulo, addr, tam in alvos:
        if addr in vistos: continue
        vistos.add(addr); unicos.append((rotulo, addr, tam))

    dados, mudos = {}, 0
    with EntradaMIDI(*tin) as tr_in, SaidaMIDI(*tout) as tr_out:
        for n, (rotulo, addr, tam) in enumerate(unicos, 1):
            tr_in.iter_pending()                     # descarta keep-alive pendente
            d = ler_bloco(tr_in, tr_out, addr, tam, timeout=SNAP_TIMEOUT)
            if d is None: mudos += 1
            dados[_chave(addr)] = {"rotulo": rotulo, "dados": d}
            print(f"\r  {n}/{len(unicos)}  {rotulo:22} "
                  f"{'sem resposta' if d is None else str(len(d)) + ' bytes':14}",
                  end="", flush=True)
    print()

    with open(destino, "w") as f:
        json.dump({"variacoes": vars_, "pattern": pattern,
                   "blocos": dados}, f)
    resp = len(unicos) - mudos
    print(f"{destino}: {resp} enderecos responderam, {mudos} calaram "
          f"(calar = endereco que nao existe).")


def _e_regiao_pattern(addr):
    """O endereco cai na regiao de pattern?

    Nao da mais para testar `addr[0] == 0x20`: o primeiro byte e
    0x20 + ((pattern*16 + var) >> 7), ou seja 0x20 so ate o pattern 7. No
    pattern 3-06, por exemplo, os enderecos comecam com 0x24 - e a traducao
    de offset parava de aparecer justamente nos patterns onde se estava
    trabalhando."""
    return 0x20 <= addr[0] <= 0x2F


def _traduzir_offset(addr, i, tamanho):
    """Offset cru -> o que ele significa naquele endereco."""
    if tamanho == 128 and _e_regiao_pattern(addr) and addr[3] == 0x08:
        step, campo = divmod(i, BYTES_P_STEP)
        return f"step {step + 1:2}, byte {campo}"
    if tamanho == 8 and _e_regiao_pattern(addr) and addr[2] == 0x00 and addr[3] == 0x00:
        # bytes 0-3 = mascara de ACCENT em nibbles; 4-7 = o resto do cabecalho
        # da variacao, ainda sem nome (candidatos: last step, scale, shuffle)
        return f"nibble {i} do ACCENT" if i < 4 else f"cabecalho byte {i}"
    return ""


def cmd_snapdiff(p1, p2):
    def carregar(p):
        with open(p) as f:
            j = json.load(f)
        return {k: v for k, v in j["blocos"].items()}, j.get("pattern")

    (a, pa), (b, pb) = carregar(p1), carregar(p2)
    # Os enderecos da regiao de pattern DEPENDEM do pattern carregado, e o
    # diff casa bloco por endereco. Dois snaps de patterns diferentes nao tem
    # endereco em comum ali, e o `if chave not in b: continue` engolia todos:
    # o diff dizia "nada mudou" e a conclusao ("esse parametro nao mora no
    # pattern") virava fato na REFERENCIA. Recusar e a resposta certa.
    if pa != pb:
        def rot(p):
            return "desconhecido (snap antigo)" if p is None else nome_pattern(p)
        print(f"(!) os dois snapshots sao de patterns DIFERENTES: "
              f"{p1} = {rot(pa)}, {p2} = {rot(pb)}.\n"
              "    Os enderecos da regiao de pattern dependem do pattern, "
              "entao comparar\n    os dois nao diria nada - e o silencio "
              "pareceria 'nada mudou'.")
        return
    if pa is not None:
        print(f"pattern {nome_pattern(pa)}\n")
    achou = False

    for chave in a:
        if chave not in b: continue
        da, db = a[chave]["dados"], b[chave]["dados"]
        if da == db: continue
        addr = tuple(int(x, 16) for x in chave.split())
        rotulo = a[chave]["rotulo"]
        if da is None or db is None:
            print(f"\n### {chave}  ({rotulo})  respondeu num arquivo e no outro nao")
            achou = True; continue
        achou = True
        print(f"\n### {chave}  ({rotulo})")
        for i, (x, y) in enumerate(zip(da, db)):
            if x == y: continue
            extra = _traduzir_offset(addr, i, len(da))
            print(f"  offset {i:5} (0x{i:03X}): {x:02X} -> {y:02X}"
                  f"{'   -> ' + extra if extra else ''}")
        if len(da) != len(db):
            print(f"  (tamanhos diferentes: {len(da)} vs {len(db)})")

    for chave in b:
        if chave not in a:
            print(f"Endereco so em {p2}: {chave}"); achou = True

    if not achou:
        print("Nenhuma diferenca. O gesto no painel nao mexeu em nenhum endereco "
              "que sabemos ler - ou nao mexeu em nada.")


def cmd_sniff(argv):
    arquivo = None
    if "--arquivo" in argv:
        arquivo = argv[argv.index("--arquivo") + 1]

    tin, tout = _portas_tr8s()
    if not tin:
        print("Porta TR-8S CTRL nao encontrada."); return

    f = open(arquivo, "w") if arquivo else None
    print(f"Escutando [{tin[0]}] {tin[1]}."
          f"{'  Gravando em ' + arquivo if arquivo else ''}")

    vistos = 0
    try:
        with EntradaMIDI(*tin) as tr_in:
            # AUTOTESTE: manda um RQ1 e confere que a resposta chega por este
            # mesmo caminho. Sem ele, "nao apareceu nada" seria ambiguo entre a
            # maquina estar calada e o nosso listener estar surdo - e a conclusao
            # errada iria parar na REFERENCIA como se fosse achado.
            if tout:
                tr_in.iter_pending()
                with SaidaMIDI(*tout) as t_out:
                    # liveness: o no do pattern 0 existe sempre e nao depende
                    # de saber onde a maquina esta
                    t_out.send(rq1(ADDR_PATTERN_ZERO, 8))
                limite, ecoou = time.time() + 1.5, False
                while time.time() < limite and not ecoou:
                    for msg in tr_in.iter_pending():
                        if msg.type == 'sysex' and list(msg.data)[:6] == HDR:
                            ecoou = True
                    time.sleep(0.005)
                print("autoteste: " + ("a maquina respondeu ao RQ1 aqui - o "
                      "listener esta bom, entao silencio daqui pra frente e "
                      "silencio de verdade." if ecoou else
                      "(!) a maquina NAO respondeu nem ao RQ1. O problema e a "
                      "porta ou o listener, nao o silencio dela. Confira se o "
                      "TR-EDITOR ou o app estao abertos segurando a CTRL."))
            print("\nMexa no painel da TR-8S. Ctrl+C pra sair.\n")
            while True:
                for msg in tr_in.iter_pending():
                    if msg.type != 'sysex': continue
                    d = list(msg.data)
                    if len(d) < 12 or d[:6] != HDR: continue
                    addr = tuple(d[7:11])
                    if addr in ((0x00, 0x03, 0x00, 0x3B), (0x00, 0x03, 0x00, 0x36)):
                        continue                      # keep-alive do editor
                    corpo = d[11:-1]
                    cmd = {RQ1: "RQ1", DT1: "DT1"}.get(d[6], f"{d[6]:02X}")
                    vistos += 1
                    print(f"{time.strftime('%H:%M:%S')}  {cmd}  {_chave(addr)}  "
                          f"{len(corpo):4}B  "
                          + " ".join(f"{x:02X}" for x in corpo[:16])
                          + ("..." if len(corpo) > 16 else ""))
                    if f:
                        # formato que o tr8s_sysex.py parse consegue ler
                        f.write("  " + time.strftime('%H:%M:%S') + "   From TR-8S   "
                                + " ".join(f"{x:02X}" for x in
                                           [0xF0] + d + [0xF7]) + "\n")
                        f.flush()
                time.sleep(0.005)
    except KeyboardInterrupt:
        print(f"\n{vistos} mensagens.")
    finally:
        if f: f.close()


# ─────────────────────────────────────────────────────────────
# varrer: mapa de quais enderecos a maquina reconhece
#
# Endereco invalido CALA (verificado: e assim que o snap conta os "mudos"), entao
# uma sonda de 1 byte em cada candidato desenha o mapa do que existe. O silencio e
# a propria informacao.
#
# A aposta mais forte esta na REFERENCIA 2.1: o TR-EDITOR faz keep-alive a cada 3 s
# em 00 03 00 3B e 00 03 00 36. Como a maquina nao empurra estado (o sniff provou),
# o editor SO pode se manter sincronizado relendo - e a regiao 00 03 e onde ele
# rele. Candidata natural a "estado corrente", que e o que o mute provavelmente e.
# ─────────────────────────────────────────────────────────────
VARRER_TIMEOUT = 0.15     # a maquina responde em ~20 ms; isto e 7x de folga
VARRER_PAUSA   = 0.004    # respiro entre sondas; a REFERENCIA usa 0.002 nas rajadas
VARRER_PULSO   = 25       # reconferir que a maquina esta viva a cada N sondas

# RQ1 EM ENDERECO INVALIDO ENVENENA A PORTA CTRL (medido em 14/08/2026).
# Depois de ~60-75 sondas em enderecos que nao existem, a TR-8S para de responder
# a QUALQUER RQ1 - inclusive aos enderecos conhecidos que respondiam um segundo
# antes. Nao se recupera sozinha (testado ate 30 s); so religando a maquina.
#
# Leitura VALIDA nao faz isso: o run() rele a maquina a cada 1,5 s por horas, e o
# snap dos ~50 conhecidos passa inteiro. O veneno e perguntar pelo que nao existe.
#
# Por isso a varredura anda em LOTES e guarda o progresso: cada retomada custa uma
# religada, que e uma acao humana, entao perder o lote inteiro sai caro.
VARRER_LOTE = 50          # abaixo do limiar observado, com folga


def _candidatos_varredura():
    """[(rotulo, endereco, tamanho_no_snap)], do palpite mais forte ao mais fraco.

    O tamanho e o que o snap --amplo vai LER depois, nao o da sonda (que e sempre
    1 byte). Na regiao fina ele e 1 porque varremos byte a byte e a soma ja cobre
    a regiao inteira; nas sondas de bloco e 128, que e o tamanho de bloco que a
    maquina usa em todo o resto do mapa."""
    alvos = []
    for lo in range(0x00, 0x80):
        alvos.append((f"estado corrente? +{lo}", (0x00, 0x03, 0x00, lo), 1))
    for hi in range(0x00, 0x10):
        alvos.append((f"sistema {hi:02X}?", (0x00, hi, 0x00, 0x00), 128))
    for hh in range(0x2B, 0x80):
        alvos.append((f"kit bloco {hh:02X}?", (0x10, 0x00, hh, 0x00), 128))
    for hh in range(0x01, 0x80):
        alvos.append((f"pattern bloco {hh:02X}?", (0x20, 0x00, hh, 0x00), 128))
    for base in (0x30, 0x40, 0x50, 0x60, 0x70):
        alvos.append((f"base {base:02X}?", (base, 0x00, 0x00, 0x00), 128))
    # o mesmo endereco cai em duas listas (00 03 00 00 e sondado fino e como bloco):
    # a primeira ocorrencia vence, que e a fina
    vistos, unicos = set(), []
    for rotulo, addr, tam in alvos:
        if addr in vistos: continue
        vistos.add(addr); unicos.append((rotulo, addr, tam))
    return unicos


def _ler_parcial(caminho):
    """O que uma corrida anterior ja sondou. Ver o comentario de VARRER_LOTE."""
    try:
        with open(caminho) as f:
            j = json.load(f)
        return j.get("achados", []), int(j.get("sondados_ate", 0))
    except Exception:
        return [], 0


def cmd_varrer(argv):
    posicionais = [a for a in argv if not a.startswith("-")]
    destino = posicionais[0] if posicionais else None
    if not destino:
        print("Uso: varrer <saida.json> [--de N] [--lote N]")
        return

    alvos = _candidatos_varredura()
    achados, sondados_ate = _ler_parcial(destino)
    inicio = sondados_ate
    if "--de" in argv:
        inicio = int(argv[argv.index("--de") + 1])
    lote = VARRER_LOTE
    if "--lote" in argv:
        lote = int(argv[argv.index("--lote") + 1])

    if inicio >= len(alvos):
        print(f"{destino} ja cobre os {len(alvos)} candidatos. "
              f"{len(achados)} responderam."); return
    fim = min(len(alvos), inicio + lote)

    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada. A TR-8S esta ligada? "
              "O TR-EDITOR ou o app podem estar segurando a porta."); return

    def vivo(tr_in, tr_out):
        """A maquina ainda responde num endereco que sabidamente existe?"""
        tr_in.iter_pending()
        return ler_bloco(tr_in, tr_out, ADDR_PATTERN_ZERO, 8, timeout=1.0) is not None

    def gravar(ate):
        with open(destino, "w") as f:
            json.dump({"achados": achados, "sondados_ate": ate,
                       "total_candidatos": len(alvos)}, f, indent=1)

    def como_retomar(ate):
        return (f"\nProgresso salvo em {destino} ({ate}/{len(alvos)}).\n"
                f"Religue a TR-8S e retome com:\n"
                f"  python3 lp_tr8s.py varrer {destino}")

    with EntradaMIDI(*tin) as tr_in, SaidaMIDI(*tout) as tr_out:
        # AUTOTESTE, mesma logica do sniff - mas PERIODICO, nao so no comeco.
        # A primeira versao conferia uma vez e saiu com 15 "achados" que nao
        # reproduziram: a maquina tinha parado de responder no meio da varredura e
        # nada avisou. Um mapa assim e pior que mapa nenhum, porque parece achado.
        if not vivo(tr_in, tr_out):
            print("(!) a maquina nao respondeu nem no endereco de pattern, que "
                  "sabidamente existe. O problema e a porta, nao o silencio dela. "
                  "Feche o TR-EDITOR e o TR-8S Grid.app e confira se a TR-8S esta "
                  "ligada e com o cabo USB no lugar.")
            return
        print(f"autoteste ok. Sondas {inicio+1}..{fim} de {len(alvos)}, "
              f"reconferindo a cada {VARRER_PULSO}.\n")

        n = inicio
        for n in range(inicio, fim):
            rotulo, addr, tam = alvos[n]
            if (n - inicio) and (n - inicio) % VARRER_PULSO == 0 \
                    and not vivo(tr_in, tr_out):
                gravar(n)
                print(f"\n(!) a maquina parou de responder na sonda {n}. Parando: "
                      "o resto leria silencio de porta como silencio de endereco, "
                      "e o mapa sairia mentindo." + como_retomar(n))
                return
            tr_in.iter_pending()                     # descarta keep-alive pendente
            d = ler_bloco(tr_in, tr_out, addr, 1, timeout=VARRER_TIMEOUT)
            if d is not None:
                achados.append({"rotulo": rotulo, "addr": list(addr), "tam": tam})
            print(f"\r  {n+1}/{len(alvos)}  {_chave(addr)}  "
                  f"{len(achados)} responderam   ", end="", flush=True)
            time.sleep(VARRER_PAUSA)
        print()
        n = fim

        # SEGUNDO PASSE: quem respondeu tem que responder de novo. Endereco de
        # verdade nao e intermitente; falso positivo e.
        if achados:
            print(f"conferindo os {len(achados)} achados...")
            confirmados = []
            for a in achados:
                tr_in.iter_pending()
                if ler_bloco(tr_in, tr_out, tuple(a["addr"]), 1,
                             timeout=VARRER_TIMEOUT) is not None:
                    confirmados.append(a)
                time.sleep(VARRER_PAUSA)
            descartados = len(achados) - len(confirmados)
            if descartados:
                print(f"  {descartados} nao repetiram e foram descartados.")
            achados = confirmados
        if not vivo(tr_in, tr_out):
            gravar(inicio)          # este lote nao vale: volta ao ponto de partida
            print("(!) a maquina caiu antes do fim do lote. As sondas deste lote "
                  "foram descartadas." + como_retomar(inicio))
            return
        gravar(n)

    if n < len(alvos):
        print(f"\nLote ok: {n}/{len(alvos)} sondados, {len(achados)} responderam "
              f"ate agora. Continue com:\n"
              f"  python3 lp_tr8s.py varrer {destino}")
        return
    if not achados:
        print("Nenhum endereco novo respondeu, e a maquina estava viva do inicio "
              "ao fim. O mapa conhecido e o mapa inteiro que ela expoe por estes "
              "candidatos - isso e resultado, nao falha.")
        return
    print(f"\n{destino}: {len(achados)} de {len(alvos)} responderam.\n")
    # agrupa por prefixo pra caber na tela: 128 enderecos seguidos viram uma linha
    grupos = {}
    for a in achados:
        grupos.setdefault(tuple(a["addr"][:2]), []).append(a["addr"])
    for pref, lista in sorted(grupos.items()):
        print(f"  {pref[0]:02X} {pref[1]:02X}: {len(lista):3} enderecos, "
              f"de {_chave(lista[0])} a {_chave(lista[-1])}")
    print(f"\nAgora: snap base.json --amplo {destino}")


# ─────────────────────────────────────────────────────────────
# escutar: listener amplo na porta TR-8S COMUM
#
# O sniff so ve SysEx na CTRL, e ja provou que ela e muda para gestos de painel.
# Este ve TUDO na porta comum, que e outra coisa: e por ela que a maquina manda as
# notas do proprio sequenciador. Se a nota de um track sumir quando ele e mutado,
# da pra inferir mute SEM endereco nenhum.
#
# RESSALVA GRANDE (REFERENCIA secao 6): se o UTILITY:MIDI:Inst Note estiver em
# '---' nos 11 instrumentos - que e a receita anotada la para matar as notas
# fantasma na cadeia DIN - a maquina nao manda nota nenhuma e este canal nao
# existe. Conferir antes de concluir qualquer coisa a partir do silencio.
# ─────────────────────────────────────────────────────────────
NOTAS_INST = {36: "BD", 38: "SD", 43: "LT", 47: "MT", 50: "HT", 37: "RS",
              39: "HC", 42: "CH", 46: "OH", 49: "CC", 51: "RC"}
NOTAS_INST_ALT = {35: "BD", 40: "SD", 41: "LT", 45: "MT", 48: "HT", 56: "RS",
                  54: "HC", 44: "CH", 55: "OH", 61: "CC", 63: "RC"}


def cmd_escutar(argv):
    # --segundos existe porque um escutar sem fim, morto a forca pelo timeout de
    # quem o chamou, deixa a porta rtmidi aberta - e foi logo depois de um desses
    # que a CTRL emudeceu em 14/08/2026. Sair sozinho fecha tudo pelo __exit__.
    segundos = None
    if "--segundos" in argv:
        segundos = float(argv[argv.index("--segundos") + 1])

    porta = _porta_comum(True)
    if not porta:
        print("Porta TR-8S comum nao encontrada. A TR-8S esta ligada?"); return

    print(f"Escutando [{porta[0]}] {porta[1]} - todos os tipos de mensagem.")
    # active sensing NAO ignorado: e o unico sinal continuo que prova o listener
    with EntradaMIDI(*porta, ignorar_sense=False) as tr_in:
        limite, vivo = time.time() + 2.0, None
        while time.time() < limite and vivo is None:
            for msg in tr_in.iter_pending():
                if msg.type in ('active_sensing', 'clock'):
                    vivo = msg.type
            time.sleep(0.005)
        print("autoteste: " + (
            f"chegou {vivo} - o listener esta bom, entao silencio daqui pra "
            "frente e silencio de verdade." if vivo else
            "(!) nao chegou nem active sensing nem clock. Nao da pra distinguir "
            "maquina calada de listener surdo - conserte isso antes de concluir "
            "qualquer coisa."))
        print(f"\nMexa no painel da TR-8S. "
              f"{'Ctrl+C pra sair.' if segundos is None else f'{segundos:.0f} s.'}\n")

        contagem, ultimo_clock = {}, [0]
        fim = None if segundos is None else time.time() + segundos
        try:
            while fim is None or time.time() < fim:
                for msg in tr_in.iter_pending():
                    if msg.type in ('active_sensing', 'clock'):
                        ultimo_clock[0] += 1        # so conta, nao imprime
                        continue
                    rotulo = ""
                    if msg.type in ('note_on', 'note_off'):
                        nome = (NOTAS_INST.get(msg.note)
                                or NOTAS_INST_ALT.get(msg.note))
                        if nome:
                            rotulo = f"  <- {nome}" + (
                                " (ALT)" if msg.note in NOTAS_INST_ALT else "")
                        if msg.type == 'note_on' and msg.velocity:
                            contagem[nome or msg.note] = \
                                contagem.get(nome or msg.note, 0) + 1
                    if segundos is None:
                        print(f"{time.strftime('%H:%M:%S')}  {msg}{rotulo}")
                time.sleep(0.005)
        except KeyboardInterrupt:
            pass

        print(f"\n{ultimo_clock[0]} mensagens de clock/sense (nao listadas).")
        if contagem:
            print("notas por instrumento: " + "  ".join(
                f"{k}={v}" for k, v in sorted(contagem.items(), key=str)))
            print("O track mutado no painel e o que PARA de contar aqui.")
        else:
            print("Nenhuma nota. Ou a maquina estava parada, ou o "
                  "UTILITY:MIDI:Inst Note esta em '---' (REFERENCIA secao 6) "
                  "- e ai este canal nao serve pra detectar mute.")


# ─────────────────────────────────────────────────────────────
# O grid ao vivo
#
# Tudo isto era o corpo de cmd_run(): um while True com closures sobre estado
# local. Virou classe pra que a janela do gui.py possa hospedar o mesmo motor -
# ela precisa rodar o laco e desenhar ao mesmo tempo, o que com closures dentro
# de uma funcao bloqueante era impossivel. O cmd_run continua existindo e faz
# exatamente o que fazia: instancia e chama tick() num laco.
# ─────────────────────────────────────────────────────────────
MODO_ON, MODO_OFF, MODO_STANDBY = "on", "off", "standby"


def carregar_estado():
    """Espelho local do que ainda nao sabemos ler da maquina.

    ATENCAO: e espelho, nao verdade. Os last steps ficam aqui porque o endereco
    deles nao foi decodificado (REFERENCIA 7.1); se voce mexer no [LAST] do
    painel, isto NAO fica sabendo. Depois da captura, o recarregar() passa a ler
    os valores reais e este arquivo vira so fallback.
    """
    # 'esconder_mudos' e preferencia de visualizacao, nao espelho: o mute em si e
    # lido da maquina (addr_mute), que e a autoridade. O que fica aqui e so a
    # escolha de mostrar ou nao as linhas mutadas.
    vazio = {"ultimo_var": {}, "ultimo_track": [None]*len(INSTRUMENTOS),
             "esconder_mudos": False, "passo_inst": PASSO_INST_PADRAO}
    if not os.path.exists(ESTADO_FILE):
        return vazio
    try:
        with open(ESTADO_FILE) as f:
            e = json.load(f)
    except Exception:
        return vazio
    # so as chaves conhecidas sobrevivem. Versoes antigas deixaram 'mudo' e
    # 'oculto' aqui, e uma chave 'mudo' num arquivo local diz exatamente o
    # contrario da regra de hoje: o mute mora na maquina e nunca e espelhado.
    # Descartar limpa o arquivo sozinho na primeira gravacao.
    limpo = {}
    for k, v in vazio.items():
        val = e.get(k, v)
        if isinstance(v, list) and (not isinstance(val, list) or len(val) != len(v)):
            val = v
        limpo[k] = val
    return limpo


def salvar_estado(e):
    try:
        with open(ESTADO_FILE, "w") as f:
            json.dump(e, f, indent=2)
    except Exception:
        pass


class CicloVars:
    """Qual variacao a TR-8S toca, derivada da contagem de passos.

    Pura de proposito - nenhuma porta MIDI, nenhum estado do Motor. E o unico
    jeito de provar o congelamento e a correcao sem hardware (ver testes.py).

    POR QUE ISTO EXISTE (16/08/2026). A versao anterior era um acumulador com
    estado escondido: '_ciclo_idx' andava um passo por vez e '_ciclo_limite'
    so CRESCIA, num 'while passo_abs >= limite'. Bastava passo_abs andar para
    tras UMA vez - e o _ressincronizar() fazia isso a cada 1,5 s, rebaixando
    um contador absoluto para o step modular 0..15 da maquina - para o limite
    virar inalcancavel e a variacao CONGELAR ate o fim da sessao.

    Aqui a variacao e FUNCAO da posicao, entao nao ha o que ficar preso: se
    passo_abs volta, a resposta volta junto.

    Premissa que continua valendo (e continua deducao, nao medida): as
    habilitadas ciclam em ordem ascendente e cada uma dura o proprio last
    step. Ver REFERENCIA 2.3.2."""

    def __init__(self):
        self.soltar()

    def soltar(self):
        """Sem ancora = '?'. Melhor que afirmar a variacao errada."""
        self.ancora = None      # passo_abs em que a PRIMEIRA da lista comecou
        self.vars = []
        self.dur = {}

    def ancorado(self):
        return self.ancora is not None and bool(self.vars)

    def ancorar(self, passo_abs, vars_hab, dur, v, dentro=0):
        """Fixa que a variacao v esta tocando ha 'dentro' passos, em passo_abs."""
        if not vars_hab or v not in vars_hab:
            self.soltar()
            return
        self.vars = list(vars_hab)
        self.dur = dict(dur)
        antes = sum(self.dur.get(x, 16)
                    for x in self.vars[:self.vars.index(v)])
        self.ancora = passo_abs - dentro - antes

    def deslocar(self, passos):
        """Move a ancora junto com uma correcao de fase do playhead.

        Sem isto, corrigir a fase empurraria o contador para dentro da
        variacao vizinha - o resync consertaria o playhead e estragaria a
        variacao, que foi exatamente o bug de 16/08."""
        if self.ancora is not None:
            self.ancora += passos

    def total(self):
        return sum(self.dur.get(v, 16) for v in self.vars)

    def variacao_em(self, passo_abs):
        """A variacao que toca no passo dado, ou None se nao ha ancora."""
        if not self.ancorado():
            return None
        t = self.total()
        if t <= 0:
            return None
        p = (passo_abs - self.ancora) % t
        for v in self.vars:
            d = self.dur.get(v, 16)
            if p < d:
                return v
            p -= d
        return self.vars[-1]        # so por seguranca; o laco acima cobre


class Motor:
    """O grid. tick() e nao-bloqueante; chame num laco a ~3 ms."""

    # SCALE do pattern, no nivel da CLASSE de proposito: o testes.py monta um
    # Motor cru (sem __init__, que precisaria de porta MIDI) e o
    # _ressincronizar pergunta a scale. Sem o default aqui, o teste de
    # regressao do playhead morria em AttributeError.
    scale = None
    # bits 11-15 da mascara de mute, guardados crus: a 2.7 nao diz o que eles
    # fazem, e alternar_mudo reescreve a mascara inteira
    mudo_bits_altos = 0
    # None = ainda nao lido; True/False = a maquina esta (ou nao) num fill
    fill_ativo = None
    auto_fill = None      # intervalo do AUTO FILL IN (32/16/12/8/4/2)
    kit_level_ref = None  # volume do kit como ele foi lido (botao de reset)

    def __init__(self, cfg, log=print):
        self.cfg, self.log = cfg, log
        self.lock = threading.RLock()

        esq, dir_ = cfg["esquerdo"], cfg["direito"]
        self.lp_in  = {"E": EntradaMIDI(esq["in_idx"], esq["in_nome"]),
                       "D": EntradaMIDI(dir_["in_idx"], dir_["in_nome"])}
        self.lp_out = {"E": SaidaMIDI(esq["out_idx"], esq["out_nome"]),
                       "D": SaidaMIDI(dir_["out_idx"], dir_["out_nome"])}
        self.geo = {"E": esq, "D": dir_}

        # TR-8S: aberta so quando precisa. O modo off dispensa a
        # maquina inteira, e e util poder brincar com os pads sem ligar ela.
        self.tr_in = self.tr_out = self.clk = None
        self.clk_nome = None

        self.variacao = VARIACAO
        self.cache, self.acc, self.kit_params = {}, 0, {}
        # blocos cuja leitura falhou: escrever neles mandaria lixo pros bytes
        # 0-3 (probability inclusive) - escrever_step se recusa ate reler
        self.cache_invalido = set()
        # comandos vindos da janela: rodam dentro do tick(), com o lock, na
        # thread do motor - a UI nunca mais mexe no Motor da thread do Tk
        self.fila_cmd = queue.Queue()
        self.base_inst, self.modo, self.vel_idx = 0, 0, VEL_PADRAO
        self.mostrar_acc = MOSTRAR_ACC
        self.passo, self.tocando, self.pulsos = -1, False, 0
        self.passo_abs = 0        # contagem absoluta, pros tracks curtos
        self.ultima_leitura = 0.0
        self.copia, self.armado, self.armado_t = None, None, 0.0
        # PILHA de snapshots de escrita (biblioteca/estocastica): cada item e
        # (rotulo, variacao, copia do cache, accent). Virou pilha em 15/08 a
        # noite para o "Reverter por edicao" da estocastica - um snapshot
        # unico obrigava o Reverter a engolir varias edicoes de uma vez.
        self.pilha_desfazer = []
        self.TETO_DESFAZER = 10
        self._clock_ts = collections.deque(maxlen=25)  # BPM medido do clock
        self.chain = None         # ferramentas.Chain, quando armado
        self.alt = False               # flag do ALTERNATE, nao um dos 5 modos
        self.mudo = [False]*len(INSTRUMENTOS)   # lido da maquina, nunca inventado
        self.passo_maquina = None               # step que a TR-8S diz estar tocando
        self.passo_maquina_t = 0.0              # quando foi lido (envelhece rapido)
        self.var_pedida = None                  # duplo clique: entra na virada
        self._ciclo_pedido = None               # ciclo em que o pedido entrou
        self.var_presumida = False              # ancora por palpite, nao por leitura
        # ESPELHO SUSPEITO (16/08/2026): quando o no 20 xx nao corresponde ao
        # pattern que a maquina toca, o grid mostra outro pattern - e escrever
        # a partir dele DESTROI o que esta na maquina. Ver _conferir_espelho.
        self.espelho_suspeito = False
        self._saltos = []                       # carimbos das correcoes grandes
        self._t_log_bloqueio = 0.0              # throttle do aviso de bloqueio
        self._erros_seguidos = []               # so corrige deriva consistente
        self.variacao_tocando = None            # qual variacao a maquina toca
        self.kit_atual = None                   # offset 0 do perf (01 00 00 00)
        self.kit_trocou = False                 # troca vista no painel
        self.pattern_trocou = False             # idem, para o pattern
        self.pattern_nome = None                # bytes 0-15 do no do pattern
        self.vars_habilitadas = []              # mascara 63-66 decodificada
        # ciclo de variacoes derivado do CLOCK (16/08/2026): a variacao que
        # toca nao existe em nenhum no SysEx que conhecemos (o watch de 193
        # bytes nao viu nada mudar com A->B->C ciclando) - mas da para contar:
        # ordem ascendente das habilitadas, cada uma dura o SEU last step.
        # Sem ancora = honesto no "?" (so um start alinha sozinho; quem chega
        # com a maquina ja rodando precisa que alguem diga qual e).
        self.ciclo = CicloVars()
        self.fx_fila = []                       # blocos de FX a reler, aos poucos
        self.fx_rearmado = 0.0                  # quando a fila deu a ultima volta
        self.scale = None                       # SCALE do pattern (OFF_SCALE)
        self.fill_ativo = None                  # a maquina esta num fill?
        self.auto_fill = None                   # intervalo do AUTO FILL IN
        self.kit_level_ref = None               # volume original do kit
        self.cache_var = {}                     # (pattern, var) -> espelho lido
        self.leituras_falhas = 0                # seguidas; >=2 e sumico da maquina
        self.rodizio_linha = 0                  # proxima linha do rodizio de releitura
        self.pattern_atual = None
        self._pattern_tentado = 0.0   # ultima tentativa de descobri-lo
        self.kit_nome = None                    # lidos por ler_kit(), sob demanda
        self.tone_ids = [None] * len(INSTRUMENTOS)
        # mixer/FX: blocos de kit vigiados, mapa de parametros decodificados e
        # o estado da captura guiada (ver efeitos.py e REFERENCIA 7.2)
        self.fx_blocos = {}                     # "kit" | indice_inst -> bytes
        self.mapa_fx = efeitos.carregar()
        self.captura_fx = None
        self.fx_kit_grande = None               # o no do kit responde a 128 B?
        self.carregado = False

        e = carregar_estado()
        self.ultimo_var    = {int(k): v for k, v in e["ultimo_var"].items()}
        self.ultimo_track  = list(e["ultimo_track"])
        self.esconder_mudos = bool(e["esconder_mudos"])
        try:
            self.passo_inst = max(1, min(PASSO_INST_MAX, int(e["passo_inst"])))
        except (KeyError, TypeError, ValueError):
            self.passo_inst = PASSO_INST_PADRAO

        self.modo_geral = MODO_OFF
        self.ondas, self.onda_suja = [], False
        self.ultimo_quadro = 0.0
        self.logo_t = {}
        self.estilo_standby = ESTILO_CHUVA
        self.proxima_onda = 0.0     # quando nasce a proxima onda do standby

    # ── portas ──────────────────────────────────────────────
    def _abrir_tr8s(self):
        if self.tr_in and self.tr_out:
            return True
        tin, tout = _portas_tr8s()
        if not (tin and tout):
            return False
        self.tr_in, self.tr_out = EntradaMIDI(*tin), SaidaMIDI(*tout)
        return True

    def abrir_clock(self):
        if self.clk or not SEGUIR_CLOCK:
            return
        p = _porta_clock()
        if p:
            # callback=True: e a unica porta em que perder mensagem CORROMPE
            # estado (a variacao que toca e derivada da contagem de pulsos).
            # A CTRL e os Launchpad seguem em polling - a CTRL porque o
            # request/response do ler_bloco depende dele, e ja e provado
            self.clk, self.clk_nome = EntradaMIDI(*p, callback=True), p[1]

    def fechar(self):
        with self.lock:
            for p in (self.clk, self.tr_in, self.tr_out):
                if p: p.close()
            for p in list(self.lp_in.values()) + list(self.lp_out.values()):
                p.close()
            self.lp_in, self.lp_out = {}, {}
            self.clk = self.tr_in = self.tr_out = None

    # ── geometria ───────────────────────────────────────────
    def nota_de(self, dev, linha, col):
        c = self.geo[dev]
        return c["origem"] + linha * c["passo_lin"] + col * c["passo_col"]

    def _decodificar(self, dev, nota):
        """nota -> (linha, col) ou None. Ver REFERENCIA 5 sobre a ambiguidade."""
        c = self.geo[dev]
        d = nota - c["origem"]
        for linha in range(8):
            resto = d - linha * c["passo_lin"]
            if c["passo_col"] and resto % c["passo_col"] == 0:
                col = resto // c["passo_col"]
                if 0 <= col < 8:
                    return linha, col
        return None

    # ── fila de comandos da janela ──────────────────────────
    def enfileirar(self, fn, *args, **kw):
        """Thread-safe. fn roda dentro do tick(), com o lock, na thread do
        motor. E o UNICO caminho pela qual a janela dispara acoes - chamar
        metodos do Motor direto da thread do Tk congelava a janela nas rajadas
        e corria contra o tick."""
        self.fila_cmd.put((fn, args, kw))

    def _drenar_fila(self):
        # poucos por tick: um comando longo (rajada) ja segura o lock o
        # suficiente - a janela pula quadros, que e o contrato dela
        for _ in range(4):
            try:
                fn, args, kw = self.fila_cmd.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args, **kw)
            except Exception as exc:
                self.log(f"(!) comando da janela falhou: {exc}")

    # ── leitura do pattern ──────────────────────────────────
    def _garantir_pattern(self):
        """Indice do pattern corrente, lendo o perf se ainda nao souber.

        TODO endereco da regiao de pattern depende dele (o segundo byte vale
        `pattern*16 + variacao`). Nao ha default: um numero chutado aponta
        para o pattern errado em silencio, que e exatamente o bug que o
        `24 5x` fixo escondia. Duas tentativas, como os blocos de step - a
        maquina engasga."""
        if self.pattern_atual is not None:
            return self.pattern_atual
        if not (self.tr_in and self.tr_out):
            return None
        # NAO insistir a cada chamada: sao duas leituras de SNAP_TIMEOUT, e o
        # escrever_step roda em rajada (o Chain manda 3 por tick). Sem este
        # intervalo, uma maquina muda travava o tick inteiro - que e quem
        # tambem cuida do clock, dos pads e do playhead - por segundos.
        agora = time.time()
        if agora - self._pattern_tentado < INTERVALO_RELEITURA:
            return None
        self._pattern_tentado = agora
        for _ in range(2):
            d = ler_bloco(self.tr_in, self.tr_out, ADDR_PERF, 128,
                          timeout=SNAP_TIMEOUT)
            if d and len(d) > OFF_PATTERN_ATUAL:
                self.pattern_atual = d[OFF_PATTERN_ATUAL]
                break
        return self.pattern_atual

    def _pattern_para_escrever(self, rot):
        """O pattern corrente, ou None avisando. Use antes de montar endereco.

        Sem isto o `addr_no_pattern(None)` levanta TypeError la dentro, e o
        erro sobe como '(!) erro no motor' (na tela) ou derruba o `run` do
        terminal, que so trata KeyboardInterrupt."""
        p = self._garantir_pattern()
        if p is None:
            self.log(f"(!) {rot}: nao sei em que pattern a maquina esta - "
                     "abortado (a leitura do no de performance falhou).")
        return p

    def recarregar(self):
        if self._garantir_pattern() is None:
            # Mesma semantica de uma linha que nao respondeu, de proposito:
            # marca tudo como nao lido (a escrita fica bloqueada pelo guarda
            # do escrever_step) e SEGUE ate carregado=True. Abortar aqui
            # deixaria carregado=False para sempre, e o bloco periodico do
            # tick - que e quem se cura sozinho - nunca mais rodaria.
            self.log("(!) nao consegui ler em que pattern a maquina esta; "
                     "sem isso todo endereco cairia no pattern errado. "
                     "Escrita bloqueada ate uma releitura funcionar.")
            for i in range(len(INSTRUMENTOS)):
                self.cache_invalido.add(i)
                self.cache.setdefault(i, [0]*128)
            self.carregado = True
            return
        for i in range(len(INSTRUMENTOS)):
            # o clock nao espera a leitura terminar: sem isto o playhead
            # congela ~250 ms a cada troca de variacao (ver _bombear_clock)
            self._bombear_clock()
            d = None
            for _ in range(2):                     # a maquina engasga as vezes
                d = ler_bloco(self.tr_in, self.tr_out,
                              addr_bloco_rd(i, self.variacao, self.pattern_atual))
                if d: break
            if d:
                self.cache[i] = d
                self.cache_invalido.discard(i)
            else:
                # O placeholder de zeros e SO pra tela: a escrita fica
                # bloqueada pelo guarda do escrever_step ate uma releitura
                # funcionar. Antes o placeholder era o cache de verdade, e a
                # primeira escrita mandava zeros nos bytes 0-3 - apagando a
                # probability do step na maquina.
                self.cache_invalido.add(i)
                self.cache[i] = [0]*128
                self.log(f"(!) leitura do {INSTRUMENTOS[i]} falhou - "
                         "escrita nessa linha bloqueada ate reler")
        cab = ler_bloco(self.tr_in, self.tr_out,
                        addr_accent_rd(self.variacao, self.pattern_atual), 8) or [0]*8
        self.acc = nibbles_para_mascara(cab[:4])
        self.ler_last_steps()
        self.ler_mudos()
        self.carregado = True
        self._guardar_cache_var()

    def _guardar_cache_var(self):
        """Guarda o espelho DESTA variacao para a proxima vez que ela abrir.

        A maquina em rodizio volta na mesma variacao a cada volta. Reler os 11
        blocos leva ~500 ms, e nesse tempo a tela mostrava a variacao ANTIGA:
        a 40 bpm em 32nd sao uns 3 steps antes da nova aparecer, que foi o
        "demora pra carregar e pula uns 3 passos" de 17/08/2026.

        Guarda as MESMAS listas, sem copiar: assim uma edicao de step - que
        escreve DENTRO da lista - aparece aqui sem ninguem sincronizar nada.
        Espelho com linha nao lida nao entra: melhor nao ter cache do que ter
        um com buraco."""
        if self.pattern_atual is None or self.cache_invalido:
            return
        if len(self.cache_var) > 12:          # teto: 10 variacoes + folga
            self.cache_var.clear()
        self.cache_var[(self.pattern_atual, self.variacao)] = (dict(self.cache),
                                                              self.acc)

    # quantas linhas do pattern o tick relê por ciclo. 6 das 12 (11
    # instrumentos + accent) da a volta em dois ciclos, ~3 s. Reler as 12 de
    # uma vez atropelava a leitura seguinte e produzia o "BD nao lido".
    LINHAS_POR_CICLO = 6

    def _reler_pattern_rodizio(self):
        """Relê parte do pattern, em rodizio, para VER o que o painel muda.

        Ate 15/08/2026 o espelho so andava num sentido: o tick relia os last
        steps e os mutes, mas nunca as notas. Ligar um step no painel da TR-8S
        nao aparecia no grid nem nos Launchpad - so "se acertava" quando o
        Luan clicava naquele step aqui, porque a escrita relê a linha.

        Falha isolada aqui NAO invalida a linha (diferente do recarregar()):
        aqui e vigilancia de fundo, e marcar a linha como nao lida bloquearia
        a escrita dela por um engasgo passageiro."""
        if self._garantir_pattern() is None:
            return False
        mudou = False
        total = len(INSTRUMENTOS) + 1          # +1 = a fileira de accent
        for _ in range(self.LINHAS_POR_CICLO):
            self._bombear_clock()   # 6 linhas por ciclo tambem seguram o tick
            i = self.rodizio_linha
            self.rodizio_linha = (self.rodizio_linha + 1) % total
            if i == len(INSTRUMENTOS):
                cab = ler_bloco(self.tr_in, self.tr_out,
                                addr_accent_rd(self.variacao, self.pattern_atual), 8)
                if cab:
                    novo = nibbles_para_mascara(cab[:4])
                    if novo != self.acc:
                        self.acc, mudou = novo, True
                continue
            d = ler_bloco(self.tr_in, self.tr_out,
                          addr_bloco_rd(i, self.variacao, self.pattern_atual))
            if d and d != self.cache[i]:
                # DENTRO da lista, nao rebind: o cache_var guarda a MESMA lista
                # (ver _guardar_cache_var), e trocar o objeto aqui deixava o
                # espelho da variacao envelhecido em silencio - a proxima troca
                # pintaria o grid sem o step que o painel acabou de ligar
                self.cache[i][:] = d
                self.cache_invalido.discard(i)
                mudou = True
        return mudou

    def ler_last_steps(self, quieto=False):
        """Le os last steps REAIS da maquina. Devolve True se algo mudou.

        Chamado tambem periodicamente pelo tick(), senao mexer no [LAST] do painel
        nunca apareceria no grid."""
        if self._garantir_pattern() is None:
            return False
        self.ultima_leitura = time.time()
        # 193 e o tamanho real deste no (o 20 xx tinha 128). O excedente
        # guarda campos ainda nao decodificados - candidatos ao last step dos
        # Fill In, que continua desconhecido (REFERENCIA 2.3.1)
        d = ler_bloco(self.tr_in, self.tr_out,
                      addr_no_pattern(self.pattern_atual), 193,
                      timeout=SNAP_TIMEOUT)
        if not d or len(d) < OFF_LAST_TRACK + len(INSTRUMENTOS):
            if not quieto:
                self.log("(!) nao consegui ler os last steps; usando o espelho.")
            return False
        # o NOME do pattern corrente mora nos bytes 0-15 do mesmo no (ASCII,
        # '----' = sem nome) - de graca na leitura que ja acontece
        self.pattern_nome = ("".join(chr(b) for b in d[:16]
                                     if 32 <= b < 127).strip() or None)
        # a SCALE vem no mesmo no, tambem de graca (nenhum RQ1 novo): e ela
        # que diz quantos pulsos dura um step. Sem isto o playhead andava em
        # metade da velocidade num pattern em 32nd
        # o intervalo do AUTO FILL IN vem no mesmo no, tambem de graca
        if len(d) > OFF_AUTO_FILL:
            i = d[OFF_AUTO_FILL]
            self.auto_fill = (AUTO_FILL_VALORES[i]
                              if i < len(AUTO_FILL_VALORES) else None)
        if len(d) > OFF_SCALE and d[OFF_SCALE] != self.scale:
            antiga, self.scale = self.scale, d[OFF_SCALE]
            if antiga is not None:
                self.log(f"scale do pattern: {self.nome_scale()} "
                         f"({self.pulsos_p_step()} pulsos por step)")
        antes = (dict(self.ultimo_var), list(self.ultimo_track),
                 self.variacao_tocando)
        for v in range(1, 9):                       # A-H; fills nao tem slot
            self.ultimo_var[v] = d[OFF_LAST_VAR + v - 1] + 1
        for i in range(len(INSTRUMENTOS)):
            # 0 = o track NAO tem last step proprio, entao segue a variacao.
            # No no 20 xx (que a gente lia ate 16/08) este campo vinha 15 pra
            # todos, o que dava 16 e era inofensivo por acidente - min(16, x)
            # nunca encurtava nada. Na regiao 24 5x ele vem 0 de verdade, e
            # somar 1 as cegas faria cada instrumento tocar UM step so.
            bruto = d[OFF_LAST_TRACK + i]
            self.ultimo_track[i] = (bruto + 1) if bruto else None
        # CORRECAO DE 16/08/2026: a mascara dos offsets 63-66 e das variacoes
        # HABILITADAS para ciclar, nao da que toca agora. Com uma so
        # habilitada as duas coincidem (por isso funcionou ate hoje); com
        # A..C habilitadas a tela cravava "A" enquanto o visor dizia C. Com
        # varias habilitadas, a variacao tocando e DESCONHECIDA ate o
        # var_watch achar o byte dela - e melhor "?" que errado.
        m = nibbles_para_mascara(d[OFF_VAR_TOCANDO:OFF_VAR_TOCANDO + 4])
        antes_hab = self.vars_habilitadas
        self.vars_habilitadas = [v for v in range(1, 9) if m >> (v - 1) & 1]
        # com UMA habilitada a tocando e ela propria; com varias, a conta do
        # clock manda (_avancar_ciclo_vars) - e se o conjunto mudou no meio,
        # a ancora ja nao vale
        if len(self.vars_habilitadas) == 1:
            self.variacao_tocando = self.vars_habilitadas[0]
            self.ciclo.soltar()
            self.var_presumida = False   # uma so: e leitura, nao palpite
        elif antes_hab != self.vars_habilitadas:
            self.ciclo.soltar()
            self.variacao_tocando = None
            self.var_presumida = False
        mudou = antes != (dict(self.ultimo_var), list(self.ultimo_track),
                          self.variacao_tocando)
        if mudou:
            self._persistir()      # so grava quando muda: o tick chama isto sempre
        return mudou

    def ler_vel(self, i, s):
        b = s * BYTES_P_STEP
        return (self.cache[i][b+VEL_HI] << 4) | self.cache[i][b+VEL_LO]

    def ler_sub(self, i, s):
        return self.cache[i][s*BYTES_P_STEP + SUB_BYTE]

    def ler_alt(self, i, s):
        return self.cache[i][s*BYTES_P_STEP + ALT_BYTE] == ALT_LIGADO

    def ler_prob(self, i, s):
        """Probability do step em %, pela formula linear (ver PROB_BYTE)."""
        return byte_para_prob(self.cache[i][s*BYTES_P_STEP + PROB_BYTE])

    # ── last step ───────────────────────────────────────────
    def last_var(self):
        return self.ultimo_var.get(self.variacao, 16)

    def ultimo_efetivo(self, i):
        """Reference p. 12: o last step do track tem prioridade sobre o da
        variacao. None no track = segue a variacao."""
        t = self.ultimo_track[i] if i < len(self.ultimo_track) else None
        return min(self.last_var(), t or 16)

    def definir_last_var(self, n):
        with self.lock:
            if self._pattern_para_escrever("last step da variacao") is None:
                return
            if self.escrita_bloqueada("last step da variacao"):
                return
            n = max(1, min(16, int(n)))
            self.ultimo_var[self.variacao] = n
            if self.tr_out and self.variacao <= 8:
                self.tr_out.send(dt1(addr_last_var(self.variacao, self.pattern_atual), [n - 1]))
            elif self.variacao > 8:
                self.log("(!) o last step dos Fill In nao foi decodificado - "
                         "este valor fica so aqui, nao vai pra maquina.")
            self._persistir(); self.pintar()
            self.log(f"last step da variacao {VARIACOES[self.variacao-1]}: {n}")

    def definir_last_track(self, i, n):
        with self.lock:
            if self._pattern_para_escrever("last step do track") is None:
                return
            if self.escrita_bloqueada("last step da linha"):
                return
            n = 16 if n is None else max(1, min(16, int(n)))
            self.ultimo_track[i] = n
            if self.tr_out:
                self.tr_out.send(dt1(addr_last_track(i, self.pattern_atual), [n - 1]))
            self._persistir(); self.pintar()
            self.log(f"last step do {INSTRUMENTOS[i]}: {n}")

    def _persistir(self):
        salvar_estado({"ultimo_var": {str(k): v for k, v in self.ultimo_var.items()},
                       "ultimo_track": self.ultimo_track,
                       "esconder_mudos": self.esconder_mudos,
                       "passo_inst": self.passo_inst})

    def definir_passo_inst(self, n):
        """Quantas linhas o INST UP/DOWN anda por toque."""
        with self.lock:
            n = max(1, min(PASSO_INST_MAX, int(n)))
            if n == self.passo_inst:
                return
            self.passo_inst = n
            self._persistir()
            self.log(f"INST UP/DOWN anda {n} linha" + ("s" if n > 1 else ""))

    # ── mute ────────────────────────────────────────────────

    def ler_mudos(self, quieto=False):
        """Le da maquina quem esta mutado. Devolve True se algo mudou.

        Chamado pelo tick() junto com os last steps: sem reler, apertar [MUTE] no
        painel nunca chegaria ao grid. A maquina e a autoridade - o grid nao tem
        espelho local de mute, e nao escreve aqui. Mutar continua sendo gesto de
        painel; o que o grid faz e enxergar."""
        d = ler_bloco(self.tr_in, self.tr_out, ADDR_PERF, 128, timeout=SNAP_TIMEOUT)
        if not d or len(d) < OFF_MUTE + 4:
            self.leituras_falhas += 1
            if not quieto:
                self.log("(!) nao consegui ler os mutes da maquina.")
            return False
        # A TR-8S sumiu e voltou: desligar/ligar a maquina (ou tirar o USB) faz
        # ela recarregar os patterns do disco, e o cache daqui fica falando de
        # um estado que nao existe mais. Isso apareceu como steps errados no
        # grid que "se acertavam" quando o Luan clicava neles - o clique
        # escrevia e relia aquela linha. Voltar a responder e o sinal de que
        # tudo precisa ser lido de novo.
        if self.leituras_falhas >= 2:
            self.log(f"a TR-8S voltou depois de {self.leituras_falhas} "
                     "leituras sem resposta - relendo tudo (ela pode ter sido "
                     "reiniciada, e o cache daqui estaria mentindo)")
            self.recarregar()
            self.kit_trocou = True
        self.leituras_falhas = 0
        # o step atual vem no mesmo bloco, de graca - guarda para o tick
        # ressincronizar o playhead sem gastar um RQ1 a mais
        self.passo_maquina = d[OFF_STEP_ATUAL] if len(d) > OFF_STEP_ATUAL else None
        self.passo_maquina_t = time.time()      # carimbo: ele azeda em ~1 step
        # kit e pattern atuais tambem moram aqui (offsets 0-2, mapa do ARIA) -
        # de graca na mesma leitura, nenhum RQ1 novo
        novo_kit = d[OFF_KIT_ATUAL] if len(d) > OFF_KIT_ATUAL else None
        # Trocar de kit no painel muda TUDO que a aba de efeitos mostra: nome,
        # tones e os 26 blocos. Sem perceber a troca, a tela segue falando do
        # kit anterior com ar de certeza - foi o que aconteceu ao passar do
        # TR-707 para o TR-808. O proprio TR-EDITOR fica relendo este byte de
        # 2 em 2 segundos pelo mesmo motivo.
        if novo_kit != self.kit_atual and self.kit_atual is not None:
            self.kit_trocou = True
            self.log(f"kit mudou no painel ({self.kit_atual} -> {novo_kit}): "
                     "relendo nome, tones e efeitos")
        self.kit_atual = novo_kit
        # Mesmo raciocinio para o PATTERN: trocar de pattern (no painel ou
        # remotamente) muda todos os steps, e sem esta bandeira o grid segue
        # mostrando o pattern anterior com ar de certeza. Buraco achado no
        # planejamento da reforma 2 - a deteccao existia so para o kit.
        novo_pat = (d[OFF_PATTERN_ATUAL]
                    if len(d) > OFF_PATTERN_ATUAL else None)
        if novo_pat != self.pattern_atual and self.pattern_atual is not None:
            self.pattern_trocou = True
            # O cache ainda e do pattern ANTERIOR, e o endereco de escrita ja
            # aponta para o novo. O escrever_step manda os 8 bytes do step
            # inteiro - inclusive os bytes 0-2, que ele nao entende e copia do
            # cache -, entao escrever nessa janela carregaria lixo do pattern
            # velho para dentro do novo. A releitura pode demorar (ela e
            # ADIADA enquanto o chain persegue o playhead), entao a escrita
            # fica bloqueada ate ela acontecer, pelo mesmo caminho que uma
            # linha nao lida usa.
            self.cache_invalido.update(range(len(INSTRUMENTOS)))
            n = novo_pat
            self.log("pattern mudou "
                     f"({nome_pattern(n)}): relendo o grid")
            # HIPOTESE de 16/08/2026 (sintoma: apos trocar de pattern, editar
            # o grid nao soava e o painel nao aparecia no grid): o buffer de
            # edicao SysEx (blocos 20 xx) pode nao acompanhar a troca sozinho.
            # Reescrever o pattern ATUAL com o mesmo numero deve forca-lo a
            # recarregar - o offset 1 e provado e preserva a posicao do step,
            # entao com o MESMO pattern e para ser inaudivel. Se o Luan ainda
            # vir dessincronizacao, este e o primeiro suspeito a revisar.
            self.tr_out.send(dt1(addr_soma(ADDR_PERF, OFF_PATTERN_ATUAL),
                                 [n & 0x7F]))
        self.pattern_atual = novo_pat
        m = nibbles_para_mascara(d[OFF_MUTE:OFF_MUTE + 4])
        # A mascara tem 16 bits e a 2.7 so decodificou os 11 dos instrumentos.
        # Guardar os bits DE CIMA crus e o que permite reescrever a mascara sem
        # apagar funcao que ninguem mapeou (ver alternar_mudo).
        self.mudo_bits_altos = m & ~((1 << len(INSTRUMENTOS)) - 1)
        # o fill vem no mesmo bloco, sem custo nenhum de leitura
        if len(d) > OFF_FILL:
            antes_fill, self.fill_ativo = self.fill_ativo, bool(d[OFF_FILL])
            # REPINTAR NA VIRADA, nos dois sentidos. Entrando no fill, o
            # mover_playhead para de pintar a coluna e o ultimo verde ficaria
            # CONGELADO no grid ate alguem repintar. Saindo, o respiro precisa
            # desfazer. Um quadro inteiro sao 2 SysEx, e isto acontece duas
            # vezes por fill - mais barato que qualquer alternativa.
            if antes_fill is not None and antes_fill != self.fill_ativo:
                self.pintar()
        novo = [bool(m >> i & 1) for i in range(len(INSTRUMENTOS))]
        mudou = novo != self.mudo
        self.mudo = novo
        return mudou

    def ler_passo_maquina(self):
        """O step em que o sequenciador da TR-8S esta, 0-15, ou None."""
        d = ler_bloco(self.tr_in, self.tr_out, ADDR_PERF, 128, timeout=SNAP_TIMEOUT)
        return d[OFF_STEP_ATUAL] if d and len(d) > OFF_STEP_ATUAL else None

    def adotar_transporte(self):
        """Descobre se a maquina JA esta tocando, e entra em fase com ela.

        Sem isto, subir o grid com a TR-8S rodando deixava o playhead apagado
        para sempre: 'tocando' so ligava no start/continue, e quem ja estava
        tocando nunca manda start. Nao da para inferir do clock, que ela
        transmite mesmo parada (ver OFF_STEP_ATUAL).

        Duas leituras espacadas: se o step andou, esta tocando. O espacamento
        cobre com folga um step a 40 bpm (0,375 s), o andamento mais lento que a
        maquina aceita - senao um tempo muito lento pareceria estar parado."""
        if not (self.tr_in and self.tr_out) or self.tocando:
            return False
        a = self.ler_passo_maquina()
        if a is None:
            return False
        time.sleep(0.5)
        b = self.ler_passo_maquina()
        if b is None or a == b:
            return False

        # Fixar a fase e sair NAO basta, por dois motivos.
        #
        # 1. Enquanto ninguem chamava tick(), os pulsos de clock se acumularam
        #    na fila do rtmidi desde que a porta abriu. O primeiro tick
        #    processaria a fila inteira e jogaria o playhead pra frente por todo
        #    esse tempo. Por isso a fila e drenada antes de medir.
        # 2. A leitura do step custa um round-trip de SysEx, e o valor que volta
        #    ja nasce velho. Fixar a fase nele deixa o playhead atrasado por essa
        #    fracao de step - pequena demais pra ressincronizacao corrigir, e
        #    grande o bastante pra se ver.
        #
        # O truque pro item 2 e nao precisar do andamento: contando quantos
        # pulsos chegam DURANTE a leitura, temos exatamente quanto tempo passou,
        # ja na unidade certa. Serve a qualquer BPM sem medir nenhum.
        if self.clk:
            self.clk.iter_pending()                    # zera a fila
        c = self.ler_passo_maquina()
        decorridos = 0
        if self.clk:
            decorridos = sum(1 for m in self.clk.iter_pending()
                             if m.type == 'clock')
        if c is None:
            c = b
        self.tocando = True
        pps = self.pulsos_p_step()
        self.pulsos = c * pps + decorridos + AJUSTE_PLAYHEAD
        self.passo_abs = self.pulsos // pps
        self.mover_playhead(self.passo_abs % max(1, self.last_var()))
        self.log(f"a TR-8S ja estava tocando - playhead entrou no step "
                 f"{self.passo_abs % max(1, self.last_var()) + 1} "
                 f"(compensados {decorridos} pulsos de leitura)")
        # A FASE da pra adotar; QUAL variacao, nao. O byte que temos
        # (OFF_STEP_ATUAL) diz onde estamos DENTRO da variacao, nunca qual e
        # ela - e ancorar em vs[0] as cegas seria cara ou coroa com duas
        # habilitadas, exatamente o erro que a REFERENCIA 2.3.2 ja pagou caro
        # pra nao cometer. Fica em "?" ate alguem dizer, e quem sabe e o Luan,
        # que esta olhando o visor (ver ancorar_variacao)
        if len(self.vars_habilitadas) > 1 and not self.ciclo.ancorado():
            self.log("nao da pra saber QUAL variacao ela esta tocando - "
                     "de stop/play na maquina, ou SHIFT-clique na variacao "
                     "cujo LED verde estiver aceso no painel")
        return True

    def ancorar_variacao(self, v):
        """O Luan diz qual variacao esta no visor; a conta se alinha por ela.

        E a saida honesta para o caso normal - quem sobe o app com a maquina
        ja rodando nunca recebe um start, e sem start nao ha como deduzir a
        variacao (ela nao existe em no SysEx nenhum, REFERENCIA 2.3.2).

        O passo_maquina diz a que altura da variacao estamos, entao a ancora
        sai exata - mas SO se ele for fresco. Ele e gravado no ler_mudos, que
        roda a cada INTERVALO_RELEITURA (1,5 s), e o clique chega num instante
        qualquer dessa janela: sem reler aqui, o guarda de validade descartava
        o valor em quase todo clique e a ancora caia como se a variacao tivesse
        acabado de comecar - ate 8 steps de erro, com o log afirmando 'step 1'."""
        with self.lock:
            if not self.vars_habilitadas:
                self.log("(!) nenhuma variacao habilitada para ciclar")
                return
            if v not in self.vars_habilitadas:
                hab = " ".join(VARIACOES[x-1] for x in self.vars_habilitadas)
                self.log(f"(!) a variacao {VARIACOES[v-1]} nao esta habilitada "
                         f"na maquina (habilitadas: {hab})")
                return
            self.ler_mudos(quieto=True)     # renova o passo_maquina agora
            dentro = 0
            if (self.passo_maquina is not None
                    and time.time() - self.passo_maquina_t <= VALIDADE_PASSO):
                dentro = self.passo_maquina
            else:
                self.log("(!) nao consegui ler o step da maquina agora - "
                         "ancorei no comeco da variacao, pode sair torto")
            self._ancorar_ciclo_vars(v, dentro)
            self.log(f"ancorado: a TR-8S esta tocando a "
                     f"{VARIACOES[v-1]} (step {dentro + 1})")

    def definir_mudos(self, mascara):
        """Escreve a mascara de mute. Testado em hardware: silencia de verdade.

        O grid nao usa isto - mutar e no painel, por escolha. Fica exposto para a
        janela do app, que ja edita last step do mesmo jeito."""
        with self.lock:
            if not self.tr_out:
                return
            self.tr_out.send(dt1(addr_mute(), mascara_para_nibbles(mascara)))
            self.mudo = [bool(mascara >> i & 1) for i in range(len(INSTRUMENTOS))]
            self.base_inst = min(self.base_inst, self.base_max())
            self.pintar(); self.pintar_botoes()

    def alternar_mudo(self, i):
        """Toggle do mute de UM instrumento, para o botao da mesa.

        Rele a mascara antes de inverter: o espelho self.mudo pode ter ate
        1,5 s de idade, e um toggle sobre mascara velha ressuscitaria um mute
        feito no painel nesse intervalo. Roda na thread do motor (via
        enfileirar), serializado com o tick; o lock e reentrante."""
        # o mesmo guarda do definir_fx/definir_prob_inst: sair do modo ON NAO
        # fecha a porta CTRL, entao sem isto o botao da mesa seria o unico
        # controle da pagina que ainda escreve na maquina em standby
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) mute so no modo ON, com a TR-8S conectada")
            return
        # a mascara tem 16 bits e so 11 sao conhecidos: indice fora da faixa
        # escreveria em bit de funcao ignorada (2.7), justo o que o Metodo
        # manda nao fazer
        if not 0 <= i < len(INSTRUMENTOS):
            self.log(f"(!) instrumento {i} fora da faixa")
            return
        # RELER, e SO seguir se a releitura funcionou. ler_mudos devolve False
        # tanto quando nada mudou quanto quando a leitura falhou - e no segundo
        # caso ele deixa self.mudo intacto. Seguir ali escreveria a mascara
        # montada a partir de um espelho velho, que e exatamente o que esta
        # releitura existe para evitar: um mute feito no painel no ultimo
        # segundo e meio seria desfeito por um clique noutro instrumento.
        # O contador de falhas e o unico sinal que distingue os dois casos.
        falhas_antes = self.leituras_falhas
        self.ler_mudos(quieto=True)
        if self.leituras_falhas > falhas_antes:
            self.log("(!) nao consegui reler os mutes - nao vou escrever a "
                     "mascara por cima de um espelho velho. Tente de novo")
            return
        mascara = 0
        for j, m in enumerate(self.mudo):
            if m:
                mascara |= 1 << j
        mascara ^= 1 << i
        # os bits acima dos 11 instrumentos vao de volta COMO ESTAVAM: a 2.7 nao
        # diz o que eles fazem, e mandar zero neles seria escrever num campo que
        # ninguem mapeou. Este e o primeiro caminho do projeto que reescreve
        # esta mascara - antes dele, o definir_mudos nao tinha nenhum caller
        mascara |= self.mudo_bits_altos
        self.definir_mudos(mascara)
        self.log(f"{INSTRUMENTOS[i]} "
                 + ("mutado" if mascara >> i & 1 else "desmutado")
                 + " pela mesa")

    def _bombear_clock(self):
        """Processa o clock represado NO MEIO de uma leitura longa.

        Reler uma variacao sao 11 blocos de SysEx (~250 ms) com o lock na mao.
        O clock nao para de chegar nesse tempo: ele fica na fila e era aplicado
        todo de uma vez no fim, entao o playhead CONGELAVA, pulava os steps que
        passaram e reaparecia atrasado - e o BPM medido desaparecia, porque
        lote > 1 zera a janela de medicao de proposito (ver _aplicar_pulsos).

        Aparece a cada troca de variacao, e quem segue o rodizio da maquina
        troca a cada volta: a 40 bpm em 32nd isso e a cada 3 s. Foi assim que
        o Luan viu "atrasado e travando" em 17/08/2026.

        ONDE CHAMAR: sempre ANTES de um ler_bloco, nunca entre o RQ1 e a
        resposta dele. Nao e verdade que "nenhum byte vai para a TR-8S aqui":
        pelo _atender_var_pedida isto pode mandar um DT1 na porta CTRL, e um
        DT1 no meio de uma leitura embaralharia o casamento pedido/resposta.
        Pintar LED e inofensivo (os Launchpad tem porta propria) e o lock e
        reentrante, mas a ordem das chamadas nao e detalhe de estilo."""
        if self.modo_geral == MODO_ON and self.clk:
            self._ler_clock()

    def pulsos_p_step(self):
        """Quantos pulsos de clock dura um step NESTE pattern (ver OFF_SCALE).

        Enquanto a scale nao foi lida vale a semicolcheia, que e o que a
        maquina traz de fabrica e o que o motor assumiu ate 17/08/2026."""
        return PULSOS_POR_SCALE.get(self.scale, PULSOS_P_STEP)

    def nome_scale(self):
        return NOME_SCALE.get(self.scale, "16th")

    def aplicar_mudos(self):
        """Depois de reler os mutes: o scroll pode ter ficado fora de faixa."""
        self.base_inst = min(self.base_inst, self.base_max())
        self.pintar(); self.pintar_botoes()

    def lista_visivel(self):
        """Quais instrumentos o grid mostra, na ordem.

        Com esconder_mudos ligado a linha mutada sai do grid e as de baixo sobem:
        com LT, MT e HT mutados sobram 8 instrumentos, que e exatamente a altura
        do grid, e o scroll deixa de existir. Desligado, os 11 ficam la e a linha
        mutada so troca de familia de cor (ver cor_base).

        Ninguem fica preso: o que sumiu volta pelo mesmo botao, e mutar/desmutar
        continua no painel da TR-8S de qualquer jeito."""
        if not self.esconder_mudos:
            return list(range(len(INSTRUMENTOS)))
        return [i for i in range(len(INSTRUMENTOS)) if not self.mudo[i]]

    def inst_da_linha(self, linha):
        """Instrumento naquela linha do grid, ou None se a linha esta sobrando."""
        if self.eh_acc(linha):
            return None
        vis = self.lista_visivel()
        k = self.base_inst + linha
        return vis[k] if k < len(vis) else None

    def linha_muda(self, linha):
        i = self.inst_da_linha(linha)
        return i is not None and self.mudo[i]

    # ── cores ───────────────────────────────────────────────
    def eh_acc(self, linha):
        return self.mostrar_acc and linha == LINHA_ACC_POS

    def linhas_de_inst(self):
        return 7 if self.mostrar_acc else 8

    def base_max(self):
        return max(0, len(self.lista_visivel()) - self.linhas_de_inst())

    def cor_vazia(self, linha, step):
        """Step apagado: cabeca de tempo num branco fraco, como na TR-8S - mas
        nao na linha mutada. Numa linha que nao soa nao ha tempo que marcar, e a
        ausencia do branco de fundo e metade do aviso de que ela esta muda."""
        if self.linha_muda(linha):
            return COR_OFF
        return COR_TEMPO if step % STEPS_TEMPO == 0 else COR_OFF

    def step_ligado(self, linha, step):
        if self.eh_acc(linha):
            return bool(self.acc & (1 << step))
        i = self.inst_da_linha(linha)
        return i is not None and self.ler_vel(i, step) > 0

    def cor_base(self, linha, step):
        if self.eh_acc(linha):
            if step >= self.last_var():
                return COR_FORA
            return COR_ACC if self.acc & (1 << step) else self.cor_vazia(linha, step)
        i = self.inst_da_linha(linha)
        if i is None:
            return COR_OFF                 # linha sobrando: escondeu mais que 3
        if step >= self.ultimo_efetivo(i):
            return COR_FORA
        v, sub = self.ler_vel(i, step), self.ler_sub(i, step)
        if v == 0:
            return self.cor_vazia(linha, step)
        # linha mutada troca de FAMILIA de cor, nao de brilho: vermelho vira roxo
        # e laranja vira azul. Escurecer confundiria com o par forte/fraca, que
        # continua valendo dentro de cada familia pelo mesmo VEL_LIMIAR.
        fraca = v <= VEL_LIMIAR
        # Precedencia: mute > ALT > flam/sub > nota. O mute vem primeiro porque
        # numa linha muda o que importa e que ela nao soa; que som ela nao esta
        # fazendo e detalhe. O ALT vem antes do flam porque ele troca o TOM que
        # vai tocar, enquanto flam e sub so mudam como ele e disparado.
        if self.mudo[i]:
            return COR_MUDA_FRACA if fraca else COR_MUDA_FORTE
        if self.ler_alt(i, step):
            return COR_ALT_FRACA if fraca else COR_ALT_FORTE
        if sub == SUB_FLAM:
            return COR_FLAM_FRACA if fraca else COR_FLAM
        if sub:                       # 2, 3, 4 = sub step 1/2, 1/3, 1/4
            return COR_SUB_FRACA if fraca else COR_SUB
        return COR_FRACA if fraca else COR_FORTE

    def passo_da_linha(self, linha):
        """Onde o playhead esta NAQUELA linha. Track curto anda no proprio
        comprimento; quem acompanha a variacao devolve o passo global."""
        i = self.inst_da_linha(linha)
        if i is None:
            return self.passo
        lim = self.ultimo_efetivo(i)
        if lim >= self.last_var():
            return self.passo
        base = self.passo if TRACK_REINICIA_NA_VARIACAO else self.passo_abs
        return base % lim

    def em_fase_com_a_maquina(self):
        """O grid esta na MESMA variacao que a maquina toca?

        Condicao estrita, usada para decidir se vale comparar o passo daqui com
        o passo de la. Fora dela os dois contam em modulos diferentes - cada
        variacao tem seu proprio last step - e a comparacao nao significa nada.

        None = nao conseguimos ler qual toca; aceita, porque era o comportamento
        de antes da leitura existir."""
        return (self.variacao_tocando is None
                or self.variacao == self.variacao_tocando)

    def eh_fill(self):
        return self.variacao > 8            # 09 = Fill 1, 0A = Fill 2

    def playhead_visivel(self):
        """O verde so aparece quando faz sentido ele estar ali.

        Editar uma variacao enquanto outra soa e o recurso mais valioso do
        projeto - e era justamente ali que o playhead mentia, correndo sobre um
        pattern que ninguem estava ouvindo.

        DURANTE O FILL O PLAYHEAD FICA - e quem decidiu isso foi a maquina.
        A primeira versao disto (17/08/2026, de manha) fazia o verde SUMIR no
        fill, pelo raciocinio de que o que soa nao e a variacao aberta. Ai o
        Luan olhou o painel da TR-8S e viu que **ela mantem o playhead durante
        o fill in**. E ela esta certa: a POSICAO e verdadeira - o sequenciador
        esta naquele step, contando igual. O que muda e de qual variacao sai o
        som, e para isso existe o respiro (ver _fator_respiro).

        A licao vale mais que o caso: "nao desenhar o que nao esta soando" foi
        aplicado a um dado que ESTAVA soando. Quando a maquina tem opiniao
        sobre uma questao de interface, ela ganha.

        Os FILLS sao excecao aqui por outro motivo: a mascara de variacao
        habilitada so reporta A-H (REFERENCIA 2.3.2), entao editar um fill
        perderia a referencia de tempo por um detalhe de protocolo.

        Isto e mais frouxo que em_fase_com_a_maquina() de propósito: dá pra
        DESENHAR o playhead num fill, mas não dá pra CORRIGIR a fase por ele."""
        return self.em_fase_com_a_maquina() or self.eh_fill()

    def polirritmia(self):
        """Alguma linha visivel e mais curta que a variacao?"""
        return any(self.ultimo_efetivo(i) < self.last_var()
                   for i in self.lista_visivel())

    def cor_do_step(self, linha, step):
        base = self.cor_base(linha, step)
        if self.tocando and step == self.passo_da_linha(linha):
            # o step que nao existe vence o playhead: nada acontece ali.
            if base == COR_FORA:
                return COR_FORA
            if not self.playhead_visivel():
                return base
            # linha muda nao tem playhead NENHUM - nem o verde forte nem o fraco.
            # O verde diz "esta soando agora", e ali nada esta soando; deixa-lo
            # passar seria a unica cor da linha mentindo sobre o som.
            if self.linha_muda(linha):
                return base
            # o playhead pergunta se o step esta LIGADO, nao se a cor e diferente
            # de apagado - senao a marca de tempo faria o verde forte em vazio
            if self.step_ligado(linha, step):
                return COR_PLAY_HIT
            return COR_PLAY
        return base

    # ── pintura ─────────────────────────────────────────────
    def pintar_coluna(self, step):
        """Repinta so uma coluna - barato o bastante pra rodar a cada step."""
        if step < 0 or self.modo_geral != MODO_ON:
            return
        dev = "E" if step < 8 else "D"
        col = step if step < 8 else step - 8
        enviar_cores(self.lp_out[dev],
                     [(self.nota_de(dev, l, col), self.cor_do_step(l, step))
                      for l in range(8)])

    def pintar(self, fator=None):
        """Repinta o grid inteiro: dois SysEx, um por Launchpad.

        'fator' e o respiro do fill: com ele, so as celulas COM NOTA saem
        escurecidas (o resto sai igual), para o pattern continuar legivel
        enquanto o grid avisa que quem esta soando e outra coisa. Passa pelo
        mesmo caminho de geometria de sempre - nao ha segunda versao desta
        funcao para manter em sincronia."""
        # fora do ON o grid nao tem o que desenhar - e o fundo preto que a
        # ondinha usa. Isso NAO e cosmetico: no standby a TR-8S pode estar
        # desligada, e cor_do_step leria um cache vazio.
        if self.modo_geral != MODO_ON:
            for dev in ("E", "D"):
                enviar_cores(self.lp_out[dev],
                             [(self.nota_de(dev, l, c), COR_OFF)
                              for l in range(8) for c in range(8)])
            return
        for dev, off in (("E", 0), ("D", 8)):
            pares = []
            for l in range(8):
                # o step do playhead DAQUELA linha uma vez por linha, nao por
                # celula: track curto tem modulo proprio, e perguntar 128 vezes
                # por quadro era exatamente o desperdicio que o "pads" fazia
                pl = self.passo_da_linha(l) if fator is not None else -1
                for c in range(8):
                    step = off + c
                    cor = self.cor_do_step(l, step)
                    # respira o que esta ACESO e tambem o playhead: ele fica no
                    # fill (a maquina o mantem) e respira junto, dizendo "o
                    # tempo e este, o som e de outra variacao"
                    if fator is not None and (self.step_ligado(l, step)
                                              or step == pl):
                        cor = respirar(cor, fator)
                    pares.append((self.nota_de(dev, l, c), cor))
            enviar_cores(self.lp_out[dev], pares)

    def _fator_respiro(self):
        """A curva do respiro, em funcao da FASE DO COMPASSO.

        Sem timer e sem estado: depende so do step atual, entao o respiro fica
        em tempo com a musica de graca e FECHA sozinho na virada - que e
        exatamente onde o fill acaba (medido em 17/08/2026: 17 de 17 transicoes
        no step 15 -> 0). Vale 1 nas pontas e RESPIRO_FUNDO no meio."""
        lim = max(1, self.last_var())
        fase = (self.passo % lim) / lim if self.passo >= 0 else 0.0
        return 1.0 - (1.0 - RESPIRO_FUNDO) * math.sin(math.pi * fase)

    def _luz(self, out, control, valor):
        if isinstance(valor, tuple):
            out.send(mido.Message('sysex', data=LED_SYSEX + _spec_cor(control, valor)))
        else:
            out.send(mido.Message('control_change', channel=0,
                                  control=control, value=valor))

    def pintar_botoes(self):
        e, d = self.lp_out["E"], self.lp_out["D"]
        if self.modo_geral != MODO_ON:
            for out in (e, d):
                for cc in FUNC_CCS + CENA_CCS + [LOGO_CC]:
                    self._luz(out, cc, COR_OFF)
            return
        # Toda cor daqui pra baixo passa por cor_borda(): o adesivo colado nos
        # botoes fica ilegivel com o LED forte embaixo (ver BRILHO_BORDA).
        # TOPO ESQUERDO (coluna de cena girada): variacoes A-H
        for i, c in enumerate(CENA_CCS):
            self._luz(e, c, cor_borda(COR_VAR, True) if self.variacao == i + 1
                      else cor_borda(COR_OFF))
        # BORDA ESQUERDA (fileira de funcao girada), de cima pra baixo
        self._luz(e, 98, cor_borda(COR_FILL, True) if self.variacao == 0x09
                  else cor_borda(COR_OFF))
        self._luz(e, 97, cor_borda(COR_FILL, True) if self.variacao == 0x0A
                  else cor_borda(COR_OFF))
        self._luz(e, 96, cor_borda(COR_ARMADO, True) if self.armado == "inst"
                  else cor_borda(COR_CLEAR))
        self._luz(e, 95, cor_borda(COR_ARMADO, True) if self.armado == "var"
                  else cor_borda(COR_CLEAR))
        self._luz(e, 94, cor_borda(COR_ATIVO, True) if self.esconder_mudos
                  else (cor_borda(COR_MUDA_BOTAO) if any(self.mudo)
                        else cor_borda(COR_OFF)))                  # ESCONDER
        self._luz(e, 93, cor_borda(COR_ALT, True) if self.alt
                  else cor_borda(COR_OFF))                         # ALT
        self._luz(e, 92, cor_borda(COR_COPIA))
        self._luz(e, 91, cor_borda(COR_COPIA, True) if self.copia
                  else cor_borda(COR_OFF))
        # TOPO DIREITO (fileira de funcao), da esquerda pra direita
        self._luz(d, 91, cor_borda(COR_SETA) if self.base_inst > 0
                  else cor_borda(COR_OFF))
        self._luz(d, 92, cor_borda(COR_SETA) if self.base_inst < self.base_max()
                  else cor_borda(COR_OFF))
        for k in range(5):
            self._luz(d, 93 + k, cor_borda(COR_ATIVO, True) if self.modo == k
                      else cor_borda(COR_OFF))
        self._luz(d, 98, cor_borda(COR_ACC, True) if self.mostrar_acc
                  else cor_borda(COR_OFF))
        # BORDA DIREITA (coluna de cena): seletor de velocity. O 80 e o 50
        # vestem a mesma cor que a nota deles vai ter no grid, porque sao os
        # dois valores que a propria maquina usa - o resto fica cinza.
        for i, c in enumerate(CENA_CCS):
            v = VELOCIDADES[i]
            if i == self.vel_idx:   cor = cor_borda(COR_ATIVO, True)
            elif v == VEL_FORTE:    cor = cor_borda(COR_FORTE)
            elif v == VEL_FRACA:    cor = cor_borda(COR_FRACA)
            else:                   cor = cor_borda(COR_VEL_OFF)
            self._luz(d, c, cor)
        # LOGOS: nao sao botoes, so LED - servem de indicador passivo.
        # O da esquerda acende quando ha alguem mutado na maquina, o que importa
        # justamente quando esconder_mudos esta ligado e a linha nem aparece.
        self._luz(e, LOGO_CC, cor_borda(COR_MUDA_BOTAO, True) if any(self.mudo)
                  else cor_borda(COR_OFF))
        self._luz(d, LOGO_CC, cor_borda(COR_OFF))

    def mover_playhead(self, novo):
        if novo == self.passo:
            return
        antigo, self.passo = self.passo, novo
        # o passo continua avancando mesmo invisivel: e isso que faz o verde
        # reaparecer no lugar certo quando voce volta pra variacao que toca,
        # em vez de ressuscitar onde parou
        if not self.playhead_visivel():
            return
        # A MAQUINA NUM FILL: o grid inteiro RESPIRA, playhead junto. Sao 16
        # quadros por compasso dirigidos pelo proprio clock, ao mesmo custo de
        # 2 SysEx por step que o playhead normal ja tinha - sem timer, sem laco
        # de fps, sem trafego novo.
        #
        # O respiro anda COLADO no playhead de proposito: ele existe para dizer
        # "o tempo e este, o som vem de outra variacao", e isso so faz sentido
        # onde ha playhead desenhado. Com o grid noutra variacao o verde ja nao
        # aparece - o grid ja nao esta afirmando nada, e nao ha o que qualificar.
        # A tela usa a MESMA condicao (ver app.mjs): as duas superficies
        # respiram juntas ou nenhuma respira.
        if self.fill_ativo and self.modo_geral == MODO_ON:
            self.pintar(self._fator_respiro())
            return
        if self.polirritmia():
            # cada linha esta numa coluna diferente: repintar duas colunas nao
            # basta. Sai caro? Nao: o quadro inteiro vai em 2 SysEx em lote.
            self.pintar()
        else:
            self.pintar_coluna(antigo)
            self.pintar_coluna(novo)

    # ── escrita na TR-8S ────────────────────────────────────
    def escrever_step(self, i, step, vel, sub, alt=False, prob=None):
        """Escreve um step. prob=None PRESERVA o byte 3 do cache (probability);
        um numero (10-100, em %) escreve. Devolve False se abortou.

        O step de 8 bytes vai inteiro pra maquina, entao os bytes que este
        metodo nao entende (0-2) saem do cache - dai o guarda: cache que nao
        reflete a maquina nao pode ser escrito de volta."""
        if self._garantir_pattern() is None:
            self.log("(!) escrita: nao sei em que pattern a maquina esta - abortado.")
            return False
        if self.escrita_bloqueada("step"):
            return False
        if i in self.cache_invalido:
            d = ler_bloco(self.tr_in, self.tr_out,
                          addr_bloco_rd(i, self.variacao, self.pattern_atual))
            if not d:
                self.log(f"(!) {INSTRUMENTOS[i]}: cache invalido e releitura "
                         "falhou - escrita abortada")
                return False
            self.cache[i][:] = d      # dentro da lista: ver _guardar_cache_var
            self.cache_invalido.discard(i)
        b = step * BYTES_P_STEP
        self.cache[i][b+VEL_HI]   = (vel >> 4) & 0x0F
        self.cache[i][b+VEL_LO]   = vel & 0x0F
        self.cache[i][b+SUB_BYTE] = sub if vel else 0
        self.cache[i][b+ALT_BYTE] = (ALT_LIGADO if alt else 0) if vel else 0
        if prob is not None and vel:
            self.cache[i][b+PROB_BYTE] = prob_para_byte(prob)
        self.tr_out.send(dt1(addr_step_rd(i, step, self.variacao, self.pattern_atual),
                             self.cache[i][b:b+BYTES_P_STEP]))
        return True

    def limpar_instrumento(self, i):
        if i >= len(INSTRUMENTOS):
            return
        for s in range(16):
            self.escrever_step(i, s, 0, 0)
            time.sleep(0.002)          # rajada: nao afogar a maquina
        self.log(f"CLEAR {INSTRUMENTOS[i]}")

    def limpar_variacao(self):
        if self._garantir_pattern() is None:
            self.log("(!) CLEAR variacao: nao sei em que pattern a maquina esta - abortado.")
            return
        if self.escrita_bloqueada("CLEAR"):
            return
        for i in range(len(INSTRUMENTOS)):
            for s in range(16):
                self.escrever_step(i, s, 0, 0)
                time.sleep(0.002)
        self.acc = 0
        self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual), mascara_para_nibbles(0)))
        self.log(f"CLEAR variacao {VARIACOES[self.variacao-1]} (11 instrumentos + ACC)")

    def copiar_variacao(self):
        # o cache e autoritativo: toda escrita nossa passa por ele
        self.copia = (VARIACOES[self.variacao-1],
                      {i: list(d) for i, d in self.cache.items()}, self.acc)
        self.log(f"COPY: variacao {self.copia[0]} no buffer")

    def colar_variacao(self):
        if self._garantir_pattern() is None:
            self.log("(!) PASTE: nao sei em que pattern a maquina esta - abortado.")
            return
        if not self.copia:
            self.log("COPY: buffer vazio - copie uma variacao primeiro"); return
        if self.escrita_bloqueada("PASTE"):
            return
        origem, blocos, mascara = self.copia
        for i, dados in blocos.items():
            for s in range(16):
                b = s * BYTES_P_STEP
                self.cache[i][b:b+BYTES_P_STEP] = dados[b:b+BYTES_P_STEP]
                self.tr_out.send(dt1(addr_step_rd(i, s, self.variacao, self.pattern_atual),
                                     dados[b:b+BYTES_P_STEP]))
                time.sleep(0.002)
        self.acc = mascara
        self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                             mascara_para_nibbles(mascara)))
        self.log(f"PASTE: {origem} -> {VARIACOES[self.variacao-1]}")

    def escrever_pattern(self, dados, accent=0, last_var=None, nome=""):
        """Escreve um pattern inteiro na variacao aberta (biblioteca/estocastica).

        dados = {indice_inst: [(vel, sub, prob, alt)] * 16} - o formato do
        biblioteca.expandir(). Rajada DT1 identica a colar_variacao (provada em
        hardware); passa por escrever_step, entao respeita o guarda do cache e
        preserva os bytes 0-2 de cada step.

        Antes de tocar em qualquer coisa tira um snapshot para desfazer_escrita
        - o mesmo formato do buffer de COPY, que ja provou o caminho de volta."""
        if self._garantir_pattern() is None:
            self.log("(!) escrever pattern: nao sei em que pattern a maquina esta - abortado.")
            return
        if self.modo_geral != MODO_ON or not self.carregado:
            self.log("(!) escrever pattern so no modo ON")
            return False
        if self.escrita_bloqueada("escrever pattern"):
            return False
        self.snapshot_escrita(f"escrita '{nome or '?'}'")
        for i in range(len(INSTRUMENTOS)):
            for s in range(16):
                vel, sub, prob, alt = dados.get(i, [(0, 0, 100, False)]*16)[s]
                if not self.escrever_step(i, s, vel, sub, alt,
                                          prob=prob if vel else None):
                    self.log("(!) escrita interrompida no "
                             f"{INSTRUMENTOS[i]} - desfazer_escrita volta o resto")
                    return False
                time.sleep(0.002)          # rajada: nao afogar a maquina
        self.acc = accent & 0xFFFF
        self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                             mascara_para_nibbles(self.acc)))
        if last_var is not None:
            self.definir_last_var(last_var)
        self.pintar()
        self.log(f"pattern '{nome or '?'}' escrito na variacao "
                 f"{VARIACOES[self.variacao-1]}")
        return True

    def definir_pattern(self, n, agora=False):
        """Troca o pattern da maquina - protocolo PROVADO em 15/08/2026.

        agora=False: escreve o PROXIMO pattern (01 00 00 02); a maquina troca
        na virada, como no painel - o modo do chain e da estrutura.
        agora=True: escreve o pattern ATUAL (01 00 00 01); corta no meio do
        compasso PRESERVANDO o step - troca de conteudo com o relogio
        intacto, para performance.

        A releitura do grid vem pela deteccao de pattern_trocou no
        ler_mudos(), igual a troca feita no painel."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) trocar pattern so no modo ON")
            return
        n = int(n) & 0x7F
        off = OFF_PATTERN_ATUAL if agora else OFF_PATTERN_PROX
        self.tr_out.send(dt1(addr_soma(ADDR_PERF, off), [n]))
        nome = nome_pattern(n)
        self.log(f"pattern {'AGORA' if agora else 'na virada'} -> {nome}")

    def definir_kit(self, n):
        """Troca o kit da maquina escrevendo o byte 0 do perf.

        HIPOTESE (15/08/2026): os offsets 1 e 2 do mesmo no sao provados
        (troca de pattern); o 0 e lido ha dias como kit atual, mas NUNCA foi
        escrito. Primeiro uso em hardware: conferir o visor. A releitura de
        nome/tones/efeitos vem pela deteccao de kit_trocou no ler_mudos()."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) trocar kit so no modo ON")
            return
        n = int(n) & 0x7F
        self.tr_out.send(dt1(addr_soma(ADDR_PERF, OFF_KIT_ATUAL), [n]))
        self.log(f"kit -> {n + 1:03d} (escrita nova em hardware: confira o "
                 "visor da TR-8S)")

    def definir_bpm(self, bpm):
        """Escreve o TEMPO (40.0-300.0) no no do pattern - o Auto BPM.

        Quatro nibbles a partir de OFF_TEMPO_NO, o campo INTEIRO: escrita
        parcial e recusada, e escrever no espelho da performance nao faz nada
        (a maquina aceita o valor ali e nao aplica). Os dois erros custaram uma
        sessao inteira em 17/08/2026 - o comentario de OFF_TEMPO_NO tem a
        historia.

        O tempo e por PATTERN: trocar de pattern troca o andamento."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) BPM so no modo ON")
            return
        if self._garantir_pattern() is None:
            self.log("(!) sem saber o pattern, o tempo cairia no no errado")
            return
        v = int(round(max(40.0, min(300.0, float(bpm))) * 10))
        self.tr_out.send(dt1(
            addr_soma(addr_no_pattern(self.pattern_atual), OFF_TEMPO_NO),
            [(v >> (4 * i)) & 0x0F for i in range(3, -1, -1)]))
        self.log(f"TEMPO -> {v / 10:.1f}")

    def snapshot_escrita(self, rotulo):
        """Empilha o estado da variacao aberta antes de uma escrita em massa.

        O rotulo e o que a tela mostra no historico ("ghosts BD", "escrita
        'Deep house'") e o que o Reverter-por-edicao compara para saber se a
        SUA edicao ainda e o topo da pilha."""
        # o PATTERN entra no snapshot desde 16/08/2026. Antes so a variacao
        # entrava, e enquanto todo endereco caia no mesmo lugar isso bastava.
        # Com o endereco correto, desfazer depois de trocar de pattern
        # despejava o conteudo do pattern antigo por cima do novo - 16 steps x
        # 11 instrumentos, calado.
        self.pilha_desfazer.append(
            (rotulo, self.variacao, self.pattern_atual,
             {i: list(d) for i, d in self.cache.items()}, self.acc))
        del self.pilha_desfazer[:-self.TETO_DESFAZER]

    def _restaurar_snapshot(self, snap):
        if self._garantir_pattern() is None:
            self.log("(!) desfazer: nao sei em que pattern a maquina esta - abortado.")
            return
        rotulo, var, pat, blocos, mascara = snap
        if self.escrita_bloqueada("desfazer"):
            return False
        if pat != self.pattern_atual:
            self.log(f"(!) '{rotulo}' foi feito no pattern "
                     f"{nome_pattern(pat) if pat is not None else '?'} e a "
                     f"maquina esta no {nome_pattern(self.pattern_atual)} - "
                     "desfazer aqui sobrescreveria o pattern errado.")
            return False
        if var != self.variacao:
            self.log(f"(!) '{rotulo}' e da variacao {VARIACOES[var-1]} - va "
                     "ate ela para desfazer")
            return False
        for i, dados_i in blocos.items():
            for s in range(16):
                b = s * BYTES_P_STEP
                self.cache[i][b:b+BYTES_P_STEP] = dados_i[b:b+BYTES_P_STEP]
                self.tr_out.send(dt1(addr_step_rd(i, s, self.variacao, self.pattern_atual),
                                     dados_i[b:b+BYTES_P_STEP]))
                time.sleep(0.002)
        self.acc = mascara
        self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                             mascara_para_nibbles(mascara)))
        self.pintar()
        return True

    def desfazer_escrita(self):
        """Desfaz a ULTIMA escrita em massa (topo da pilha)."""
        if not self.pilha_desfazer:
            self.log("(!) nada para desfazer")
            return
        if self._restaurar_snapshot(self.pilha_desfazer[-1]):
            rotulo = self.pilha_desfazer.pop()[0]
            self.log(f"desfeito: {rotulo}")

    def desfazer_tudo(self):
        """Volta ao estado ANTES da primeira escrita da pilha e a esvazia."""
        if not self.pilha_desfazer:
            self.log("(!) nada para desfazer")
            return
        if self._restaurar_snapshot(self.pilha_desfazer[0]):
            n = len(self.pilha_desfazer)
            self.pilha_desfazer.clear()
            self.log(f"desfeitas {n} edicoes - variacao de volta ao inicio")

    def alternar(self, linha, step):
        # a linha mutada continua editavel: ela some do grid so quando voce pede,
        # e enquanto esta a vista escrever nela e legitimo - o pattern existe, o
        # que esta desligado e o som. Por isso nao ha desvio aqui.
        #
        # O guarda do espelho, esse sim, vale para tudo: as linhas de ACC
        # mandam DT1 direto, sem passar pelo escrever_step
        if self.escrita_bloqueada("grid"):
            return
        if self.armado == "inst":                 # CLEAR armado: limpa a linha
            self.armado = None
            if self.eh_acc(linha):
                self.acc = 0
                self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                                     mascara_para_nibbles(0)))
                self.log("CLEAR ACCENT")
            else:
                i = self.inst_da_linha(linha)
                if i is not None:
                    self.limpar_instrumento(i)
            self.pintar(); self.pintar_botoes()
            return
        if self.eh_acc(linha):
            self.acc ^= (1 << step)
            self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                                 mascara_para_nibbles(self.acc)))
            self.log(f"ACC step {step+1:2} -> "
                     f"{'ON ' if self.acc & (1<<step) else 'OFF'}  (0x{self.acc:04X})")
            return
        i = self.inst_da_linha(linha)
        if i is None:
            return
        vel_alvo, sub_alvo, alt_alvo = (VELOCIDADES[self.vel_idx],
                                        MODOS[self.modo][1], self.alt)
        # identico ao que ja esta la -> desliga; diferente -> repinta.
        # sem isso, trocar a velocity de um step existente exigiria dois toques.
        # o ALT entra na comparacao pelo mesmo motivo: com ele de fora, ligar o
        # alternate num step que ja existe apagaria o step em vez de marca-lo.
        if (self.ler_vel(i, step) == vel_alvo and self.ler_sub(i, step) == sub_alvo
                and self.ler_alt(i, step) == alt_alvo):
            vel_alvo, sub_alvo, alt_alvo = 0, 0, False
        self.escrever_step(i, step, vel_alvo, sub_alvo, alt_alvo)
        desc = "OFF" if vel_alvo == 0 else \
               f"vel {vel_alvo}" + ("" if sub_alvo == 0 else f" + {MODOS[self.modo][0]}") \
               + (" + ALT" if alt_alvo else "")
        self.log(f"{INSTRUMENTOS[i]:3} step {step+1:2} -> {desc}")

    def alternar_editor(self, i, step, fraco=False):
        """Toggle de step vindo da JANELA: mesmo criterio do alternar() dos
        pads, mas com o indice do instrumento direto (sem a geometria do
        launchpad). i == len(INSTRUMENTOS) e a linha do ACCENT. Roda via
        enfileirar(), na thread do motor."""
        if self.modo_geral != MODO_ON or not self.carregado:
            self.log("(!) o editor so escreve no modo ON")
            return
        # a linha do ACCENT manda DT1 direto, sem passar pelo escrever_step
        if self.escrita_bloqueada("editor"):
            return
        if i == len(INSTRUMENTOS):
            self.acc ^= (1 << step)
            self.tr_out.send(dt1(addr_accent_rd(self.variacao, self.pattern_atual),
                                 mascara_para_nibbles(self.acc)))
            self.log(f"ACC step {step+1:2} -> "
                     f"{'ON ' if self.acc & (1 << step) else 'OFF'}"
                     f"  (0x{self.acc:04X})")
            self.pintar()
            return
        vel_alvo = VEL_FRACA if fraco else VELOCIDADES[self.vel_idx]
        sub_alvo, alt_alvo = MODOS[self.modo][1], self.alt
        if (self.ler_vel(i, step) == vel_alvo
                and self.ler_sub(i, step) == sub_alvo
                and self.ler_alt(i, step) == alt_alvo):
            vel_alvo, sub_alvo, alt_alvo = 0, 0, False
        if not self.escrever_step(i, step, vel_alvo, sub_alvo, alt_alvo):
            return
        self.pintar()                      # o launchpad espelha na hora
        desc = "OFF" if vel_alvo == 0 else \
            f"vel {vel_alvo}" + ("" if sub_alvo == 0
                                 else f" + {MODOS[self.modo][0]}") \
            + (" + ALT" if alt_alvo else "")
        self.log(f"{INSTRUMENTOS[i]:3} step {step+1:2} -> {desc}  (janela)")

    def definir_step(self, i, step, vel, sub=0, alt=False, prob=None):
        """Escreve um step inteiro de uma vez - e o que o menu de step da
        janela usa. Sem isto, mudar velocity de um step pela tela exigiria
        imitar o gesto do pad (escolher velocity global, escolher modo,
        clicar), que e justamente o que o TR-EDITOR nao faz."""
        if self.modo_geral != MODO_ON or not self.carregado:
            self.log("(!) editar step so no modo ON")
            return
        if not 0 <= i < len(INSTRUMENTOS) or not 0 <= step < 16:
            self.log(f"(!) step fora de faixa: inst {i}, step {step}")
            return
        if self.escrever_step(i, step, vel, sub, alt, prob=prob):
            self.pintar()
            self.log(f"{INSTRUMENTOS[i]:3} step {step+1:2} -> "
                     + ("OFF" if not vel else
                        f"vel {vel}"
                        + (f" + {MODOS[sub][0]}" if sub else "")
                        + (" + ALT" if alt else "")
                        + (f" + prob {prob}%" if prob is not None else "")))

    def esquecer_fx(self, nome):
        """Tira um parametro do mapa - para recapturar do zero."""
        if efeitos.apagar(nome):
            self.mapa_fx = efeitos.carregar()
            self.log(f"'{nome}' esquecido; pode capturar de novo")
        else:
            self.log(f"(!) '{nome}' nao estava no mapa capturado")

    def definir_prob(self, i, step, pct):
        """Escreve a PROBABILITY de um step ligado (byte 3, ver PROB_BYTE)."""
        if self.modo_geral != MODO_ON or not self.carregado:
            self.log("(!) probability so no modo ON")
            return
        if self.ler_vel(i, step) == 0:
            self.log(f"(!) {INSTRUMENTOS[i]} step {step+1} esta desligado - "
                     "probability so em step ligado")
            return
        if self.escrever_step(i, step, self.ler_vel(i, step),
                              self.ler_sub(i, step), self.ler_alt(i, step),
                              prob=pct):
            self.log(f"{INSTRUMENTOS[i]:3} step {step+1:2} -> prob {pct}%")

    # ── kit: nome e tones (enderecos ja provados pelo snap) ─
    def ler_kit(self):
        """Nome do kit + toneId dos 11 instrumentos.

        Enderecos que o snap ja leu em hardware (10 00 00/1I 00). O toneId e
        uint16 em 4 nibbles no comeco do bloco - formato do mapa do ARIA. O
        NOME que corresponde a cada id sai da tabela do proprio TR-EDITOR
        (id = NUMBER - 1), conferida contra os 22 tones dos kits TR-808 e
        TR-707 desta maquina em 15/08/2026."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) ler kit so no modo ON")
            return
        kit = self._fx_kit()
        d = ler_bloco(self.tr_in, self.tr_out, addr_kit_nome(kit), 16,
                      timeout=SNAP_TIMEOUT)
        self.kit_nome = ("".join(chr(b) for b in d if 32 <= b < 127).strip()
                         if d else None)
        for i in range(len(INSTRUMENTOS)):
            t = ler_bloco(self.tr_in, self.tr_out, addr_kit_tone(i, kit), 16,
                          timeout=SNAP_TIMEOUT)
            self.tone_ids[i] = nibbles_para_mascara(t[:4]) if t else None
        self.log(f"kit '{self.kit_nome or '?'}' lido; toneIds: "
                 + " ".join("?" if t is None else str(t)
                            for t in self.tone_ids))

    def definir_tone(self, i, tone_id):
        """Troca o tone do instrumento i - o gesto INST do TR-EDITOR.

        A ESCRITA FUNCIONA - provada em 15/08/2026, e foi ela que derrubou a
        tabela antiga: escrever o id 8 ("707 Bass1/2" pela numeracao do PDF)
        carregou "808 High Tom" na maquina. O id certo vem do tones.py
        regerado da tabela do TR-EDITOR. Round-trip continua nao provando
        som: OUVIR e conferir o nome no visor."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) trocar tone so no modo ON")
            return
        kit = self._fx_kit()
        self.tr_out.send(dt1(addr_kit_tone(i, kit),
                             mascara_para_nibbles(tone_id)))
        time.sleep(0.05)
        t = ler_bloco(self.tr_in, self.tr_out, addr_kit_tone(i, kit), 16,
                      timeout=SNAP_TIMEOUT)
        lido = nibbles_para_mascara(t[:4]) if t else None
        self.tone_ids[i] = lido
        self.log(f"{INSTRUMENTOS[i]}: toneId {tone_id} escrito, relido "
                 f"{lido if lido is not None else '?'} - toque o pad e confira "
                 "o som E o nome no visor da TR-8S (id->nome e hipotese)")

    # ── mixer/FX: decodificacao por observacao (efeitos.py) ─
    def _fx_tam_kit(self):
        """105 bytes: o que o TR-EDITOR pede de 10 KK 00 00 (sniff 15/08)."""
        return efeitos.BLOCOS["kit"]["tam"]

    def ler_fx(self):
        """Rele os 26 blocos de efeito do kit atual (efeitos.BLOCOS).

        Ate 15/08/2026 isto sondava o no do kit com 128 bytes para descobrir
        o tamanho. A sonda morreu com o sniff: o TR-EDITOR le 105, e pedir
        128 de um bloco de 105 e exatamente a leitura fora da faixa que a
        3.1 diz envenenar a porta CTRL. Agora todo tamanho vem da tabela do
        que o editor oficial pede."""
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) ler FX so no modo ON")
            return
        faltaram = []
        for chave, addr, tam in self._fx_alvos():
            d = ler_bloco(self.tr_in, self.tr_out, addr, tam,
                          timeout=SNAP_TIMEOUT)
            if d:
                self.fx_blocos[chave] = list(d)
                self._lembrar_kit_level(chave)
            else:
                faltaram.append(chave)
        if faltaram:
            self.log(f"(!) {len(faltaram)} bloco(s) de FX sem resposta: "
                     + ", ".join(faltaram[:6])
                     + ("..." if len(faltaram) > 6 else ""))

    def _fx_kit(self):
        """Numero do kit para o endereco. NAO VERIFICADO se o byte lido do
        no de performance ja e 0-based: o kit "003" do Luan mora em 10 02, e
        so uma comparacao com o visor fecha isso. Enquanto nao fecha, vale o
        valor cru - que ao menos acerta o kit 001 como antes."""
        return self.kit_atual or 0

    def _fx_alvos(self):
        """Todos os blocos de efeito do kit atual: (chave, endereco, tamanho).

        A chave identifica o bloco no self.fx_blocos ('reverb', 'inst:0'...).
        Os tamanhos sao os que o TR-EDITOR pede - ler alem do fim de um bloco
        e justamente o RQ1 invalido que mata a porta CTRL (REFERENCIA 3.1)."""
        kit = self._fx_kit()
        alvos = []
        for nome, b in efeitos.BLOCOS.items():
            if b["por_inst"]:
                for i in range(len(INSTRUMENTOS)):
                    alvos.append((f"{nome}:{i}", addr_fx(nome, kit, i),
                                  b["tam"]))
            else:
                tam = self._fx_tam_kit() if nome == "kit" else b["tam"]
                alvos.append((nome, addr_fx(nome, kit), tam))
        return alvos

    # quantos blocos de FX o tick relê por vez. 4 esvazia os 26 em ~7 ciclos
    # (uns 3 s) sem deixar o pattern sem banda para a sua propria releitura.
    FX_POR_CICLO = 4

    def _drenar_fx_fila(self):
        for _ in range(self.FX_POR_CICLO):
            if not self.fx_fila:
                return
            self._bombear_clock()      # 4 blocos sao ~100 ms de tick parado
            chave, addr, tam = self.fx_fila.pop(0)
            d = ler_bloco(self.tr_in, self.tr_out, addr, tam,
                          timeout=SNAP_TIMEOUT)
            if d:
                self.fx_blocos[chave] = list(d)
                # e por aqui que o bloco chega depois de uma troca de kit: o
                # ler_fx inteiro so roda ao entrar no modo ON
                self._lembrar_kit_level(chave)

    def _lembrar_kit_level(self, chave):
        """Guarda o VOLUME DO KIT como ele chegou da maquina.

        Pedido do Luan em 17/08/2026: um botao que devolve o volume do kit ao
        que era. "De fabrica" nao da para saber - o valor de fabrica so existe
        na memoria da maquina, e recarregar o kit para ler seria mais caro que
        o problema. O que da para prometer com honestidade e ESTE valor: o que
        estava quando o kit foi lido, antes de qualquer mexida nossa. E e isso
        que a dica na tela diz."""
        if chave != "kit" or self.kit_level_ref is not None:
            return
        ent = self.mapa_fx.get("kit level")
        if ent:
            self.kit_level_ref = self._fx_ler_valor(self.fx_blocos.get("kit"),
                                                    ent)

    def resetar_kit_level(self):
        """Devolve o volume do kit ao valor de quando o kit foi lido."""
        if self.kit_level_ref is None:
            self.log("(!) ainda nao li o volume original deste kit")
            return
        self.definir_fx("kit level", self.kit_level_ref)

    def _fx_alvo(self, ent, inst=None):
        """(chave do bloco, endereco base, tamanho) do parametro."""
        bloco = ent.get("bloco") or ("inst" if ent["tipo"] == "inst" else "kit")
        b = efeitos.BLOCOS.get(bloco)
        if b is None:                       # bloco desconhecido: nao adivinha
            return None, None, 0
        kit = self._fx_kit()
        if b["por_inst"]:
            return f"{bloco}:{inst}", addr_fx(bloco, kit, inst), b["tam"]
        tam = self._fx_tam_kit() if bloco == "kit" else b["tam"]
        return bloco, addr_fx(bloco, kit), tam

    @staticmethod
    def _fx_off(ent, inst=None):
        """Offset efetivo do parametro. 'off_por_inst' e o terceiro caso de
        enderecamento: um byte por instrumento DENTRO de um bloco de kit
        (CTRL em 0x01+i; COLOR 0x42+i, OUTPUT e choke sao o mesmo padrao)."""
        if ent.get("off_por_inst") and inst is not None:
            return ent["off"] + int(inst)
        return ent["off"]

    @staticmethod
    def _fx_ler_valor(bloco, ent, inst=None):
        """Valor de um parametro no bloco. Parametros de faixa 0-255 ocupam
        DOIS bytes em nibbles, do mesmo jeito que a velocity (REFERENCIA 2.4):
        valor = (hi << 4) | lo."""
        off, n = Motor._fx_off(ent, inst), ent.get("bytes", 1)
        if not bloco or off + n > len(bloco):
            return None
        if n == 2:
            return (bloco[off] << 4) | (bloco[off + 1] & 0x0F)
        return bloco[off]

    @staticmethod
    def _fx_bytes(valor, ent):
        if ent.get("bytes", 1) == 2:
            return [(valor >> 4) & 0x0F, valor & 0x0F]
        return [valor & 0x7F]

    def iniciar_captura_fx(self, nome):
        """Captura guiada: retrata os blocos e espera o controle mexer.

        O Luan mexe SO no controle que quer mapear, no painel; o tick relê e
        compara; o byte que mudou vira a entrada do mapa (efeitos.registrar).
        Leitura passiva em enderecos validos - zero RQ1 novo no desconhecido.

        Parametro de 2 bytes (faixa 0-255) so e registrado quando os DOIS
        offsets vizinhos ja tiverem sido vistos mudando - por isso a instrucao
        de girar o knob de ponta a ponta."""
        nome = (nome or "").strip().lower()
        if not nome:
            self.log("(!) de um nome ao parametro antes de capturar")
            return
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) captura so no modo ON")
            return
        self.ler_fx()
        if not self.fx_blocos:
            self.log("(!) nao consegui ler os blocos do kit - captura abortada")
            return
        cat = efeitos.POR_NOME.get(nome, {})
        esperado = cat.get("bytes", 1)
        self.captura_fx = {"nome": nome, "t": 0.0, "bytes": esperado,
                           "vistos": {}, "chave": None,
                           "antes": {k: list(v)
                                     for k, v in self.fx_blocos.items()}}
        dica = cat.get("dica")
        self.log(f"capturando '{nome}': mexa SO nesse controle no painel"
                 + (f" ({dica})" if dica else "")
                 + ("  - gire de ponta a ponta, e um parametro de 2 bytes"
                    if esperado == 2 else ""))

    def cancelar_captura_fx(self):
        self.captura_fx = None
        self.log("captura cancelada")

    def _fx_fechar_captura(self, c, chave, off, nbytes):
        bloco, _, idx = chave.partition(":")
        tipo = "inst" if idx else "kit"
        self.mapa_fx[c["nome"]] = efeitos.registrar(c["nome"], tipo, off,
                                                    nbytes, bloco)
        onde = (f"bloco {bloco}" if not idx
                else f"bloco {bloco} (visto no {INSTRUMENTOS[int(idx)]})")
        self.log(f"CAPTURADO '{c['nome']}': {onde}, offset {off}"
                 + (f" (2 bytes: {off} e {off+1})" if nbytes == 2 else "")
                 + ". Mexa o controle novo na janela e OUCA para confirmar.")
        self.captura_fx = None

    def _tick_captura_fx(self):
        c = self.captura_fx
        if not c or time.time() - c["t"] < 0.35:
            return
        c["t"] = time.time()
        for chave, addr, tam in self._fx_alvos():
            d = ler_bloco(self.tr_in, self.tr_out, addr, tam,
                          timeout=SNAP_TIMEOUT)
            if not d:
                continue
            antes = c["antes"].get(chave)
            self.fx_blocos[chave] = list(d)
            if antes is None or list(d) == antes:
                continue
            difs = [off for off, (a, b) in enumerate(zip(antes, d)) if a != b]
            c["antes"][chave] = list(d)
            if len(difs) > 4:
                # trocou de kit/tone, nao girou um knob: retrato renovado
                self.log(f"(!) {len(difs)} bytes mudaram de uma vez - isso "
                         "nao foi um knob; retrato renovado, tente de novo")
                return
            if c["chave"] is not None and c["chave"] != chave:
                continue                       # ruido noutro bloco: ignora
            c["chave"] = chave
            for off in difs:
                c["vistos"][off] = c["vistos"].get(off, 0) + 1
            if c["bytes"] == 1:
                self._fx_fechar_captura(c, chave, difs[0], 1)
                return
            # 2 bytes: preciso do par vizinho (hi e lo)
            offs = sorted(c["vistos"])
            par = next(((o, o + 1) for o in offs if o + 1 in c["vistos"]),
                       None)
            if par:
                self._fx_fechar_captura(c, chave, par[0], 2)
            else:
                self.log(f"vi o offset {offs[0]} mexer; gire ate o OUTRO "
                         "extremo para eu confirmar o par de bytes")
            return

    def anotar_opcao(self, nome, rotulo, inst=None):
        """Le o valor ATUAL e associa ao rotulo que esta no visor da maquina.

        E assim que os codigos dos enums (waveform do LFO, destino, tipo de
        FX) sao descobertos: o Luan poe a opcao no visor e diz qual e."""
        ent = self.mapa_fx.get(nome)
        if not ent:
            self.log(f"(!) '{nome}' ainda nao foi capturado")
            return
        rotulo = (rotulo or "").strip()
        if not rotulo:
            self.log("(!) escolha o rotulo da opcao que esta no visor")
            return
        chave, base, tam = self._fx_alvo(ent, inst)
        if ent["tipo"] == "inst" and inst is None:
            self.log(f"(!) '{nome}' e por instrumento - falta qual")
            return
        d = ler_bloco(self.tr_in, self.tr_out, base, tam, timeout=SNAP_TIMEOUT)
        if not d:
            self.log("(!) nao consegui reler o bloco")
            return
        self.fx_blocos[chave] = list(d)
        valor = self._fx_ler_valor(d, ent, inst)
        opcoes = efeitos.registrar_opcao(nome, valor, rotulo)
        if opcoes is not None:
            ent["opcoes"] = opcoes
        self.log(f"'{nome}': codigo {valor} = {rotulo}"
                 f"  ({len(ent.get('opcoes', {}))} opcoes conhecidas)")

    def definir_fx(self, nome, valor, inst=None):
        """Escreve um parametro mapeado: DT1 de 1 ou 2 bytes (escrita de byte
        em offset arbitrario e provada - REFERENCIA 3) e releitura do bloco
        para conferir."""
        ent = self.mapa_fx.get(nome)
        if not ent:
            self.log(f"(!) parametro '{nome}' nao mapeado")
            return
        if self.modo_geral != MODO_ON or not self.tr_out:
            self.log("(!) FX so no modo ON")
            return
        if ent["tipo"] == "inst" and inst is None:
            self.log(f"(!) '{nome}' e por instrumento - falta qual")
            return
        valor = max(ent.get("min", 0), min(ent.get("max", 127), int(valor)))
        chave, base, tam = self._fx_alvo(ent, inst)
        self.tr_out.send(dt1(addr_soma(base, self._fx_off(ent, inst)),
                             self._fx_bytes(valor, ent)))
        d = ler_bloco(self.tr_in, self.tr_out, base, tam, timeout=SNAP_TIMEOUT)
        lido = None
        if d:
            self.fx_blocos[chave] = list(d)
            lido = self._fx_ler_valor(d, ent, inst)
        alvo = nome if inst is None else f"{nome} do {INSTRUMENTOS[inst]}"
        self.log(f"{alvo} -> {efeitos.rotulo_valor(ent, valor, nome)}"
                 + (f" (relido {lido})" if lido is not None else "")
                 + "  - o ouvido confirma, nao o round-trip")

    def _fx_valores(self):
        """Valor de cada parametro mapeado. Os por-instrumento viram lista de
        11 (a tela escolhe pelo instrumento selecionado)."""
        out = {}
        for nome, ent in self.mapa_fx.items():
            bloco = ent.get("bloco") or ("inst" if ent["tipo"] == "inst"
                                         else "kit")
            b = efeitos.BLOCOS.get(bloco)
            if b is None:
                out[nome] = None
                continue
            if b["por_inst"]:
                out[nome] = [
                    self._fx_ler_valor(self.fx_blocos.get(f"{bloco}:{i}"), ent)
                    for i in range(len(INSTRUMENTOS))]
            elif ent.get("off_por_inst"):
                # um byte por instrumento dentro de um bloco de kit (CTRL):
                # vira lista de 11, igual aos blocos por_inst
                d = self.fx_blocos.get(bloco)
                out[nome] = [self._fx_ler_valor(d, ent, i)
                             for i in range(len(INSTRUMENTOS))]
            else:
                out[nome] = self._fx_ler_valor(self.fx_blocos.get(bloco), ent)
        return out

    # ── probability por instrumento (fileira PROB do mixer) ─
    def _prob_inst(self, i):
        """Prob comum aos steps ativos do instrumento, ou None se misto/vazio."""
        ps = {self.ler_prob(i, s) for s in range(16) if self.ler_vel(i, s)}
        return ps.pop() if len(ps) == 1 else None

    def definir_prob_inst(self, i, pct):
        """Escreve a probability em TODOS os steps ativos do instrumento."""
        if self.modo_geral != MODO_ON or not self.carregado:
            self.log("(!) probability so no modo ON")
            return
        n = 0
        for s in range(16):
            if self.ler_vel(i, s):
                if not self.escrever_step(i, s, self.ler_vel(i, s),
                                          self.ler_sub(i, s),
                                          self.ler_alt(i, s), prob=pct):
                    return
                time.sleep(0.002)
                n += 1
        self.log(f"{INSTRUMENTOS[i]:3}: prob {pct}% em {n} steps ativos")

    # ── utility (bloco 50 00 00 xx, NAO testado em hardware) ─
    def _util_pronto(self):
        if self.modo_geral != MODO_ON or not (self.tr_in and self.tr_out):
            self.log("(!) utility so no modo ON (porta CTRL)")
            return False
        return True

    def util_esta_tocando(self):
        if not self._util_pronto():
            return None
        r = ler_util(self.tr_in, self.tr_out, UTIL_PLAYING)
        if r is None:
            self.log("utility playing: sem resposta (registrar na REFERENCIA)")
            return None
        toca = bool(r and r[0])
        self.log(f"a maquina respondeu: {'TOCANDO' if toca else 'parada'} "
                 f"(bytes {r}) - confira com os olhos e registre")
        return toca

    def util_versao(self):
        if not self._util_pronto():
            return None
        r = ler_util(self.tr_in, self.tr_out, UTIL_VERSION)
        if r is None:
            self.log("utility version: sem resposta (registrar na REFERENCIA)")
            return None
        texto = "".join(chr(b) for b in r if 32 <= b < 127)
        self.log(f"firmware: '{texto}' (bytes {r})")
        return texto

    def util_escrever_visor(self, texto):
        """32 chars ASCII no visor da TR-8S. O ARIA usa isto DEPOIS de travar
        a maquina (lock) - pode ser que sem lock o firmware sobrescreva no
        refresh seguinte. E exatamente o que a observacao vai dizer."""
        if not self._util_pronto():
            return
        dados = [ord(c) & 0x7F for c in texto.ljust(32)[:32]]
        self.tr_out.send(dt1(addr_util(UTIL_DISPLAY), dados))
        self.log(f"visor: '{texto[:32]}' enviado - apareceu na maquina? "
                 "por quanto tempo? (registrar)")

    def util_write_pattern(self):
        """WRITE por SysEx: pede a maquina gravar o pattern ATUAL na memoria.

        Nas capturas ele so aparece como commit de bulk transfer; que ele
        tambem grave o buffer editado por DT1 e a hipotese da sessao - o
        teste de verdade e religar a maquina e ver se o que o grid escreveu
        sobreviveu."""
        if not self._util_pronto():
            return
        if self.pattern_atual is None:
            self.log("(!) nao sei o numero do pattern atual ainda "
                     "(a proxima releitura pega)")
            return
        n = self.pattern_atual
        self.tr_out.send(dt1(addr_util(UTIL_WRITE_PATTERN),
                             [(n >> 7) & 0x7F, n & 0x7F]))
        banco, dentro = "ABCDEFGH"[n // 16], n % 16 + 1
        self.log(f"WRITE do pattern {banco}{dentro} enviado - o visor reagiu? "
                 "religue a maquina depois e veja se a edicao sobreviveu")

    def visiveis(self):
        vis = self.lista_visivel()[self.base_inst:
                                   self.base_inst + self.linhas_de_inst()]
        return " ".join(
            (INSTRUMENTOS[i].lower() if self.mudo[i] else INSTRUMENTOS[i])
            for i in vis)                 # minusculo = mutado na TR-8S

    def executar(self, tipo, arg):
        if tipo == "variacao":
            self.variacao, self.armado = arg, None
            # se esta variacao ja foi lida (o rodizio da maquina volta nela a
            # cada volta), mostra AGORA e confirma depois - ver _guardar_cache_var
            guardado = self.cache_var.get((self.pattern_atual, arg))
            if guardado:
                self.cache, self.acc = dict(guardado[0]), guardado[1]
                self.pintar()
            self.recarregar()
            # o passo global nao parou de contar, mas o last step da variacao
            # nova pode ser outro - sem isto o verde reapareceria fora do lugar
            # ate o proximo ciclo de releitura
            self._ressincronizar()
            self.pintar(); self.pintar_botoes()
            tocando = (self.variacao_tocando is not None
                       and self.variacao != self.variacao_tocando)
            self.log(f"variacao {VARIACOES[self.variacao-1]}"
                     + (f"  (a TR-8S esta tocando a "
                        f"{VARIACOES[self.variacao_tocando-1]} - sem playhead aqui)"
                        if tocando else ""))
        elif tipo == "velocidade":
            self.vel_idx = arg; self.pintar_botoes()
            self.log(f"velocity {VELOCIDADES[self.vel_idx]}")
        elif tipo == "modo":
            self.modo = arg; self.pintar_botoes()
            self.log(f"modo: {MODOS[self.modo][0]}")
        elif tipo == "rolar":
            # arg e a DIRECAO (-1/+1); quantas linhas ela anda e o passo_inst.
            # Assim o botao da tela e o pad do Launchpad andam igual, sem cada
            # um carregar o proprio numero
            passo = self.passo_inst if abs(arg) == 1 else 1
            novo = min(self.base_max(), max(0, self.base_inst + arg * passo))
            if novo == self.base_inst: return
            self.base_inst = novo; self.pintar(); self.pintar_botoes()
            self.log(f"linhas: {self.visiveis()}")
        elif tipo == "acc":
            self.mostrar_acc = not self.mostrar_acc
            self.base_inst = min(self.base_inst, self.base_max())
            self.pintar(); self.pintar_botoes()
            self.log(f"ACCENT {'no grid' if self.mostrar_acc else 'fora'}  |  "
                     f"linhas: {self.visiveis()}")
        elif tipo == "limpar_inst":
            self.armado = None if self.armado == "inst" else "inst"
            self.pintar_botoes()
            self.log("CLEAR instrumento: " +
                     ("aperte um pad da linha" if self.armado else "cancelado"))
        elif tipo == "limpar_var":
            agora = time.time()
            if self.armado == "var" and agora - self.armado_t < 2.0:
                self.armado = None
                self.limpar_variacao(); self.pintar(); self.pintar_botoes()
            else:
                self.armado, self.armado_t = "var", agora
                self.pintar_botoes()
                self.log("CLEAR variacao: aperte de novo em 2 s pra confirmar")
        elif tipo == "copiar":
            self.copiar_variacao(); self.pintar_botoes()
        elif tipo == "colar":
            self.colar_variacao(); self.pintar(); self.pintar_botoes()
        elif tipo == "oculto":
            self.esconder_mudos = not self.esconder_mudos
            self.base_inst = min(self.base_inst, self.base_max())
            self._persistir()
            self.pintar(); self.pintar_botoes()
            quantos = sum(self.mudo)
            self.log(("linhas mutadas fora do grid" if self.esconder_mudos else
                      "linhas mutadas de volta ao grid, em roxo/azul")
                     + (f" ({quantos} mutado{'s' if quantos != 1 else ''})"
                        if quantos else "  (ninguem mutado na TR-8S agora)")
                     + f"  |  linhas: {self.visiveis()}")
        elif tipo == "alt":
            self.alt = not self.alt
            self.pintar_botoes()
            self.log("ALT " + ("ligado: os pads gravam o som alternado"
                               if self.alt else "desligado")
                     + "  (so soa nos tones com / no nome - REFERENCIA 5.2)")

    # ── modos ───────────────────────────────────────────────
    def definir_modo(self, modo, estilo=None):
        """Troca entre ON, off e standby. Devolve False se recusou.

        O 'estilo' so vale pro standby, e trocar de estilo estando ja em standby
        precisa passar batido pelo atalho de 'mesmo modo' - senao clicar
        'ambiente' com a chuva rodando nao faria nada."""
        with self.lock:
            trocou_estilo = (modo == MODO_STANDBY and estilo is not None
                             and estilo != self.estilo_standby)
            if modo == self.modo_geral and not trocou_estilo:
                return True
            # o espelho da janela zera em TODA troca: saindo do standby o
            # _animar nao roda mais (ondas vazias, nada sujo), entao ninguem
            # limparia o ultimo quadro e a janela ficaria com uma onda congelada
            # enquanto os LEDs ja estao pretos
            if modo == MODO_STANDBY:
                self.estilo_standby = estilo or self.estilo_standby
                self.ondas, self.onda_suja = [], False
                self.proxima_onda = 0.0        # a primeira onda nasce ja
            if modo == MODO_ON:
                if not self._abrir_tr8s():
                    self.log("(!) porta TR-8S CTRL nao encontrada. A maquina esta "
                             "ligada? O modo off funciona sem ela.")
                    return False
                self.abrir_clock()
                self.modo_geral = MODO_ON
                if not self.carregado:
                    self.recarregar()
                    self.log(f"Variacao {VARIACOES[self.variacao-1]} carregada. "
                             f"ACCENT = 0x{self.acc:04X}")
                    self.ler_kit()
                    self.ler_fx()
                self.adotar_transporte()
            else:
                self.modo_geral = modo
                self.ondas, self.onda_suja = [], False
                self.armado = None
            self.pintar(); self.pintar_botoes()
            self.log({MODO_ON: "ON - o grid esta escrevendo na TR-8S",
                      MODO_OFF: "off - LEDs apagados, os pads so fazem ondinha",
                      MODO_STANDBY: f"standby ({self.estilo_standby}) - ondas "
                                    "nascendo sozinhas; a TR-8S nao e tocada"
                      }[self.modo_geral])
            return True

    # ── ondinha do modo off e do standby ────────────────────
    @staticmethod
    def _cor_aleatoria():
        h = random.random() * 6.0
        i, f = int(h), h - int(h)
        r, g, b = [(1, f, 0), (1-f, 1, 0), (0, 1, f),
                   (0, 1-f, 1), (f, 0, 1), (1, 0, 1-f)][i % 6]
        return (r * 127, g * 127, b * 127)

    def _nova_onda(self, lin, col, estilo=None):
        """Poe uma onda no grid. Cada onda carrega os proprios parametros.

        Sem estilo, sao as constantes ONDA_* de sempre - o toque no modo off
        continua identico ao que ja rodou em hardware. Com estilo, sorteia nas
        faixas de STANDBY_ESTILOS, o que faz duas ondas nunca serem iguais."""
        rgb = self._cor_aleatoria()
        if estilo is None:
            vel, larg, alc = ONDA_VEL, ONDA_LARGURA, ONDA_ALCANCE
        else:
            e = STANDBY_ESTILOS[estilo]
            vel  = random.uniform(*e["vel"])
            larg = random.uniform(*e["larg"])
            alc  = random.uniform(*e["alc"])
            rgb  = tuple(c * e["brilho"] for c in rgb)
        self.ondas.append({"lin": lin, "col": col, "t0": time.time(),
                           "rgb": rgb, "vel": vel, "larg": larg, "alc": alc})

    def _fps_atual(self):
        if self.modo_geral == MODO_STANDBY:
            return STANDBY_ESTILOS[self.estilo_standby]["fps"]
        return ONDA_FPS

    def _semear(self):
        """Onda automatica do standby, no ritmo do estilo."""
        agora = time.time()
        if agora < self.proxima_onda:
            return
        e = STANDBY_ESTILOS[self.estilo_standby]
        self.proxima_onda = agora + random.uniform(*e["intervalo"])
        self._nova_onda(random.randrange(8), random.randrange(16),
                        self.estilo_standby)

    def _animar(self):
        agora = time.time()
        if agora - self.ultimo_quadro < 1.0 / self._fps_atual():
            return
        self.ultimo_quadro = agora
        self.ondas = [o for o in self.ondas
                      if (agora - o["t0"]) * o["vel"] < o["alc"]]
        if not self.ondas:
            if self.onda_suja:            # um ultimo quadro pra apagar tudo
                self.pintar(); self.onda_suja = False
            return
        self.onda_suja = True
        for dev, off in (("E", 0), ("D", 8)):
            pares = []
            for l in range(8):
                for c in range(8):
                    step, r, g, b = off + c, 0.0, 0.0, 0.0
                    for o in self.ondas:
                        vt = (agora - o["t0"]) * o["vel"]
                        d = math.hypot(l - o["lin"], step - o["col"])
                        anel = 1.0 - abs(d - vt) / o["larg"]
                        if anel <= 0: continue
                        k = anel * (1.0 - vt / o["alc"])
                        r += o["rgb"][0]*k; g += o["rgb"][1]*k; b += o["rgb"][2]*k
                    cor = (min(127, r), min(127, g), min(127, b))
                    pares.append((self.nota_de(dev, l, c), cor))
            enviar_cores(self.lp_out[dev], pares)

    # ── laco ────────────────────────────────────────────────
    def _ler_clock(self):
        if not self.clk:
            return
        if self.modo_geral != MODO_ON:
            self.clk.iter_pending()    # drena e descarta: senao, ao voltar pro ON,
            return                     # um monte de clock atrasado chutaria o playhead
        lote = 0            # pulsos consecutivos, aplicados de uma vez so
        for msg in self.clk.iter_pending():
            t = msg.type
            if t == 'clock':
                # carimbo para o BPM medido (24 ppq); a TR-8S manda clock
                # mesmo parada, entao o BPM aparece sempre que ha cabo
                self._clock_ts.append(time.time())
                lote += 1
                continue
            # transporte fecha o lote: aplicar depois inverteria a ordem
            lote = self._aplicar_pulsos(lote)
            if t == 'start':
                self.pulsos, self.passo_abs, self.tocando = 0, 0, True
                self._ancorar_ciclo_vars()
                self.mover_playhead(0)
            elif t == 'continue':
                # retomada no meio: com varias variacoes habilitadas nao ha
                # como saber em qual a maquina esta - honesto e "?"
                self.tocando = True
                if len(self.vars_habilitadas) > 1:
                    self.ciclo.soltar()
                    self.variacao_tocando = None
                    self.var_presumida = False
            elif t == 'stop':
                # repinta o quadro inteiro, nao a coluna: com track curto cada
                # linha tem o playhead numa coluna diferente, e limpar so uma
                # deixaria as outras com o verde preso na tela
                self.tocando, self.passo = False, -1
                self.pintar()
        self._aplicar_pulsos(lote)

    def _aplicar_pulsos(self, lote):
        """Aplica N pulsos de clock de uma vez. Devolve 0 (lote zerado).

        Em lote porque, desde que a porta de clock virou modo callback, nada
        mais e descartado: depois de uma leitura longa (recarregar, ler_kit)
        chega uma RAJADA de pulsos represados. Pintar um por um varreria o
        grid inteiro numa piscada, e ninguem veria nada util - o playhead so
        precisa chegar onde a musica esta."""
        if lote and self.tocando:
            self.pulsos += lote
            self.passo_abs = self.pulsos // self.pulsos_p_step()
            self._avancar_ciclo_vars()
            # da a volta no last step da variacao, nao em 16 fixo - era
            # a causa da dessincronizacao documentada na REFERENCIA 5
            self.mover_playhead(self.passo_abs % max(1, self.last_var()))
            self._atender_var_pedida()
        if lote > 1:
            # QUALQUER lote acima de 1 carimba pulsos com a mesma hora - a da
            # drenagem, nao a da chegada - e encolhe o dt da janela do BPM, que
            # entao salta (medido: 86 -> ~109 por 0,7 s com lote de 6). Sumir
            # por um instante e honesto; mentir o andamento, nao
            self._clock_ts.clear()
        return 0

    def pedir_variacao(self, v):
        """Duplo clique numa variacao: ela passa a tocar na proxima virada.

        Diferente do clique simples, que so ABRE a variacao no grid pra editar
        (e ai o playhead some, porque o grid nao esta no que soa).

        PROVADO EM HARDWARE em 16/08/2026: tres pedidos seguidos, a maquina
        obedeceu nos tres (log em REFERENCIA, secao da mascara 63-66).

        Escrevemos um bit so, e isso e o que torna o resultado auto-confirmante:
        a maquina fica com UMA variacao habilitada, entao a releitura seguinte
        de ler_last_steps ve len(vars_habilitadas)==1 e crava a variacao tocando
        com CERTEZA, sem depender de conta de clock nenhuma. E o unico caminho
        em que a variacao que toca deixa de ser deducao e vira leitura.

        Efeito colateral a ter em conta: com um bit so, o rodizio A->B->C morre.
        Quem quiser o rodizio de volta usa alternar_no_ciclo."""
        with self.lock:
            # os Fill In (9, 10) NAO tem slot na mascara 63-66: ela so reporta
            # A-H (REFERENCIA 2.3.2, medido em 14/08). Escrever 1<<8 mandaria um
            # bit de significado desconhecido e, pior, uma mascara com ZERO
            # variacao A-H habilitada - estado que ninguem testou, com a caixa
            # tocando. O botao existe para ABRIR o fill no grid, nao para pedi-lo
            if v > 8:
                self.log(f"(!) {VARIACOES[v-1]} e Fill In: pedir que ele toque "
                         "nao tem endereco conhecido (use o painel)")
                return
            if v not in self.vars_habilitadas and len(self.vars_habilitadas) > 1:
                self.log(f"(!) {VARIACOES[v-1]} nao esta habilitada na maquina")
                return
            if not self.tocando:
                self.var_pedida = None
                self._escrever_var_mask(v)
                return
            self.var_pedida = v
            self._ciclo_pedido = self.passo_abs // max(1, self.last_var())
            self.log(f"variacao {VARIACOES[v-1]} pedida - entra na virada")

    def _escrever_var_mask(self, v):
        if not self.tr_out:
            self.log("(!) sem porta CTRL - ligue o modo ON")
            return
        p = self._pattern_para_escrever("pedir variacao")
        if p is None:
            return
        self.tr_out.send(dt1(addr_soma(addr_no_pattern(p), OFF_VAR_TOCANDO),
                             mascara_para_nibbles(1 << (v - 1))))
        self.log(f"pedi a variacao {VARIACOES[v-1]} a maquina "
                 "(a proxima leitura confirma se ela obedeceu)")

    def alternar_no_ciclo(self, v):
        """Liga/desliga uma variacao no RODIZIO, sem zerar as outras.

        Existe porque o duplo clique (pedir_variacao) escreve UM bit e por isso
        desliga o rodizio: quem estava com A+B+C ciclando passava a ouvir so
        uma, sem caminho de volta pelo app. Aqui a mascara e montada com
        varios bits - mesmo endereco, cuja escrita foi provada em 16/08/2026.

        Nunca deixa a mascara vazia: zero variacao habilitada e um estado que
        nao sabemos o que significa para a maquina, e nao e hora de descobrir
        com a musica tocando."""
        with self.lock:
            if not self.tr_out:
                self.log("(!) sem porta CTRL - ligue o modo ON")
                return
            # ver pedir_variacao: a mascara so tem slot para A-H. Sem este
            # guarda, o Fill In nunca esta em vars_habilitadas (montada com
            # range(1,9)), entao o symmetric_difference so ADICIONA - cada
            # clique direito somava 1<<8 de novo, sem caminho de volta
            if v > 8:
                self.log(f"(!) {VARIACOES[v-1]} e Fill In: nao entra no rodizio "
                         "(a mascara 63-66 so reporta A-H)")
                return
            atual = set(self.vars_habilitadas)
            if v in atual and len(atual) == 1:
                self.log(f"(!) {VARIACOES[v-1]} e a unica habilitada - "
                         "ligue outra antes de desligar esta")
                return
            atual.symmetric_difference_update({v})
            m = 0
            for x in atual:
                m |= 1 << (x - 1)
            p = self._pattern_para_escrever("rodizio de variacoes")
            if p is None:
                return
            self.tr_out.send(dt1(addr_soma(addr_no_pattern(p), OFF_VAR_TOCANDO),
                                 mascara_para_nibbles(m)))
            nomes = " ".join(VARIACOES[x-1] for x in sorted(atual))
            self.log(f"rodizio agora: {nomes}"
                     + ("  (varias habilitadas: a conta da variacao vira "
                        "deducao de novo - um stop/play reancora)"
                        if len(atual) > 1 else ""))

    def _atender_var_pedida(self):
        """Na virada do compasso, manda o pedido guardado pelo duplo clique."""
        if self.var_pedida is None:
            return
        ciclo = self.passo_abs // max(1, self.last_var())
        if self._ciclo_pedido is not None and ciclo <= self._ciclo_pedido:
            return                          # ainda nao virou
        v, self.var_pedida, self._ciclo_pedido = self.var_pedida, None, None
        self._escrever_var_mask(v)

    # ── ciclo de variacoes derivado do clock ────────────────
    # A variacao que TOCA nao existe em nenhum no SysEx conhecido (o watch de
    # 193 bytes nao viu nada mudar com A->B->C ciclando; o perf 0x40 e so
    # paridade). Mas da para CONTAR: a maquina cicla as habilitadas em ordem
    # ascendente e cada uma dura o proprio last step - com o clock pulso a
    # pulso, a conta e exata. Limite conhecido: se a variacao principal nao
    # for a mais baixa das habilitadas (ex. segurar C e somar A), o comeco
    # desalinha - caso raro, documentado.

    def _ancorar_ciclo_vars(self, v=None, dentro=0, presumida=False):
        """Ancora o ciclo. Sem v, assume a mais baixa das habilitadas - o que
        so e legitimo no start, onde a maquina realmente comeca por ela."""
        vs = self.vars_habilitadas
        self.var_presumida = presumida
        if len(vs) > 1:
            self.ciclo.ancorar(self.passo_abs, vs, self.ultimo_var,
                               v or vs[0], dentro)
            self.variacao_tocando = self.ciclo.variacao_em(self.passo_abs)
        else:
            self.ciclo.soltar()
            self.var_presumida = False      # com uma so nao ha o que presumir
            if vs:
                self.variacao_tocando = vs[0]

    def _reancorar_apos_troca(self):
        """Trocou de pattern: PRESUME que o rodizio recomecou pela variacao
        mais baixa habilitada - o mesmo que a maquina faz no start.

        NAO PROVADO em hardware (16/08/2026). Por isso a ancora sai marcada
        como presumida e a tela desenha o ponto verde VAZADO em vez de solido:
        o palpite aparece - senao a troca de pattern jogaria tudo em '?' e o
        grid pararia de seguir - mas nao se disfarca de leitura.

        Se o palpite estiver errado, o erro e CONSTANTE (sempre a mesma
        defasagem), o que e facil de ver e facil de corrigir com um
        Shift-clique ou um stop/play."""
        vs = self.vars_habilitadas
        if len(vs) <= 1 or not self.tocando:
            return
        dentro = 0
        if (self.passo_maquina is not None
                and time.time() - self.passo_maquina_t <= VALIDADE_PASSO):
            dentro = self.passo_maquina
        self._ancorar_ciclo_vars(vs[0], dentro, presumida=True)
        self.log(f"pattern novo: SUPUS que o rodizio recomeca pela "
                 f"{VARIACOES[vs[0]-1]} - confira o LED verde no painel "
                 "(stop/play ou Shift-clique corrigem)")

    def _avancar_ciclo_vars(self):
        vs = self.vars_habilitadas
        if len(vs) <= 1:
            self.variacao_tocando = vs[0] if vs else self.variacao_tocando
            return
        v = self.ciclo.variacao_em(self.passo_abs)
        if v is not None:               # None = sem ancora (continue/attach)
            self.variacao_tocando = v

    def _bpm_medido(self):
        """BPM derivado do intervalo entre clocks (24 por seminima), ou None.

        Mostrar e barato; ESCREVER BPM nao tem endereco conhecido - o tempo
        continua sendo o knob TEMPO da maquina (REFERENCIA 7)."""
        ts = self._clock_ts
        if len(ts) < 13 or time.time() - ts[-1] > 1.0:
            return None
        dt = ts[-1] - ts[0]
        if dt <= 0:
            return None
        return round((len(ts) - 1) / dt * 60.0 / 24.0, 1)

    def _escape(self, cc):
        """Fora do ON (off e standby), HIDE MUTED + ALT juntos (os dois vizinhos
        do meio da borda esquerda, CC 94 e 93) voltam pro ON - senao nao haveria
        como voltar sem ir ate o Mac. Sao dois porque um so dispararia sem querer
        justamente nos modos em que se fica cutucando os pads."""
        agora = self.logo_t[cc] = time.time()
        outro = ESCAPE_CHORD[1] if cc == ESCAPE_CHORD[0] else ESCAPE_CHORD[0]
        if agora - self.logo_t.get(outro, 0.0) < 0.5:
            self.logo_t = {}
            self.definir_modo(MODO_ON)

    def _ler_pads(self):
        for dev, off in (("E", 0), ("D", 8)):
            for msg in self.lp_in[dev].iter_pending():

                if msg.type == 'control_change':
                    if msg.value == 0: continue
                    if self.modo_geral != MODO_ON:
                        if dev == "E" and msg.control in ESCAPE_CHORD:
                            self._escape(msg.control)
                        continue
                    acao = BOTOES.get((dev, msg.control))
                    if acao: self.executar(*acao)
                    continue

                if msg.type != 'note_on' or msg.velocity == 0: continue
                pos = self._decodificar(dev, msg.note)
                if pos is None: continue
                linha, col = pos
                if self.modo_geral == MODO_ON:
                    self.alternar(linha, off + col)
                    self.pintar()
                else:
                    # no standby o toque entra no estilo da vez, senao um dedo
                    # jogaria chuva no meio do ambiente
                    self._nova_onda(linha, off + col,
                                    self.estilo_standby
                                    if self.modo_geral == MODO_STANDBY else None)

    def tick(self):
        with self.lock:
            if not self.lp_in:
                return
            self._drenar_fila()
            self._ler_clock()
            self._ler_pads()
            if self.modo_geral != MODO_ON:
                if self.modo_geral == MODO_STANDBY:
                    self._semear()
                self._animar()
            elif (self.carregado and
                  time.time() - self.ultima_leitura > INTERVALO_RELEITURA):
                antes_toc = self.variacao_tocando
                if self.ler_last_steps(quieto=True):
                    self.pintar()
                    if self.variacao_tocando != antes_toc:
                        nome = (VARIACOES[self.variacao_tocando-1]
                                if self.variacao_tocando else "?")
                        self.log(f"a TR-8S passou a tocar a variacao {nome}")
                    else:
                        self.log(f"last steps mudaram no painel  |  "
                                 f"variacao {self.last_var()}")
                # O GRID NAO SEGUE MAIS A VARIACAO QUE TOCA (17/08/2026).
                #
                # Ele seguiu de 16/08 ate aqui, e por um bom motivo: o visor
                # mostrava "2-04B" com o grid na A, editar nao soava e a
                # estocastica caia no vazio. Mas seguir custa uma releitura de
                # 11 blocos (~500 ms), e com varias variacoes habilitadas a
                # maquina troca a cada volta - a 40 bpm em 32nd, a cada 3 s.
                # O resultado era a vista pulando debaixo da mao de quem edita.
                #
                # Decisao do Luan: "o grid tem funcao principal inspecionar e
                # editar o que esta tocando e o que vai ser tocado" - a vista
                # fica onde ele deixou, e quem diz o que soa e o ponto verde na
                # coluna das variacoes (mais o display "toca" x "edita" e a
                # ausencia de playhead numa variacao que nao esta soando).
                # Tres sinais honestos valem mais que uma vista que se mexe.
                # mesma releitura periodica dos last steps, mesmo motivo: sem ela
                # o [MUTE] do painel nunca chegaria ao grid. Custa um RQ1, ~20 ms.
                if self.ler_mudos(quieto=True):
                    self.aplicar_mudos()
                    mutados = [INSTRUMENTOS[i] for i in range(len(INSTRUMENTOS))
                               if self.mudo[i]]
                    self.log("mute no painel: "
                             + (" ".join(mutados) if mutados else "ninguem")
                             + f"  |  linhas: {self.visiveis()}")
                # AQUI, colado no ler_mudos, porque e ele quem grava o
                # passo_maquina. La embaixo (onde isto ficava) ja passaram o
                # ler_kit, a fila de FX e o rodizio - o alvo chegava velho e o
                # proprio guarda de validade o descartaria
                self._ressincronizar()
                # a releitura do kit anda DEPOIS da dos mutes, que e quem
                # levanta a bandeira. Ela e CARA - nome + 11 tones + 26 blocos
                # de efeito - e num tick so ela atropelava a releitura do
                # pattern: a linha do BD caia no timeout e aparecia como
                # "BD nao lido", com a escrita bloqueada. Por isso os blocos
                # de FX entram numa fila e saem POUCOS POR CICLO.
                if self.kit_trocou:
                    self.kit_trocou = False
                    # kit novo, referencia nova: o botao de reset passa a
                    # apontar para o volume DESTE kit
                    self.kit_level_ref = None
                    self.ler_kit()
                    self.fx_fila = self._fx_alvos()
                    self.fx_rearmado = time.time()
                elif (not self.fx_fila and
                      time.time() - self.fx_rearmado > INTERVALO_FX):
                    # RODIZIO DOS BLOCOS DE FX (17/08/2026). A fila so era
                    # armada na TROCA DE KIT: mexer no GAIN, no LEVEL, no PAN
                    # ou nos sends pelo painel da maquina nunca chegava a tela
                    # - a escrita ia, a leitura nao voltava, e a mesa mentia um
                    # estado congelado no momento do ON. Mesmo espirito do
                    # _reler_pattern_rodizio logo abaixo: poucos blocos por
                    # ciclo, para nunca disputar um tick com a releitura do
                    # pattern (foi ela que virou "BD nao lido" quando o ler_kit
                    # rodava inteiro num tick so).
                    self.fx_rearmado = time.time()
                    self.fx_fila = self._fx_alvos()
                self._drenar_fx_fila()
                # pattern trocou: o grid inteiro e outro. ADIADO enquanto o
                # chain estiver perseguindo o playhead (a releitura de ~2 s
                # atropelaria a fila de escrita dele)
                if self.pattern_trocou and not (
                        self.chain and getattr(self.chain, "_fila_escrita",
                                               None)):
                    self.pattern_trocou = False
                    self.recarregar()
                    self._reancorar_apos_troca()
                    self.pintar()
                # e as notas: sem isto, ligar um step no painel da TR-8S
                # nunca chegaria ao grid nem aos Launchpad
                if self._reler_pattern_rodizio():
                    self.pintar()
            if self.modo_geral == MODO_ON and self.chain:
                try:
                    self.chain.tick(self)
                except Exception as exc:
                    self.log(f"(!) chain quebrou e foi desarmado: {exc}")
                    self.chain = None
            if self.modo_geral == MODO_ON and self.captura_fx:
                self._tick_captura_fx()

    def _ressincronizar(self):
        """Puxa o playhead de volta pro step que a MAQUINA diz estar tocando.

        Contar clock e exato enquanto nenhum pulso se perde, mas qualquer pulso
        engolido vira erro permanente - nada no caminho o corrige. Como o step
        vem de graca junto com o mute, da pra conferir a cada releitura.

        So corrige com folga de mais de um step: a propria leitura leva algumas
        dezenas de ms, e a 120 bpm um step e 125 ms, entao uma divergencia de um
        step e latencia de medicao, nao erro - corrigi-la faria o playhead
        tremer pra frente e pra tras sem parar.

        CORRIGIDO EM 16/08/2026 - ele era a causa do 'grid nao espelha o que
        toca'. Duas coisas estavam erradas:

        1. Reatribuia passo_abs (contador ABSOLUTO, cresce sem fim) com o step
           da maquina (MODULAR, 0..15). Como o ciclo de variacoes e o free-run
           do track curto contam no absoluto, a variacao CONGELAVA. Agora a
           correcao e por DELTA: a fase anda, a contagem continua.
        2. Usava um passo_maquina que podia ter dezenas de steps de idade -
           ele e gravado no ler_mudos() e so consumido bem depois, com
           leituras caras no meio. Corrigir por um alvo velho gera flap
           sozinho. Agora ha prazo de validade."""
        # a janela expira sozinha; se ela esvaziou, o espelho voltou a bater e
        # a escrita e liberada. Fica aqui, antes dos returns, pra rodar sempre
        agora = time.time()
        self._saltos = [t for t in self._saltos if agora - t <= JANELA_ESPELHO]
        if self.espelho_suspeito and not self._saltos:
            self.espelho_suspeito = False
            self.log("o grid voltou a bater com a maquina - escrita liberada")
        if not (self.tocando and TOLERANCIA_SYNC is not None):
            return
        # So faz sentido quando o grid esta NA variacao que toca. Divergindo, o
        # alvo vem do comprimento da variacao da maquina e o lim daqui vem do
        # comprimento da variacao aberta no grid: comparar os dois e comparar
        # modulos diferentes, e a "correcao" empurra passo_abs para um valor sem
        # significado. Nao aparecia na tela porque o playhead esta escondido
        # justamente nesse caso - o que tornava o erro silencioso, nao inofensivo.
        # Quem realinha ao voltar e o executar("variacao"), que chama isto de novo
        # ja com as duas coincidindo.
        #
        # Repare que a condicao aqui e a ESTRITA, nao playhead_visivel(): num
        # fill o playhead e desenhado, mas o passo da maquina se refere a
        # variacao base, com outro comprimento. Corrigir por ele traria de volta
        # exatamente a comparacao de modulos diferentes que este guarda existe
        # para impedir.
        if not self.em_fase_com_a_maquina():
            return
        alvo = self.passo_maquina
        if alvo is None:
            return
        # o alvo veio de um round-trip de SysEx e envelhece rapido: a 86 bpm um
        # step dura 0,17 s. Entre gravar (ler_mudos) e usar (aqui) passam
        # ler_kit, a fila de FX e o rodizio - facil dar mais de um step
        if time.time() - self.passo_maquina_t > VALIDADE_PASSO:
            return
        agora_res = time.time()
        lim = max(1, self.last_var())
        atual = self.passo_abs % lim
        erro = (alvo - atual) % lim
        if min(erro, lim - erro) <= TOLERANCIA_SYNC:
            self._erros_seguidos = []
            return
        # delta com sinal (-lim/2 .. +lim/2): o caminho mais curto ate o alvo
        delta = erro if erro <= lim - erro else erro - lim
        # SO CORRIGE ERRO CONSISTENTE (16/08/2026). O alvo vem de um round-trip
        # de SysEx e a maquina responde com atraso variavel; medindo 103
        # amostras, o erro aparente se espalhou UNIFORMEMENTE de -5 a +6 steps,
        # com media +0,12 - ou seja, ruido de medicao, nao deriva. Corrigir por
        # ruido fazia o playhead saltar do step 1 pro 8 e voltar pro 2.
        #
        # Deriva de verdade (pulso perdido) da erro do MESMO sinal, leitura
        # apos leitura. Desde que a porta de clock virou callback nada se
        # perde, entao este caminho quase nunca dispara - e e assim que tem
        # que ser: a contagem de clock e exata, quem chega velho e o alvo.
        # com carimbo: sem ele, amostras separadas por minutos (e ate de outro
        # pattern) se somavam num trio "consistente" e disparavam correcao
        self._erros_seguidos = [(t, d) for t, d in self._erros_seguidos
                                if agora_res - t <= JANELA_ESPELHO]
        self._erros_seguidos.append((agora_res, delta))
        del self._erros_seguidos[:-ERROS_P_CORRIGIR]
        if len(self._erros_seguidos) < ERROS_P_CORRIGIR:
            return
        ds = [d for _, d in self._erros_seguidos]
        if not (all(d > 0 for d in ds) or all(d < 0 for d in ds)):
            return                      # sinais misturados = ruido, nao deriva
        delta = min(ds, key=abs)                     # o mais conservador
        self._erros_seguidos = []
        pps = self.pulsos_p_step()
        self.pulsos += delta * pps
        self.passo_abs = self.pulsos // pps
        # a fronteira entre as variacoes anda JUNTO com a fase, senao consertar
        # o playhead empurraria a contagem para dentro da variacao vizinha
        self.ciclo.deslocar(delta)
        if abs(delta) > SALTO_SOLTA_ANCORA:
            # desvio grande = pulsos perdidos de verdade. A fase da pra
            # consertar; QUAL variacao, nao - e "?" e melhor que errado
            self.ciclo.soltar()
            self.variacao_tocando = None
            self.var_presumida = False
            agora = time.time()
            # uma rajada de correcoes vale UMA: ver INTERVALO_MIN_SALTO. O
            # mesmo intervalo silencia o log - senao uma rajada enche a tela
            # de linhas iguais e esconde o diagnostico que vem depois dela
            if not self._saltos or agora - self._saltos[-1] >= INTERVALO_MIN_SALTO:
                self._saltos.append(agora)
                self.log(f"(!) playhead estava {delta:+d} steps fora - corrigi, "
                         "mas perdi a conta da variacao.")
            self._conferir_espelho()
        self.mover_playhead(self.passo_abs % lim)

    def escrita_bloqueada(self, rot=""):
        """True quando o espelho nao corresponde ao que a maquina toca.

        TODO caminho que manda DT1 de pattern tem que passar por aqui, nao so o
        escrever_step: colar, limpar, escrever_pattern, o accent e o Chain
        mandam direto, e enquanto o guarda vivia dentro do escrever_step a tela
        dizia 'ESCRITA BLOQUEADA' enquanto um PASTE sobrescrevia o pattern real
        com o cache do pattern errado - exatamente o dano que ele existe para
        impedir.

        O log sai no maximo uma vez por janela: estes chamadores rodam em laco
        (11x16 no colar, 11 por step no Chain) e a mesma linha repetida empurra
        para fora da tela justamente a mensagem que explica a causa."""
        if not self.espelho_suspeito:
            return False
        agora = time.time()
        if agora - self._t_log_bloqueio > INTERVALO_MIN_SALTO:
            self._t_log_bloqueio = agora
            self.log(f"(!) escrita bloqueada{' (' + rot + ')' if rot else ''}: "
                     "o grid nao corresponde ao pattern que a maquina toca")
        return True

    def _conferir_espelho(self):
        """Desvio grande e REPETIDO significa que o comprimento da variacao que
        usamos nao e o da maquina - e o comprimento vem do no 20 xx.

        Descoberto em 16/08/2026: esse no pode nao corresponder ao pattern que
        a maquina toca (ver REFERENCIA). Quando isso acontece o grid mostra
        OUTRO pattern, e escrever a partir dele manda velocity, sub step e
        probability do pattern errado por cima do certo - destroi o trabalho
        do usuario em silencio. Entao aqui a escrita e bloqueada.

        Conta por JANELA DE TEMPO, nao por saltos consecutivos: a divergencia
        cresce, e corrigida, cresce de novo, e no meio caem correcoes pequenas
        que zeravam um contador de consecutivos. Medido no aparelho: com o
        espelho errado saem ~5 saltos por minuto; com ele certo, nenhum."""
        agora = time.time()
        self._saltos = [t for t in self._saltos if agora - t <= JANELA_ESPELHO]
        if self.espelho_suspeito or len(self._saltos) < SALTOS_P_SUSPEITA:
            return
        self.espelho_suspeito = True
        self.log("(!) o playhead nao para de divergir "
                 f"({len(self._saltos)} correcoes grandes em "
                 f"{JANELA_ESPELHO:.0f}s), sinal de que o last step daqui nao e "
                 "o da maquina. ESCRITA BLOQUEADA por precaucao. Causa mais "
                 "provavel: outro programa na porta CTRL (TR-EDITOR aberto?) - "
                 "as respostas se misturam e a leitura sai errada.")

    # ── espelho pra UI ──────────────────────────────────────
    def estado(self, bloquear=False):
        """Espelho pra UI. Com bloquear=False devolve None em vez de esperar -
        a janela prefere pular um quadro a congelar durante os 2 s que o
        recarregar() gasta lendo a maquina."""
        if not self.lock.acquire(blocking=bloquear):
            return None
        try:
            return {
                "modo_geral": self.modo_geral,
                "variacao": self.variacao,
                "variacao_nome": VARIACOES[self.variacao-1],
                "velocidade": VELOCIDADES[self.vel_idx],
                "modo": MODOS[self.modo][0],
                "base_inst": self.base_inst,
                "passo_inst": self.passo_inst,
                "passo_inst_max": PASSO_INST_MAX,
                "visiveis": self.visiveis(),
                # a JANELA dos Launchpads como lista de indices (a moldura da
                # tela usa; "visiveis" e string para logs e nao serve de dado)
                "janela": list(self.lista_visivel()[
                    self.base_inst:self.base_inst + self.linhas_de_inst()]),
                "mostrar_acc": self.mostrar_acc,
                "passo": self.passo, "tocando": self.tocando,
                "carregado": self.carregado,
                "acc": self.acc,
                "mudo": list(self.mudo),
                # os bits 11-15 da mascara de mute, CRUS. A 2.7 decodificou os
                # 11 dos instrumentos e nunca olhou o resto; expor aqui e a
                # unica forma de responder "a maquina usa esses bits?" sem
                # fechar o app para rodar um snap. Ver alternar_mudo, que os
                # devolve como estavam em vez de mandar zero.
                "mudo_bits_altos": self.mudo_bits_altos,
                # a maquina esta tocando um FILL IN (perf 0x09): o que soa nao
                # e a variacao aberta no grid
                "fill_ativo": self.fill_ativo,
                # intervalo do AUTO FILL IN lido do no do pattern (e por
                # pattern, nao global). O que o numero conta segue desconhecido
                "auto_fill": self.auto_fill,
                # volume do kit como foi lido - o alvo do botao de reset
                "kit_level_ref": self.kit_level_ref,
                "last_var": self.last_var(),
                "last_track": list(self.ultimo_track),
                "armado": self.armado,
                "esconder_mudos": self.esconder_mudos,
                "variacao_tocando": self.variacao_tocando,
                "variacao_tocando_nome": (
                    VARIACOES[self.variacao_tocando - 1]
                    if self.variacao_tocando else None),
                "vars_habilitadas": self.vars_habilitadas,
                # pedida pelo duplo clique e ainda esperando a virada
                "var_pedida": self.var_pedida,
                # True = ha varias habilitadas e a conta esta SOLTA, entao nao
                # sabemos qual toca e da pra fazer algo a respeito (Shift-clique
                # na do visor). Com uma habilitada so nao ha incerteza nenhuma,
                # mesmo o ciclo estando solto - por isso nao e so 'not ancorado'
                "var_incerta": (len(self.vars_habilitadas) > 1
                                and not self.ciclo.ancorado()),
                # a ancora veio de palpite (troca de pattern), nao de leitura
                # nem de start: a tela desenha o ponto verde vazado
                "var_presumida": self.var_presumida,
                # o no 20 xx nao corresponde ao pattern que a maquina toca:
                # o grid mostra outro pattern e a escrita esta bloqueada
                "espelho_suspeito": self.espelho_suspeito,
                # o step que a MAQUINA diz estar tocando (perf 01 00 00 07).
                # Foi comparando a volta dele com a nossa contagem de clock
                # que a scale apareceu, em 17/08/2026 - hoje ela e lida do no
                # do pattern (OFF_SCALE) e o playhead ja anda na velocidade
                # certa; isto continua exposto como conferencia
                "passo_maquina": self.passo_maquina,
                "scale": self.nome_scale() if self.scale is not None else None,
                "playhead_visivel": self.playhead_visivel(),
                "lista_visivel": self.lista_visivel(),
                "tem_clock": self.clk is not None,
                "tem_tr8s": self.tr_out is not None,
                "estilo_standby": self.estilo_standby,
                "pattern": {i: [self.ler_vel(i, s) for s in range(16)]
                            for i in self.cache} if self.carregado else {},
                "subs": {i: [self.ler_sub(i, s) for s in range(16)]
                         for i in self.cache} if self.carregado else {},
                "alts": {i: [self.ler_alt(i, s) for s in range(16)]
                         for i in self.cache} if self.carregado else {},
                "probs": {i: [self.ler_prob(i, s) for s in range(16)]
                          for i in self.cache} if self.carregado else {},
                "cache_invalido": set(self.cache_invalido),
                "chain": self.chain.resumo() if self.chain else None,
                "kit_atual": self.kit_atual,
                "pattern_atual": self.pattern_atual,
                "pattern_nome": self.pattern_nome,
                "kit_nome": self.kit_nome,
                "tone_ids": list(self.tone_ids),
                # indices (nao so os nomes): a tela precisa marcar qual chip
                # esta ativo, e o ALT era invisivel para ela
                "alt": self.alt,
                "vel_idx": self.vel_idx,
                "modo_idx": self.modo,
                "copia_cheia": self.copia is not None,
                "desfazer_disponivel": bool(self.pilha_desfazer),
                "desfazer_pilha": [s[0] for s in self.pilha_desfazer],
                "bpm": self._bpm_medido(),
                "polirritmia": self.polirritmia(),
                "fx": self._fx_valores(),
                "mapa_fx": {n: dict(e) for n, e in self.mapa_fx.items()},
                "captura_fx": (self.captura_fx["nome"]
                               if self.captura_fx else None),
                "probs_inst": ([self._prob_inst(i)
                                for i in range(len(INSTRUMENTOS))]
                               if self.carregado else
                               [None] * len(INSTRUMENTOS)),
            }
        finally:
            self.lock.release()


def cmd_run():
    cfg = carregar_layout()
    _programmer_mode(True)
    m = Motor(cfg)
    if not m.definir_modo(MODO_ON):
        m.fechar(); return
    print(f"""
Pronto.  Linhas: {m.visiveis()}{'  + ACC' if m.mostrar_acc else ''}
  pad          liga com a velocity atual; mesma velocity+modo desliga;
               diferente repinta sem precisar apagar antes

  TOPO ESQUERDO    variacoes A-H
  BORDA ESQUERDA   FILL 1 / FILL 2 / CLEAR inst / CLEAR variacao (2x) /
                   ESCONDER MUTADOS / WRITE (reservado) / copiar / colar
  TOPO DIREITO     INST UP / INST DN / NORMAL FLAM 1-2 1-3 1-4 / ACCENT
  BORDA DIREITA    velocity {' '.join(str(v) for v in VELOCIDADES)}

  As setas de rolagem ficaram so no aparelho DIREITO: as do esquerdo faziam a
  mesma coisa, e viraram ESCONDER e WRITE quando se descobriu que os logos nao
  sao botoes, so LED.

  MUTE  o grid LE o mute da TR-8S (a cada {INTERVALO_RELEITURA} s) e nunca escreve:
        mutar continua sendo [MUTE] + instrumento no painel. A linha mutada fica
        roxa (notas) e azul (flam/sub), sem cabeca de tempo e sem playhead. O
        botao ESCONDER tira essas linhas do grid e devolve.  mutados agora: {
        ' '.join(INSTRUMENTOS[i] for i in range(len(INSTRUMENTOS)) if m.mudo[i])
        or 'ninguem'}

  velocity atual: {VELOCIDADES[m.vel_idx]}      modo: {MODOS[m.modo][0]}
  last step da variacao: {m.last_var()}   (ajuste na janela do app)
  Ctrl+C  = sair
{('  playhead ligado (clock de ' + m.clk_nome + ')') if m.clk else '  (sem clock - playhead desligado)'}
""")
    try:
        while True:
            m.tick()
            time.sleep(0.003)
    except KeyboardInterrupt:
        print("\nsaindo...")
    finally:
        m.fechar()



def cmd_standby(argv):
    """So as luzes. Nao abre a TR-8S: da pra rodar com a maquina desligada."""
    estilo = ESTILO_AMBIENTE if "ambiente" in argv else ESTILO_CHUVA
    cfg = carregar_layout()
    _programmer_mode(True)
    m = Motor(cfg)
    m.definir_modo(MODO_STANDBY, estilo)
    print(f"""
standby ({estilo}) - as ondas nascem sozinhas, a TR-8S nem precisa estar ligada.

  pad                      joga uma onda ali, no estilo da vez
  HIDE MUTED + ALT juntos  (borda esquerda, CC 94 e 93) volta pro ON -
                           precisa da porta CTRL
  Ctrl+C                   sai

  estilos: 'standby' = chuva (variada e rapida)   'standby ambiente' = lento
""")
    try:
        while True:
            m.tick()
            time.sleep(0.003)
    except KeyboardInterrupt:
        print("\nsaindo...")
    finally:
        m.fechar()


# ─────────────────────────────────────────────────────────────
# Sessoes de hardware guiadas (rodar com o .app FECHADO - porta CTRL unica)
# ─────────────────────────────────────────────────────────────
def cmd_prob_watch():
    """Sessao A: calibrar a tabela de PROBABILITY (REFERENCIA 2.4).

    Le em loop os 8 bytes do step 1 do BD e imprime quando mudam. Leitura em
    endereco PROVADO - zero risco de envenenar a CTRL (3.1).

    Roteiro pro Luan:
      1. maquina ligada e parada, variacao A aberta;
      2. ligar o step 1 do BD no painel (o watch mostra a velocity);
      3. long-press no pad do step + VALUE, percorrer CADA valor de probability
         que o painel oferece, um por vez, esperando o watch imprimir;
      4. ditar o valor do painel a cada linha nova; ao final, voltar pra 100%.
    """
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    with EntradaMIDI(*tin) as tin, SaidaMIDI(*tout) as tout:
        p = pattern_corrente(tin, tout)
        if p is None:
            print("(!) nao consegui ler o pattern corrente."); return
        print(f"Observando o step 1 do BD (pattern {nome_pattern(p)}, "
              "variacao A). Ctrl+C sai.\n"
              "byte3 e a PROBABILITY; anote o valor do painel a cada mudanca.\n")
        antes = None
        try:
            while True:
                d = ler_bloco(tin, tout, addr_bloco_rd(0, 0x01, p), 8)
                if d and d[:BYTES_P_STEP] != antes:
                    antes = d[:BYTES_P_STEP]
                    vel = (d[VEL_HI] << 4) | d[VEL_LO]
                    print(f"bytes={' '.join(f'{b:02X}' for b in antes)}   "
                          f"byte3=0x{d[PROB_BYTE]:02X} "
                          f"(formula linear diria {byte_para_prob(d[PROB_BYTE])}%)"
                          f"   vel={vel}")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nfim.")


def cmd_tempo_watch():
    """Sessao T: achar o byte do TEMPO (destrava o Auto BPM de verdade).

    Le em loop os nos de performance (01 00 00 00) e de pattern
    (20 00 00 00) - ambos leitura provada - e imprime o que mudar.

    Roteiro pro Luan (app FECHADO/off - porta CTRL unica):
      1. rodar isto;
      2. girar o knob TEMPO da TR-8S devagar, de ponta a ponta;
      3. ditar dois valores do visor (ex. "agora 90.0", "agora 240.0")
         para casar byte com escala.
    """
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    # o no de pattern tem 193 bytes (o TR-EDITOR le 16+193); ler so 128
    # escondia a regiao 128-192 - e foi ali que a variacao tocando NAO
    # apareceu na primeira cacada, entao agora o watch olha o no inteiro
    with EntradaMIDI(*tin) as tin, SaidaMIDI(*tout) as tout:
        p = pattern_corrente(tin, tout)
        if p is None:
            print("(!) nao consegui ler o pattern corrente."); return
        # o no do pattern CORRENTE - ADDR_PATTERN_ZERO e o do pattern 0, e o
        # watch estaria olhando um pattern que nao e o que esta tocando
        alvos = [("perf", ADDR_PERF, 128), ("pattern", addr_no_pattern(p), 193)]
        print(f"Observando perf e o no do pattern {nome_pattern(p)}. "
              "Gire o TEMPO devagar.\nCtrl+C sai.\n")
        antes = {}
        try:
            while True:
                for rot, addr, tam in alvos:
                    d = ler_bloco(tin, tout, addr, tam, timeout=SNAP_TIMEOUT)
                    if not d:
                        continue
                    a = antes.get(rot)
                    if a and len(a) == len(d):
                        difs = [(i, x, y) for i, (x, y)
                                in enumerate(zip(a, d)) if x != y]
                        # ignora o passo (perf 7) e a paridade (perf 0x40)
                        difs = [x for x in difs
                                if not (rot == "perf" and x[0] in (7, 0x40))]
                        if difs and len(difs) <= 6:
                            print(f"{rot}: " + "  ".join(
                                f"off {i} (0x{i:02X}): {x:02X}->{y:02X}"
                                for i, x, y in difs))
                    antes[rot] = list(d)
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nfim.")


def cmd_kit_watch(argv):
    """Sessao K: decodificar o bloco de params do instrumento (10 00 2I 00).

    uso: kit_watch <BD|SD|...|RC>

    E onde devem morar CTRL SELECT, INST FX e os knobs do kit - o TR-EDITOR
    edita tudo isso e o endereco responde 128 bytes (lido pelo snap), mas
    nenhum offset tem nome ainda. Leitura em endereco provado: zero risco.

    Roteiro pro Luan (um gesto por vez, esperando o print entre um e outro):
      1. maquina ligada, o instrumento escolhido selecionado no painel;
      2. girar o knob CTRL um clique -> anotar o offset que mudou;
      3. trocar o CTRL SELECT (SHIFT+INST, ou pelo TR-EDITOR) -> anotar;
      4. trocar o INST FX -> anotar; mexer no knob do FX -> anotar;
      5. ditar o que fez a cada linha nova do watch.
    """
    if not argv or argv[0].upper() not in INSTRUMENTOS:
        print("uso: kit_watch <BD|SD|LT|MT|HT|RS|HC|CH|OH|CC|RC>"); return
    i = INSTRUMENTOS.index(argv[0].upper())
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    print(f"Observando os 128 bytes de params do {INSTRUMENTOS[i]} "
          f"(10 00 {0x20+i:02X} 00). Ctrl+C sai.\n"
          "Mexa em UMA coisa por vez no painel/TR-EDITOR e anote o offset.\n")
    with EntradaMIDI(*tin) as tin, SaidaMIDI(*tout) as tout:
        antes = None
        try:
            while True:
                d = ler_bloco(tin, tout, addr_kit_param(i), 128,
                              timeout=SNAP_TIMEOUT)
                if d and antes and d != antes:
                    for off, (a, b) in enumerate(zip(antes, d)):
                        if a != b:
                            print(f"offset {off:3} (0x{off:02X}): "
                                  f"{a:02X} -> {b:02X}")
                    print()
                if d:
                    antes = d
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nfim.")


def _num_pattern(arg):
    """'A12' -> 11, '27' -> 27. 0-based no fio (banco A-H x 16)."""
    a = arg.strip().upper()
    if a and a[0] in "ABCDEFGH":
        return (ord(a[0]) - ord("A")) * 16 + int(a[1:]) - 1
    return int(a)


def cmd_pattern(argv):
    """Sessao B: troca remota de pattern via DT1 (mapa oficial do ARIA).

    uso: pattern <A1..H16 | 0-127> [now]
      sem 'now' -> escreve o PROXIMO pattern (01 00 00 02)
      com 'now' -> escreve o pattern ATUAL (01 00 00 01): troca imediata?

    PROVADO em 15/08/2026 (A1->A2, A2->A1, A1->A2, A2->B1, maquina tocando):
    o modo 'proximo' troca NA VIRADA do pattern, como no painel - e o
    mecanismo certo para o chain. A variante 'now' CORTA NO MEIO do compasso
    (B1<->B2 tocando, confirmado em duas passadas com BPM baixo) e PRESERVA
    A POSICAO: o pattern novo continua do mesmo step, sem voltar ao 1 -
    troca de conteudo com o relogio intacto, nao um restart."""
    if not argv:
        print("uso: pattern <A1..H16 | 0-127> [now]"); return
    n = _num_pattern(argv[0])
    if not 0 <= n <= 127:
        print("pattern fora de 0-127"); return
    off = OFF_PATTERN_ATUAL if "now" in argv[1:] else OFF_PATTERN_PROX
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    with SaidaMIDI(*tout) as out:
        out.send(dt1(addr_soma(ADDR_PERF, off), [n]))
    banco, dentro = "ABCDEFGH"[n // 16], n % 16 + 1
    print(f"DT1 enviado: {'pattern ATUAL' if off == OFF_PATTERN_ATUAL else 'PROXIMO pattern'}"
          f" = {banco}{dentro} (0x{n:02X}).\n"
          "Observe a maquina: trocou? na hora ou na virada? o visor mudou?")


def cmd_pc(argv):
    """Sessao B, plano B: Program Change na porta comum, canal 10.

    uso: pc <A1..H16 | 0-127>
    A implementation chart diz que PC e transmitido para pattern; se ela
    tambem RECONHECE e o que este teste decide. A chart ja errou 2x."""
    if not argv:
        print("uso: pc <A1..H16 | 0-127>"); return
    n = _num_pattern(argv[0])
    if not 0 <= n <= 127:
        print("pattern fora de 0-127"); return
    p = _porta_comum(entradas=False)
    if not p:
        print("Porta TR-8S comum (nao-CTRL) nao encontrada."); return
    with SaidaMIDI(*p) as out:
        out.send(mido.Message('program_change', channel=CANAL_TR8S, program=n))
    print(f"Program Change {n} enviado na porta comum, canal 10.\n"
          "Observe a maquina: trocou de pattern?")


def cmd_var_mask(argv):
    """Sessao C: a mascara de variacao (offsets 63-66) ACEITA escrita?

    uso: var_mask <A-H>
    Leitura provada (REFERENCIA 2.3.2); escrita nunca tentada. DT1 em endereco
    valido e seguro. Round-trip nao prova obediencia (Metodo, regra 9): o que
    decide e o OUVIDO - a maquina passou a tocar a variacao pedida?"""
    if not argv or argv[0].strip().upper() not in "ABCDEFGH" or len(argv[0].strip()) != 1:
        print("uso: var_mask <A-H>"); return
    v = ord(argv[0].strip().upper()) - ord("A") + 1
    tin, tout = _portas_tr8s()
    if not (tin and tout):
        print("Porta TR-8S CTRL nao encontrada."); return
    with EntradaMIDI(*tin) as tin, SaidaMIDI(*tout) as tout:
        p = pattern_corrente(tin, tout)
        if p is None:
            print("(!) nao consegui ler o pattern corrente."); return
        no = addr_no_pattern(p)
        tout.send(dt1(addr_soma(no, OFF_VAR_TOCANDO),
                      mascara_para_nibbles(1 << (v - 1))))
        time.sleep(0.1)
        d = ler_bloco(tin, tout, no, 128, timeout=SNAP_TIMEOUT)
        if d:
            m = nibbles_para_mascara(d[OFF_VAR_TOCANDO:OFF_VAR_TOCANDO + 4])
            print(f"mascara relida: 0x{m:04X} "
                  f"({'bate' if m == 1 << (v - 1) else 'NAO bate'} com o pedido)")
        else:
            print("(!) releitura falhou")
    print(f"Pedida a variacao {argv[0].strip().upper()}. O que vale e o OUVIDO: "
          "a maquina trocou? na hora ou na virada?")


if __name__ == "__main__":
    cmd, resto = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    simples = {"ports": cmd_ports, "learn": cmd_learn, "probe": cmd_probe,
               "colors": cmd_colors, "dump": cmd_dump, "run": cmd_run,
               "prob_watch": cmd_prob_watch, "tempo_watch": cmd_tempo_watch}
    if cmd in simples:
        simples[cmd]()
    elif cmd == "standby":
        cmd_standby(resto)
    elif cmd == "snap":
        cmd_snap(resto)
    elif cmd == "sniff":
        cmd_sniff(resto)
    elif cmd == "escutar":
        cmd_escutar(resto)
    elif cmd == "varrer":
        cmd_varrer(resto)
    elif cmd == "snapdiff" and len(resto) >= 2:
        cmd_snapdiff(resto[0], resto[1])
    elif cmd == "pattern":
        cmd_pattern(resto)
    elif cmd == "pc":
        cmd_pc(resto)
    elif cmd == "var_mask":
        cmd_var_mask(resto)
    elif cmd == "kit_watch":
        cmd_kit_watch(resto)
    else:
        print(__doc__)
