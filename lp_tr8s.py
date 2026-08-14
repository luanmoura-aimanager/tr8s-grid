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
import sys, time, json, os, math, random, threading
import mido
import rtmidi

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
# Fills sao DEDUZIDOS pela regra linear - nunca foram exercitados ate agora.
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

def addr_bloco(inst, var=None):   return (0x20, var or VARIACAO, inst, 0x08)
def addr_step(inst, s, var=None): return addr_soma(addr_bloco(inst, var),
                                                   s * BYTES_P_STEP)
def addr_accent(var=None):        return (0x20, var or VARIACAO, 0x00, 0x00)
def addr_kit_param(inst):         return (0x10, 0x00, 0x20 + inst, 0x00)

# Nivel de PATTERN, decodificado em 13/08/2026 com snap/snapdiff (REFERENCIA 2.3.1).
# Os dois LAST STEP moram na mesma tabela de 20 bytes e sao 0-based: o valor 0x0F
# e 16 steps. As variacoes A-H tem slot; os dois Fill In nao - onde eles guardam
# o comprimento continua desconhecido.
ADDR_PATTERN   = (0x20, 0x00, 0x00, 0x00)
OFF_VAR_TOCANDO = 63   # 63-66: mascara de 4 nibbles, bit i = variacao i+1
OFF_LAST_VAR   = 67    # +0 = A ... +7 = H
OFF_LAST_TRACK = 75    # +0 = BD ... +10 = RC, +11 = TRG

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

def addr_last_var(var):     return addr_soma(ADDR_PATTERN, OFF_LAST_VAR + var - 1)
def addr_last_track(inst):  return addr_soma(ADDR_PATTERN, OFF_LAST_TRACK + inst)

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

def addr_mute():            return addr_soma(ADDR_PERF, OFF_MUTE)

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
COR_FLAM       = (98, 62, 127)   # lilas
COR_FLAM_FRACA = (34, 20, 46)
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
# Ondinha do modo off
ONDA_VEL     = 9.0    # celulas por segundo
ONDA_LARGURA = 2.2    # espessura do anel, em celulas
ONDA_ALCANCE = 15.0   # celulas ate morrer (a diagonal do 16x8 e ~17)
ONDA_FPS     = 30

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

# De quantos steps de divergencia o playhead e puxado de volta pro step que a
# maquina diz estar tocando (ver Motor._ressincronizar). None desliga a correcao
# e volta a confiar so na contagem de clock.
TOLERANCIA_SYNC = 1

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
ESCAPE_CHORD = (94, 93)   # no modo off, esses dois juntos voltam pro ON


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
    """Entrada aberta por indice. Expoe a mesma interface que a do mido."""
    def __init__(self, idx, nome=None, ignorar_sense=True):
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

    def iter_pending(self):
        while True:
            r = self._rt.get_message()
            if r is None:
                break
            self._parser.feed(r[0])
        return list(self._parser)          # lista, nao generator: drenar e seguro

    def close(self):
        try: self._rt.close_port(); self._rt.delete()
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

    # snapshot: se a enumeracao mudar (replug, reboot), os indices nao valem mais
    cfg["_portas_in"]  = [n for _, n in listar_portas(True)]
    cfg["_portas_out"] = [n for _, n in listar_portas(False)]

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


def carregar_layout():
    if not os.path.exists(LAYOUT_FILE):
        print("Rode 'learn' primeiro."); sys.exit(1)
    with open(LAYOUT_FILE) as f:
        cfg = json.load(f)

    if "porta_in" in cfg.get("esquerdo", {}):
        print("Layout no formato antigo (portas por nome). Rode 'learn' de novo.")
        sys.exit(1)

    # indices so valem enquanto a enumeracao do CoreMIDI for a mesma
    if (cfg.get("_portas_in")  != [n for _, n in listar_portas(True)] or
            cfg.get("_portas_out") != [n for _, n in listar_portas(False)]):
        print("(!) As portas MIDI mudaram desde o 'learn' (replug? outro aparelho "
              "ligado?).\n    Os indices salvos podem apontar pro aparelho errado. "
              "Rode 'learn' de novo.")
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
        cab = ler_bloco(tin, tout, addr_accent(), 8)
        if cab:
            print(f"ACCENT = 0x{nibbles_para_mascara(cab[:4]):04X}\n")
        for i, nome in enumerate(INSTRUMENTOS):
            d = ler_bloco(tin, tout, addr_bloco(i))
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


def _addrs_do_snapshot(var, incluir_kit=True, incluir_motion=False):
    """[(rotulo, endereco, tamanho)] dos enderecos CONHECIDOS. Ver REFERENCIA 2.3.

    Sao ~50, e todos moram no pattern ou no kit. Isso basta para o que ja foi
    decodificado, mas e cego para estado de PERFORMANCE - o mute, por exemplo, que
    o manual em lugar nenhum diz ser salvo no pattern. Para esses casos existe o
    'varrer', cujo resultado entra aqui pelo snap --amplo."""
    alvos = [(f"var {var:02X} cabecalho", (0x20, var, 0x00, 0x00), 8)]

    # 20 0V hh 08: instrumento I comeca no offset I*128+8, entao hh = I.
    # 0x00-0x0A sao os 11 instrumentos, 0x0B e o TRG (11*128+8 = 1416), e
    # 0x0C-0x18 sao blocos que nunca foram lidos.
    for hh in range(0x00, 0x19):
        if hh < len(INSTRUMENTOS):   rotulo = f"var {var:02X} {INSTRUMENTOS[hh]}"
        elif hh == 0x0B:             rotulo = f"var {var:02X} TRG?"
        else:                        rotulo = f"var {var:02X} bloco {hh:02X}?"
        alvos.append((rotulo, (0x20, var, hh, 0x08), 128))

    if incluir_motion:
        alvos.append((f"var {var:02X} motion", (0x20, var, 0x19, 0x08), 1664))

    # 20 00: a variacao 0x00 nao existe (A e 0x01), entao e candidata natural a
    # guardar o que e do PATTERN e nao da variacao - por exemplo o last step do
    # track, que o Reference p. 12 diz ser compartilhado entre A-H.
    alvos.append(("pattern 20 00?", (0x20, 0x00, 0x00, 0x00), 128))

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

    alvos = []
    for v in vars_:
        alvos += _addrs_do_snapshot(v, incluir_kit, incluir_motion)
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
        json.dump({"variacoes": vars_, "blocos": dados}, f)
    resp = len(unicos) - mudos
    print(f"{destino}: {resp} enderecos responderam, {mudos} calaram "
          f"(calar = endereco que nao existe).")


def _traduzir_offset(addr, i, tamanho):
    """Offset cru -> o que ele significa naquele endereco."""
    if tamanho == 128 and addr[0] == 0x20 and addr[3] == 0x08:
        step, campo = divmod(i, BYTES_P_STEP)
        return f"step {step + 1:2}, byte {campo}"
    if tamanho == 8 and addr[0] == 0x20 and addr[2] == 0x00 and addr[3] == 0x00:
        # bytes 0-3 = mascara de ACCENT em nibbles; 4-7 = o resto do cabecalho
        # da variacao, ainda sem nome (candidatos: last step, scale, shuffle)
        return f"nibble {i} do ACCENT" if i < 4 else f"cabecalho byte {i}"
    return ""


def cmd_snapdiff(p1, p2):
    def carregar(p):
        with open(p) as f:
            j = json.load(f)
        return {k: v for k, v in j["blocos"].items()}

    a, b = carregar(p1), carregar(p2)
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
                    t_out.send(rq1(addr_accent(), 8))
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
        return ler_bloco(tr_in, tr_out, ADDR_PATTERN, 8, timeout=1.0) is not None

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
MODO_ON, MODO_OFF = "on", "off"


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
             "esconder_mudos": False}
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


class Motor:
    """O grid. tick() e nao-bloqueante; chame num laco a ~3 ms."""

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
        self.base_inst, self.modo, self.vel_idx = 0, 0, VEL_PADRAO
        self.mostrar_acc = MOSTRAR_ACC
        self.passo, self.tocando, self.pulsos = -1, False, 0
        self.passo_abs = 0        # contagem absoluta, pros tracks curtos
        self.ultima_leitura = 0.0
        self.copia, self.armado, self.armado_t = None, None, 0.0
        self.alt = False               # flag do ALTERNATE, nao um dos 5 modos
        self.mudo = [False]*len(INSTRUMENTOS)   # lido da maquina, nunca inventado
        self.passo_maquina = None               # step que a TR-8S diz estar tocando
        self.variacao_tocando = None            # qual variacao a maquina toca
        self.carregado = False

        e = carregar_estado()
        self.ultimo_var    = {int(k): v for k, v in e["ultimo_var"].items()}
        self.ultimo_track  = list(e["ultimo_track"])
        self.esconder_mudos = bool(e["esconder_mudos"])

        self.modo_geral = MODO_OFF
        self.ondas, self.onda_suja = [], False
        self.ultimo_quadro = 0.0
        self.logo_t = {}

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
            self.clk, self.clk_nome = EntradaMIDI(*p), p[1]

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

    # ── leitura do pattern ──────────────────────────────────
    def recarregar(self):
        for i in range(len(INSTRUMENTOS)):
            self.cache[i] = ler_bloco(self.tr_in, self.tr_out,
                                      addr_bloco(i, self.variacao)) or [0]*128
        cab = ler_bloco(self.tr_in, self.tr_out,
                        addr_accent(self.variacao), 8) or [0]*8
        self.acc = nibbles_para_mascara(cab[:4])
        self.ler_last_steps()
        self.ler_mudos()
        self.carregado = True

    def ler_last_steps(self, quieto=False):
        """Le os last steps REAIS da maquina. Devolve True se algo mudou.

        Chamado tambem periodicamente pelo tick(), senao mexer no [LAST] do painel
        nunca apareceria no grid."""
        self.ultima_leitura = time.time()
        d = ler_bloco(self.tr_in, self.tr_out, ADDR_PATTERN, 128,
                      timeout=SNAP_TIMEOUT)
        if not d or len(d) < OFF_LAST_TRACK + len(INSTRUMENTOS):
            if not quieto:
                self.log("(!) nao consegui ler os last steps; usando o espelho.")
            return False
        antes = (dict(self.ultimo_var), list(self.ultimo_track),
                 self.variacao_tocando)
        for v in range(1, 9):                       # A-H; fills nao tem slot
            self.ultimo_var[v] = d[OFF_LAST_VAR + v - 1] + 1
        for i in range(len(INSTRUMENTOS)):
            self.ultimo_track[i] = d[OFF_LAST_TRACK + i] + 1
        # a variacao que toca vem no mesmo bloco, de graca (ver OFF_VAR_TOCANDO)
        m = nibbles_para_mascara(d[OFF_VAR_TOCANDO:OFF_VAR_TOCANDO + 4])
        self.variacao_tocando = next((v for v in range(1, 9) if m >> (v-1) & 1),
                                     None)
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
            n = max(1, min(16, int(n)))
            self.ultimo_var[self.variacao] = n
            if self.tr_out and self.variacao <= 8:
                self.tr_out.send(dt1(addr_last_var(self.variacao), [n - 1]))
            elif self.variacao > 8:
                self.log("(!) o last step dos Fill In nao foi decodificado - "
                         "este valor fica so aqui, nao vai pra maquina.")
            self._persistir(); self.pintar()
            self.log(f"last step da variacao {VARIACOES[self.variacao-1]}: {n}")

    def definir_last_track(self, i, n):
        with self.lock:
            n = 16 if n is None else max(1, min(16, int(n)))
            self.ultimo_track[i] = n
            if self.tr_out:
                self.tr_out.send(dt1(addr_last_track(i), [n - 1]))
            self._persistir(); self.pintar()
            self.log(f"last step do {INSTRUMENTOS[i]}: {n}")

    def _persistir(self):
        salvar_estado({"ultimo_var": {str(k): v for k, v in self.ultimo_var.items()},
                       "ultimo_track": self.ultimo_track,
                       "esconder_mudos": self.esconder_mudos})

    # ── mute ────────────────────────────────────────────────

    def ler_mudos(self, quieto=False):
        """Le da maquina quem esta mutado. Devolve True se algo mudou.

        Chamado pelo tick() junto com os last steps: sem reler, apertar [MUTE] no
        painel nunca chegaria ao grid. A maquina e a autoridade - o grid nao tem
        espelho local de mute, e nao escreve aqui. Mutar continua sendo gesto de
        painel; o que o grid faz e enxergar."""
        d = ler_bloco(self.tr_in, self.tr_out, ADDR_PERF, 128, timeout=SNAP_TIMEOUT)
        if not d or len(d) < OFF_MUTE + 4:
            if not quieto:
                self.log("(!) nao consegui ler os mutes da maquina.")
            return False
        # o step atual vem no mesmo bloco, de graca - guarda para o tick
        # ressincronizar o playhead sem gastar um RQ1 a mais
        self.passo_maquina = d[OFF_STEP_ATUAL] if len(d) > OFF_STEP_ATUAL else None
        m = nibbles_para_mascara(d[OFF_MUTE:OFF_MUTE + 4])
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
        self.pulsos = c * PULSOS_P_STEP + decorridos + AJUSTE_PLAYHEAD
        self.passo_abs = self.pulsos // PULSOS_P_STEP
        self.mover_playhead(self.passo_abs % max(1, self.last_var()))
        self.log(f"a TR-8S ja estava tocando - playhead entrou no step "
                 f"{self.passo_abs % max(1, self.last_var()) + 1} "
                 f"(compensados {decorridos} pulsos de leitura)")
        return True

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

    def playhead_visivel(self):
        """O verde so aparece quando o grid esta na variacao que a maquina toca.

        Editar uma variacao enquanto outra soa e o recurso mais valioso do
        projeto - e era justamente ali que o playhead mentia, correndo sobre um
        pattern que ninguem estava ouvindo.

        None = nao conseguimos ler a variacao que toca. Nesse caso o playhead
        volta a aparecer sempre, como antes: falha de leitura nao pode virar
        grid apagado."""
        return (self.variacao_tocando is None
                or self.variacao == self.variacao_tocando)

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

    def pintar(self):
        if self.modo_geral == MODO_OFF:
            for dev in ("E", "D"):
                enviar_cores(self.lp_out[dev],
                             [(self.nota_de(dev, l, c), COR_OFF)
                              for l in range(8) for c in range(8)])
            return
        for dev, off in (("E", 0), ("D", 8)):
            enviar_cores(self.lp_out[dev],
                         [(self.nota_de(dev, l, c), self.cor_do_step(l, off + c))
                          for l in range(8) for c in range(8)])

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
        # TOPO ESQUERDO (coluna de cena girada): variacoes A-H
        for i, c in enumerate(CENA_CCS):
            self._luz(e, c, COR_VAR if self.variacao == i + 1 else COR_OFF)
        # BORDA ESQUERDA (fileira de funcao girada), de cima pra baixo
        self._luz(e, 98, COR_FILL if self.variacao == 0x09 else COR_OFF)
        self._luz(e, 97, COR_FILL if self.variacao == 0x0A else COR_OFF)
        self._luz(e, 96, COR_ARMADO if self.armado == "inst" else COR_CLEAR)
        self._luz(e, 95, COR_ARMADO if self.armado == "var" else COR_CLEAR)
        self._luz(e, 94, COR_ATIVO if self.esconder_mudos      # ESCONDER MUTADOS
                  else (COR_MUDA_BOTAO if any(self.mudo) else COR_OFF))
        self._luz(e, 93, COR_ALT if self.alt else COR_OFF)             # ALT
        self._luz(e, 92, COR_COPIA)
        self._luz(e, 91, COR_COPIA if self.copia else COR_OFF)
        # TOPO DIREITO (fileira de funcao), da esquerda pra direita
        self._luz(d, 91, COR_SETA if self.base_inst > 0 else COR_OFF)
        self._luz(d, 92, COR_SETA if self.base_inst < self.base_max() else COR_OFF)
        for k in range(5):
            self._luz(d, 93 + k, COR_ATIVO if self.modo == k else COR_OFF)
        self._luz(d, 98, COR_ACC if self.mostrar_acc else COR_OFF)
        # BORDA DIREITA (coluna de cena): seletor de velocity. O 80 e o 50
        # vestem a mesma cor que a nota deles vai ter no grid, porque sao os
        # dois valores que a propria maquina usa - o resto fica cinza.
        for i, c in enumerate(CENA_CCS):
            v = VELOCIDADES[i]
            if i == self.vel_idx:   cor = COR_ATIVO
            elif v == VEL_FORTE:    cor = COR_FORTE
            elif v == VEL_FRACA:    cor = COR_FRACA
            else:                   cor = COR_VEL_OFF
            self._luz(d, c, cor)
        # LOGOS: nao sao botoes, so LED - servem de indicador passivo.
        # O da esquerda acende quando ha alguem mutado na maquina, o que importa
        # justamente quando esconder_mudos esta ligado e a linha nem aparece.
        self._luz(e, LOGO_CC, COR_MUDA_BOTAO if any(self.mudo) else COR_OFF)
        self._luz(d, LOGO_CC, COR_OFF)

    def mover_playhead(self, novo):
        if novo == self.passo:
            return
        antigo, self.passo = self.passo, novo
        # o passo continua avancando mesmo invisivel: e isso que faz o verde
        # reaparecer no lugar certo quando voce volta pra variacao que toca,
        # em vez de ressuscitar onde parou
        if not self.playhead_visivel():
            return
        if self.polirritmia():
            # cada linha esta numa coluna diferente: repintar duas colunas nao
            # basta. Sai caro? Nao: o quadro inteiro vai em 2 SysEx em lote.
            self.pintar()
        else:
            self.pintar_coluna(antigo)
            self.pintar_coluna(novo)

    # ── escrita na TR-8S ────────────────────────────────────
    def escrever_step(self, i, step, vel, sub, alt=False):
        b = step * BYTES_P_STEP
        self.cache[i][b+VEL_HI]   = (vel >> 4) & 0x0F
        self.cache[i][b+VEL_LO]   = vel & 0x0F
        self.cache[i][b+SUB_BYTE] = sub if vel else 0
        self.cache[i][b+ALT_BYTE] = (ALT_LIGADO if alt else 0) if vel else 0
        self.tr_out.send(dt1(addr_step(i, step, self.variacao),
                             self.cache[i][b:b+BYTES_P_STEP]))

    def limpar_instrumento(self, i):
        if i >= len(INSTRUMENTOS):
            return
        for s in range(16):
            self.escrever_step(i, s, 0, 0)
            time.sleep(0.002)          # rajada: nao afogar a maquina
        self.log(f"CLEAR {INSTRUMENTOS[i]}")

    def limpar_variacao(self):
        for i in range(len(INSTRUMENTOS)):
            for s in range(16):
                self.escrever_step(i, s, 0, 0)
                time.sleep(0.002)
        self.acc = 0
        self.tr_out.send(dt1(addr_accent(self.variacao), mascara_para_nibbles(0)))
        self.log(f"CLEAR variacao {VARIACOES[self.variacao-1]} (11 instrumentos + ACC)")

    def copiar_variacao(self):
        # o cache e autoritativo: toda escrita nossa passa por ele
        self.copia = (VARIACOES[self.variacao-1],
                      {i: list(d) for i, d in self.cache.items()}, self.acc)
        self.log(f"COPY: variacao {self.copia[0]} no buffer")

    def colar_variacao(self):
        if not self.copia:
            self.log("COPY: buffer vazio - copie uma variacao primeiro"); return
        origem, blocos, mascara = self.copia
        for i, dados in blocos.items():
            for s in range(16):
                b = s * BYTES_P_STEP
                self.cache[i][b:b+BYTES_P_STEP] = dados[b:b+BYTES_P_STEP]
                self.tr_out.send(dt1(addr_step(i, s, self.variacao),
                                     dados[b:b+BYTES_P_STEP]))
                time.sleep(0.002)
        self.acc = mascara
        self.tr_out.send(dt1(addr_accent(self.variacao),
                             mascara_para_nibbles(mascara)))
        self.log(f"PASTE: {origem} -> {VARIACOES[self.variacao-1]}")

    def alternar(self, linha, step):
        # a linha mutada continua editavel: ela some do grid so quando voce pede,
        # e enquanto esta a vista escrever nela e legitimo - o pattern existe, o
        # que esta desligado e o som. Por isso nao ha desvio aqui.
        if self.armado == "inst":                 # CLEAR armado: limpa a linha
            self.armado = None
            if self.eh_acc(linha):
                self.acc = 0
                self.tr_out.send(dt1(addr_accent(self.variacao),
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
            self.tr_out.send(dt1(addr_accent(self.variacao),
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

    def visiveis(self):
        vis = self.lista_visivel()[self.base_inst:
                                   self.base_inst + self.linhas_de_inst()]
        return " ".join(
            (INSTRUMENTOS[i].lower() if self.mudo[i] else INSTRUMENTOS[i])
            for i in vis)                 # minusculo = mutado na TR-8S

    def executar(self, tipo, arg):
        if tipo == "variacao":
            self.variacao, self.armado = arg, None
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
            novo = min(self.base_max(), max(0, self.base_inst + arg))
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
    def definir_modo(self, modo):
        """Troca entre ON e off. Devolve False se recusou."""
        with self.lock:
            if modo == self.modo_geral:
                return True
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
                self.adotar_transporte()
            else:
                self.modo_geral = modo
                self.ondas, self.onda_suja = [], False
                self.armado = None
            self.pintar(); self.pintar_botoes()
            self.log({MODO_ON: "ON - o grid esta escrevendo na TR-8S",
                      MODO_OFF: "off - LEDs apagados, os pads so fazem ondinha"
                      }[self.modo_geral])
            return True

    # ── ondinha do modo off ─────────────────────────────────
    @staticmethod
    def _cor_aleatoria():
        h = random.random() * 6.0
        i, f = int(h), h - int(h)
        r, g, b = [(1, f, 0), (1-f, 1, 0), (0, 1, f),
                   (0, 1-f, 1), (f, 0, 1), (1, 0, 1-f)][i % 6]
        return (r * 127, g * 127, b * 127)

    def _animar(self):
        agora = time.time()
        if agora - self.ultimo_quadro < 1.0 / ONDA_FPS:
            return
        self.ultimo_quadro = agora
        self.ondas = [o for o in self.ondas
                      if (agora - o["t0"]) * ONDA_VEL < ONDA_ALCANCE]
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
                        vt = (agora - o["t0"]) * ONDA_VEL
                        d = math.hypot(l - o["lin"], step - o["col"])
                        anel = 1.0 - abs(d - vt) / ONDA_LARGURA
                        if anel <= 0: continue
                        k = anel * (1.0 - vt / ONDA_ALCANCE)
                        r += o["rgb"][0]*k; g += o["rgb"][1]*k; b += o["rgb"][2]*k
                    pares.append((self.nota_de(dev, l, c),
                                  (min(127, r), min(127, g), min(127, b))))
            enviar_cores(self.lp_out[dev], pares)

    # ── laco ────────────────────────────────────────────────
    def _ler_clock(self):
        if not self.clk:
            return
        if self.modo_geral != MODO_ON:
            self.clk.iter_pending()    # drena e descarta: senao, ao voltar pro ON,
            return                     # um monte de clock atrasado chutaria o playhead
        for msg in self.clk.iter_pending():
            t = msg.type
            if t == 'clock':
                if self.tocando:
                    self.pulsos += 1
                    self.passo_abs = self.pulsos // PULSOS_P_STEP
                    # da a volta no last step da variacao, nao em 16 fixo - era
                    # a causa da dessincronizacao documentada na REFERENCIA 5
                    self.mover_playhead(self.passo_abs % max(1, self.last_var()))
            elif t == 'start':
                self.pulsos, self.passo_abs, self.tocando = 0, 0, True
                self.mover_playhead(0)
            elif t == 'continue':
                self.tocando = True
            elif t == 'stop':
                # repinta o quadro inteiro, nao a coluna: com track curto cada
                # linha tem o playhead numa coluna diferente, e limpar so uma
                # deixaria as outras com o verde preso na tela
                self.tocando, self.passo = False, -1
                self.pintar()

    def _escape(self, cc):
        """No modo off, MUTE + WRITE juntos (os dois vizinhos do meio
        da borda esquerda) voltam pro ON - senao nao haveria como voltar sem ir
        ate o Mac. Sao dois porque um so dispararia sem querer no modo off, que
        e justamente o modo em que se fica cutucando os pads."""
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
                if self.modo_geral == MODO_OFF:
                    self.ondas.append({"lin": linha, "col": off + col,
                                       "t0": time.time(),
                                       "rgb": self._cor_aleatoria()})
                elif self.modo_geral == MODO_ON:
                    self.alternar(linha, off + col)
                    self.pintar()

    def tick(self):
        with self.lock:
            if not self.lp_in:
                return
            self._ler_clock()
            self._ler_pads()
            if self.modo_geral == MODO_OFF:
                self._animar()
            elif (self.carregado and
                  time.time() - self.ultima_leitura > INTERVALO_RELEITURA):
                antes_toc = self.variacao_tocando
                if self.ler_last_steps(quieto=True):
                    self.pintar()
                    if self.variacao_tocando != antes_toc:
                        nome = (VARIACOES[self.variacao_tocando-1]
                                if self.variacao_tocando else "?")
                        self.log(f"a TR-8S passou a tocar a variacao {nome}"
                                 + ("" if self.playhead_visivel() else
                                    "  - o grid esta noutra, playhead escondido"))
                    else:
                        self.log(f"last steps mudaram no painel  |  "
                                 f"variacao {self.last_var()}")
                # mesma releitura periodica dos last steps, mesmo motivo: sem ela
                # o [MUTE] do painel nunca chegaria ao grid. Custa um RQ1, ~20 ms.
                if self.ler_mudos(quieto=True):
                    self.aplicar_mudos()
                    mutados = [INSTRUMENTOS[i] for i in range(len(INSTRUMENTOS))
                               if self.mudo[i]]
                    self.log("mute no painel: "
                             + (" ".join(mutados) if mutados else "ninguem")
                             + f"  |  linhas: {self.visiveis()}")
                self._ressincronizar()

    def _ressincronizar(self):
        """Puxa o playhead de volta pro step que a MAQUINA diz estar tocando.

        Contar clock e exato enquanto nenhum pulso se perde, mas qualquer pulso
        engolido vira erro permanente - nada no caminho o corrige. Como o step
        vem de graca junto com o mute, da pra conferir a cada releitura.

        So corrige com folga de mais de um step: a propria leitura leva algumas
        dezenas de ms, e a 120 bpm um step e 125 ms, entao uma divergencia de um
        step e latencia de medicao, nao erro - corrigi-la faria o playhead
        tremer pra frente e pra tras sem parar."""
        if not (self.tocando and TOLERANCIA_SYNC is not None):
            return
        alvo = self.passo_maquina
        if alvo is None:
            return
        lim = max(1, self.last_var())
        atual = self.passo_abs % lim
        erro = (alvo - atual) % lim
        if min(erro, lim - erro) <= TOLERANCIA_SYNC:
            return
        self.pulsos = alvo * PULSOS_P_STEP
        self.passo_abs = alvo
        self.mover_playhead(alvo % lim)

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
                "visiveis": self.visiveis(),
                "mostrar_acc": self.mostrar_acc,
                "passo": self.passo, "tocando": self.tocando,
                "carregado": self.carregado,
                "acc": self.acc,
                "mudo": list(self.mudo),
                "last_var": self.last_var(),
                "last_track": list(self.ultimo_track),
                "armado": self.armado,
                "esconder_mudos": self.esconder_mudos,
                "variacao_tocando": self.variacao_tocando,
                "playhead_visivel": self.playhead_visivel(),
                "lista_visivel": self.lista_visivel(),
                "tem_clock": self.clk is not None,
                "tem_tr8s": self.tr_out is not None,
                # cores ja resolvidas: a UI so traduz indice/tupla em hex
                "pads": [[self.cor_do_step(l, s) for s in range(16)]
                         for l in range(8)] if self.modo_geral == MODO_ON else None,
                "pattern": {i: [self.ler_vel(i, s) for s in range(16)]
                            for i in self.cache} if self.carregado else {},
                "subs": {i: [self.ler_sub(i, s) for s in range(16)]
                         for i in self.cache} if self.carregado else {},
                "alts": {i: [self.ler_alt(i, s) for s in range(16)]
                         for i in self.cache} if self.carregado else {},
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



if __name__ == "__main__":
    cmd, resto = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    simples = {"ports": cmd_ports, "learn": cmd_learn, "probe": cmd_probe,
               "colors": cmd_colors, "dump": cmd_dump, "run": cmd_run}
    if cmd in simples:
        simples[cmd]()
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
    else:
        print(__doc__)
