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
2 do step, o last step dos Fill In, SCALE/SHUFFLE, os blocos `0C`–`18`, e o comando
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

**Deduzido, nunca exercitado:**
- Que o bloco `20 0V 0B 08` seja mesmo o **TRIGGER OUT**. Ele existe, é distinto e
  tem formato de step; que seja o TRG vem do diagrama da p. 8, não de teste.

**Desconhecido:**
- Bytes 0, 1 e 2 de cada step — os três últimos sem nome, agora que o 4 fechou
- Comando WRITE
- SCALE, SHUFFLE — com suspeitos em 2.3.1 (os bytes 17-19 do nó de pattern)
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
| `lp_tr8s.py` | Dois Launchpad Mini MK3. O motor virou `class Motor`; o `run` do terminal só instancia e chama `tick()` num laço |
| `gui.py` | Janela Tk: ON / off / standby (chuva e ambiente), status, e quatro seções expansíveis |
| `criar_app.py` | Monta o `TR-8S Grid.app` no Desktop. Ícone desenhado em Python puro (sem PIL), `sips` + `iconutil` fazem o resto |
| `tr8s_sysex.py` | Parser/diff de capturas do MIDI Monitor |
| `layout.html` | Referência visual dos botões — abrir no browser |
| `gen_layout.py` | Gera o `layout.html`. Editar aqui, não no HTML |
| `adesivo.pdf` | 34 etiquetas em **tamanho real**, uma página A4 — recortar e colar **em cima** dos botões (32) e nos cantos do logo (2) |
| `gen_adesivo.py` | Gera o `adesivo.pdf`. A única medida que importa é `BOTAO = 15 mm`. Ver a compensação de escala abaixo |
| `apagar_luzes.py` | Apaga os LEDs dos Launchpad. Alias `launchpad_blackout` no `~/.zshrc` |

O `.app` carrega uma **cópia** dos scripts em `Contents/Resources/`. Depois de editar
o `gui.py` ou o `lp_tr8s.py`, rodar `python3 criar_app.py` de novo. Se ele não abrir,
o motivo cai em `~/Library/Logs/tr8s-grid.log`.

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
ainda assume scale de semicolcheia, então scale diferente continua dessincronizando.

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
Fora do `ON`, **MUTE + WRITE apertados juntos voltam para o ON** — senão não
haveria como voltar sem ir até o Mac.

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

### Onde parou agora

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
   de ~15 mm** (medido no aparelho, 13/08) e a etiqueta vai **por cima** deles, não
   ao lado — então passo entre botões e distância até a borda não importam mais.
   A primeira versão eram tiras em L com furos redondos, medindo o bezel inteiro a
   partir da spec de 181 mm; virou lixo assim que se soube a forma e a ideia.

---

## 8. Ideias registradas, não implementadas

- **Edição silenciosa + lançamento separado:** CLIP STOP escolhe onde editar,
  SHIFT + CLIP STOP dispara a troca de variação na máquina. Depende de capturar o
  comando de troca de variação.
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

- `github.com/compuphonic/TR-8S-SysEx` — dumps de kits, parou antes dos patterns
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
