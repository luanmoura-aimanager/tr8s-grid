# TR-8S Grid Controller — Referência

Base de conhecimento do projeto: o protocolo SysEx da TR-8S decifrado por engenharia
reversa, as notas de hardware e o estado atual. **Ler antes de mexer em qualquer
coisa** — a seção 3 separa o que está provado do que é só dedução, e essa distinção
é o que impede retrabalho caro.

O protocolo foi levantado **empiricamente** em 08/08/2026 via MIDI Monitor (snoize)
sniffando o Roland TR-EDITOR, e ampliado em 13/08/2026. Tudo aqui é verificado com
hardware salvo onde marcado como dedução ou desconhecido.

---

## 1. Objetivo do projeto

Ter um controlador físico de grid que liga/desliga steps **no sequenciador interno
da TR-8S** — não um sequenciador externo disparando notas. Grid ideal: 11
instrumentos × 16 steps, mais ACC, com forte/fraco, flam e sub steps.

**Status: provado e funcionando em dois controladores.** Um APC40 mkII escreve na
TR-8S em tempo real via script Python no Mac. **A migração para dois Launchpad Mini
MK3 foi concluída em 13/08/2026** — `learn` e `run` rodando, grid 16×8 escrevendo na
máquina, e um `TR-8S Grid.app` no Desktop no lugar do comando no terminal.

**Em 13/08/2026 o projeto ficou funcionalmente completo.** A sessão de captura fechou
o LAST STEP (variação e track) e a PROBABILITY, e confirmou o TRG. A persistência,
que parecia bloqueio, nunca foi: basta apertar `[WRITE]` no painel (ver 2.6).

O que sobra é **opcional**, e nenhum item impede usar o controlador: os bytes 0, 1 e
2 do step, o last step dos Fill In, SHUFFLE, os blocos `0C`–`18`, e o comando
WRITE por SysEx — este último só útil para automação sem ninguém na frente da máquina.

Arquitetura (não muda):

```
controlador (nota/CC via USB) → Mac (Python + mido) → SysEx → TR-8S
Mac (note_on com velocity = cor)  →  controlador (LEDs)
```

A TR-8S é USB **device**, não host — nada pluga diretamente nela por USB. O Mac é
sempre o cérebro.

---

## 2. Protocolo SysEx da TR-8S (não documentado pela Roland)

### 2.1 Porta

Toda a comunicação acontece na porta USB MIDI **`TR-8S CTRL`** (a segunda porta que
a máquina expõe). A porta `TR-8S` comum carrega notas e MIDI clock.

O TR-EDITOR faz polling de keep-alive a cada 3 s nos endereços `00 03 00 3B` e
`00 03 00 36`. Descartar essas mensagens ao analisar capturas.

**O TR-EDITOR segura a porta CTRL.** Fechar o editor antes de rodar os scripts.

### 2.2 Formato da mensagem

```
F0 41 10 00 00 00 45 <cmd> <addr×4> <dados...> <checksum> F7
   │  │  └─────────┘   │
   │  │   model ID     ├─ 0x11 = RQ1 (ler)
   │  └─ device ID     └─ 0x12 = DT1 (escrever)
   └─ Roland
```

**Checksum** (validado contra 7+ mensagens reais):

```python
checksum = (128 - sum(endereço + dados) % 128) % 128
```

**Aritmética de endereço** — carry de 7 bits, não 8:

```python
def addr_soma(addr, offset):
    a = list(addr)
    for i in range(3, -1, -1):
        v = a[i] + (offset & 0x7F)
        offset >>= 7
        a[i] = v & 0x7F
        offset += v >> 7
    return tuple(a)
```

### 2.3 Mapa de endereços

| Endereço | Conteúdo |
|---|---|
| `00 03 00 3B` / `00 03 00 36` | keep-alive do editor (ignorar) |
| `10 00 00 00` | kit: nome (ex. "TR-808") |
| `10 00 10` … `10 00 1A` | 11 instrumentos do kit |
| `10 00 20` … `10 00 2A` | params por instrumento |
| `20 0V 00 00` | **cabeçalho da variação V**, 8 bytes: 0–3 = máscara de ACCENT, **4–7 livres** |
| `20 0V I 08` | **128 bytes de steps** do instrumento I na variação V |
| `20 0V 0B 08` | **TRG** — confirmado pela aritmética, ver abaixo |
| `20 0V 0C` … `20 0V 18` | desconhecido |
| `20 0V 19 08` | 1664 bytes — provavelmente motion/automation |
| `20 00 00 00` | **nível de pattern**, 128 bytes — nome, **variação tocando** (2.3.2), **LAST STEP** |
| `01 00 00 00` | **sistema/performance** — offsets 12–15 = **MUTE de track** (ver 2.7) |
| `00 00`, `00 01`, `00 02`, `00 03`, `30 00`, `40 00` | outras regiões que respondem, conteúdo não decodificado |

**A aritmética por trás disso** (diagrama da p. 8 do Reference, lido em 13/08/2026):
o endereço é um offset de 14 bits, `hi*128 + lo`. O instrumento `I` mora no offset
`I*128 + 8`, e os 8 bytes iniciais são um cabeçalho da variação. Daí
`11*128 + 8 = 1416` = `20 0V 0B 08` = **TRIGGER OUT**, que o diagrama lista logo
depois dos 11 tracks — o palpite virou conta fechada. Os bytes 4–7 do cabeçalho são
os candidatos naturais a last step da variação, scale e shuffle.

- `V` = variação: `01`=A … `08`=H, `09`=Fill 1, `0A`=Fill 2
- `I` = instrumento: `00`=BD, `01`=SD, `02`=LT, `03`=MT, `04`=HT, `05`=RS,
  `06`=HC, `07`=CH, `08`=OH, `09`=CC, `0A`=RC

### 2.3.1 O nó de pattern `20 00 00 00` — decodificado em 13/08/2026

A variação `0x00` não existe (A é `0x01`), e esse endereço guarda o que é do
**pattern**, não da variação. Confirmado com `snap`/`snapdiff`, um gesto por vez:

| offset | conteúdo |
|---|---|
| `0`–`15` | **nome do pattern**, ASCII (`"----"` num pattern novo) |
| `17`, `18`, `19` | três parâmetros, valores `03 05 0C` — não identificados |
| `35`–`59`, ímpares | treze valores `08` — não identificados. Treze = 11 inst + TRG + ACC, mas **não** é o last step |
| **`67`–`74`** | **LAST STEP das variações A–H**, um byte, **0-based** |
| **`75`–`86`** | **LAST STEP de cada track**, um byte, **0-based** |
| `90` | provavelmente o instrumento selecionado no painel — muda sozinho e suja diffs |
| `95`–`109` | sequência `01 02 … 0F` |

### 2.3.2 A variação que está tocando — offsets 63–66, decodificada em 14/08/2026

```
20 00 00 00, offsets 63–66    máscara de 16 bits em 4 nibbles
bit 0 = A  …  bit 7 = H
```

**Terceiro campo da máquina no mesmo formato do ACCENT** (2.5) e do MUTE (2.7) — vale
tratar 4 nibbles como o idioma padrão dela para conjuntos, e desconfiar de qualquer
candidato a "número" que se mexa em dois bytes.

Confirmada em três estados: A → `0x0001`, B → `0x0002`, E → `0x0010`. Foi o E que
denunciou o formato: se fosse um número simples, o offset 66 marcaria `05`; em vez disso
o 65 virou `01` e o 66 zerou, que é exatamente o nibble transbordando.

Ela mora **imediatamente antes da tabela de last steps** (67–86), o que fecha a leitura
daquele bloco: 63–66 dizem qual variação toca, 67–74 o tamanho de cada uma, 75–86 o dos
tracks. E cai **de graça** no RQ1 que o `ler_last_steps()` já faz a cada 1,5 s.

**Trocar de variação não emite Program Change** — escutados 14 s na porta comum durante a
troca, só clock. A implementation chart marca PC como transmitido, mas é para pattern, não
para variação. Ler o endereço é o único caminho.

**Para que serve:** o grid escreve numa variação independente da que toca — o recurso mais
valioso do projeto (2.6). Mas o playhead não sabia disso e continuava correndo ao trocar
para B enquanto a máquina tocava A, afirmando que aquele padrão soava. Desde 14/08 a
coluna verde **só aparece quando o grid está na variação que a máquina toca**; ela some
nos outros casos, e o contador continua andando por baixo para reaparecer em fase.

**Os Fill In não aparecem nesta máscara** — testado em 14/08/2026: com a máquina tocando e
o `[MANUAL TRIG]` disparado várias vezes, a máscara **não se mexeu** em 30 s de
amostragem a cada 50 ms. Ela continua marcando a variação base durante o fill. Duas
consequências, ambas benignas:

- Durante um fill, o grid segue mostrando o playhead da variação base. O verde "mente" por
  um compasso, e essa é a leitura menos surpreendente das disponíveis
- **Editar um Fill In no grid mostra o playhead**, por decisão de 14/08. As variações
  `09`/`0A` nunca coincidem com uma máscara que só reporta A–H, então sobre elas não há
  informação nenhuma — e a regra da casa quando falta informação é mostrar, não apagar.
  Esconder ali custaria a referência de tempo por um detalhe de protocolo

  Isso obrigou a separar duas condições que pareciam uma só: `playhead_visivel()` decide
  se o verde é **desenhado** (frouxa, inclui os fills) e `em_fase_com_a_maquina()` decide
  se a fase pode ser **corrigida** pelo step da máquina (estrita). Num fill o passo lido
  se refere à variação base, de outro comprimento — corrigir por ele traria de volta a
  comparação de módulos diferentes que a 3.2 já custou caro para descobrir

Onde os fills guardam esse estado continua desconhecido, como o last step deles (2.3.1).

**Os dois LAST STEP moram na mesma tabela de 20 bytes**, offsets 67 a 86:

```
67 68 69 70 71 72 73 74 │ 75 76 77 78 79 80 81 82 83 84 85 86
 A  B  C  D  E  F  G  H │ BD SD LT MT HT RS HC CH OH CC RC TRG
    variações A-H       │           tracks
```

**Ambos 0-based**: pad 6 grava `05`, pad 10 grava `09`, pad 12 grava `0B`, e o
default `0F` = 16 steps.

O do track ficar no nível de pattern era esperado — o Reference p. 12 diz que ele é
compartilhado entre A–H. **O da variação ficar aqui também não era**: ele é por
variação, e a intuição dizia que estaria no cabeçalho `20 0V 00 00`. Os bytes 4–7
daquele cabeçalho continuam zerados e sem função conhecida.

Ainda não localizado: o last step dos dois **Fill In** (Reference p. 11 diz que dá
para ajustar). Não está em 67–74, que tem exatamente oito bytes para A–H.

### 2.4 Layout do step

Os 128 bytes = **16 steps × 8 bytes**. O editor escreve **um step por vez** (8
bytes), com o endereço andando de 8 em 8.

```
byte  0 1 2 3 4  5   6  7
      ─ ─ ─ │ ─  │   └──┴─ velocity em nibbles
      └───┘ │ │  └─ tipo do step
        ?   │ └─ ?
            └─ PROBABILITY
```

**Byte 3 = PROBABILITY**, decodificado em 13/08/2026. É o **complemento** da
porcentagem, em passos de 10:

```python
byte3 = (100 - porcentagem) // 10        # 100% -> 0,  50% -> 5,  10% -> 9
```

Confirmado com três pontos: 50% grava `05`, 90% grava `01`, 20% grava `08`. O
default `00` = 100% fecha a origem — step sem probability definida sempre toca.

**Byte 4 = ALTERNATE. Confirmado em 14/08/2026** — leitura, escrita e prova
auditiva.

```python
byte4 = 0x08   # ALT ligado      (bit 3, nao 0x01)
byte4 = 0x00   # som normal
```

A confirmação veio com `707 Bass1/2` carregado no BD e o gesto feito em dois steps:
`08` nos dois, `00` nos catorze restantes — dois casos e catorze controles, em vez
da medição solta de 13/08. Depois, escrever `08` num terceiro step fez a máquina
tocar o som alternado ali, ouvido na caixa.

**ALT é independente da velocity** (um dos steps marcados estava em 50) e do byte 5,
igual ao flam.

Continua em aberto **por que bit 3 e não bit 0**. A leitura mais provável é que o
byte seja um campo de bits com outras flags ainda sem uso, mas nada foi testado —
tratar `08` como "o valor do ALT", não como "o bit 3 significa ALT".

O motivo do gesto ser difícil vale mais que o achado. A máquina estava com o
**Weak Beat em modo PAD** (Reference p. 45), no qual *cada toque no pad cicla
`strong → weak → off`*. Se o botão de instrumento não registrar, o toque vira toque
comum e cicla a velocity em vez de marcar o alternate. **O sinal de que falhou é a
velocity mudar** — quando o gesto pega, ela fica parada. Para tentar de novo, vale
antes trocar o Weak Beat para `wSHIFT` no UTILITY, e aí o pad solto para de ciclar.

De brinde, isso confirmou **ao vivo** o par 80/50 que a seção 2.4 tinha levantado só
de manual: o ciclo do pad alternou exatamente entre esses dois valores.

Restam **três** bytes sem nome no step: 0, 1 e 2.

*Nota de procedimento:* o Reference p. 20 diz "*press the [COPY] or [UTILITY] button
to select either PROB or SUB PROB*", como se fosse um toque para cada. **Na máquina
eles ciclam uma lista que começa no TUNE** — é preciso apertar `[UTILITY]` várias
vezes até chegar no PROB. E tudo isso só existe dentro do **TR-REC**; fora dele,
segurar o pad mostra o parâmetro do instrumento.

**Bytes 6 e 7 = velocity**, nibble alto e nibble baixo:

```python
velocity = (byte6 << 4) | byte7
byte6, byte7 = (v >> 4) & 0x0F, v & 0x0F
```

**Velocity 0 = step desligado.** Não existe flag de on/off separada.
Valores usados pelo TR-EDITOR: `05 00` = 80 (normal), `03 02` = 50 (weak beat).

**A TR-8S aceita velocity contínua por step — não é só forte/fraco.** O painel
esconde isso atrás de dois gestos pouco óbvios (Reference p. 19–20):

- *Changing the Dynamics for Each Step*: segurar o pad `[1]–[16]` e girar o
  **ACCENT [LEVEL]** — o manual chama de "accent level (velocity)" por step
- long-press no pad abre a tela **MOTION/VELOCITY**

`SHIFT`+pad (WEAK BEAT) é só o atalho de dois níveis. Ou seja, velocity fina está na
mesma categoria de flam e sub step: existe na máquina, mas é desconfortável no
painel — exatamente o tipo de coisa que o grid resolve com um toque.

**Byte 5 = tipo do step:**

| Valor | Significado |
|---|---|
| `00` | normal |
| `01` | FLAM |
| `02` | SUB STEP 1/2 |
| `03` | SUB STEP 1/3 |
| `04` | SUB STEP 1/4 |

Flam e velocity são **independentes** — flam fraco = byte5 `01` + velocity 50.

### 2.5 ACCENT

Não é por step. É uma **máscara de 16 bits** em `20 0V 00 00`, escrita como 4
nibbles. Bit 0 = step 1.

```python
nibbles = [(m >> 12) & 0xF, (m >> 8) & 0xF, (m >> 4) & 0xF, m & 0xF]
```

Exemplos reais capturados: `00 00 00 01` = step 1; `00 00 0F 0F` = steps 1–8;
`05 05 05 05` = steps ímpares.

### 2.7 MUTE de track — decodificado em 14/08/2026

```
01 00 00 00, offsets 12–15   máscara de 16 bits em 4 nibbles
bit i = instrumento i         BD=0 SD=1 LT=2 MT=3 HT=4 RS=5 HC=6 CH=7 OH=8 CC=9 RC=10
```

**É o mesmo formato do ACCENT** (2.5) — as funções `mascara_para_nibbles` /
`nibbles_para_mascara` servem sem alteração.

Confirmado em quatro estados, incluindo um que cruza a fronteira de nibble
(`CH+OH+CC+RC` = `0x0780` → nibbles `0 7 8 0`), e round-trip nos 11 instrumentos.

**Leitura e escrita provadas em hardware.** A escrita silencia de verdade: o Luan
ouviu os chimbais sumirem e voltarem na caixa, não foi só releitura de valor.

Duas coisas que este achado corrige no resto do documento:

- **A seção 10 partia de uma premissa falsa.** MUTE virou HIDE porque parecia
  impossível silenciar por software. O que era impossível era pelo **CC de LEVEL**;
  o mute sempre esteve ali, num endereço de sistema. A conclusão de 13/08 ("não
  tentar de novo sem uma razão nova") estava certa quanto ao CC e errada quanto ao
  recurso.
- **Por que o `snap` nunca acharia.** Ele mora fora do pattern e fora do kit — é
  estado de **performance**, não conteúdo salvo. Os ~50 endereços do snapshot
  cobriam `10 xx` e `20 xx`; o mute está em `01 00`. Mutar mil vezes não produziria
  diff nenhum, e a ausência de diff parecia significar "não é legível".

**Ele não é salvo com o pattern**, o que é consistente com ser performance — e por
isso o grid nunca guarda espelho local: relê a máquina a cada 1,5 s, junto com os
last steps.

### 2.8 Step atual do sequenciador — mesmo bloco, offset 7

```
01 00 00 00, offset 7    step que a TR-8S está tocando, 0–15
```

Anda 0→15 e dá a volta; **congela quando o transporte para**. Ele apareceu como
"ruído que muda sozinho" num diff de mute e quase foi descartado como tal — a lição
é que num diff de gesto único, o que se mexe sem motivo aparente merece uma pergunta
antes de virar ruído.

Ele resolve um problema que o MIDI clock não resolve:

> **A TR-8S transmite MIDI clock mesmo PARADA** — medido em 14/08/2026: 138 pulsos
> em 4 s com o transporte parado. Portanto "chegou clock" **não** prova que ela está
> tocando; só `start`/`continue` provam.

E quem sobe o grid com a máquina **já rodando** nunca recebe um `start`. O playhead
ficava apagado até parar e tocar de novo — bug real, encontrado no teste de 14/08.
Hoje o `adotar_transporte()` lê este byte duas vezes com 0,5 s de intervalo: se andou,
está tocando, e a fase entra alinhada.

Dois cuidados que a implementação precisou:

1. **Drenar a fila de clock antes de fixar a fase.** Enquanto ninguém chama `tick()`,
   os pulsos se acumulam no buffer do rtmidi desde que a porta abriu; o primeiro tick
   processaria tudo de uma vez e jogaria o playhead para frente.
2. **Compensar a latência da leitura sem saber o andamento.** Contando quantos pulsos
   chegam *durante* o RQ1, tem-se o tempo decorrido já na unidade certa. Na prática deu
   0 pulsos — o round-trip é mais rápido que 21 ms — mas a conta serve a qualquer BPM.

O byte também é relido de graça a cada 1,5 s, porque vem no mesmo bloco do mute. O
`_ressincronizar()` usa isso para puxar o playhead de volta quando ele diverge mais de
um step, o que **limita estruturalmente a deriva**: contar clock é exato enquanto
nenhum pulso se perde, e um pulso perdido seria erro permanente sem essa correção.

**Sobra uma latência física** que não dá para medir de dentro — o LED do Launchpad
acende alguns ms depois do comando sair, e o som sai da TR-8S por outro caminho. É o
`AJUSTE_PLAYHEAD`, em pulsos, **calibrado no olho**: a 120 bpm, 0 ficou atrasado, 2
acertou e 3 passou do ponto.

### 2.9 O mapa OFICIAL da Roland — achado em 14/08/2026, nada testado aqui ainda

O repo vizinho `TR-8S-SysEx/` (compuphonic) guarda o código-fonte do site **ARIA
Sound Library** da Roland, e dentro dele, em `js/Tr8s/Tr8sData.js`, está **a tabela
de endereços oficial da máquina**, em base64 (`TR8S_DATA`, decodificada por
`eval(atob(...))`). As 4 capturas `.mmon` do mesmo repo mostram esses comandos em
tráfego real (o `tr8s_sysex.py` agora lê `.mmon` direto). Não é engenharia reversa:
é a Roland falando com a própria máquina.

**Estatuto epistêmico: entre "deduzido" e "provado".** Veio de tabela oficial E foi
visto no fio — mas contra OUTRA máquina, em outro contexto (o ARIA trava a máquina
com `lock` antes de várias operações). Nada disso rodou na nossa TR-8S. Cada item
entra em uso só depois da sua mini-sessão, e o resultado (positivo OU negativo) volta
para cá.

**Troca remota de kit e pattern** — o bloco `01 00 00 00` (o mesmo do MUTE, 2.7):

| offset | conteúdo | como usar |
|---|---|---|
| `0` | **kit atual** (0-based) | DT1 de 1 byte troca o kit |
| `1` | **pattern atual** (0–127 = banco A–H × 16) | DT1 troca na hora (?) |
| `2` | **próximo pattern** | DT1 agenda a troca (na virada?) — candidato a chain |
| `27` (`0x1B`) | patternSelect, máscara `1 << (ptn % 16)` em 4 nibbles | feedback dos pads? |

Exemplo real da captura: `F0 41 10 00 00 00 45 12 01 00 00 01 7F 7F F7` = pattern
atual → 127. O `cmd_pattern` do `lp_tr8s.py` manda exatamente isso (sessão B).

**Bloco utility `50 00 00 xx`** — uma TERCEIRA semântica de mensagem: pergunta e
resposta são **ambas DT1 no mesmo endereço** (não é RQ1/DT1):

| sub | comando | observado na captura |
|---|---|---|
| `01`/`02`/`03` | **WRITE** de pattern/kit/tone, data = `[id>>7, id&0x7F]` | `12 50 00 00 02 00 7E 30` grava o kit 127 |
| `10` | **está tocando?** | resposta 1 byte, 0 = parada — mata a armadilha do clock (2.8) |
| `11` | lock/unlock (trava a máquina) | o ARIA trava antes de bulk; **nós não queremos** |
| `12` | **escrever 32 chars ASCII no visor** | `"Optimizing..."` na captura |
| `13`/`14` | versão do firmware / UID | `"1.13"` + serial |
| `20`–`24` | optimize / freeArea / freeTone / deleteTone | gestão de samples |
| `30`–`75` | get/send em bulk: pattern **24504 B**, kit **1312 B**, system 752 B | chunks de até 1024 B com packing 7-bit e progresso |

Ressalva do WRITE: nas capturas ele só aparece como *commit de bulk transfer*. Que
ele também grave o buffer editado por DT1 (o que o `[WRITE]` do painel faz) é
hipótese — o teste é editar um step, mandar WRITE, **religar a máquina** e ver se
sobreviveu.

**Confirmações de coisas que estavam em aberto no 2.3:**
- `10 00 10` … `10 00 1A` = **toneIds** dos 11 instrumentos (uint16 nibbled).
  Em cima disso a aba **Instrumento** da janela troca o tone (o gesto INST do
  TR-EDITOR): leitura pelos endereços que o snap já provou, escrita por DT1
  nunca testada. **A ponte id→nome é HIPÓTESE**: a Preset Tone List (PDF, 514
  tones, extraída para `tones.py` por `gen_tones.py`) não numera; assumimos
  id = posição na lista (base 0) porque o ARIA reserva 624–1023 aos tones de
  usuário. Sessão de confirmação: ler o toneId de um kit conhecido (ex.
  BD do kit TR-808 deveria ser um dos "808 Bass") e conferir 2–3 pontos; se
  houver deslocamento, corrigir só o `BASE_ID` do `tones.py`.
- `10 00 20` … `10 00 2A` (params por instrumento, 128 B cada) é onde devem
  morar **TUNE, DECAY, LEVEL, GAIN, PAN, sends de reverb/delay, INST FX,
  destino e depth do LFO** — é o bloco que a aba INST do TR-EDITOR edita;
  nenhum offset tem nome ainda.

  **Dois bytes por parâmetro.** O manual (p. 29–33) dá faixas de **0–255**
  (Decay, Level, sends, LFO Rate) e **−128…+127** (Tune, Pan, Gain, LFO
  Depth) — nenhuma cabe num byte MIDI de 7 bits. A máquina deve usar o mesmo
  truque do velocity (2.4): **dois bytes em nibbles, valor = (hi<<4)|lo**.
  Por isso a captura de um parâmetro de faixa larga só fecha quando vê os
  **dois offsets vizinhos** mexerem — daí a instrução "gire de ponta a ponta".
  O manual também entrega que **o centro dos bipolares é 128** ("If the
  setting of the parameter to be modified is 128 (the center value)", p. 33),
  então −128…+127 é 0–255 deslocado. Isto é leitura de manual, não protocolo
  provado: confirma-se comparando o número da janela com o do visor.

  **LFO** (Reference p. 29 e 33), o que a janela cobre:
  | parâmetro | escopo | valores | gesto no painel |
  |---|---|---|---|
  | Waveform | kit | SIN, TRI, SAW, SQR, S&H | SHIFT+[KIT] → LFO → Waveform |
  | Tempo Sync | kit | OFF, ON | SHIFT+[KIT] → LFO → Tempo Sync |
  | Rate | kit | 0–255, ou 64.00–0.25 step com sync | SHIFT+[KIT] → LFO → Rate |
  | destino | instrumento | Tune, Decay, Level, Pan, ReverbSend, DelaySend, InstFX + params do tone | SHIFT+[INST] → LFO |
  | Depth | instrumento | −128…+127 | SHIFT+[INST] → LFO Depth |

  Os **códigos** das listas (qual número é S&H) não estão em lugar nenhum:
  descobrem-se um a um pelo botão "Anotar opção" — põe a opção no visor,
  escolhe o rótulo, e o app associa o valor lido ao nome.
  Três caminhos de decodificação, todos passivos: a sessão K
  (`python3 lp_tr8s.py kit_watch BD`), a **captura guiada da aba Avançado**
  (morava na Mixer & FX até a reforma 3, 16/08/2026)
  (M1: nomear o parâmetro, Capturar, mexer só naquele knob — o app registra o
  offset em `~/.lp_tr8s_fx.json` e o fader nasce) e o **sniff do TR-EDITOR**
  (M2: MIDI Monitor + `.mmon`, cobre o que o painel não alcança; o resultado
  vira entrada estática em `efeitos.py`). Parâmetros de kit-level (reverb,
  delay, master FX) são procurados no nó do kit lido a 128 B — primeira
  leitura nesse tamanho; se não responder, ficam só com o M2.
- `20 00 00 14` = **kitReference** do pattern (uint16 nibbled) — vizinho dos bytes
  17–19 "não identificados" do 2.3.1; vale re-olhar aquele trecho com esta lente
- `30 00 00 00` = nome/categoria/tipo de **tone**; `40 00 00 00` = endereço/tamanho
  do **sample** na flash; `00 01 00 n0` = 32 nomes de categoria de usuário
- Os endereços do keep-alive continuam sem explicação — o ARIA não os usa; são
  exclusivos do TR-EDITOR

O firmware update (`50 00 00 74/75`) fica **registrado e intocado**: o risco é
tijolar a máquina.

### 2.6 Comportamento da escrita

- Escreve no **buffer ativo**, não na memória permanente. Para persistir, **aperta-se
  o `[WRITE]` no painel** — e isso resolve o problema. Durante muito tempo este
  documento chamou o WRITE por SysEx de "a peça que falta para autonomia total";
  **estava errado**, e a correção veio de uma pergunta do Luan em 13/08: nada se
  perde, o botão está ali. O comando por SysEx compraria só **gravar num slot
  específico sem navegar no painel** — automação, não autonomia.
- Escreve **independente do que está selecionado no painel**. Dá para editar a
  variação B enquanto a A toca. Este é o recurso mais valioso descoberto e não
  existe nativamente na máquina.
- Trocar de variação no script **não** troca o que a TR-8S reproduz — só onde ele
  escreve. Comando de troca remota de variação não capturado (existe: há um device
  Max for Live comercial que faz "next pattern" via SysEx).

---

## 3. O que está provado vs. deduzido vs. desconhecido

**Provado (testado com hardware):**
- Protocolo, checksum, aritmética de endereço com carry
- Os 11 instrumentos, escrita testada em todos
- Os 16 steps, incluindo o step 16 que cruza o limite de 7 bits (`20 01 01 00`)
- Velocity forte (80) e fraca (50)
- Flam e sub steps 1/2, 1/3, 1/4
- ACCENT
- Leitura (RQ1) e escrita (DT1) aceitas pela máquina
- **Fills `0x09` e `0x0A`** — escrita confirmada em hardware em 13/08/2026; eram
  dedução desde o começo do projeto
- **Rajadas de DT1** (CLEAR variação e COPY/PASTE, 176 mensagens) com
  `sleep(0.002)` entre mensagens — a máquina aguenta
- **SysEx de LED em RGB** do Launchpad
- **LAST STEP da variação e do track** — decodificados, lidos e escritos com
  round-trip confirmado em 13/08/2026 (ver 2.3.1)
- **Escrita de 1 byte** num offset arbitrário: a máquina aceita, não é preciso
  respeitar o bloco de 8 bytes dos steps
- **TRG existe em `20 0V 0B 08`** como bloco distinto — comparado byte a byte com o
  do BD, não é espelho
- **MUTE de track** (2.7) e **step atual do sequenciador** (2.8) — lidos e escritos,
  com o mute confirmado de ouvido
- **Variação que está tocando** (2.3.2) — confirmada em três variações
- **Byte 4 do step = ALTERNATE** (2.4) — confirmado de ouvido em 14/08/2026

**Observado uma vez, não confirmado:**
- (nada no momento)

**Documentado pela Roland (mapa do ARIA, 2.9), nunca exercitado NA NOSSA máquina:**
- Troca remota de kit/pattern (`01 00 00 00/01/02`) — sessão B
- Bloco utility inteiro: playing, visor, versão/UID, WRITE, bulk (2.9)
- Que o WRITE utility grave o buffer editado por DT1 (só foi visto como commit de
  bulk)

**Deduzido, nunca exercitado:**
- Que o bloco `20 0V 0B 08` seja mesmo o **TRIGGER OUT**. Ele existe, é distinto e
  tem formato de step; que seja o TRG vem do diagrama da p. 8, não de teste.
- A **fórmula linear da probability** (`byte3 = (100 - pct) // 10`): três pontos
  provados por leitura (2.4), o resto é interpolação. A sessão A (`prob_watch`)
  fecha a tabela. A ESCRITA do byte 3 nunca foi tentada — o `definir_prob` da
  janela avisa isso no log.
- ~~A **escrita da máscara de variação** (offsets 63–66)~~ — **PROVADA em
  16/08/2026**, três trocas seguidas obedecidas, e também com vários bits
  (montando o rodízio A+B+C remotamente). Ver a seção da máscara 63–66 em 7.

**Desconhecido:**
- Bytes 0, 1 e 2 de cada step — os três últimos sem nome, agora que o 4 fechou
- ~~Comando WRITE~~ — candidato forte no utility (`50 00 00 01`, ver 2.9), falta a
  sessão
- ~~SCALE~~ — **resolvida em 17/08/2026**: nó do pattern, offset `0x16`
  (2 = `16th`, 3 = `32nd`, medidos). SHUFFLE segue desconhecido
- O last step dos dois **Fill In**
- ~~Onde mora o mute de track~~ — **resolvido em 14/08/2026**, ver 2.7. Os CCs de
  LEVEL continuam não servindo; o mute nunca esteve neles.
- Blocos `0C`–`19`

**Três métodos para mapear o que falta**, do mais barato ao mais caro:

1. **`snap` + `snapdiff`** (13/08/2026) — lê a máquina inteira com RQ1, você mexe
   **uma coisa** no painel, lê de novo, compara. Não precisa de editor nem de MIDI
   Monitor. Pega qualquer coisa que seja *estado* guardado no pattern ou no kit.
   Não pega comandos, que não deixam rastro.
2. ~~**`sniff`**~~ — **testado em 13/08/2026 e a aposta caiu.** A máquina **não
   transmite SysEx dos gestos do painel**: knob girado, step aceso em TR-REC, troca
   de variação e `[LAST]`+pad não produzem nada na porta CTRL. Ela só responde
   quando perguntada.

   O resultado é confiável porque o `sniff` faz **autoteste**: antes de escutar ele
   manda um RQ1 e confirma que a resposta chega pelo mesmo caminho. Sem isso,
   "não apareceu nada" seria ambíguo entre a máquina calada e o listener surdo — e
   a conclusão errada teria virado achado aqui. **Não repetir esse teste**; ele já
   foi feito com o controle no lugar.

   O `sniff` continua útil para ver o que a máquina *responde*, mas não serve para
   capturar comando nenhum.

   *Inferência, não fato:* se ela não empurra estado, o TR-EDITOR só pode se manter
   sincronizado relendo — o que combina com o polling de keep-alive da seção 2.1.
3. **MIDI Monitor** (funcionou 4×) — o único que vê o que o editor manda **para** a
   máquina, porque usa a API privada de espionagem do CoreMIDI, que o rtmidi não
   expõe. Filtro só SysEx + Invalid, uma alteração por vez, `tr8s_sysex.py diff`.
   Reservar para o que os dois primeiros não alcançarem.
4. **`varrer`** (14/08/2026) — sonda de 1 byte em endereços candidatos para descobrir
   **quais existem**, já que endereço inválido cala. Leia a armadilha abaixo antes de
   usar: ele é o único método que danifica o estado da máquina enquanto roda.

### 3.1 RQ1 em endereço inválido envenena a porta CTRL — medido em 14/08/2026

Depois de **~60–75 sondas em endereços que não existem**, a TR-8S para de responder a
**qualquer** RQ1 — inclusive aos endereços conhecidos que respondiam um segundo antes.
Ela **não se recupera sozinha** (testado até 30 s parada); só religando a máquina. A porta
comum continua normal o tempo todo, mandando clock, então de fora parece tudo bem.

**Leitura válida não faz isso.** O `run` relê a máquina a cada 1,5 s por horas e o `snap`
dos ~50 endereços conhecidos passa inteiro. O veneno é *perguntar pelo que não existe*.

Isso custou caro para descobrir e vale registrar como aconteceu, porque o erro é sutil: a
primeira versão do `varrer` conferia se a máquina estava viva **uma vez, no começo**, e
saiu com 15 "achados" em `00 03` — offsets `0`–`3` e `0x32`–`0x3C`, sendo que `0x32`–`0x3C`
são **exatamente 11**, o número de instrumentos, com os dois keep-alives do editor caindo
dentro da faixa. Bonito demais, e **falso**: não reproduziu, e minutos depois a CTRL estava
muda em todos os endereços conhecidos. O que parecia o mapa do mute era a máquina morrendo.

Consequências para quem for varrer:
- O autoteste tem que ser **periódico**, não de abertura, e a varredura tem que **abortar**
  quando a máquina cair — senão ela lê silêncio de porta como silêncio de endereço.
- Todo achado precisa de um **segundo passe**: endereço de verdade responde duas vezes,
  falso positivo não.
- A varredura anda em **lotes de 50** com o progresso salvo em disco. Cada retomada custa
  uma religada, que é uma ação humana; perder o lote inteiro sai caro.
- **Varrer é o último recurso, não o primeiro.** O `snap`/`snapdiff` dos endereços
  conhecidos não tem esse custo e resolve tudo que estiver no pattern ou no kit.

---

### 3.2 Método: como descobrir coisas nesta máquina

Destilado da sessão de 14/08/2026, que decodificou o mute, o ALT e o step atual em algumas
horas depois de meses de itens parados. O que mudou não foi a sorte — foram estas regras.
Elas custaram caro para aprender e são baratas de seguir.

**1. Autoteste sempre, e periódico.** Sem ele, "não apareceu nada" é ambíguo entre a
máquina calada e o listener surdo, e a leitura errada vira achado no documento. Foi o
autoteste que tornou confiável o resultado negativo do `sniff`, e foi a falta dele que
produziu os 15 endereços fantasma da 3.1 — a primeira versão do `varrer` conferia se a
máquina respondia **uma vez, no começo**, e não viu que ela morreu no meio.

**2. Piso de ruído antes de qualquer diff.** Dois snapshots sem tocar em nada, e compare.
Custa 10 segundos. Sem essa medida, um byte que muda sozinho — e existem, como o offset 90
do nó de pattern — vira "achado" no primeiro diff que você olhar.

**3. Um gesto por vez, e o inverso logo em seguida.** O valor tem que voltar. Mutar o BD e
desmutar o BD prova mais que mutar cinco instrumentos, porque o retorno elimina
coincidência.

**4. Segundo passe em todo achado.** Endereço de verdade responde duas vezes; falso
positivo não. É uma linha de código e teria matado os 15 fantasmas sozinha.

**5. Ler blocos, não sondar bytes.** Uma leitura de 128 bytes cobre o que 128 sondas
cobririam, é ~100× mais rápida e **não envenena a porta** (3.1). A varredura byte a byte
existe para mapear fronteiras de região, e é o último recurso, não o primeiro.

**6. O que muda sem motivo aparente merece uma pergunta antes de virar ruído.** O byte de
step atual (2.8) apareceu como "ruído que muda sozinho" num diff de mute e quase foi
descartado. Ele acabou consertando dois bugs do playhead.

**7. Teste negativo não vira afirmação geral.** O CC de LEVEL não silenciar virou "não dá
para silenciar por software", e essa frase ficou errada no documento por um dia — tempo em
que um recurso funcionando parecia impossível (seção 10). Registre o que **foi** testado,
não a generalização que ele sugere.

**8. A ordem certa é do barato para o caro.** `snap`/`snapdiff` nos endereços conhecidos →
leitura em bloco de regiões novas → varredura → MIDI Monitor. Cada degrau só se justifica
quando o anterior não alcança; a sessão de 14/08 quase começou pelo caro e teria gasto
várias religadas da máquina à toa.

**9. O que o hardware confirma vale mais que o que o round-trip confirma.** Escrever um
valor e reler prova que a máquina *aceitou*, não que ela *obedeceu*. O mute só virou fato
quando o Luan ouviu os chimbais sumirem.

---

## 4. Arquivos

| Arquivo | Estado |
|---|---|
| `apc_tr8s.py` | **Funcionando e testado** — APC40 mkII |
| `lp_tr8s.py` | Dois Launchpad Mini MK3. O motor virou `class Motor`; o `run` do terminal só instancia e chama `tick()` num laço. Desde 14/08/2026: fila de comandos da janela (`enfileirar`), probability (`PROB_BYTE`/`ler_prob`/`escrever_step(prob=)`), guarda do cache inválido, `escrever_pattern`+`desfazer_escrita`, luz da borda escurecida (`BRILHO_BORDA`), comandos utility (2.9) e as CLIs de sessão `prob_watch`/`pattern`/`pc`/`var_mask` |
| `web/` | **A interface, desde 15/08/2026.** `index.html` + `css/` (tokens, base, componentes, grade, abas) + `js/` (nucleo: rede/store/dom/paleta/formato · comp: knob, fader, LED, grade-steps, toast, tooltip, secao · abas: pattern, fx "Efeitos", mixer "a mesa", instrumento, grooves, estocastica, avancado). Módulos ES nativos, zero build, zero dependência. Cada aba monta uma vez e só a visível é atualizada |
| `servidor.py` + `pagina.html` | **A tela, desde 15/08/2026.** (`pagina.html` virou fallback: o servidor prefere `web/index.html`) Servidor HTTP local (só stdlib, 127.0.0.1) + página. O `.app` sobe o servidor e abre o navegador. Motor, SysEx e Launchpads inalterados: a página fala com o Motor pelas mesmas chamadas (`enfileirar`) que a janela Tk fazia. Segunda instância só reabre a página em vez de brigar pela porta CTRL |
| ~~`gui.py`~~ | **Obsoleto** — a janela Tk. Não é mais empacotada; ver a nota sobre o Tk 8.5.9 abaixo |
| `gui.py` (histórico) | **Reescrita em 14/08/2026** (a anterior quebrava no Tk 8.5.9 Aqua, que ignora cores de `tk.Button`/`tk.Checkbutton`). Janela fixa, botões de modo em Canvas com indicação do ativo, log em `~/Library/Logs/TR8S-Grid.log`. **Sem grid**: o físico já mostra steps; as abas são o que o físico não tem — Mixer & FX (captura guiada + fileira PROB), Instrumento (troca de tone), Biblioteca, Chain, Estocástica (com régua de probability por step), Avançado. A UI só fala com o Motor via `enfileirar` + `estado()`. Nada de Toplevel: o Tk 8.5.9 Aqua trava ao atualizar um recém-criado |
| `efeitos.py` | Duas metades: o **catálogo** (o que a máquina tem — LFO, sends, INST, reverb/delay/master — com faixa, opções e o gesto que chega nele no painel, tirado do manual p. 24–33) e o **mapa decodificado** (offsets capturados em `~/.lp_tr8s_fx.json` + fixos do sniff M2). Nenhum offset vem de chute; parâmetro de 2 bytes e código de opção de lista são tratados explicitamente |
| `biblioteca.py` | Puro-dados: 54 patterns clássicos em 34 estilos, com kit sugerido e preview. `python3 biblioteca.py` valida e imprime ASCII; o `testes.py` roda o `validar()` em toda suíte |
| `tones.py` | Puro-dados: a Preset Tone List (514 tones, 19 categorias) para a aba Instrumento. **Não editar na mão** — regerar com `gen_tones.py`. O `BASE_ID` carrega a hipótese de id (2.9) |
| `gen_tones.py` | Extrai a Preset Tone List do PDF da Roland e gera o `tones.py` (trata as 3 linhas quebradas do extrator de texto) |
| `ferramentas.py` | `Chain` (reescrita perseguindo o playhead — provada em mesa; modos pattern/variação/PC aguardam as sessões B/C) e `Estocastica` (densidade/humanize/retrig/ghosts com seed reprodutível) |
| `criar_app.py` | Monta o `TR-8S Grid.app` no Desktop. Ícone desenhado em Python puro (sem PIL), `sips` + `iconutil` fazem o resto |
| `tr8s_sysex.py` | Parser/diff de capturas do MIDI Monitor — texto colado E `.mmon` (binary plist) |
| `layout.html` | Referência visual dos botões — abrir no browser |
| `gen_layout.py` | Gera o `layout.html`. Editar aqui, não no HTML |
| `adesivo.pdf` | 34 etiquetas em **tamanho real**, uma página A4 — recortar e colar **em cima** dos botões (32) e nos cantos do logo (2) |
| `gen_adesivo.py` | Gera o `adesivo.pdf`. A única medida que importa é `BOTAO = 15 mm`. Ver a compensação de escala abaixo |
| `apagar_luzes.py` | Apaga os LEDs dos Launchpad. Alias `launchpad_blackout` no `~/.zshrc` |

O `.app` carrega uma **cópia** dos scripts em `Contents/Resources/`. Depois de editar
`servidor.py`, `pagina.html` ou `lp_tr8s.py`, rodar `python3 criar_app.py` de novo. Se
ele não abrir, o motivo cai em `~/Library/Logs/tr8s-grid.log`.

### Por que a janela Tk morreu (15/08/2026)

O Python 3.9 do Command Line Tools traz **Tk 8.5.9** — build de 2010, o Aqua legado
que a Apple abandonou. Com a janela de abas ele entrava em **tempestade de redesenho**
no macOS 26. Medido com o app lançado pelo Finder, contando eventos `Expose` em 2,5 s:

| o que estava na tela | Expose |
|---|---|
| janela + label / canvas / 11 Scales / Notebook / label com wraplength (cada um isolado) | 17–97 |
| App completo | **4313–6538** |
| App com as abas vazias | 1190 |
| App com abas vazias e sem o laço de UI | 200 |

O `sample` do processo mostrava `TclServiceIdle → XDrawLine → NSView
lockFocusIfCanDraw → setNeedsDisplayInRect` em loop: o layout nunca estabilizava, a
janela nunca terminava de pintar e o processo passava de 600 MB (um esquecido aberto
por 12 h chegou a 1,6 GB). **Não era layout**: a janela pedia 796×633 numa área de
820×680 — cabia folgado. Nenhum widget isolado reproduzia; só o conjunto.

Duas armadilhas de diagnóstico que custaram tempo e ficam registradas:
1. **Testar com `withdraw()` esconde o problema** — sem desenho não há tempestade, e
   todos os smoke tests passavam. Janela Tk só se testa visível.
2. **`~/Library/Logs/TR8S-Grid.log` e `tr8s-grid.log` são o mesmo arquivo** (o disco
   do macOS não distingue maiúsculas): o log do app apagava o stderr do lançador,
   justamente onde apareceria o traceback. O do app virou `TR8S-Grid-app.log`.

A troca para página web resolveu na medida: **23 MB e 0,6 % de CPU, estáveis**.

### O servidor local não é privado (15/08/2026)

Uma página web local é servida a **qualquer coisa aberta no navegador**. Sem
proteção, um site qualquer poderia `POST /acao` e disparar um WRITE na TR-8S.
O que fecha isso, tudo com a stdlib:

- **token de sessão** (`secrets.token_urlsafe`) entregue por `?t=` na abertura e
  guardado em cookie `SameSite=Strict; HttpOnly`; todo POST exige o header
  `X-TR8S-Token` (um `<form>` de outro site não emite header custom, e um
  `fetch` cross-site dispara preflight, que respondemos sem CORS);
- validação de **`Origin`** e de **`Host`** (esta fecha DNS rebinding);
- **CSP** `default-src 'none'` — só possível porque o CSS e o JS saíram do HTML
  para `web/`;
- limite de corpo, e `403` **com linha no log**: se aparecer, é informação.

Testável inteiro por `curl`, sem hardware: POST sem token → 403, com token e
motor desligado → 409 (erro legível, não silêncio), Origin forjada → 403, Host
forjado → 403, `..%2f` → 403, corpo de 300 KB → 413, `OPTIONS` sem nenhum
`Access-Control-Allow-*`.

Dois detalhes que custam tempo se esquecidos: o **`mimetypes` do Python 3.9 não
conhece `.mjs`** (sem registrar `text/javascript` o navegador recusa os módulos
e a página fica em branco), e o `_porta_livre()` antigo tratava **qualquer**
listener na porta como "sou eu mesmo" — agora o processo deixa
`~/.lp_tr8s_servidor.json` (0600) e a segunda instância confirma por `GET /ping`
antes de só reabrir a página.

### Armadilha de teste: aba em segundo plano não pinta

`requestAnimationFrame` não dispara em aba oculta, e o laço de estado cai para
2 s com `document.hidden`. Isso é o comportamento certo — mas escondeu um bug
real: **nada forçava um repaint ao voltar para a aba**, então a tela mostrava o
quadro velho por até 2 s. O `store` agora anota o render devido e o refaz no
`visibilitychange`. Vale para o diagnóstico também: automação de browser roda a
aba em background, então `document.hidden` é `true` e a tela parece morta — foi
preciso ativar o Chrome de verdade para validar a pintura.

**Duas armadilhas de macOS que custaram a primeira tentativa** (13/08/2026), ambas
invisíveis pelo Terminal e só reproduzíveis pelo Finder:

1. **TCC.** O bundle começou como um invólucro que chamava o `gui.py` lá em
   `~/Documents`. Pasta protegida: um `.app` sem assinatura **nem consegue pedir
   permissão**, leva `Operation not permitted` calado e não abre. Por isso os scripts
   foram para dentro do bundle — assim ele não sai de pasta nenhuma. O bundle também
   ganhou assinatura ad-hoc (`codesign --sign -`), que exige `xattr -cr` antes (o
   iCloud carimba o Desktop) e a marca de controle dentro de `Contents/`.
2. **Arquitetura.** O Finder lança app baseado em script como **x86_64**. O
   `/usr/bin/python3` é universal e obedece calado, mas o `rtmidi` instalado é arm64:
   `ImportError ... (have 'arm64', need 'x86_64')`. Do Terminal isso nunca aparece,
   porque o shell já é nativo. O lançador força `arch -arm64` quando
   `sysctl -n hw.optional.arm64` é 1.

Estado que não cabe no código, em `~/.lp_tr8s_layout.json` (geometria, do `learn`) e
`~/.lp_tr8s_estado.json` (last steps, mutes, níveis — espelho local, ver 5.3).
| `TR_Editor_eng04_W.pdf` | Manual do TR-EDITOR (8 p.) — a p. 8, de atalhos, é o mapa do que sniffar |
| `TR-8S_Reference_eng05_W.pdf` | Manual da máquina (56 p.) — p. 19–20 step edit, p. 17 pattern settings, p. 31 WRITE |
| `TR-8S_MIDIImpleChart_eng03_W.pdf` | Lista de CCs reconhecidos (seção 5.1) |
| `TR-8S_PresetToneList_eng04_W.pdf` | Tones; os 6 com `/` no nome têm som alternado |

Nenhum PDF abre com `pdftotext` (não instalado). Usar `fitz` (PyMuPDF), que já está
no ambiente: `python3 -c "import fitz; print(fitz.open(f)[0].get_text())"`.

Todos em Python 3.9 do Command Line Tools, com `mido` + `python-rtmidi` já
instalados em `~/Library/Python/3.9/`. **Não usar `--break-system-packages`** — o
pip é 21.2.4 e não suporta.

### apc_tr8s.py — mapeamento funcionando

| Controle | Função |
|---|---|
| pad | liga/desliga forte (vel 80) |
| SHIFT + pad | liga/desliga fraco (vel 50) |
| linha 5 (de baixo) | ACCENT |
| SCENE LAUNCH 1–5 | NORMAL / FLAM / SUB 1-2 / 1-3 / 1-4 |
| CLIP STOP 1–8 | variação A–H (recarrega o cache) |
| bank ▲▼ | rola os 11 instrumentos |
| bank ◀▶ | steps 1–8 ↔ 9–16 |

Comandos: `ports`, `learn`, `dump`, `test`, `run`.
O `learn` pede 3 pads e deduz a geometria — não hardcodar layout.
Layout salvo em `~/.apc_tr8s_layout.json`.

---

## 5. Launchpad Mini MK3 — notas técnicas

**Programmer mode** (necessário: LEDs controlados pelo host, notas previsíveis):

```
ligar:   F0 00 20 29 02 0D 0E 01 F7
desligar: F0 00 20 29 02 0D 0E 00 F7
```

Em programmer mode o endereçamento é `nota = linha*10 + coluna`, linha 1 = base,
coluna 1 = esquerda. Grid 8×8 = notas 11–88.

- Fileira de função (▲▼◀▶ Session Drums Keys User) = **CC 91–98**
- Coluna de cena (>) = **CC 89, 79, 69, 59, 49, 39, 29, 19** (topo → base)
- Logo = CC 99

LEDs: `note_on` canal 1 com velocity = índice da paleta. Botões CC: `control_change`
com value = índice. Paleta padrão Novation: 0=off, 1=cinza escuro, 3=branco,
5=vermelho, 7=vermelho escuro, 9=laranja, 11=laranja escuro, 13=amarelo, 45=azul.
O `lp_tr8s.py colors` acende a paleta inteira para escolher visualmente.

**Cada aparelho expõe duas portas:** `LPMiniMK3 DAW` e `LPMiniMK3 MIDI`. O
programmer mode responde na MIDI. O script manda o SysEx para todas as saídas
Launchpad e deixa o `learn` detectar qual porta recebe os pads.

Com dois aparelhos são **quatro portas de nome idêntico** — nome não identifica
aparelho. Endereçar por índice via rtmidi, nunca por nome (seção 7).

**Arranjo físico atual:** dois aparelhos lado a lado formando 16×8. O da **esquerda
está girado 90° anti-horário (270°)**, o da **direita em posição normal**. Efeito:
os botões de função e cena ficam nas bordas externas e no topo. O `learn` deduz a
rotação sozinho pelos deltas de nota — não hardcodar.

Geometria **confirmada pelo `learn` em 13/08/2026** — deduzida sozinha, sem hardcode:
- direito (normal): origem 81, +coluna +1, +linha −10
- esquerdo (90° CCW): origem 88, +coluna −10, +linha −1

A decodificação nota→(linha,coluna) do `run` é unívoca para as duas geometrias. O
caso delicado é o direito, onde `passo_col = 1` faz `resto % passo_col == 0` ser
sempre verdadeiro; funciona porque a checagem de faixa `0 <= col < 8` descarta os
candidatos errados. Não simplificar essa checagem sem refazer a conta.

**Grid:** 8 instrumentos, um por linha, **sem linha de ACCENT** por padrão
(`MOSTRAR_ACC = False`; o botão ACC alterna em execução). Rolagem de um instrumento
por vez, inclusive nas duas pontas: BD–CH, SD–OH, LT–CC, MT–RC.

**Toque no pad — compara estado, não alterna.** Com o seletor de velocity, o
liga/desliga binário não bastava: trocar o nível de um step existente exigiria dois
toques. A regra virou:

- apagado → liga com (velocity atual, modo atual)
- ligado com velocity **ou** modo diferentes → repinta com os atuais
- ligado e idêntico → desliga

Espelha o `[S]`/`[F]`+pad do TR-EDITOR, que aplica o tipo a um step já existente.

**Os 32 botões** — desenho em `layout.html`. Ordem derivada da rotação, não
hardcodada; confira com `probe` se algo não bater.

| Grupo | Posição física | Função |
|---|---|---|
| cena do esquerdo | topo esquerdo, esq→dir `89…19` | variações A–H |
| função do esquerdo | borda esquerda, cima→baixo `98…91` | FILL 1, FILL 2, CLEAR inst, CLEAR variação, **HIDE MUTED**, **ALT**, copiar, colar |
| função do direito | topo direito, esq→dir `91…98` | INST UP, INST DN, NORMAL, FLAM, SUB 1/2, 1/3, 1/4, ACCENT |
| cena do direito | borda direita, cima→baixo `89…19` | velocity 127, 110, 100, **80**, 60, **50**, 30, 10 |
| logos (`CC 99`) | cantos | **não são botões** — só LED, ver abaixo. No adesivo levam etiqueta branca: `VAR ▸` no esquerdo, `VELOCITY ▾` no direito |

> **Os logos não têm chave embaixo** (visto no hardware, 13/08/2026). Eles têm LED
> endereçável em `CC 99`, mas **nunca enviam nada**. HIDE e WRITE tinham sido postos
> ali, o que os deixava inalcançáveis. Foram para as **setas do aparelho esquerdo**
> (`CC 94` = HIDE e `93` = WRITE), que eram a única função **duplicada** do mapa — as do direito
> fazem exatamente o mesmo. Custo: rolagem de linha agora só no aparelho direito.
> O logo esquerdo virou indicador passivo: acende quando há linha escondida.

No modo `off`, **HIDE MUTED + ALT juntos** (os dois vizinhos do meio da borda
esquerda) voltam para o `ON`. São dois porque um só dispararia sem querer justamente
no modo em que se fica cutucando os pads.

São **32 botões**, não 34. O **SHIFT deixou de existir** — a borda direita substituiu o toggle forte/fraco por
oito níveis. `CLEAR instrumento` arma e o próximo pad limpa aquela linha; `CLEAR
variação` exige segundo toque em 2 s. `COPY` usa o cache como fonte, que é
autoritativo porque toda escrita do script passa por ele.

**Rajadas de escrita** (CLEAR variação = 176 DT1, COPY idem) vão em blocos de 8
bytes, um step por vez, com `sleep(0.002)` entre mensagens. Escrever 128 bytes num
único DT1 **nunca foi testado** — não arriscar sem capturar antes.

**Decisão 13/08/2026 sobre a borda direita:** manter os 8 níveis de velocity. A
dúvida era se a TR-8S seria degrau (forte/fraco); o Reference p. 19–20 mostra que
não — ver 2.4. Reavaliar depois da captura, quando houver candidatos concretos: um
toggle **FRACO** (que junto com os 5 modos dá as seis variantes usando um botão só,
em vez de três), **ALT INST**, **track TRG**, e os toggles por CC da seção 5.1.

**A paleta do adesivo — um grupo, uma cor.** A primeira versão reaproveitava três
acentos (teal/roxo/laranja) e acabava com dois grupos diferentes vestindo a mesma
cor: variações e fills no teal, modos e velocity no roxo. Corrigido em 13/08 para:

| Cor | Grupo |
|---|---|
| teal | variações A–H |
| verde | FILL 1 / FILL 2 |
| verde claro | ACCENT (texto escuro — o claro não contrasta com branco) |
| preto | rolagem de instrumento |
| roxo | tipo do step: NORMAL, FLAM, SUB |
| azul | velocity, **azul escuro** nos dois que a máquina usa |
| laranja | edições em lote: CLEAR, COPY, PASTE, HIDE |
| cinza | WRITE, ainda sem função |

A cor do texto é escolhida por luminância, não à mão — senão o próximo ajuste de
paleta esqueceria o contraste. Setas são **triângulos vetoriais**, porque a fonte
base do PDF usa WinAnsiEncoding e não tem nenhuma seta; embutir uma fonte inteira
por um glifo não se paga.

**A paleta do LED não é a mesma, e não dá para ser.** O adesivo é rótulo fixo; o LED
mostra *estado*. Preto não existe como LED aceso, e o nível selecionado precisa do
branco. Na coluna de velocity o LED usa vermelho/vermelho-escuro nos dois canônicos
— a mesma cor que a nota deles vai ter no grid — e cinza no resto.

**Os dois níveis canônicos de velocity.** O ciclo do pad da própria TR-8S é
**`strong → weak → off`** (Reference p. 45), e esses dois estados são **80 e 50** —
três fontes independentes batem: o SysEx capturado do TR-EDITOR (`05 00` = 80,
`03 02` = 50), o manual do editor p. 8 ("*velocity value of 50*" no atalho de weak
beat), e o ciclo do painel. Na coluna de velocity eles acendem na **mesma cor que a
nota deles vai ter no grid** (vermelho e vermelho escuro) e os outros seis ficam
cinza — esses seis só existem porque a máquina aceita velocity contínua, que é
exatamente o que o grid destrava (ver 2.4).

**Playhead por linha, não por coluna.** Um track mais curto que a variação roda no
**próprio comprimento**: com o BD em 10 numa variação de 16, no step 11 ele já voltou
ao 1 enquanto os outros seguem no 11 — e a coluna verde deixa de ser uma coluna.
Observado na máquina em 13/08/2026; o manual não diz isso em lugar nenhum.

Quando há alguma linha curta, o step repinta o **quadro inteiro** em vez das duas
colunas de sempre. Não sai caro: o quadro vai em dois SysEx em lote, o que a 120 bpm
dá 16 mensagens por segundo.

**É free-run**, testado na máquina em 13/08/2026: quando a variação dá a volta, o
track curto **continua de onde parou** — a fase anda e o padrão só fecha depois de
vários compassos. Só o **stop/start** zera tudo de volta ao step 1. É o que o código
faz: `TRACK_REINICIA_NA_VARIACAO = False`, e o `start` zera `pulsos` e `passo_abs`.

No `stop` o quadro inteiro é repintado, não a coluna do playhead. Com track curto
cada linha está numa coluna diferente, e limpar só uma deixaria o verde preso nas
outras — bug encontrado justamente por causa da observação do stop/start.

**Playhead:** implementado contando MIDI clock da porta `TR-8S` comum (não a CTRL).
24 pulsos por semínima ÷ 4 = **6 pulsos por step**. `start` zera, `stop` apaga — e
desde 14/08 ele também **entra em fase com a máquina já tocando**, e se corrige
sozinho a cada 1,5 s, pelo byte de step da seção 2.8.
Repinta só as duas colunas afetadas (16 mensagens/step, não 128). **Desde 13/08 dá a
volta no last step da variação**, o que conserta a dessincronização em pattern curto;
**Desde 17/08 lê a SCALE do pattern** (nó `0x16`) e usa os pulsos por step dela —
antes assumia semicolcheia sempre, e um pattern em `32nd` andava em metade da
velocidade da máquina.

**Cores fora da paleta.** A paleta indexada não chega ao escuro que os steps fora do
LAST STEP e as notas mutadas precisam. Para essas, o SysEx de LED em RGB:

```
F0 00 20 29 02 0D 03  <spec> [<spec> ...]  F7
spec estatico = 00 <nota> <indice>     spec RGB = 03 <nota> <r> <g> <b>   (0-127)
```

Vários specs cabem numa mensagem só, de tipos misturados — o que a ondinha do modo
`off` usa para mandar o quadro inteiro numa mensagem em vez de 128. No código,
**cor `int` = paleta, cor tupla = RGB**, e o `enviar_cor`/`enviar_cores` despacha.

---

## 5.1 Control Change: uma segunda superfície, sem SysEx

A implementation chart (`TR-8S_MIDIImpleChart_eng03_W.pdf`) mostra que a TR-8S
**reconhece** uma lista grande de CCs — não só transmite. Vão pela porta `TR-8S`
comum, não pela CTRL, e não precisam de SysEx nenhum.

> **Corrigido em 13/08/2026 — a tabela anterior estava deslocada em uma linha.**
> A chart tem 55 linhas de CC para 55 remarks, em correspondência direta. A prova
> está nos agrupamentos: a leitura certa dá `BD 20/23/24`, `SD 25/28/29`,
> `LT 46/47/48` e fecha os `CTRL` em exatamente 11 (`96, 97, 102…110`); a leitura
> deslocada partiria o SD em `28/29/46` e sobraria uma linha nos CTRL.

| CC | Função | Serve como |
|---|---|---|
| `9` | SHUFFLE | contínuo |
| `12` | EXTERNAL IN LEVEL | contínuo |
| `14` | AUTO FILL IN [ON] | **só transmitido** |
| `15` | MASTER FX [ON] | **toggle — bom para botão** |
| `16`–`18` | DELAY LEVEL / TIME / FEEDBACK | contínuo |
| `19` | MASTER FX CTRL | contínuo |
| `70` | AUTO FILL IN [MANUAL TRIG] | **só transmitido** |
| `71` | **ACCENT** (o nível) | contínuo |
| `91` | REVERB LEVEL | contínuo |

Por instrumento, TUNE / DECAY / LEVEL, todos reconhecidos:

| | BD | SD | LT | MT | HT | RS | HC | CH | OH | CC | RC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TUNE  | 20 | 25 | 46 | 49 | 52 | 55 | 58 | 61 | 80 | 83 | 86 |
| DECAY | 23 | 28 | 47 | 50 | 53 | 56 | 59 | 62 | 81 | 84 | 87 |
| LEVEL | 24 | 29 | 48 | 51 | 54 | 57 | 60 | 63 | 82 | 85 | 88 |

E os CTRL: BD `96`, SD `97`, LT–RC `102`–`110`.

**Os dois botões de AUTO FILL IN são transmit-only** — a máquina não os aceita por
CC. Isso derruba o AUTO FILL IN como candidato a botão de borda, que a versão
anterior desta seção listava. O único toggle realmente acionável é o MASTER FX (`15`).

**Os LEVEL não funcionam.** Foram a base de uma tentativa de mute que falhou —
testado e descartado em 13/08/2026. Ver 5.3.

> **A chart marca `System Exclusive: x / x` — e mesmo assim tudo na seção 2
> funciona.** Ou seja, a implementation chart da Roland **não é evidência de
> ausência de SysEx**. Isso derruba o principal argumento contra a TR-1000 na seção
> 8, que estava justamente baseado na chart dela marcar SysEx ✗.

## 5.2 Gestos do painel que o grid pode substituir

Colhidos do `TR-8S_Reference_eng05_W.pdf`, todos incômodos no painel:

| Função | No painel | Onde estamos |
|---|---|---|
| WEAK BEAT | `SHIFT` + pad (p. 19) | temos, via seletor de velocity |
| velocity fina por step | segurar pad + girar ACCENT LEVEL (p. 19) | temos |
| FLAM | `SHIFT` + `[SUB]`, depois pad (p. 19) | temos |
| SUB 1/2, 1/3, 1/4 | `[SUB]` + girar VALUE (p. 19) | temos |
| **ALT INST** | segurar instrument select + pad (p. 19) | **decodificado** (2.4); falta o botão |
| **track TRG** | segurar `[CC]` + `[RC]` (p. 19) | falta — sniffar |
| **PROB / SUB PROB** | long-press pad + `[COPY]`/`[UTILITY]` + VALUE (p. 20) | falta — sniffar |
| CLEAR de um track | segurar instrument select + `[CLEAR]` (p. 19) | temos |
| WRITE do pattern | segurar `[WRITE]` + `[PTN SELECT]` (p. 31) | falta — sniffar |

**ALT INST só existe nos tones com `/` no nome. São 20, não 6** — a contagem
anterior desta seção estava errada, e o erro importava: seis tones quase todos de
bumbo e caixa fazem o ALT parecer um caso de canto, e vinte cobrindo percussão
inteira fazem dele um recurso de verdade. Recontados no PresetToneList em
14/08/2026:

```
707 Bass1/2        707 Bass2/1       707 Snare1/2      707 Snare2/1
707 Rim Shot/CB    CR78 Rim Shot/CL  707 Hand Clap/TB  707 Cowbell/RS
707Tambourine/HC   CR78 Claves/RS    CR78 Tamb 1/2     CR78 Guiro 1/2
727 HighBongo/LB   727 LowBongo/HB   727MtHiConga/OHC  727OpHiConga/…
727 Cabasa/MA      727 Maracas/CA    727 HighAgogo/LA  727 Low Agogo/HA
```

Um botão de ALT só faz sentido se o instrumento tiver um desses carregado — o que
com vinte opções é bem mais provável do que parecia.

Parâmetros de pattern ainda não localizados no mapa de endereços (Reference p. 17):
Scale (`8th(T)`, `16th(T)`, `16th`, `32nd`), Shuffle (−128…+127), Flam Spacing (0–8),
ScatterType/Depth (1–10), MstrProb (−100…+100%), Tempo (40–300).

## 5.3 MUTE, LAST STEP e os modos (atualizado em 14/08/2026)

**O grid lê o mute da TR-8S e esconde as linhas mutadas.** O endereço está em 2.7.
Mutar continua sendo gesto de painel (`[MUTE]` + instrumento) **por escolha, não por
limitação**: a escrita funciona e está implementada (`definir_mudos`), mas o botão do
launchpad não muta — o painel está ali do lado e faz melhor.

O `CC 94` da borda esquerda virou **ESCONDER MUTADOS**, um toggle:

| esconder_mudos | o grid mostra |
|---|---|
| desligado (padrão) | os 11, com a linha mutada em cor própria |
| ligado | só as não mutadas; as de baixo sobem |

Com **LT, MT e HT mutados sobram 8 instrumentos, que é exatamente a altura do grid** —
o scroll deixa de existir. Ninguém fica preso: o que sumiu volta pelo mesmo botão, e
desmutar é no painel de qualquer jeito.

### A paleta espelha o painel da TR-8S (14/08/2026)

Ideia do Luan, olhando os dois aparelhos lado a lado: a máquina já pinta cada tipo de
step com uma cor, e o grid usava outras por acaso histórico. Espelhar tira uma tradução
mental de quem opera os dois.

| conteúdo | na TR-8S | no grid |
|---|---|---|
| nota | vermelho | vermelho |
| **flam** | **lilás** | roxo |
| **sub step** 1/2, 1/3, 1/4 | **amarelo** | amarelo |
| **ALT** | **rosa** | rosa |
| ACCENT | — | azul vívido |
| **linha mutada** | (some do painel) | **cinza-azulado dessaturado** |

Cada família tem par claro/escuro pelo mesmo `VEL_LIMIAR` que separa forte de fraca no
resto do grid.

**Flam e sub eram a mesma cor, e não deviam ser.** Os dois moram no byte 5 (`1` = flam,
`2`–`4` = sub), e o código tratava "byte 5 ≠ 0" como uma coisa só — laranja para ambos.
São gestos diferentes na máquina, com cores diferentes lá.

**A linha mutada perdeu o matiz de propósito.** A primeira versão trocava de família
(roxo para nota, azul para flam) e funcionava — até as famílias acabarem. Com nota, flam,
sub e ALT espelhando a máquina, não sobrou matiz. Dessaturar acabou sendo melhor que
inventar um quinto: uma linha muda não está fazendo som nenhum, e **ausência de cor diz
isso melhor do que qualquer cor nova diria**. São dois tons só, sem distinguir flam de
sub: numa linha que não soa, o tipo do som que ela não está fazendo é detalhe.

O **playhead não aparece** na linha mutada, e a cabeça de tempo também não. O verde diz
"está soando agora"; numa linha muda ele seria a única coisa na tela mentindo sobre o som.

**Precedência**, em `cor_base()`: mute > ALT > flam/sub > nota. O ALT vem antes do flam
porque troca o *tom* que vai tocar, enquanto flam e sub só mudam como ele é disparado.

`lista_visivel()` e `inst_da_linha()` continuam sendo o único caminho de linha →
instrumento; `base_inst` re-clampa sozinho toda vez que a lista muda de tamanho.

### O caminho errado que precedeu isso

A primeira versão tentava silenciar mandando `LEVEL 0` no CC do instrumento. **Não
funciona, testado em 13/08/2026:** com a máquina tocando, `USBMidiThru` ON e canal 10,
a caixa não silenciou. A explicação mais provável é do Luan: **o LEVEL é um fader
físico**, e um CC não move fader.

Aquele fracasso gerou o HIDE — um filtro de visão que não silenciava — e o rename de
MUTE para HIDE da seção 10. **Ambos partiam de uma generalização indevida:** o CC de
LEVEL não silenciar virou "não dá para silenciar por software". O mute estava em
`01 00 00 00` o tempo todo, e a busca de 13/08 não o encontrou porque procurou onde
o `snap` olhava — pattern e kit — e ele é estado de sistema.

O "KIT: MUTE" da p. 29 continua sendo outra coisa: é *mute group* (qual instrumento
abafa qual).

**LAST STEP.** São dois (Reference p. 11–12): o **da variação** e o **do track**,
sendo que o do track é compartilhado entre A–H e **tem prioridade**. O grid escurece
o que passa de `min(variação, track)` com um cinza quase preto via SysEx RGB, e o
playhead passou a dar a volta no last step da variação — era a causa da
dessincronização que a seção 5 documentava.

**Desde 13/08 o grid lê os valores reais da máquina** (2.3.1) e escreve neles: mexer
no `[LAST]` do painel chega ao grid no próximo `recarregar()`, e mexer na janela do
app chega à máquina na hora. O `~/.lp_tr8s_estado.json` virou só fallback para quando
a leitura falha, e para os dois Fill In, cujo slot ainda não foi localizado.

**Onde o LAST STEP deve estar.** O diagrama da p. 8 do Reference explica a
aritmética: instrumento `I` começa no offset `I*128+8`, o que dá `11*128+8 = 1416 =
20 0V 0B 08` e **confirma o TRG** que a seção 2.3 listava como palpite. Os offsets
0–7 são um **cabeçalho da variação** — bytes 0–3 são a máscara de ACCENT, e os
**bytes 4–7 estão livres**, candidatos diretos ao last step da variação, scale e
shuffle. O do track, por ser compartilhado entre A–H, não pode estar em `20 0V`;
o palpite é `20 00`, que a varredura do `snap` agora lê.

**Três modos gerais**, exclusivos:

| Modo | LEDs | Pads | Precisa da TR-8S |
|---|---|---|---|
| `ON` | o grid | escrevem no pattern | sim |
| `off` | apagados, ondinha ao toque | só a ondinha | **não** |
| `standby` | ondas nascendo sozinhas | somam uma onda | **não** |

O `off` **não** é o `launchpad_blackout`: apaga mas continua ouvindo os pads. Para
soltar os aparelhos de verdade, o botão "Apagar e soltar os pads" ou o alias.
Fora do `ON`, **HIDE MUTED + ALT apertados juntos voltam para o ON** (`ESCAPE_CHORD`,
CC 94 e 93 da borda esquerda) — senão não haveria como voltar sem ir até o Mac. É o que
o adesivo já imprime; a linha antiga desta seção dizia "HIDE + WRITE", nome que ficou
para trás quando o CC 93 virou ALT.

### O `standby` (14/08/2026)

É a ondinha do `off` sem precisar de dedo: um semeador cria ondas em posição e cor
aleatórias, no ritmo do estilo escolhido. **Não entra sozinho** — decisão do Luan, para
que o `ON` nunca caísse em standby no meio de um set. Só o botão da janela ou
`python3 lp_tr8s.py standby [ambiente]`, que nem abre a porta da TR-8S.

Dois estilos, que são o **mesmo modo com outra tabela de números** (`STANDBY_ESTILOS`):

| | `chuva` | `ambiente` |
|---|---|---|
| onda a cada | 0,35–1,1 s | 2,5–5 s |
| velocidade | 6–13 células/s | 1,6–3,2 |
| espessura | 1,4–3,0 | 3,5–6,0 |
| alcance | 9–17 | 14–20 |
| brilho | cheio | 45% |
| quadros/s | 30 | 15 |

O que mudou no código para isso caber: **cada onda passou a carregar os próprios
parâmetros** (`vel`, `larg`, `alc`) no dicionário, em vez de todas lerem as constantes
`ONDA_*`. O toque no modo `off` continua criando a onda **sem estilo**, isto é, com
exatamente os valores fixos de antes — o comportamento já exercitado em hardware não
mudou. O render (`_animar`) não sabe que estilos existem; ele só lê o que a onda traz.

O `_animar` agora também guarda o quadro em `self.quadro_onda`, e o `estado()` devolve
isso no lugar de `pads` quando está fora do `ON`: a seção "Grid 16×8" da janela mostra a
mesma animação dos LEDs, de graça, sem recalcular nada.

Isto **não** é o modo `coração` (que desenhava `C E`/`C I` e um coração, e foi removido a
pedido em 13/08/2026 — não reintroduzir): aquele era figura fixa, este é procedural e não
desenha nada.

## 6. Configurações da TR-8S

- `UTILITY → MIDI → USBMidiThru` = **OFF**, senão o MIDI USB do Ableton vaza na
  cadeia DIN e dispara notas nos synths downstream.
- Fantasma de notas na cadeia: reativar ECHO DIN IN no Sub 37 (`[MIDI] → 2.3`),
  USBMidiThru off na TR-8S, e Instrument Note = `---` nos 11 instrumentos.
  **Atenção:** com Inst Note em OFF a TR-8S também não *recebe* notas. Para o modo
  sequenciador externo, manter as notas ligadas e usar canais diferentes nos synths.

---

## 7. Enumeração de portas — RESOLVIDO em 13/08/2026

O sintoma era `mido.get_input_names()` retornar só um par de portas Launchpad em
vez de quatro. **Não era hub, nem cabo, nem CoreMIDI** — o hub está inocente e os
quatro endpoints sempre existiram. Era o mido. Não foi preciso abrir o MIDI Studio:
`rtmidi` cru já é fonte da verdade suficiente.

```python
import rtmidi
m = rtmidi.MidiIn(); [ (i, m.get_port_name(i)) for i in range(m.get_port_count()) ]
```

rtmidi enumera 7 entradas (os dois aparelhos inteiros); o mido devolve 5. **Dois
bugs distintos** em `mido/backends/rtmidi.py`:

- `get_devices()` (~linha 61): `if name not in devices` — deduplica por nome, então
  `get_input_names()` esconde as duplicatas.
- `_open_port()` (~linha 100): `port_names.index(name)` — casa sempre a **primeira**
  ocorrência. Ou seja, mesmo sabendo que existem dois, abrir por nome nunca alcança
  o segundo aparelho: as duas portas DAW abririam a mesma unidade física.

**Correção aplicada no `lp_tr8s.py`:** toda enumeração e abertura de porta passou a
usar rtmidi cru por **índice** (`listar_portas`, `achar_portas`, `EntradaMIDI`,
`SaidaMIDI`). O mido ficou só para montar e parsear mensagens.

Armadilha ao escrever o wrapper: replicar `ignore_types(False, False, True)` —
sysex e timing **não** ignorados. Sem isso o SysEx da TR-8S nunca responde e o
playhead não conta clock.

Três consequências que o patch teve de resolver:

1. **Identidade.** Nomes idênticos não permitem parear entrada→saída por string. O
   `learn` pareia por posição ordinal entre as portas Launchpad e **confirma
   acendendo o grid** ("o esquerdo acendeu de azul? s/n"), porque a ordem do
   CoreMIDI não é garantida.
2. **Índices são voláteis** (replug, reboot, outro aparelho ligado). O layout salvo
   guarda um snapshot da enumeração; se mudar, `carregar_layout` recusa e manda
   rodar `learn` de novo em vez de escrever no aparelho errado.
   **Revisado em 16/08/2026 — a recusa era grosseira demais, ver 7.3.**
3. Bug no `learn` antigo: ao detectar pad do aparelho errado, o `continue` pulava o
   pedido em vez de repeti-lo e `notas` terminava curta → `IndexError`. Virou retry.

**Verificado com hardware em 13/08/2026:** as 4 entradas abrem simultaneamente; o
`dump` leu o pattern inteiro pelo wrapper novo; e acendendo cada saída de uma cor
os **dois aparelhos responderam independentemente**. Mapa observado naquele boot —
o aparelho enumerado primeiro é o da **direita**:

| Índice out | Aparelho |
|---|---|
| `[4]` (MIDI da 1ª dupla) | direito |
| `[6]` (MIDI da 2ª dupla) | esquerdo (girado 270°) |

Não hardcodar essa tabela — vale só para aquela enumeração. É o `learn` que amarra
índice → aparelho, e o snapshot que detecta quando a amarração venceu.

### 7.3 A guarda de portas recusava demais — corrigido em 16/08/2026

**Sintoma: "o app não conecta".** `/estado` devolvia `"ligado": false` e o log
repetia *"As portas MIDI mudaram desde o 'learn' (replug?). Aperte Recalibrar"*
— com TR-8S, clock e os dois Launchpad todos presentes e enumerados.

**Causa.** O `learn` de 13/08 01:01 rodou com a **Scarlett 18i8 USB** no índice
0. Com ela desligada, tudo andou −1 e os índices salvos (6 e 4) deixaram de
existir. A guarda comparava a **lista inteira** de nomes de porta por
igualdade, em três cópias (`lp_tr8s.py`, `servidor.py`, `gui.py`), então
qualquer aparelho MIDI a mais ou a menos — interface de áudio, IAC Driver, um
teclado, o Ableton criando portas virtuais — invalidava uma calibração boa.

**A mensagem levava à ação errada, e isso é o pior da história.** "Aperte
Recalibrar" refaria o `learn` *sem* a Scarlett; ao religá-la, quebraria de
novo, no sentido inverso. Ciclo vicioso. A ação certa era "ligue a Scarlett", e
o app não tinha como dizer isso.

**Correção.** Uma função só (`resolver_layout`, reusada pelos três) que casa
por **nome + ordinal dentro do grupo Launchpad**, não por índice global. O
grupo Launchpad precisa estar idêntico (mesmo tamanho, mesma sequência de
nomes) para os ordinais valerem; fora do grupo, entra e sai à vontade. A
decisão é **atômica** — se um lado não resolve, recusa os dois, porque meio
grid escrevendo no aparelho errado é pior que grid nenhum. O `learn` passou a
gravar `in_ord`/`out_ord`; layouts antigos migram derivando o ordinal do
snapshot já salvo.

Sete enumerações verificadas de mesa (`testes.py`, `TesteGuardaDePortas`):

| cenário | antes | agora |
|---|---|---|
| Scarlett ligada (= o do `learn`) | aceita | aceita |
| **Scarlett desligada** | **recusa** | **aceita, reresolve 6→5 e 4→3** |
| IAC Driver a mais | recusa | aceita |
| TR-8S também desligada | recusa | aceita |
| um Launchpad só | recusa | **recusa** (grupo 4→2) |
| três Launchpad | recusa | **recusa** (grupo 4→6) |
| Launchpad em ordem trocada | recusa | **recusa** (ordem mudou) |

**Limite honesto, inalterado:** os dois Mini MK3 têm nome idêntico, então o
ordinal é a única forma de distingui-los sem `learn`. Se o CoreMIDI trocar os
dois entre si, isto aceita e o grid sai espelhado — a guarda antiga também não
pegava esse caso (a lista de nomes ficaria idêntica), e a única prova continua
sendo o olho, que é por que o `learn` confirma acendendo o aparelho.

### 7.4 O nó `20 xx` é MUDO na leitura — medido em 16/08/2026, 12:56

Este é o achado que fecha o "grid não espelha o que toca", e ele **derruba** a
hipótese que estava aberta desde 15/08.

**O caso, com gabarito.** O Luan pôs a máquina no **pattern 3-06, variação A**, e
leu no painel: **BD só no step 1**, **last step da variação = 12**. O app, no
mesmo instante:

| | máquina (painel) | app (SysEx) |
|---|---|---|
| número do pattern (`01 00 00 01`) | 3-06 | **37 = 3-06** ✔ |
| kit (`01 00 00 00`) | Simple Trap | **Simple Trap** ✔ |
| BD ligados (`20 01 00 08`) | `[1]` | `[5, 13]` �’ |
| last step da var A (`20 00 00 00`+67) | 12 | `16` ✗ |
| nome do pattern (`20 00 00 00`+0..15) | — | `'----'` |

Repare que o app leu um step **13**, que nem existe numa variação que termina no
12. Não é leitura corrompida: é outro pattern.

**O teste que derrubou a hipótese antiga.** Se fosse "o buffer ficou no pattern
antigo", trocar de pattern deveria mexer nele. Não mexe — nem pelo painel, nem
remotamente:

```
estado inicial (troca feita no painel)  BD=[5,13]  last=16  nome='----'
troca remota para 1-01 (n=0)            BD=[5,13]  last=16  nome='----'
volta remota para 3-06 (n=37)           BD=[5,13]  last=16  nome='----'
```

E os dois ressincronizadores previstos no roteiro **falharam**, confirmando a
desconfiança que já estava anotada:

| tentativa | resultado |
|---|---|
| `01 00 00 01` = n (o resync especulativo que já estava no motor) | não resolveu |
| `01 00 00 02` = n | não resolveu |

**Conclusão.** O nó `20 xx` **não é uma janela para o pattern corrente**. Ele é um
buffer que, na leitura, devolve sempre o mesmo conteúdo, independente do que a
máquina carregou ou toca. Enquanto isso o bloco de performance (`01 xx`) está
**correto e atualizado** — número do pattern e kit acompanham as trocas.

**Mas a ESCRITA nele funciona** — é o que acontece quando se clica num step do
grid e a máquina muda. Ou seja: **escrita vai para o pattern ativo, leitura vem
de outro lugar.** É essa assimetria que explica todo o sintoma.

> O que o Luan descrevia como *"tenho que apertar no grid pra sincronizar"* não
> era sincronização: era ele **copiando à mão** para o app o que via na TR-8S. O
> grid está cego para o conteúdo real.

**RISCO DE PERDA DE DADOS, e a proteção que entrou.** `escrever_step` manda o
step de 8 bytes **inteiro**, e os bytes 0–3 (velocity, sub step, probability)
saem do cache. Com o cache de outro pattern, cada clique gravava valores alheios
por cima do pattern real. Entrou o guarda `Motor._conferir_espelho`: quatro
correções grandes de playhead numa janela de 60 s denunciam que o last step
daqui não é o de lá, e a **escrita é bloqueada** com aviso na tela. Medido no
aparelho: com o espelho errado saem ~5 correções por minuto, sem parar; com ele
certo, o resync mal dispara. O detector subiu em 30 s no caso real.

### 7.7 A TR-8S EMPURRA estado sozinha — medido em 16/08/2026

**Isto corrige a seção 3 (método 2), que diz que a máquina é muda.** Ela é muda
para *gestos de painel* (mexer num knob não sai). Mas ela **transmite DT1
espontâneo** — sem RQ1, sem ninguém pedir — para uma porção da região de
performance.

Medido com o **TR-EDITOR fechado**, escuta passiva de 20 s na porta CTRL:

| endereço | o que é | frequência |
|---|---|---|
| `01 00 00 07` | **step atual** | **8,6 por segundo** |
| `01 00 00 09` | ? (valor 0 constante no teste) | 0,75/s |
| `01 00 00 01` | **pattern atual** | na troca |
| `01 00 00 00` | kit / pattern / próximo | na troca |
| `01 00 00 02`, `1B`, `39`, `40`, `08` | ainda não decodificados | na troca |

Na captura de 36 mil mensagens foram **3.635 espontâneas**, 3.199 delas o step.

**A sequência do step vem limpa**, com last step 12:

```
9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2, ...
```

Sem repetição, sem salto, e já no módulo certo da variação.

**O que isso vale.** Hoje o playhead é derivado da contagem de pulsos de clock,
com um ressincronizador que compara com uma leitura pedida — foi de onde saíram
o congelamento da variação, a deriva e o "playhead maluco" desta sessão. Com o
push, o step vem **pronto e exato**, sem contar nada e sem pedir nada. A troca de
pattern também chega na hora, em vez de esperar a releitura periódica.

Isso não foi implementado ainda: fica como o caminho natural do playhead e da
detecção de troca de pattern. Cuidado ao adotar: a leitura passa a ter **duas
origens** (push e resposta a RQ1) na mesma porta, e o `ler_bloco` atual casa
resposta por endereço — um DT1 espontâneo do mesmo endereço que se está pedindo
pode ser confundido com a resposta.

### 7.6 O playhead maluco era da TELA, não do motor (16/08/2026)

Sintoma: a coluna verde invadia o **step 13** numa variação de 12 steps, e ao
voltar caía no **2** em vez do 1.

Custou três rodadas de medição no motor — todas dando limpo, porque o motor
sempre mandou `passo` entre 0 e 11. O erro estava no **relógio local da tela**
(`web/js/comp/grade-steps.mjs`): a página pede estado a cada 250 ms, mas um step
a 86 bpm dura 174 ms, então ela mede a duração do step e **avança sozinha** entre
as respostas. Esse relógio ciclava em `% 16` fixo:

```js
const prox = (passoReal + 1) % 16;   // <- 16 fixo
```

Com last step 12, ele adivinhava o step 13; e quando o servidor confirmava o
step 1, o timer já tinha disparado o seguinte e mostrava o 2. Agora o ciclo vem
de `e.last_var`.

**Dois lugares, o mesmo engano.** A moldura da janela dos Launchpads tinha o
mesmo 16 fixo e avançava sobre os steps 13–16, que estão fora do pattern. São
bugs distintos que produziam a mesma queixa.

**Lição de método, que vale mais que o conserto:** o grid tem *duas* fontes de
verdade sobre o tempo — o motor e o relógio de interpolação da tela. Medir só o
motor e concluir "está limpo" foi medir o lado errado três vezes seguidas.
Quando o sintoma é visual e o backend mede limpo, o próximo lugar a olhar é o
que a tela faz **entre** dois quadros.

### 7.5b RESOLVIDO de vez — `24 5x` era o pattern 3-06, e a regra é geral

**A seção 7.5 abaixo está certa no que mediu e errada no que generalizou** — não
deve ser lida sozinha. Ela provou que o TR-EDITOR lê e escreve em `24 5x` e que
aquele conteúdo bate byte a byte com o painel. O que não podia concluir é que
`24 5x` fosse *o* endereço do pattern: era o endereço **daquele** pattern.

**O segundo byte vale `pattern × 16 + variação`**, com carry de 7 bits para o
primeiro. A captura sempre disse isso, bastava ler o começo dela: antes de ir a
`24 5x`, o editor perguntou `01 00 00 01` — *qual é o pattern atual* — e recebeu
o número. O 3-06 é o índice 37, e `37 × 16 + 1 = 593 = 4 × 128 + 81`, ou seja
byte 0 = `0x20 + 4` e byte 1 = `0x51`. Exatamente o `24 51` observado.

Confirmado lendo quatro patterns na máquina, incluindo os que transbordam:

| pattern | BD da variação A | nome |
|---|---|---|
| 0 (1-01) | `20 01 00 08` | `----` |
| 4 (1-05) | `20 41 00 08` | `SambaWork` |
| 43 (3-12) | `25 31 00 08` | `Loafing` |
| 127 (8-16) | `2F 71 00 08` | `----` |

E verificado em hardware pelo Luan com o gesto do relato original: **trocar de
pattern no painel passa a mudar o grid**.

Com isso caem, de uma vez, as três coisas que a 7.5b anterior listava como
mistério: não existe "buffer de edição" que precise ser carregado, não existe
gatilho a descobrir, e o GET do TR-EDITOR não é um comando — ele é só uma
leitura no endereço certo. Os sete estímulos testados contra a hipótese do
buffer (troca pelo painel, troca remota, `01 00 00 01`, `01 00 00 02`,
keep-alives, TR-REC, `[UTILITY]`+`[PTN SELECT]`) deram todos negativo porque
não havia nada para ressincronizar.

**A lição de método**, que vale mais que o achado: uma pilha de negativos
consistentes pareceu confirmar a hipótese quando só dizia que ela era
irrelevante. O que destravou não foi mais um teste na mesma direção — foi ler o
que o programa que funciona faz, na captura que já estava em disco.

**Armadilha para quem for mexer nisto:** todo endereço da região depende do
pattern carregado, então qualquer ferramenta que monte endereço sem perguntar
`01 00 00 01` observa um pattern que não é o que está tocando. Foi assim que o
`snap`, o `tempo_watch`, o `var_mask` e a máscara de variação do Chain ficaram
ancorados no 1-01 — e a saída do `snap` é o que vira fato neste documento.
Dois snapshots de patterns diferentes agora são **recusados** pelo `snapdiff`,
porque o silêncio deles parecia "nada mudou".

### 7.5 A captura que achou a região (16/08/2026) — leia a 7.5b antes

*Registro do que a captura mostrou. A generalização correta está na 7.5b
acima: `24 5x` é o pattern 3-06, não o endereço fixo do pattern.*

A captura do GET do TR-EDITOR foi feita, e o achado **não é um comando**: o
editor não manda nada para "carregar" buffer nenhum. Ele simplesmente **lê outra
região**, que este projeto nunca tinha visto.

**A tradução é mecânica** — `0x20` → `0x24`, e o segundo byte somado de `0x50`:

| o que é | como líamos (errado) | onde de fato mora |
|---|---|---|
| cabeçalho do pattern | `20 00 00 00` (128 B) | `24 50 00 00` (**193 B**) |
| variação V, instrumento ii | `20 0V ii 08` | `24 5V ii 08` |
| accent da variação V | `20 0V 00 00` | `24 5V 00 00` |
| step s | `+ s*8` | igual |

`24 51`…`24 5A` são as **10 variações** (A–H + os dois Fill In), espelhando
`20 01`…`20 0A`.

**Conferido contra o painel** (pattern 3-06 "32bars Trap", variação A):

| | `20 01 ii 08` | `24 51 ii 08` | painel |
|---|---|---|---|
| BD | `[1, 10, 13]` | `[1]` | `[1]` |
| CH | `[1,3,5,7,9,11,13,15]` | `[1, 4, 7, 10]` | — |
| last var A–H | `[16, 16, …]` | `[12, 12, …]` | 12 |
| nome | `'----'` | `'32bars Trap'` | — |

Depois da migração, os **11 instrumentos batem** com a captura e com o painel.

**A ESCRITA vai no mesmo lugar** — segundo sniff, ligando o step 2 do BD no
editor. Saiu **uma** mensagem:

```
DT1  24 51 00 10   data=[0, 0, 0, 0, 0, 0, 5, 0]
```

`24 51` = variação A, `00` = BD, `0x10` = `0x08 + 1*8` = step 2, e os nibbles
`5,0` são a velocity 80 que o editor exibia. Bate byte a byte com `addr_step()`.

> Ou seja: o `20 xx` estava errado nas **duas** pontas. Escrever nele nunca
> chegou a mudar a máquina — o que parecia "sincronizar ao clicar no grid" era
> só o cache local do app se atualizando. O sintoma de 15/08 tinha uma causa
> única, e não era buffer dessincronizado: era **endereço errado**.

**Armadilha na migração:** o bloco novo tem 193 bytes (não 128) e o campo de
last step por track (offset 75+) vem **0** em vez de 15. Somar 1 às cegas fazia
cada instrumento tocar **um step só**; `0` significa "sem last step próprio,
segue a variação" e tem que virar `None`.

**Ainda aberto nesta região:** os offsets 128–192, que só existem aqui. O trecho
`[8, 11, 11, 1, 0, 0, 1, 6, 5]` a partir de 128 é candidato natural ao **last
step dos dois Fill In**, que continua desconhecido (2.3.1).

**Nota sobre o TR-EDITOR:** trocar a variação exibida nele **não gera MIDI** — ele
lê as 10 variações de uma vez no GET e alterna qual mostra, localmente. E ele
**não faz uma variação tocar**; isso só pelo painel. O app faz o que o editor não
faz, escrevendo a máscara 63–66 (provado, ver acima).

### Onde parou em 15/08/2026, noite (a sessão M2 aconteceu — e rendeu)

A sessão de sniff do TR-EDITOR foi feita. Resultado: **245/245 parâmetros de
efeito mapeados** (56 medidos por gesto do Luan, 189 derivados de duas regras
medidas), escrita de efeito **provada de ouvido** (reverb level, reverb send
por instrumento), tone **trocado e conferido no visor**. Capturas versionadas
em `capturas/`; método e achados no commit `13f0324`. Os blocos do kit, as
duas regras de região compartilhada e a regra dos tones (id = NUMBER − 1 da
tabela do próprio TR-EDITOR) estão documentados no `efeitos.py` e no
`gen_tones.py`.

O que a sessão **derrubou**: a numeração de tones por posição no PDF (o id 8
carregou "808 High Tom", não "707 Bass1/2") e o offset 0 do perf como kit
atual em `10 xx` (o kit atual mora em `01 00 00 00`, 1 byte, confirmado por
três caminhos).

**Os seis sniffs pendentes foram TODOS feitos na mesma noite (15/08):**

1. ~~PROBABILITY~~ — **a hipótese estava certa**: byte 3 do step, mesmo
   endereço do grid, `byte = (100−pct)÷10`. O que a observação tinha pego era
   um bug do *menu* da tela (listener órfão fechava o menu antes do clique
   completar), não do protocolo. Bônus: existe o byte **10 = 0%**, step que
   nunca toca. O "não fica" do painel segue por conferir com o menu já
   consertado.
2. ~~Opções com `?`~~ — os 10 dropdowns percorridos. **Todos** com código =
   posição na lista do catálogo, e os seis do MASTER FX caíram exatamente
   onde a regra `0x27+2i` previa — seis provas independentes da regra.
3. ~~COLOR~~ — sequencial confirmado (BD=0x42, SD=0x43), códigos 0–11 na
   ordem do menu: RED, ORANGE, YELLOW, LIME, GREEN, SKYBLUE, LIGHTBLUE,
   BLUE, PURPLE, MAGENTA, PINK, WHITE (`efeitos.CORES_INST`).
4. ~~Blocos 04/07/08~~ — nomeados: **04 = EXT IN** (side chain 0x00, gain
   0x04), **07 = OUTPUT** (1 byte/inst), **08 = MUTE/choke** (1 byte/inst).
   GROUP master no bloco do kit, offset 0x11. Mapa de blocos **completo**.
5. ~~CTRL por instrumento~~ — bloco 06, 1 byte/inst a partir de 0x01.
   Códigos 0–5 fixos (OFF, Pan, ReverbSend, DelaySend, LFO Depth, InstFX);
   do 6 em diante é o parâmetro do tone (6=Attack BD, 7=Snappy SD; LT/MT/HT
   têm "Color" não medido; RS–RC não têm nenhum).
6. ~~Troca remota de pattern~~ — **PROVADA tocando** (A1→A2→A1→A2→B1):
   escrever o "próximo pattern" (`01 00 00 02`) troca **na virada**, como no
   painel. É o mecanismo certo para o chain. A variante `now` (offset 1)
   **corta no meio do compasso** (B1↔B2 tocando, confirmado em duas passadas
   com BPM baixo) **e preserva a posição** — o pattern novo continua do mesmo
   step, sem voltar ao 1: troca de conteúdo com o relógio intacto, não um
   restart. O chain ganha dois modos musicais: na virada (`próximo`) e
   imediato (`now`).

E os arremates da mesma noite: **CTRL dos toms** fechou por eliminação
(espaço de códigos global — LT sample percorreu 0–5 e 9–23, o pulo 6/7/8 é
Attack/Snappy/**Color**; tabela em `efeitos.CTRL_TONE_PARAMS`), **EXT IN
completo** (bloco 04 contíguo: source, type 0–7, depth, gain 0–161, pan,
sends — painel próprio no catálogo, **252/252 mapeados**), e uma descoberta
de graça: **a TR-8S transmite sozinha o step atual** (`DT1 01 00 00 07`)
enquanto toca — é como o TR-EDITOR anima o playhead sem polling; upgrade
futuro para o nosso.

Capturas de tudo em `capturas/*-2026-08-15.mmon`.

### BUG ABERTO em 16/08/2026, madrugada — o grid não espelha o que toca

Sintoma: com a máquina tocando (patterns/variações trocados livremente), o
conteúdo do grid **não corresponde ao que soa**, e editar pelo grid não soa.
A sessão achou e consertou várias causas parciais — kit certo, espelho
bidirecional, seguir variação, nomenclatura 2-05, moldura — e o sintoma
persistiu. O que já se sabe:

- A máscara 63–66 é das variações **habilitadas**; a variação tocando **não
  existe em nó SysEx conhecido** (watch de 193 bytes em silêncio; perf 0x40
  é paridade de compasso). Hoje ela é **derivada do clock** (ordem
  ascendente × last step de cada uma, âncora no start) — `_avancar_ciclo_vars`.
- Hipótese PRINCIPAL não testada de forma isolada: o **buffer de edição
  (nós `20 xx`) não acompanha a troca de pattern** — leituras e escritas
  continuariam caindo no pattern antigo. Há um "resync" especulativo no
  motor (reescrever `01 00 00 01` com o mesmo n ao detectar troca) que
  **pode não fazer nada**.
  → **DERRUBADA e substituída em 16/08/2026, 12:56. Ver 7.4.** O nó não
  "fica no pattern antigo": ele **nunca muda**, para nenhum pattern.

**Roteiro do debug com calma (próxima sessão), do isolante ao complexo:**

1. App **fechado**. Máquina tocando o pattern X, variação A só.
   `python3 lp_tr8s.py prob_watch` (vigia o step 1 do BD na var A).
   Ligar/desligar o step 1 do BD **no painel** → o watch imprime?
   - Imprime → o nó 20 segue o pattern corrente; o bug é do motor
     (variação aberta/cache/rodízio) — instrumentar o motor.
   - Silêncio → **buffer dessincronizado confirmado**; ir ao passo 2.
2. Com o watch rodando, trocar o pattern **pelo painel** e repetir o toggle.
   Depois trocar **remotamente** (`pattern <n>`) e repetir. Isola qual troca
   dessincroniza.
3. Se dessincroniza: testar ressincronizadores um a um, com o watch aberto —
   escrever `01 00 00 01` = n; `01 00 00 02` = n; `UTIL 0x12`/GET-like?
   O TR-EDITOR resolve com o botão GET — se nada funcionar, capturar o GET
   dele (1 gesto) e imitar.
4. Só então revalidar grid/ghosts/click-to-sound.

### 16/08/2026, manhã — duas causas do sintoma acima, ambas provadas de mesa

O bug continua **aberto** (nada abaixo toca no buffer `20 xx`), mas duas causas
independentes que o mascaravam foram encontradas e corrigidas **sem hardware**.
Isso muda o roteiro acima: o ramo "imprime → o bug é do motor" era
inconclusivo, porque o motor errava a variação por conta própria.

**1. `_ressincronizar()` congelava a variação — e travava o Chain junto.**
Ele reatribuía `passo_abs` (contador **absoluto**, cresce sem fim) com o step
que a máquina informa (**modular**, 0–15). Três consumidores contam no
absoluto: `_avancar_ciclo_vars` (`while passo_abs >= _ciclo_limite`, e o
limite só crescia), o free-run do track curto, e o `ciclo = passo_abs // lim`
do Chain. Rodando a cada 1,5 s, bastavam dois ciclos para o limite ficar
inalcançável e a variação **congelar até o fim da sessão**; o Chain contava
repetições que nunca tocaram.

Simulado com a lógica exata, 12 compassos, A/B/C habilitadas, com perda de
pulsos. Máquina tocando `A B C A B C…`:

| resync | variação calculada |
|---|---|
| sem resync | `A B C A B C A B C A B C` |
| **como estava** | `A B C A A A A A A A A A` ← congela |
| delta só nos pulsos | `A B C B C C A B A A B C` ← ainda erra |
| **delta + fronteira junto** | `A B C A B C A B C A B C` ← certo |

A correção óbvia (delta) **não basta**: mover `passo_abs` faz o contador cruzar
fronteiras de variação que não deveriam ter sido cruzadas. A fronteira tem que
andar junto. Está em `CicloVars.deslocar`, e a variação virou **função pura da
posição** — sem estado acumulado, não há o que ficar preso. Guardado em
`testes.py` (`TesteResyncNaoCongela`), que falha se o bug voltar.

**2. Pulsos de clock eram descartados de verdade.** 657 ocorrências de
`MidiInCore: message queue limit reached!!` no log de 15/08. O rtmidi enfileira
1024 mensagens e joga o resto fora **em silêncio** — o aviso sai num `cerr` cru
do CoreMIDI, fora do log do app. A 86 bpm são ~34 msg/s, e o tick para de
drenar durante as leituras longas (`recarregar`, `ler_kit`); com a CTRL muda
isso passa de 30 s. Como a variação é derivada da **contagem**, cada pulso
perdido virava erro permanente.

Medido nesta máquina, fila de 2 e ninguém drenando por 3 s:

| modo | entregues | avisos |
|---|---|---|
| polling (como estava) | 1 | ~100 |
| `set_callback` | 104 | 0 |

**`set_error_callback` não resolve** — não é chamado para este aviso (testado:
0 chamadas). A porta de clock passou a **modo callback**, com deque ilimitado;
CTRL e Launchpad seguem em polling. Como agora nada se perde, depois de uma
leitura longa chega uma rajada represada — daí `_aplicar_pulsos` processar em
**lote**, senão o playhead varreria o grid numa piscada.

**3. Consequência para a variação, e o que ficou honesto.** `adotar_transporte`
**não** ancora o ciclo, e isso é de propósito: `OFF_STEP_ATUAL` diz onde
estamos *dentro* da variação, nunca *qual* é ela — ancorar em `vs[0]` às cegas
seria cara ou coroa com duas habilitadas. Quem sobe o app com a máquina já
rodando fica em `"?"` até dizer qual está no visor (**Shift-clique** na
variação → `Motor.ancorar_variacao`, que usa `passo_maquina` para acertar a
fase na hora). Uma correção de fase maior que 3 steps **solta a âncora**: a
fase dá para consertar, qual variação não.

Ainda não testado em hardware: se o ordinal de porta é fisicamente o aparelho
da esquerda.

### A escrita da máscara 63–66 FUNCIONA — provado em 16/08/2026, 12:25

Era a última incógnita da seção 2.3.2 ("leitura provada, escrita é a sessão C —
round-trip não prova obediência"). **Provada em hardware**, com o Luan na
máquina, três vezes seguidas, pelo duplo clique do app
(`Motor.pedir_variacao` → `dt1(20 00 00 00 +63, 1 << (v-1))`):

```
12:25:27  variacao B pedida - entra na virada
12:25:30  pedi a variacao B a maquina
12:25:30  a TR-8S passou a tocar a variacao B     <- obedeceu
12:25:52  variacao C pedida  ->  12:25:53 passou a tocar a C
12:26:41  variacao B pedida  ->  12:26:43 passou a tocar a B
```

A espera pela virada também confere: 3 s entre pedido e envio, e um compasso de
16 steps a 86 bpm dura 2,79 s.

**O mecanismo é auto-confirmante, e é por isso que ele é bom.** Escrever *um bit
só* faz a máquina ficar com **uma** variação habilitada; a releitura seguinte de
`ler_last_steps` vê `len(vars_habilitadas) == 1` e crava `variacao_tocando` com
**certeza**, sem depender de contagem de clock nenhuma. Ou seja: pedir a
variação pelo app é o único caminho em que a variação que toca deixa de ser
dedução e vira leitura.

**Efeito colateral que isso tem, e que é preciso ter em conta:** escrever um bit
só **desliga o rodízio**. Quem estava com A+B+C ciclando e dá um duplo clique
passa a ouvir só aquela — não há como pedir "toque a B *e continue ciclando*"
com uma escrita de bit único.

**A escrita com VÁRIOS bits também funciona** — provada em seguida, no mesmo
dia, montando o rodízio remotamente e lendo de volta a cada passo:

```
[D] -> liga A -> [A,D] -> liga B -> [A,B,D] -> liga C -> [A,B,C,D] -> desliga D -> [A,B,C]
```

Ou seja, **o rodízio inteiro é controlável pelo app** (`Motor.alternar_no_ciclo`,
clique direito na variação). Nunca deixar a máscara vazia: zero habilitada é um
estado cujo efeito não conhecemos, e há uma trava no código para não descobrir
isso com a música tocando.

### Os LEDs de VARIATION separam "toca" de "mostra" — 16/08/2026

**Correção de uma anotação errada feita horas antes nesta mesma seção.** Ao ser
perguntado qual variação aparecia "no visor", o Luan respondeu *"nenhuma"*, e
daí saiu a conclusão de que o painel não expunha a variação que toca. **Estava
errado** — a pergunta é que apontava para o lugar errado (o display numérico).
Quem mostra são os **LEDs dos botões A–H**, e eles dizem duas coisas ao mesmo
tempo, em cores diferentes:

| LED | Significado |
|---|---|
| **verde piscando, alternando** entre A, B e C | as habilitadas no rodízio; o verde acompanha **a que está tocando** |
| **amarelo piscando** no D | a variação que o painel está **mostrando/editando** |

Observado com `vars_habilitadas = [A,B,C]` tocando e o **D em amarelo** — ou
seja, a máquina estava **tocando A→B→C e exibindo a D**.

**A TR-8S tem nativamente a distinção "toca" vs. "edita"**, e sinaliza cada uma
com uma cor. É exatamente o modelo que o app já usa (ponto verde = o que toca,
quadrinho destacado = o que está aberto no grid) — o que era projeto nosso
acabou sendo convergência com o aparelho.

**Como o D foi parar em amarelo:** um duplo clique do app escreveu a máscara com
o bit do D (`Motor.pedir_variacao`); depois o rodízio A+B+C foi restaurado por
cima. O painel manteve o D como a variação *em exibição*. Portanto:

> Escrever a máscara 63–66 muda **o que toca**, e não muda **o que o painel
> mostra**. São dois estados independentes na máquina, e só um deles tem
> endereço conhecido.

**Consequência prática, e é um risco real:** com o painel mostrando D, um gesto
no painel edita a **D** — não a que está soando. Quem estiver olhando só para o
que ouve vai achar que "editar não faz nada".

**Pista para o BUG ABERTO** (o buffer `20 xx`, seção acima): esse segundo estado
— "variação em exibição no painel" — não foi procurado em nenhum sniff até
agora, e é candidato natural a explicar edições que não soam. Vale um
`snapdiff` mudando **só** a variação exibida no painel, sem tocar em mais nada.

O que continua valendo do que foi anotado antes:

- **stop/play reancora a conta**, e agora está **PROVADO** (abaixo).
- O **duplo clique** transforma dedução em leitura, fixando uma variação só.
- `Motor.ancorar_variacao` (Shift-clique) volta a ser utilizável, já que o LED
  verde de fato indica a que toca — com a ressalva de que a janela é curta: um
  compasso de 16 steps a 86 bpm dura 2,79 s.

### A máquina começa pela mais baixa habilitada — PROVADO em 16/08/2026

Era a premissa de `_ancorar_ciclo_vars()` sem argumento, e o que faz o stop/play
funcionar. Com A+B+C habilitadas, a máquina rodando e a conta em `"?"`, o Luan
deu **stop e play**; a partir daí o app acompanhou por 40 s medidos:

```
A B C A B C A B C A B C A B     (uma virada a cada ~2,8 s, sem repetir, sem "?")
```

Compare com o mesmo teste antes das correções deste dia, que produzia
`A A B C A A A B B B B B B B B B C C C C` — a variação congelando por dez
compassos. É a confirmação em hardware de que o `_ressincronizar` era a causa.

**Referência de UI para troca de pattern/kit — TR-EDITOR, 16/08/2026.** O Luan
apontou a janela `PATTERN / KIT SELECT` do editor como o modelo a seguir para a
nossa seleção de patterns, ritmos e kits. O que vale copiar dela:

- **Duas abas** no topo — `PATTERN` e `KIT` — no mesmo diálogo, em vez de dois
  lugares diferentes.
- **Tudo à vista, em colunas**: os 128 patterns (`1-01`…`8-16`) e os 128 kits
  (`001`…`128`) numa grade de 4 colunas, sem scroll e sem paginação. Dá para
  varrer o banco inteiro com o olho.
- **Número e nome juntos** em cada linha (`3-06: 32bars Trap`, `019: Simple
  Trap`), com os vazios marcados `----`.
- **O item corrente em destaque colorido** (amarelo/verde no editor), o que
  responde "onde eu estou" sem precisar procurar.

Isso conversa direto com o pedido de 15/08 de unir Biblioteca e Chain: a lista
completa com nome é o que falta para escolher pattern sem decorar número. Os
nomes dos 128 patterns e dos 128 kits estão legíveis nas capturas de tela de
16/08 e podem ser transcritos para o `biblioteca.py` sem precisar da máquina.

**Pedidos de interface anotados em 15/08 à noite** (para o plano da reforma):

- Biblioteca: clicar no estilo já muda BPM e kit (ou botão ali mesmo);
  pesquisar mais patterns por estilo; **unir Biblioteca e Chain numa aba só**,
  repensando como os patterns encadeados são visualizados.
- Estocástica: fileira BD–RC clicável em vez de dropdown; multi-seleção de
  instrumentos, cada um com sua linha de faders; **Reverter por edição** ao
  lado de cada Aplicar, não só o global.
- Grid: no lugar do "espelho dos LEDs", **moldura verde 8×16 sobre o próprio
  grid** mostrando a janela dos Launchpads, acompanhando INST UP/DOWN; e o
  playhead marcando as notas da coluna (verde forte onde tem nota, fraco onde
  não), não só a moldura da coluna.
- Efeitos: painel geral de sends (linha de reverb/delay send por instrumento
  como no TR-EDITOR); separar visualmente o que é por instrumento do que é
  master; reforma geral da UI usando os prints do TR-EDITOR como referência.

### Reforma 3 da interface — 16/08/2026, tarde (nada testado em hardware ainda)

Atende os pedidos de 15/08 acima e o de 16/08 (mesa + CTRL estilo TR-EDITOR):

- **A aba "Mixer & FX" virou a MESA**: 11 canais (GAIN, PAN, sends RVB/DLY,
  fader LEVEL, knob PROB, botão MUTE) + canal MASTER (reverb/delay level,
  MFX sw+tipo, KIT level), num quadro só. O dump alfabético dos 252
  parâmetros morreu — o catálogo completo mora só na aba Efeitos. A
  ferramenta de captura (Capturar / anotar opção / Reler) foi para a aba
  Avançado, e o "esquecer" virou um select que lista **só** o que veio do
  `~/.lp_tr8s_fx.json` (flag `capturado` que o `efeitos.carregar()` marca).
- **Fileira CTRL na aba Efeitos**, como no TR-EDITOR: 11 dropdowns (um por
  instrumento, posição fixa como os Sends) + o select global do kit ao lado.
  Fiação nova: entrada `"inst ctrl select"` em `PARAMS_FIXOS` com
  `off_por_inst` — o **terceiro modo de endereçamento** (um byte por
  instrumento DENTRO de um bloco de kit, offset `0x01+i` no bloco 06), que
  também servirá para COLOR/OUTPUT/choke quando a interface precisar. A
  leitura cai de graça no `ler_fx` (o bloco 06 já era lido inteiro).
  Códigos 0–5 fixos + 6–23 de tone; o 13 exibe **"Attack (sample)"** para
  o select não colidir com o 6 (medido em ACB). **Morph (tones FM) fica de
  fora** — segue sem código medido.
- **MUTE pela mesa**: ação nova `"mudo"` → `Motor.alternar_mudo(i)`, que
  **relê a máscara antes de inverter o bit** (o espelho `self.mudo` pode ter
  1,5 s de idade; toggle sobre máscara velha ressuscitaria um mute feito no
  painel nesse intervalo).
- **Master/Kit da Efeitos dobra**: `comp/secao.mjs` (`<details>` vestido de
  painel, estado por seção no localStorage). REVERB e DELAY nascem abertos,
  MASTER FX/LFO/EXT IN/KIT fechados, com o placar "N/N mapeados" visível no
  summary. Trocar de instrumento no seletor BD..RC repinta na hora (antes
  esperava o polling, até 250 ms).
- **Biblioteca: 34 → 54 patterns** — trance, psytrance, ambient, dubstep,
  tech house, minimal, dub techno + baião, xote, maracatu, frevo, ijexá,
  samba-reggae, partido alto, bossa nova, coco e carimbó. Regra nova de
  autenticidade: **CH e OH se sufocam** (choke do par), então o fechado abre
  buraco onde o aberto toca — salvo o triângulo do baião, que usa o choke de
  propósito. `testes.py` ganhou `TesteBiblioteca` (o `validar()` não rodava
  em teste nenhum).
- **Busca textual de tone** na aba Instrumento (com texto, ignora a
  categoria e varre os 514 por nome ou id).

Conferido de mesa: 253 params no catálogo, 54 patterns validados, 28 testes,
página inteira renderizando com o motor desligado (mesa em "—", selects
populados, colapsáveis persistindo). **Nada disso tocou a máquina** — a fila
de hardware está em 7.2, e o passo crítico é a primeira escrita no bloco 06.

A revisão do código achou três coisas de comportamento, já corrigidas:

- **`alternar_mudo` escrevia em standby.** Sair do modo ON não fecha a porta
  CTRL, e o botão MUTE era o único controle da página sem o guarda
  `modo_geral != MODO_ON` que o `definir_fx`/`definir_prob_inst` têm. Ganhou
  o guarda e uma checagem de faixa do índice (a máscara tem 16 bits e só 11
  são conhecidos — bit fora da faixa seria escrita em bit de função ignorada).
- **A fileira CTRL ficava muda num código que a lista não tem.** Com um tone
  FM em "Morph" (sem código medido), o select caía calado no "—" e a tela
  dizia "não lido" onde o visor mostra um destino de verdade. Agora aparece
  `código N ?`, mesmo critério do "?" das opções presumidas.
- A dica do PROB da mesa dizia que "—" era só "steps com valores diferentes";
  também é **nenhum step ligado** (`_prob_inst` devolve `None` nos dois casos).

### Sessão de hardware 17/08/2026 — a mesa na frente da máquina

Primeira vez que a reforma 3 encostou na TR-8S. **Dois testes passaram, dois
achados novos, e uma escala decifrada.**

**H1 MUTE — PASSOU, nos dois sentidos.** O botão da mesa muta e desmuta de
verdade (o Luan ouviu), e mutar no painel acende o MUTE na tela. O caminho
UI → `alternar_mudo` → máscara de performance está provado.

**H2 escrita — PASSOU.** LEVEL, GAIN, PAN, os dois sends e o KIT LEVEL, todos
mexidos pela mesa, mudam a máquina. **A leitura de volta é que estava quebrada**
— ver abaixo.

**GAIN: a escala inteira, lida no visor.**

| byte | visor |
|---|---|
| 0 | `-INF` |
| 1 | `-40.0 dB` |
| **81** | **`0.0 dB`** |
| 132 | `+25.5 dB` |
| **161** | **`+40.0 dB`** (fim da faixa) |

Meio decibel por passo a partir do 81, e o 0 é um valor especial. Isto **fecha a
pendência do `FAIXAS_MEDIDAS`**, que registrava "parou em 161, não em 255" sem
explicação: 161 é o fim da faixa mesmo. Mandamos 255 de propósito e a máquina
grampeou em 161 com o visor em +40.0 dB — sem estrago. Até aqui a tela mostrava
o desvio de 128 (o byte 81 aparecia como **−47** com a máquina dizendo 0.0 dB);
agora a tabela mora no catálogo (`efeitos.GANHO_ESCALA`) e alimenta a mesa, a
aba Efeitos e o log de uma vez. O `extin gain`, que o comentário já dizia ter
"a mesma escala 0-161", herdou a tabela.

**Achado 1 — os blocos de FX só eram relidos na troca de kit.** Mexer no GAIN,
LEVEL, PAN ou nos sends **pelo painel da máquina nunca chegava à tela**: a
`fx_fila` era armada só quando `kit_trocou` subia, então o espelho congelava no
estado do momento do ON e a mesa mentia. Consertado com um **rodízio**
(`INTERVALO_FX`), no mesmo espírito do `_reler_pattern_rodizio`: poucos blocos
por ciclo, para nunca disputar um tick com a releitura do pattern — foi ela que
virou "BD não lido" quando o `ler_kit` rodava inteiro num tick só. A mesa também
ganhou um **Reler** para quem não quer esperar a volta da fila.

**Achado 2 — a ação `reler` não tinha botão.** No boot desta sessão a leitura do
número do pattern falhou (`nao consegui ler em que pattern a maquina esta`), o
motor marcou as 11 linhas como não lidas — de propósito, porque escrever com
endereço de pattern errado é pior — e **a escrita ficou bloqueada sem saída pela
página**: `ACOES["reler"]` existia e nenhum elemento a chamava. Agora a própria
tarja vermelha traz o botão **Reler tudo**.

**H3 probability — PASSOU.** CH a 50% pela mesa falha em cerca de metade das
voltas; de volta a 100% ele fica constante.

## H4 — a escrita no bloco 06 FUNCIONA (17/08/2026)

**O passo crítico da reforma 3 passou, nos dois sentidos.** Era a primeira vez
que a nossa ponta escrevia no bloco `10 KK 06 00`: até aqui só o TR-EDITOR
tinha sido *visto* escrevendo lá.

1. A leitura já batia com o painel antes de qualquer escrita: `inst ctrl select`
   = `[6, 7, 8, 8, 8, 5, 5, 5, 5, 5, 5]` — BD=Attack, SD=Snappy, LT/MT/HT=Color,
   RS…RC=InstFX — com o global em 6 (User). **O Luan conferiu na máquina: está
   certo.**
2. Trocar o destino no dropdown **muda na máquina**.
3. Trocar o destino **no painel da máquina** muda na tela (o rodízio novo).
4. Com o destino em ReverbSend, girar o knob CTRL físico do BD **mudou o reverb,
   audivelmente**.

Ou seja: `DT1` de um byte em `0x01+i` do bloco 06 é tudo o que o TR-EDITOR faz
ali — não há gesto escondido. O endereçamento `off_por_inst` está provado, e com
ele o mesmo mecanismo serve para COLOR (`0x42+i`), OUTPUT (bloco 07) e choke
(bloco 08) quando a interface precisar.

**Limite conhecido do select:** os códigos 0–5 valem em qualquer instrumento;
do 6 em diante são parâmetros de TONE, e **cada tone expõe só alguns** (o BD não
tem Snappy). Não existe tabela tone → parâmetros em lugar nenhum — o
`ToneDetailsConfigTable.dat` da Roland só traz número/categoria/tipo/nome —
então a lista não tem como filtrar. O que ela faz é não mentir: os códigos 6+
ficam num grupo separado, "do tone — só se este tone tiver".

### PAN: a escala, também lida no visor

| byte | visor |
|---|---|
| 0 | `L127` |
| 118 | `L9` |
| 126 | `L1` |
| **127 e 128** | **`CENTER`** (dois bytes) |
| 129 | `R1` |
| 255 | `R127` |

O CENTER ocupar **dois** bytes é o que explicava o erro de um: a tela mostrava
`-10` (o desvio de 128) onde a máquina dizia `L9`. Serve para `inst pan`; o
`extin pan` provavelmente é igual, mas isso é **dedução** e ficou sem escala até
alguém ler o visor dele.

**H5 MASTER FX — PASSOU** (liga, desliga e troca de tipo, pelo canal MASTER da
mesa). **H6 caiu**: a aba Avançado foi removida a pedido do Luan no mesmo dia
("o programa tem que ficar mais simples") — com o catálogo 253/253 mapeado, a
captura guiada estava sem trabalho. O **WRITE** mudou para a aba Pattern; o log
continua no rodapé e em `~/Library/Logs/TR8S-Grid-app.log`; a captura volta do
git se um parâmetro novo aparecer.

## SCALE decifrada — nó do pattern, offset `0x16` (17/08/2026)

**Provada por `snapdiff` com ida e volta**, com a máquina parada e nada mais
mexido:

```
32nd -> 16th :  no do pattern, offset 22 (0x16):  03 -> 02
16th -> 32nd :  no do pattern, offset 22 (0x16):  02 -> 03
```

O segundo diff veio **limpo**: só esse byte e o step atual da performance (que
anda sozinho). A ordem dos códigos é a lista do Reference:

| código | scale | pulsos por step | como se sabe |
|---|---|---|---|
| 0 | `8th(T)` | 8 | **deduzido** da ordem da lista |
| 1 | `16th(T)` | 4 | **deduzido** da ordem da lista |
| 2 | `16th` | 6 | **medido** |
| 3 | `32nd` | 3 | **medido** |

O byte vem **de graça** no nó de 193 bytes que o `ler_last_steps` já lê a cada
1,5 s — nenhum RQ1 novo. O `PULSOS_P_STEP = 6` deixou de ser constante:
`Motor.pulsos_p_step()` lê a scale, e a barra de estado mostra um display
`scale` **só quando não é `16th`** — porque é exatamente aí que o playhead anda
em outra velocidade, e foi essa invisibilidade que fez o grid "andar em metade
do tempo" sem ninguém saber por quê. Três testes de mesa guardam a conversão.

**Ainda não testado em hardware:** o playhead com o pattern em `32nd`. A conta
está certa e os testes passam, mas quem confirma é o olho no grid ao lado da
máquina.

### O TEMPO do pattern, de brinde

O mesmo diff (o sujo, com a máquina reiniciada no meio) mostrou o **mesmo par de
nibbles mudando em dois lugares ao mesmo tempo**: nó do pattern offsets 18-19 e
performance offsets 59-60, de `0E 0E` para `0D 0A`. Com o offset 58 em `02`:
`2 E E` = 750 → **75.0 BPM** antes, `2 D A` = 730 → **73.0 BPM** depois — e 73
era o que o visor mostrava. Ou seja: o `OFF_TEMPO` (`0x3A`) da performance está
certo **e o pattern guarda o próprio tempo no nó dele (offsets 17-19)**.

Isso dá a **hipótese mais provável para o Auto BPM não funcionar**: escrevemos
só na performance, e a máquina recarrega o tempo do pattern por cima. Falta
testar escrevendo no nó.

### O playhead em `32nd`: quatro consertos, um deles de política

Com o pattern em `32nd` a 40 bpm (step de 187 ms) o playhead ficou "atrasado e
travando". Não era um bug, eram quatro:

1. **O clock represado.** Reler uma variação são 11 blocos de SysEx (~500 ms)
   com o lock na mão; o clock ficava na fila e era aplicado **todo de uma vez**
   no fim. O playhead congelava, pulava os steps que passaram e o **BPM medido
   desaparecia** — porque lote > 1 zera a janela de medição de propósito. Foi o
   `bpm: None` no `/estado`, com a máquina tocando, que entregou o diagnóstico.
   `Motor._bombear_clock()` processa o clock **entre** os blocos (o LED tem
   porta própria, nenhum byte vai para a TR-8S ali).
2. **A tela só sabia adivinhar um step.** O relógio do navegador mede a duração
   do step e anda sozinho entre quadros, mas parava no primeiro. Com step de
   187 ms contra 250 ms de polling, cada quadro cobre mais de um step: agora a
   adivinhação **encadeia**, com limite em **tempo** (600 ms), não em steps.
3. **O polling era lento demais para step curto.** 250 → **120 ms enquanto a
   máquina toca**. Decidido com número: o `/estado` responde em **13 ms**
   (mediana de 164 amostras) e pega o lock sem bloquear.
4. **O conteúdo da variação nova demorava ~500 ms para aparecer.** O motor
   passou a guardar o espelho de cada variação (`_guardar_cache_var`) e mostra
   na hora, com a releitura confirmando atrás. Guarda as **mesmas listas**, não
   uma cópia, então editar um step aparece nos dois lugares sem sincronizar
   nada; espelho com linha não lida não entra.

### O grid não segue mais a variação que toca — decisão de 17/08/2026

O *follow* nasceu em 16/08 por um motivo real (o visor em `2-04B` com o grid na
A: editar não soava, o painel não aparecia no grid e a estocástica caía no
vazio). Só que **seguir custa uma releitura de 11 blocos, ~500 ms**, e com
várias variações habilitadas a máquina troca a cada volta — a 40 bpm em `32nd`,
a cada 3 s. A vista pulava debaixo da mão de quem edita.

Decisão do Luan, e ela vale mais que o mecanismo: *"o grid tem função principal
inspecionar e editar o que está tocando e o que vai ser tocado"* e *"vai ser
suficiente a luzinha verde indicando o que está tocando"*. O
`_seguir_variacao` **foi removido** (e com ele o `_var_seguida`). A vista fica
onde o Luan deixou.

Quem diz o que soa são **três sinais honestos**, todos já existentes: o ponto
verde na coluna das variações, os displays `toca` × `edita` na barra de estado,
e a **ausência de playhead** quando a variação exibida não é a que soa (regra do
`playhead_visivel` — desenhar verde sobre o que não está soando seria a única
cor da tela mentindo sobre o som). Três sinais parados valem mais que uma vista
que se mexe.

Isso também **removeu a causa raiz** dos engasgos: sem troca de variação a cada
3 s, não há releitura de 500 ms a cada 3 s. Os quatro consertos acima continuam
valendo como rede — o bombeamento protege qualquer leitura longa, o cache de
variação deixa a troca **manual** instantânea, e o polling de 120 ms serve a
qualquer step curto.

### O que a revisão de código achou depois (17/08/2026)

A revisão do diff inteiro achou oito coisas, todas corrigidas antes do merge.
As duas primeiras são do tipo que este projeto não pode ter:

1. **`alternar_mudo` zerava os bits 11-15 da máscara de mute.** A máscara tem 16
   bits e a 2.7 decodificou 11; o toggle remontava a máscara dos 11 booleanos e
   escrevia os 16 — **mandando zero num campo que ninguém mapeou**. É a mesma
   regra que fez o índice ganhar checagem de faixa, e este é o primeiro caminho
   do projeto que reescreve essa máscara (o `definir_mudos` não tinha caller
   nenhum antes). Agora `ler_mudos` guarda os bits de cima crus
   (`mudo_bits_altos`) e o toggle devolve eles como estavam.
2. **O toggle escrevia mesmo quando a releitura falhava.** `ler_mudos` devolve
   `False` tanto para "nada mudou" quanto para "não consegui ler", e no segundo
   caso deixa o espelho intacto — então a máscara velha era escrita de volta,
   exatamente o que a releitura existia para evitar. O contador
   `leituras_falhas` é o único sinal que separa os dois casos; hoje o toggle
   aborta e diz por quê.
3. **O cache de variação apostava num aliasing que dois caminhos quebravam.**
   `_reler_pattern_rodizio` e `escrever_step` faziam `self.cache[i] = d`
   (rebind), e o espelho guardado envelhecia calado: ligar um step no painel e
   trocar de variação pintava o grid **sem** aquele step por ~500 ms. Virou
   `self.cache[i][:] = d`.
4. **A captura guiada ficou sem cancelamento.** O botão que a cancelava morreu
   com a aba Avançado, mas o gatilho continuava nos controles fantasma — e
   captura sem cancelamento relê os 26 blocos a cada 0,35 s até reiniciar o app.
   Um clique acidental na janela entre o `montar()` e o primeiro `/estado` (em
   que todo knob nasce fantasma) custava isso. Hoje o clique só explica.
5. **O `extin gain` tinha ganhado a escala em dB por dedução** — dez linhas
   depois do comentário que recusa fazer isso com o `extin pan`. Ficou só com a
   faixa 0-161 (que já estava documentada) até alguém ler o visor dele.
6. A tabela do GAIN dizia `+0.0 dB` no centro; **o visor mostra `0.0 dB`**.
7. **O PROB da mesa, partindo de "—", escrevia 10%** em todos os steps ligados
   com um arrasto de dois pixels: o knob partia do mínimo. Agora parte de 100%
   (`baseNula`), que é o neutro da máquina.
8. A docstring do `_bombear_clock` garantia que "nenhum byte vai para a TR-8S
   aqui" — e pelo `_atender_var_pedida` pode ir um DT1. A garantia errada é
   convite para mover a chamada para depois de um `ler_bloco`, e aí um DT1
   entraria entre o RQ1 e a resposta. A docstring agora diz **onde** chamar.

Junto: `CTRL_OFF_BASE` passou a ser usado no lugar do `0x01` escrito à mão; a
lista de opções do CTRL é montada por índice (`[{...}[i] for i in range(24)]`),
que falha alto se alguém reordenar os códigos em vez de deslocar todos os
rótulos em silêncio; e o comentário do `FAIXAS_MEDIDAS` passou a dizer que ele é
documentação, não código vivo.

**Ficou para o hardware** (a revisão listou, e concordo): mutar o TRIG no painel
e clicar MUTE na mesa, para ver se o achado 1 era real na máquina; ler o visor
do GAIN do EXT IN; e conferir que o rodízio de FX a cada 2 s somado ao polling
de 120 ms não trouxe "BD não lido" de volta.

### Três pendências que a sessão abriu (17/08/2026)

1. ~~**SCALE — o playhead anda em metade da velocidade.**~~ **RESOLVIDA na
   mesma sessão**: o byte apareceu no `snapdiff` (nó do pattern `0x16`) e o
   playhead passou a ler a scale. Ver a seção acima. Falta só o olho no grid
   com a máquina em `32nd`.
2. **AUTO FILL IN.** Quando a máquina cai no fill, o grid não acompanha e a
   contagem se perde. É consequência conhecida: **os Fill In não aparecem na
   máscara 63-66** (2.3.2, medido em 14/08), então nada no que lemos hoje diz
   "a máquina está tocando o fill". Os dois botões de AUTO FILL IN também são
   **transmit-only** por CC. O knob de intervalo (32/16/12/8/4/2) é
   **dedução**: parece ser de quantos em quantos compassos o fill entra, e isso
   ainda não foi confirmado nem no manual nem na máquina.
3. **Escrever o TEMPO não funcionou.** O `definir_bpm` (perf, `OFF_TEMPO`,
   3 nibbles) nasceu em 16/08 com o aviso "conferir o visor no primeiro uso".
   Em 17/08 o Auto BPM da aba Grooves foi acionado e **a máquina não mudou de
   andamento** — primeiro teste, resultado negativo. Falta isolar (clicar no
   BPM do groove direto, com o visor à vista) antes de cravar.

O `snap` passou a incluir a **região de performance** (`01 00 00 00`, 128 B —
a mesma leitura que o tick já faz), justamente porque as três pendências acima
moram lá ou no nó do pattern, e o snapshot era cego para elas.

### Onde parou antes disso

Os botões estão mapeados (seção 5), o app está no Desktop, e o HIDE e o LAST STEP
funcionam. O que resta não é ergonomia: é **protocolo que ainda não foi decodificado**.

### 7.1 Roteiro da sessão de captura

Tudo escrito e testado em bancada; **nada disto rodou na máquina ainda.** A ordem
importa: o `probe` primeiro, porque se os CCs das bordas divergirem, todo o resto
seria depurado pelo motivo errado.

**Passo 0 — `probe`. FEITO em 13/08/2026, bateu inteiro.** Os 32 CCs saíram na ordem
derivada da geometria, e o pareamento porta→aparelho ficou confirmado: **entrada e
saída `[6]` = esquerdo** (girado, origem 88), **`[4]` = direito** (origem 81). Como o
topo do `[6]` é que manda `89…19`, as **variações estão mesmo no aparelho esquerdo**,
onde o código as pinta — a contradição relatada em 13/08 não se sustentou.

**Passo 1 — `sniff`. FEITO em 13/08/2026: a máquina é muda.** Não transmite gestos
de painel (ver seção 3, método 2). Consequência: o WRITE **só** sai pelo MIDI Monitor
com o TR-EDITOR, e todo o resto tem que passar pelo `snap`/`snapdiff`. Não refazer.

**Passo 2 — `snap` + `snapdiff`**, um gesto por vez. Sem editor, sem monitor.

| # | Gesto no painel | O que esperamos |
|---|---|---|
| 0 | nada — `snap base.json` | linha de base |
| 1 | `[LAST]` → `[A]` → pad **12** | um byte do cabeçalho `20 01 00 00`, offset 4–7 |
| 2 | `[LAST]` → `[A]` → pad **8** | o mesmo byte — decide se é 0-based ou 1-based |
| 3 | `[LAST]` → `[BD]` → pad **6** | **fora** de `20 01`; confirma ou derruba o palpite `20 00` |
| 4 | long-press pad 1 do BD + VALUE → 50% | um dos bytes 0–4 do step 1 do BD |
| ~~5~~ | ~~idem, ALTERNATE~~ | **FEITO 14/08**: byte 4 = `08`, ver 2.4 |
| 6 | INST SELECT → TRG, ligar step 1 | escrita em `20 01 0B 08` |
| 7 | mudar Scale para `8th` | outro byte do cabeçalho |
| ~~8~~ | ~~`[MUTE]` + `[BD]`~~ | **FEITO 14/08**: mora fora do pattern, ver 2.7 |

**Passo 3 — WRITE.** Se o passo 1 falhou: fechar os scripts, abrir o TR-EDITOR, MIDI
Monitor com filtro SysEx, apertar `[WRITE]` na aba OVERALL. **O editor precisa da
porta CTRL**, então nada nosso pode estar rodando.

Cada endereço decodificado substitui o espelho local de 5.3 e vira leitura real.

Outros achados do manual, ainda não perseguidos: `[MAP]` inverte a ordem do drum
map; `SHIFT`+TEMPO altera o andamento de 1 em 1; `[MOTION]` deve corresponder ao
bloco de 1664 bytes em `20 0V 19 08`.

O `CC 93`, que estava reservado ao WRITE, **virou o ALT** em 14/08/2026. Quando o
WRITE for decodificado precisará de outro lugar — não sobrou botão livre no mapa.

### 7.2 O que nunca foi exercitado na máquina

Testado em bancada (geometria ida e volta nos 64 pads dos dois aparelhos,
precedência de cor, wrap do playhead, lote de SysEx de LED, desenhos, ondinha) mas
**nunca em hardware**:

1. ~~`probe`~~ — **resolvido em 13/08/2026.** Os 32 botões responderam exatamente
   na ordem derivada da geometria: topo esquerdo `89…19`, borda esquerda `98…91`,
   topo direito `91…98`, borda direita `89…19`. Nenhuma correção foi precisa. Os
   logos, confirmado, **não enviam nada** (ver 5).
2. ~~Fills, rajadas, RGB, ondinha~~ — **todos exercitados em 13/08/2026** e
   promovidos para "provado" na seção 3.
3. **Quadro RGB contínuo por muito tempo** (novo em 14/08/2026, com o `standby`). A
   ondinha já foi provada, mas em rajadas de segundos, com o dedo mandando. O standby
   sustenta o mesmo tráfego **indefinidamente**: ~30 quadros/s × 2 mensagens SysEx de
   ~330 bytes. Nada indica que isso seja demais para um Mini MK3 por USB, mas *nada foi
   medido* — ninguém deixou rodando uma hora para ver se algum LED trava ou se o
   aparelho começa a atrasar. O `fps` menor do estilo `ambiente` (15) existe como
   válvula: se aparecer sintoma, ele é o primeiro lugar a mexer.
4. **O `.app`** — o Dock pode mostrar "Python" em vez do nome do bundle, já que o
   executável é um shell script que dá `exec`. É cosmético; plano B é `osacompile`.
5. **O `adesivo.pdf` impresso** — o teste saiu a **93%** (a régua de 100 mm mediu 93),
   e o teste foi feito **na impressora da própria gráfica**, que é o destino final.
   Isso importa: a compensação está calibrada contra a máquina certa, não contra uma
   intermediária. Como não dá pra contar que um balcão mude configuração de
   impressão, a decisão foi **compensar do nosso lado**:

   ```
   python3 gen_adesivo.py --medido 93     # regua saiu com 93 mm -> desenha 107,5% maior
   ```

   O arquivo em disco **já está compensado** e carrega o carimbo vermelho dizendo
   isso — sem o carimbo, uma reimpressão numa impressora ajustada sairia 7,5% grande
   e ninguém saberia por quê. A instrução para a gráfica é **Scale to Fit**, não 100%.

   Isto é remendo amarrado a uma impressora: **a régua da folha continua sendo a
   fonte da verdade**. Meça o resultado; se não der 100 mm, regere com o novo valor.
   Ao compensar, só os **vãos** encolhem — as etiquetas nunca, que são a única coisa
   que precisa de tamanho certo. Um guarda no script recusa gerar se o desenho
   esticado estourar o A4. Só falta imprimir e conferir a régua de 100 mm.
   A geometria deixou de ser risco: os botões de borda do Mini MK3 são **quadrados
   de ~15 mm** (medido no aparelho, 13/08) e a etiqueta sai a **13,3 mm** (folga de
   1,7 mm, ajustada em 14/08 depois de colar as primeiras) indo **por cima** deles, não
   ao lado — então passo entre botões e distância até a borda não importam mais.
   A primeira versão eram tiras em L com furos redondos, medindo o bezel inteiro a
   partir da spec de 181 mm; virou lixo assim que se soube a forma e a ideia.

6. **Tudo que entrou em 14/08/2026 com a reforma da janela** — escrito e testado em
   mesa (testes de unidade sem porta), **nada em hardware**. A fila de sessões, da
   mais barata para a mais cara:

   | Sessão | O quê | Ferramenta | Risco |
   |---|---|---|---|
   | A | Fechar a tabela de probability (o painel dita, o watch lê o byte 3) | `python3 lp_tr8s.py prob_watch` | zero (leitura em endereço provado) |
   | — | Calibrar `BRILHO_BORDA` olhando o adesivo (e o quanto o "ativo" precisa se destacar) | abrir o `.app`, modo ON | zero |
   | — | GUI nova no ar: modos indicando o ativo, editor pintando o pattern real, playhead em fase, clique escrevendo (ouvir!) | `.app` | zero |
   | — | `definir_prob` de 50% num step e OUVIR a máquina pular o step ~metade das voltas | janela, duplo clique no step | zero |
   | B | Troca remota de pattern: `pattern <A1..H16>` (nextPattern), depois com `now` (currentPattern), tocando e parada; `pc <n>` como plano B | `python3 lp_tr8s.py pattern B2` | baixo (DT1 do mapa oficial; não é RQ1) |
   | — | Tone: abrir a aba Instrumento, conferir se o nome mostrado bate com o visor da máquina (valida a hipótese de id do tones.py); trocar o BD por outro tone e OUVIR | aba Instrumento | baixo (leitura provada; escrita DT1 nova) |
   | K | Decodificar CTRL SELECT / INST FX / knobs do kit: watch nos 128 B de params do instrumento, um gesto por vez | `python3 lp_tr8s.py kit_watch BD` | zero (leitura provada) |
   | ~~grid da tela~~ | ~~Comparar o grid da aba Pattern com os Launchpads e o painel~~ — **FEITO 15/08/2026: o grid está igual.** Valida a tradução inteira de `cor_do_step()` para CSS (nota forte/fraca, flam, sub step, ALT, accent, linha muda, step além do last step) e a régua de last step. A escrita pela tela fica liberada para teste | aba Pattern | — |
   | M1 | Escolher o parâmetro na lista do catálogo (ela mostra o gesto), Capturar, mexer SÓ nesse controle — **girando de ponta a ponta** nos de 2 bytes. Nas listas (waveform, destino do LFO, tipos de FX), depois de capturar, anotar cada opção com o visor na opção. Depois mover o controle novo (na aba Efeitos, onde ele nasce) e OUVIR | aba Avançado, painel "Mapear parâmetro novo" | baixo (leitura passiva + escrita em offset capturado) |
   | M2 | Sniff do TR-EDITOR (.app FECHADO): MIDI Monitor na porta CTRL + TR-EDITOR; mexer UM controle por vez nas abas EFX e INST, anotando a ordem; salvar o `.mmon` — o `tr8s_sysex.py` lê direto e os offsets viram entradas fixas do `efeitos.py` | MIDI Monitor + TR-EDITOR | zero (escuta passiva) |
   | — | Probability fácil (depois da sessão A): fader PROB do CH a ~50% com a máquina tocando → o chimbal falha metade das voltas; régua por step da Estocástica confere com o painel | abas Mixer / Estocástica | zero |
   | C | Escrita da máscara de variação | `python3 lp_tr8s.py var_mask B` | baixo |
   | — | Biblioteca: escrever um pattern numa variação descartável, ouvir, Desfazer | aba Biblioteca | zero |
   | — | Chain reescrita de ponta a ponta: 2 entradas × 2 reps trocando na virada sem furo audível | aba Chain | zero |
   | — | Estocástica: densidade audível; mesma seed = mesmo resultado; Reverter | aba Estocástica | zero |
   | — | Utility: está tocando? / versão / visor / WRITE (religar depois!) | aba Avançado | baixo (2.9) |
   | — | **Reforma 3 (mesa + CTRL)**: H1 MUTE pela mesa (ouvir o CH sumir e voltar; LED de MUTE no painel); H2 LEVEL/PAN/sends/KIT LEVEL da mesa (mexer, ouvir, devolver); H3 PROB do CH a 50% (falha metade das voltas; "—" = steps mistos); **H4 primeira escrita no bloco 06**: global CTRL → User (conferir no painel), dropdown do BD → ReverbSend, girar o knob CTRL físico do BD e OUVIR o send mudar + conferir o destino no visor, depois devolver os dois valores; H5 MFX sw/tipo (ouvir entrar/sair, nome no visor); H6 capturar/cancelar/anotar na aba Avançado | página: abas Mixer, Efeitos e Avançado | baixo (DT1 em endereços provados pelo sniff; H1/H2/H3/H4 PASSARAM em 17/08/2026 — inclusive a primeira escrita no bloco 06; faltam H5 e H6) |

   As CLIs de sessão exigem o `.app` **fechado** (porta CTRL única). Registrar cada
   resultado aqui, positivo ou negativo, como manda o Método.

---

## 8. Ideias registradas, não implementadas

- **Edição silenciosa + lançamento separado:** CLIP STOP escolhe onde editar,
  SHIFT + CLIP STOP dispara a troca de variação na máquina. Depende de capturar o
  comando de troca de variação — a dimensão de *pattern* destravou com o mapa do
  ARIA (2.9, `01 00 00 01/02`, sessão B); a de *variação* é a sessão C (escrita da
  máscara 63–66).
- **Controladora custom:** desenhos SVG existem (`tr_grid_8s.svg` 16×13,
  `tr_grid_1000.svg` 16×12). Cérebro RP2040 como USB MIDI class-compliant, matriz
  com diodos, LEDs SK6812/WS2812B. Rota NeoTrellis (12 placas 4×4 + NeoKey 1x4 QT)
  orçada em ~R$4.000–4.600 desembarcada.
- **TR-1000:** os desenhos existem. O argumento contra ela era que a implementation
  chart marca SysEx ✗ — **mas a chart da própria TR-8S também marca ✗** e tudo na
  seção 2 funciona (ver 5.1). A chart não é evidência de ausência. O obstáculo real
  é outro: o TR-1000 APP edita só kits, sem editor de patterns para sniffar, então
  não há de onde tirar o protocolo. Testar antes de fabricar qualquer coisa. Ela é superior como alvo de sequenciador externo (RX/TX Note independentes,
  velocity 1–127 nativa, slices por nota em "Each Track Ch.").

---

## 9. Referências

- `github.com/compuphonic/TR-8S-SysEx` — clone local em `../TR-8S-SysEx/`. Muito
  mais valioso do que parecia: `js/Tr8s/Tr8sData.js` carrega **o mapa de endereços
  oficial da Roland** em base64 (ver 2.9), e os 4 `.mmon` são tráfego real do site
  ARIA (o `tr8s_sysex.py` lê `.mmon` direto)
- `github.com/surge-synthesizer/stochas` — o sequenciador estocástico que inspirou
  a aba Estocástica (probabilidade por célula, poly bias→densidade, humanize,
  retrigger, seed estável)
- Thread do Elektronauts sobre SysEx da TR-8S
- Launchpad Mini MK3 Programmer's Reference (Novation)
- Manuais em `/mnt/project/`: `TR8S_Reference_eng05_W.pdf`,
  `TR8S_MIDIImpleChart_eng03_W.pdf`, `APC40Mk2_Communications_Protocol_v1_2.pdf`

---

*Este trabalho foi além do material público disponível: nenhum projeto conhecido
havia decodificado a escrita de patterns da TR-8S.*

---

## 10. Nomenclatura: MUTE → HIDE → e agora as duas coisas separadas

Em 13/08/2026, depois de o CC de LEVEL não silenciar (5.3), o recurso foi renomeado de
**MUTE** para **HIDE** — no adesivo, no `layout.html`, na janela, nos logs e no código.
O argumento era bom: um botão escrito MUTE que não muta engana quem usa, e uma variável
chamada `mudo` para algo que esconde engana quem lê depois.

**Em 14/08/2026 o mute apareceu** (2.7), e com ele a distinção que faltava. Não são o
mesmo recurso com dois nomes — são dois recursos:

| | o que é | onde mora |
|---|---|---|
| **mute** | silencia o track | na TR-8S, lido e escrito pelo grid |
| **esconder** | tira do grid a linha que está mutada | preferência local, `esconder_mudos` |

Então o código voltou a ter `mudo`, mas agora ele *muta de verdade*; e o que esconde
chama-se `esconder_mudos`, que é o que ele faz. Os nomes antigos (`oculto`,
`modo_oculto`, `alternar_oculto`, `linha_oculta`, `COR_OCULTO`) **não existem mais**.

A lição que sobra não é sobre nomes, é sobre inferência: o rename de 13/08 estava certo
como reação ao que se sabia, e errado como conclusão sobre a máquina. Um teste negativo
(o CC de LEVEL) virou uma afirmação geral (não dá para silenciar), e essa afirmação ficou
no documento como se fosse resultado. **Foi só uma pergunta do Luan, um dia depois, que
a derrubou** — do mesmo jeito que a pergunta dele sobre o `[WRITE]` derrubou a "peça que
falta para autonomia total" em 2.6. Duas vezes o documento afirmou impossibilidade a
partir de uma tentativa que falhou.

**Pendências que o adesivo e o `layout.html` herdaram:** os dois ainda dizem HIDE, e o
`gen_adesivo.py` / `gen_layout.py` precisam do texto novo. O botão é o mesmo `CC 94`, só
o rótulo muda.
