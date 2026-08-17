#!/usr/bin/env python3
"""
biblioteca.py - patterns classicos de bateria por estilo musical, como DADOS.

Puro-dados de proposito: nada aqui importa mido/rtmidi nem fala com a maquina.
Quem escreve na TR-8S e o Motor.escrever_pattern (lp_tr8s.py), alimentado por
expandir(). `python3 biblioteca.py` valida tudo e imprime os previews em ASCII
- e o degrau de verificacao sem hardware.

Formato de cada pattern:
    id       identificador unico
    nome     como aparece na janela
    estilo   chave de agrupamento
    bpm      sugestao, SO exibida (andamento se ajusta na maquina)
    kit      dica de texto de que kit combina - nunca e enviado
    kit_num  opcional: numero do kit PRESET correspondente (1=TR-808,
             2=TR-909, 3=TR-707, 4=TR-727, 5=TR-606, 6=TR-626). E o que o
             botao KIT e o "Auto kit" da tela usam (byte no fio = kit_num-1).
             Ausente = sugestao so textual (acusticos/breaks)
    last_var comprimento (default 16)
    accent   mascara de 16 bits do ACCENT, bit 0 = step 1 (default 0)
    obs      aviso opcional mostrado na janela
    steps    por instrumento (BD SD LT MT HT RS HC CH OH CC RC):
        forma compacta: string de last_var chars, x = forte, o = fraca, . = off
        forma detalhada: lista de last_var entradas, cada uma:
            None ou 0        step desligado
            int              velocity
            dict             {"vel":80, "sub":0, "prob":100, "alt":False}
                             sub: 0 normal, 1 flam, 2 = 1/2, 3 = 1/3, 4 = 1/4

Os valores 80/50 sao os dois niveis nativos da TR-8S (strong/weak beat do
painel, REFERENCIA 2.4) - por isso o compacto so conhece esses dois.

As fontes dos padroes estao nos comentarios de cada um. Padrao "classico" aqui
quer dizer: a celula ritmica canonizada do estilo, do jeito que os proprios
produtores a programam em drum machine - nao uma transcricao academica.
"""
FORTE, FRACA = 80, 50          # espelham VEL_FORTE/VEL_FRACA do lp_tr8s
INSTRUMENTOS = ["BD", "SD", "LT", "MT", "HT", "RS", "HC", "CH", "OH", "CC", "RC"]

PATTERNS = [
    # ── house ────────────────────────────────────────────────
    {
        "id": "house_classico", "nome": "House quatro no chao",
        "estilo": "house", "bpm": 124, "kit": "estilo TR-909", "kit_num": 2,
        "accent": 0x1111,          # steps 1 5 9 13
        "steps": {
            "BD": "x...x...x...x...",
            "HC": "....x.......x...",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..x...x...x...x.",     # o offbeat que faz house ser house
        },
    },
    {
        "id": "deep_house", "nome": "Deep house",
        "estilo": "house", "bpm": 122, "kit": "estilo TR-909, tons abafados", "kit_num": 2,
        "steps": {
            "BD": "x...x...x...x...",
            "HC": "....o.......o...",
            "RS": "...o......o....o",     # sincopa do rim, marca do deep
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..o...o...o...o.",
        },
    },
    # ── techno ───────────────────────────────────────────────
    {
        "id": "techno_pancada", "nome": "Techno reto",
        "estilo": "techno", "bpm": 132, "kit": "estilo TR-909 (ou 606 nos hats)", "kit_num": 2,
        "accent": 0x1111,
        "steps": {
            "BD": "x...x...x...x...",
            "SD": "....x.......x...",
            "CH": "oooooooooooooooo",
            "OH": "..x...x...x...x.",
            "LT": "..............oo",     # rufinho de virada
        },
    },
    {
        "id": "techno_detroit", "nome": "Detroit",
        "estilo": "techno", "bpm": 128, "kit": "estilo TR-909 + percussao", "kit_num": 2,
        "steps": {
            "BD": "x...x...x...x...",
            "HC": "....x.......x...",
            "RS": ".o....o.....o.o.",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..x...x...x...x.",
            "HT": ".......o..o.....",
        },
    },
    # ── electro / miami ──────────────────────────────────────
    {
        "id": "electro_808", "nome": "Electro (Planet Rock)",
        "estilo": "electro", "bpm": 128, "kit": "estilo TR-808", "kit_num": 1,
        # a celula do electro: bumbo no 1, na segunda colcheia do 2 e na
        # sincopa do 3 - o esqueleto do Planet Rock / 808 classico
        "steps": {
            "BD": "x......x..x....o",
            "SD": "....x.......x...",
            "HC": "............x...",
            "CH": "x.o.x.o.x.o.x.o.",
            "OH": "......o.........",
            "RS": "..o..........o..",
        },
    },
    {
        "id": "miami_bass", "nome": "Miami bass",
        "estilo": "electro", "bpm": 130, "kit": "estilo TR-808, bumbo longo", "kit_num": 1,
        "steps": {
            "BD": "x..o..x...x...o.",
            "SD": "....x.......x...",
            "HC": "....o.......o...",
            "CH": "oooooooooooooooo",
            "OH": "..............x.",
        },
    },
    # ── hip-hop ──────────────────────────────────────────────
    {
        "id": "boom_bap", "nome": "Boom bap",
        "estilo": "hip-hop", "bpm": 92, "kit": "estilo TR-808 ou samples", "kit_num": 1,
        "steps": {
            "BD": "x.....x..o......",
            "SD": "....x.......x...",
            "CH": "x.o.x.o.x.o.x.o.",
            "OH": "..............o.",
        },
    },
    {
        "id": "trap_meio_tempo", "nome": "Trap (meio tempo)",
        "estilo": "hip-hop", "bpm": 140, "kit": "estilo TR-808, 808 longo", "kit_num": 1,
        "obs": "os dois rolos de hat usam sub step - o retrigger nativo",
        "steps": {
            "BD": "x....o....x.....",
            "SD": "........x.......",          # meio tempo: caixa so no 3
            "CH": [FORTE, None, FRACA, None, FORTE, None,
                   {"vel": FRACA, "sub": 2}, None,
                   FORTE, None, FRACA, None, FORTE, None,
                   {"vel": FORTE, "sub": 4}, None],
            "OH": "............o...",
        },
    },
    # ── drum'n'bass / jungle / breakbeat ─────────────────────
    {
        "id": "dnb_twostep", "nome": "Two-step DnB",
        "estilo": "drum'n'bass", "bpm": 174, "kit": "breaks / acustico seco",
        "steps": {
            "BD": "x.........x.....",
            "SD": "....x.......x...",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "......o.........",
            "RC": "x...x...x...x...",
        },
    },
    {
        "id": "jungle_amen", "nome": "Jungle (amen simplificado)",
        "estilo": "drum'n'bass", "bpm": 170, "kit": "breaks / acustico seco",
        "steps": {
            "BD": "x.o.......x.....",
            "SD": "....x..o.o..x..o",     # fantasmas do amen
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..........o.....",
        },
    },
    {
        "id": "funky_drummer", "nome": "Funky Drummer",
        "estilo": "breakbeat", "bpm": 98, "kit": "acustico",
        # a celula do break do Clyde Stubblefield como todo mundo a programa:
        # caixa forte no 2 e no 4, fantasmas na volta, chimbal constante
        "steps": {
            "BD": "x.x...x...x..x..",
            "SD": "....x..o.o..x..o",
            "CH": "xooooooooooooooo",
            "OH": "...........o....",
        },
    },
    # ── funk / disco / pop ───────────────────────────────────
    {
        "id": "funk_jb", "nome": "Funk (Cold Sweat)",
        "estilo": "funk", "bpm": 108, "kit": "acustico",
        "steps": {
            "BD": "x.........x.....",
            "SD": "....x....o..x...",
            "CH": "x.o.x.o.x.o.x.o.",
        },
    },
    {
        "id": "disco", "nome": "Disco",
        "estilo": "disco", "bpm": 118, "kit": "acustico ou TR-909", "kit_num": 2,
        "accent": 0x1111,
        "steps": {
            "BD": "x...x...x...x...",
            "SD": "....x.......x...",
            "HC": "....o.......o...",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..x...x...x...x.",
            "CC": "o...............",
        },
    },
    {
        "id": "pop_billie", "nome": "Pop reto (Billie Jean)",
        "estilo": "pop", "bpm": 117, "kit": "acustico seco",
        "steps": {
            "BD": "x.......x.......",
            "SD": "....x.......x...",
            "CH": "x.o.x.o.x.o.x.o.",
        },
    },
    # ── latino / caribe ──────────────────────────────────────
    {
        "id": "reggaeton_dembow", "nome": "Dembow",
        "estilo": "reggaeton", "bpm": 95, "kit": "estilo TR-808 + timbal", "kit_num": 1,
        # o dembow canonico: bumbo nos 4 tempos, caixa no 3-3-2 (4 e 7 de
        # cada metade)
        "steps": {
            "BD": "x...x...x...x...",
            "SD": "...x..x....x..x.",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..............o.",
        },
    },
    {
        "id": "dancehall", "nome": "Dancehall",
        "estilo": "reggaeton", "bpm": 100, "kit": "estilo TR-808", "kit_num": 1,
        "steps": {
            "BD": "x..x....x..x....",
            "RS": "......o.......o.",
            "CH": "x.o.x.o.x.o.x.o.",
        },
    },
    # ── brasil ───────────────────────────────────────────────
    {
        "id": "funk_tamborzao", "nome": "Funk carioca (tamborzão)",
        "estilo": "funk brasileiro", "bpm": 130,
        "kit": "estilo TR-808 + tambores/percussao", "kit_num": 1,
        "last_var": 12,
        # grade de TERCINAS: o tamborzao nao cabe em semicolcheia. 12 steps =
        # 1 compasso em tercina de colcheia; bumbo em 1-3-4-6 de cada metade
        # (a segunda metade abre com a caixa no lugar do bumbo do tempo 3).
        "obs": "colocar SCALE em triplet no painel da TR-8S, senao o compasso "
               "encurta em vez de swingar",
        "steps": {
            "BD": "x.xx.x..xx.x",
            "SD": "......x.....",
            "CH": "o.o.o.o.o.o.",
        },
    },
    {
        "id": "samba_batucada", "nome": "Samba (batucada)",
        "estilo": "samba", "bpm": 100, "kit": "percussao (surdo/caixa/agogo)",
        # surdo: resposta forte no 2 e no 4 (steps 5 e 13), marcacao fraca no
        # 1 e no 3; caixa em semicolcheia com o teleco-teco acentuado
        "steps": {
            "BD": "o...x...o...x...",
            "SD": "oooxo.oxo.oxooox",
            "RS": "x..x..x.x..x..x.",     # agogo/tamborim no papel do rim
            "CH": "....o.......o...",
        },
    },
    # ── africa / garage ──────────────────────────────────────
    {
        "id": "afrobeat", "nome": "Afrobeat",
        "estilo": "afrobeat", "bpm": 110, "kit": "acustico + sino/percussao",
        # ride no papel do sino, com a campana tipica; bumbo conversando com
        # a caixa em fantasma - Tony Allen simplificado ao que cabe em 16
        "steps": {
            "BD": "x......x..x.....",
            "SD": ".o..o..x...o.o..",
            "RC": "x..x..x..x.x..x.",
            "CH": "..o...o......o..",
        },
    },
    {
        "id": "garage_2step", "nome": "UK garage (2-step)",
        "estilo": "garage", "bpm": 132, "kit": "estilo TR-909 + samples", "kit_num": 2,
        "steps": {
            "BD": "x......x..x.....",
            "SD": "....x.......x...",
            "CH": "o.o..oo.o.o..oo.",     # o chimbal que pula e o swing do 2-step
            "RS": "...........o....",
            "OH": "..............o.",
        },
    },
    # ════ expansao da reforma 2 (16/08/2026) ═════════════════
    # Grooves classicos como os produtores os programam em drum machine.
    # ── house (mais 2) ───────────────────────────────────────
    {
        "id": "acid_house", "nome": "Acid house",
        "estilo": "house", "bpm": 126, "kit": "estilo TR-909 seco", "kit_num": 2,
        # o quatro-no-chao do acid: clap dobrado e hat aberto empurrando
        "steps": {
            "BD": "x...x...x...x...",
            "HC": "....x......ox...",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..x...x...x...xo",
            "RS": ".......o........",
        },
    },
    {
        "id": "jackin_house", "nome": "Jackin' house",
        "estilo": "house", "bpm": 126, "kit": "estilo TR-909", "kit_num": 2,
        # a caixa fantasma na colcheia e o "jack" de Chicago
        "steps": {
            "BD": "x...x...x...x...",
            "SD": "....x..o....x..o",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..x...x...x...x.",
        },
    },
    # ── techno (mais 2) ──────────────────────────────────────
    {
        "id": "techno_hipnotico", "nome": "Techno hipnótico",
        "estilo": "techno", "bpm": 134, "kit": "estilo TR-909, hats curtos", "kit_num": 2,
        # menos e mais: rim andando em ciclo de 3 contra o 4 do bumbo
        "steps": {
            "BD": "x...x...x...x...",
            "RS": "o..o..o..o..o..o",
            "CH": "..x...x...x...x.",
            "CC": "x...............",
        },
    },
    {
        "id": "techno_industrial", "nome": "Industrial",
        "estilo": "techno", "bpm": 138, "kit": "estilo TR-909 distorcido", "kit_num": 2,
        "accent": 0x1111,
        "steps": {
            "BD": "x...x..xx...x...",
            "SD": "....x.......x..o",
            "CH": "oooooooooooooooo",
            "MT": "..........o...o.",
        },
    },
    # ── hip-hop (mais 1) ─────────────────────────────────────
    {
        "id": "trap_808", "nome": "Trap (808 rolando)",
        "estilo": "hip-hop", "bpm": 150, "kit": "estilo TR-808, 808 longo", "kit_num": 1,
        "obs": "hats em sub step 1/3 - o rolo triplo classico do trap",
        "steps": {
            "BD": "x.....x...x.....",
            "SD": "........x.......",
            "CH": [FORTE, None, FRACA, None, FORTE, None, FRACA,
                   {"vel": FRACA, "sub": 3}, FORTE, None, FRACA, None,
                   {"vel": FORTE, "sub": 3}, None, FRACA, None],
            "OH": "....o...........",
        },
    },
    # ── drum'n'bass (mais 1) ─────────────────────────────────
    {
        "id": "jungle_2", "nome": "Jungle (chopped)",
        "estilo": "drum'n'bass", "bpm": 172, "kit": "breaks fatiados", "kit_num": None,
        # o Amen refatorado: caixa deslocada no 8 e ghost no 11
        "steps": {
            "BD": "x.........x.....",
            "SD": "....x..x.o..x..o",
            "CH": "o.o.o.o.o.o.o.o.",
            "RS": ".......o........",
        },
    },
    # ── breakbeat (mais 1) ───────────────────────────────────
    {
        "id": "big_beat", "nome": "Big beat",
        "estilo": "breakbeat", "bpm": 120, "kit": "breaks + crash", "kit_num": None,
        "accent": 0x0101,
        "steps": {
            "BD": "x..x....x.x.....",
            "SD": "....x.......x...",
            "CH": "o.o.o.o.o.o.o.o.",
            "CC": "x...............",
            "OH": "..............o.",
        },
    },
    # ── footwork / juke ──────────────────────────────────────
    {
        "id": "footwork", "nome": "Footwork",
        "estilo": "footwork", "bpm": 160, "kit": "estilo TR-808 seco", "kit_num": 1,
        "obs": "os toms em tercina (sub 1/3) sao a assinatura do footwork",
        "steps": {
            "BD": "x..x..x...x..x..",
            "HC": "....x.......x...",
            "LT": [None, None, None, None, None, None,
                   {"vel": FORTE, "sub": 3}, None, None, None, None, None,
                   None, None, {"vel": FRACA, "sub": 3}, None],
            "CH": "o...o...o...o...",
        },
    },
    # ── gqom ─────────────────────────────────────────────────
    {
        "id": "gqom", "nome": "Gqom",
        "estilo": "gqom", "bpm": 124, "kit": "estilo TR-808 grave + toms", "kit_num": 1,
        # o vazio no tempo 1 e proposital: o peso do gqom vem da sincopa
        "steps": {
            "BD": "..x...x...x..x..",
            "LT": "x.......x.......",
            "SD": "......o.......o.",
            "CH": "o..oo..oo..oo..o",
        },
    },
    # ── amapiano ─────────────────────────────────────────────
    {
        "id": "amapiano", "nome": "Amapiano",
        "estilo": "amapiano", "bpm": 112, "kit": "log drum no BD (tone grave)", "kit_num": None,
        "steps": {
            "BD": "..o..x.....o..x.",     # o log drum sincopado
            "RS": "x...x...x...x...",
            "CH": "o.o.o.o.o.o.o.o.",
            "HC": "..........x.....",
        },
    },
    # ── punk / rock ──────────────────────────────────────────
    {
        "id": "punk", "nome": "Punk (d-beat)",
        "estilo": "rock", "bpm": 180, "kit": "acustico seco", "kit_num": None,
        "steps": {
            "BD": "x..x..x.x..x..x.",
            "SD": "..x...x...x...x.",
            "CH": "o.o.o.o.o.o.o.o.",
            "CC": "x...............",
        },
    },
    {
        "id": "rock_basico", "nome": "Rock de garagem",
        "estilo": "rock", "bpm": 132, "kit": "acustico", "kit_num": None,
        "steps": {
            "BD": "x......xx.......",
            "SD": "....x.......x...",
            "CH": "o.o.o.o.o.o.o.o.",
            "OH": "..............o.",
        },
    },
    # ── r&b / neo-soul ───────────────────────────────────────
    {
        "id": "neo_soul", "nome": "Neo-soul",
        "estilo": "r&b", "bpm": 88, "kit": "acustico abafado", "kit_num": None,
        "obs": "ghosts de caixa fracos - o 'atras do tempo' do Dilla",
        "steps": {
            "BD": "x.....x...o.....",
            "SD": "....x..o..o.x...",
            "CH": "o.oo.o.oo.o.o.oo",
            "RS": "..............o.",
        },
    },
    # ── dembow ───────────────────────────────────────────────
    {
        "id": "dembow_cru", "nome": "Dembow (cru)",
        "estilo": "dembow", "bpm": 115, "kit": "estilo TR-808 + timbal", "kit_num": 1,
        # o dembow dominicano: mais seco e repetitivo que o reggaeton
        "steps": {
            "BD": "x...x...x...x...",
            "SD": "...x..x....x..x.",
            "HC": "...o..o....o..o.",
            "CH": "o.o.o.o.o.o.o.o.",
        },
    },
    # ════ expansao 3 (16/08/2026): trance/psy/ambient + brasil ═══
    # Regra nova de autenticidade: CH e OH se sufocam na TR-8S (choke do
    # par de chimbal), entao o CH abre buraco onde o OH toca - salvo quando
    # o abafado e o efeito desejado (o triangulo do baiao usa isso).
    # ── trance ───────────────────────────────────────────────
    {
        "id": "trance_uplifting", "nome": "Trance (uplifting)",
        "estilo": "trance", "bpm": 138, "kit": "estilo TR-909 brilhante", "kit_num": 2,
        "accent": 0x1111,
        # kick 4/4, hat aberto no contratempo, 16ths no fechado (com buraco
        # pro aberto respirar) e o rolo de caixa da virada em sub step
        "obs": "o rolo de caixa nos steps 15-16 e a virada de oito em oito "
               "compassos do uplifting",
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "oo.ooo.ooo.ooo.o",
            "OH": "..x...x...x...x.",
            "HC": "....x.......x...",
            "SD": [None, None, None, None, None, None, None, None,
                   None, None, None, None, None, None,
                   {"vel": FRACA, "sub": 2}, {"vel": FORTE, "sub": 4}],
        },
    },
    {
        "id": "trance_progressive", "nome": "Trance (progressive)",
        "estilo": "trance", "bpm": 132, "kit": "estilo TR-909 abafado", "kit_num": 2,
        # o "rolling": chimbal em pares que empurram, rim sincopado
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "o..oo..oo..oo..o",
            "OH": "..x...x...x...x.",
            "RS": "...o..o....o..o.",
            "HC": "....o.......o...",
        },
    },
    # ── psytrance ────────────────────────────────────────────
    {
        "id": "psy_fullon", "nome": "Psytrance (full-on)",
        "estilo": "psytrance", "bpm": 145, "kit": "estilo TR-909 seco", "kit_num": 2,
        "accent": 0x1111,
        # kick seco 4/4 e hat aberto no contratempo; o grave offbeat do psy
        # e o BAIXO, nao a bateria - o pattern fica limpo de proposito
        "obs": "o rolling bass do psy e o sintetizador; aqui so o esqueleto",
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "oo.ooo.ooo.ooo.o",
            "OH": "..x...x...x...x.",
            "HC": "............x...",
        },
    },
    {
        "id": "psy_prog", "nome": "Psytrance (progressivo)",
        "estilo": "psytrance", "bpm": 140, "kit": "estilo TR-909 seco", "kit_num": 2,
        # prog-psy: fechado so no "e" de cada tempo, aberto no contratempo
        "steps": {
            "BD": "x...x...x...x...",
            "CH": ".o...o...o...o..",
            "OH": "..x...x...x...x.",
            "RS": ".......o.......o",
        },
    },
    # ── ambient ──────────────────────────────────────────────
    {
        "id": "ambient_mare", "nome": "Ambient (maré)",
        "estilo": "ambient", "bpm": 76, "kit": "tones eterios, ataque lento",
        # quase nada, de proposito: um pulso que aparece e some
        "obs": "reverb time e sends bem altos - o espaco e o instrumento",
        "steps": {
            "BD": "x.........o.....",
            "RC": "....o.......o...",
            "CC": "........o.......",
            "RS": "......o.........",
            "CH": "..o.....o.....o.",
        },
    },
    {
        "id": "ambient_pulso", "nome": "Ambient (pulso)",
        "estilo": "ambient", "bpm": 90, "kit": "tones macios, sem transiente",
        # batida de coracao em colcheia larga; a caixa fraca no 4 e a unica
        # gravidade do compasso
        "steps": {
            "BD": "x.......x.......",
            "CH": "o...o...o...o...",
            "RC": "..o...o...o...o.",
            "SD": "............o...",
            "OH": "......o.........",
        },
    },
    # ── dubstep ──────────────────────────────────────────────
    {
        "id": "dubstep_halftime", "nome": "Dubstep (meio tempo)",
        "estilo": "dubstep", "bpm": 140, "kit": "estilo TR-808 grave", "kit_num": 1,
        # 140 com caixa SO no 3: o meio tempo e o que da o peso
        "obs": "o groove esta no que NAO toca - resistir a encher os vazios",
        "steps": {
            "BD": "x.....x.........",
            "SD": "........x.......",
            "CH": "o..o..o..o..o..o",
            "OH": "..........x.....",
            "RS": "..............o.",
        },
    },
    # ── tech house / minimal / dub techno ────────────────────
    {
        "id": "tech_house", "nome": "Tech house",
        "estilo": "tech house", "bpm": 126, "kit": "estilo TR-909", "kit_num": 2,
        # o shuffle do rim e o vai-e-vem do hat fazem o groove
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "o...o.o.o...o.o.",
            "OH": "..x.......x.....",
            "RS": "...o..o......o..",
            "HC": "....x.......x...",
            "LT": "..............o.",
        },
    },
    {
        "id": "minimal", "nome": "Minimal",
        "estilo": "minimal", "bpm": 128, "kit": "estilo TR-606 seco", "kit_num": 5,
        # tres linhas e so: minimal e o que se tira, nao o que se poe
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "..o...o...o...o.",
            "RS": "o..o.o..o..o.o..",
        },
    },
    {
        "id": "dub_techno", "nome": "Dub techno",
        "estilo": "dub techno", "bpm": 118, "kit": "estilo TR-909 abafado", "kit_num": 2,
        "obs": "reverb e delay send altos no chimbal e no rim - o dub mora "
               "nos efeitos, nao nos steps",
        "steps": {
            "BD": "x...x...x...x...",
            "CH": "..o...o...o...o.",
            "RS": ".......o......o.",
            "OH": ".............o..",
            "CC": "o...............",
        },
    },
    # ── brasil: forro, maracatu, frevo, afoxe, samba, bossa... ─
    {
        "id": "baiao", "nome": "Baião",
        "estilo": "forró", "bpm": 104,
        "kit": "zabumba no BD, triangulo no par CH/OH",
        # zabumba: grave na cabeca, resposta fraca no contratempo (meia-lua).
        # Triangulo = OH aberto no tempo + CH fechado nas semicolcheias: o
        # choke do par faz o abafado sozinho - aqui a colisao E o gesto.
        "obs": "triangulo usa o choke CH/OH de proposito; zabumba pede tune "
               "grave no BD",
        "steps": {
            "BD": "x.....o.x.....o.",
            "OH": "x...x...x...x...",
            "CH": ".ooo.ooo.ooo.ooo",
            "RS": "....o.......o...",
        },
    },
    {
        "id": "xote", "nome": "Xote",
        "estilo": "forró", "bpm": 92, "kit": "zabumba + caixa seca",
        # o xote anda em colcheia; zabumba com pickup fraco pro proximo tempo
        "steps": {
            "BD": "x......ox......o",
            "RS": "....x.......x...",
            "CH": "o.o.o.o.o.o.o.o.",
        },
    },
    {
        "id": "maracatu", "nome": "Maracatu (baque virado)",
        "estilo": "maracatu", "bpm": 105,
        "kit": "estilo TR-808, toms com tune la embaixo", "kit_num": 1,
        # alfaias no BD/LT (grave que pergunta, virada que responde), caixa
        # em semicolcheia com acento deslocado, gongue no rim
        "obs": "baque virado simplificado ao que cabe em 16; alfaia = tune "
               "grave e decay longo",
        "steps": {
            "BD": "x..x..x.x..x....",
            "LT": "..............xx",
            "SD": "ooxoooxoooxoooxo",
            "RS": "x..x..x.x..x..x.",
            "CH": "o.o.o.o.o.o.o.o.",
        },
    },
    {
        "id": "frevo", "nome": "Frevo",
        "estilo": "frevo", "bpm": 152, "kit": "acustico seco (bloco de rua)",
        # a caixa carrega o 3+3+2 dobrado; surdo empurra a virada do tempo
        "steps": {
            "BD": "x......xx.......",
            "SD": "xooxooxoxooxooxo",
            "HC": "....x.......x...",
            "CC": "x...............",
        },
    },
    {
        "id": "ijexa", "nome": "Ijexá (afoxé)",
        "estilo": "afoxé", "bpm": 96, "kit": "estilo TR-727 (atabaques)", "kit_num": 4,
        # agogo no rim (metade sincopada, metade andando), atabaques nos
        # toms, xequere varrendo em semicolcheia
        "steps": {
            "RS": "x..x..x.x.x.x.x.",
            "BD": "......x.......x.",
            "MT": "..o..o....o..o..",
            "CH": "oooooooooooooooo",
        },
    },
    {
        "id": "samba_reggae", "nome": "Samba-reggae",
        "estilo": "samba", "bpm": 96,
        "kit": "estilo TR-808, surdos nos graves", "kit_num": 1,
        # surdos em dialogo (BD pergunta no 1, LT responde no 2 e no 4),
        # repique costurando em 3, caixa fraca preenchendo
        "steps": {
            "BD": "x.......x.......",
            "LT": "....x.......x...",
            "SD": "..o...o...o...x.",
            "RS": "x..x..x..x..x...",
            "CH": "o.o.o.o.o.o.o.o.",
        },
    },
    {
        "id": "partido_alto", "nome": "Partido alto",
        "estilo": "samba", "bpm": 100, "kit": "pandeiro + tamborim (percussao)",
        # a figura do tamborim e o partido alto; surdo responde no 2 e no 4;
        # palmas de roda no clap
        "steps": {
            "RS": ".x..x.x...x..x..",
            "BD": "o...x...o...x...",
            "CH": "oooooooooooooooo",
            "HC": "x......x..x.....",
        },
    },
    {
        "id": "bossa_nova", "nome": "Bossa nova",
        "estilo": "bossa nova", "bpm": 132, "kit": "acustico seco, rim = clave",
        # clave da bossa no rim; surdo pontuado (tempo + pickup) no bumbo
        "steps": {
            "RS": "x..x..x...x..x..",
            "BD": "x..xx..xx..xx..x",
            "CH": "o.o.o.o.o.o.o.o.",
        },
    },
    {
        "id": "coco", "nome": "Coco",
        "estilo": "coco", "bpm": 104, "kit": "estilo TR-727 + ganza", "kit_num": 4,
        # o ganza carrega o coco; caixeta/palmas respondem no contratempo
        "steps": {
            "BD": "x.....x...x.....",
            "SD": "....x.......x...",
            "CH": "oooooooooooooooo",
            "RS": "..x...x...x...x.",
        },
    },
    {
        "id": "carimbo", "nome": "Carimbó",
        "estilo": "carimbó", "bpm": 110, "kit": "estilo TR-727, curimbo nos toms", "kit_num": 4,
        # curimbo: o tom grave pergunta, o medio responde; milheiro varre em
        # semicolcheia por cima
        "steps": {
            "LT": "x.x...x.x.x...x.",
            "BD": "x.......x.......",
            "MT": "....o..o.....o..",
            "CH": "oooooooooooooooo",
            "RS": "....x.......x...",
        },
    },
]


def _expandir_entrada(ent):
    """Uma entrada de step -> (vel, sub, prob, alt)."""
    if not ent:
        return (0, 0, 100, False)
    if isinstance(ent, int):
        return (ent, 0, 100, False)
    return (ent.get("vel", FORTE), ent.get("sub", 0),
            ent.get("prob", 100), bool(ent.get("alt", False)))


def expandir(pat):
    """Pattern da biblioteca -> {indice_inst: [(vel, sub, prob, alt)] * 16}.

    Instrumentos ausentes viram 16x desligado; um pattern mais curto que 16 e
    completado com steps desligados (o last_var e quem corta)."""
    mapa = {"x": (FORTE, 0, 100, False), "o": (FRACA, 0, 100, False),
            ".": (0, 0, 100, False)}
    fora = {}
    for nome, linha in pat["steps"].items():
        i = INSTRUMENTOS.index(nome)
        if isinstance(linha, str):
            steps = [mapa[ch] for ch in linha]
        else:
            steps = [_expandir_entrada(e) for e in linha]
        steps += [(0, 0, 100, False)] * (16 - len(steps))
        fora[i] = steps[:16]
    for i in range(len(INSTRUMENTOS)):
        fora.setdefault(i, [(0, 0, 100, False)] * 16)
    return fora


def validar(pat):
    """Levanta ValueError com a lista de problemas do pattern."""
    erros = []
    n = pat.get("last_var", 16)
    if not 1 <= n <= 16:
        erros.append(f"last_var {n} fora de 1-16")
    for chave in ("id", "nome", "estilo", "bpm", "kit", "steps"):
        if chave not in pat:
            erros.append(f"falta a chave '{chave}'")
    kn = pat.get("kit_num")
    if kn is not None and not 1 <= kn <= 128:
        erros.append(f"kit_num {kn} fora de 1-128")
    if not 0 <= pat.get("accent", 0) <= 0xFFFF:
        erros.append("accent fora de 16 bits")
    for nome, linha in pat.get("steps", {}).items():
        if nome not in INSTRUMENTOS:
            erros.append(f"instrumento desconhecido '{nome}'")
            continue
        if len(linha) != n:
            erros.append(f"{nome}: {len(linha)} steps, esperava {n}")
        if isinstance(linha, str):
            ruins = set(linha) - set("xo.")
            if ruins:
                erros.append(f"{nome}: caracteres invalidos {sorted(ruins)}")
        else:
            for s, ent in enumerate(linha):
                vel, sub, prob, _ = _expandir_entrada(ent)
                if not 0 <= vel <= 127:
                    erros.append(f"{nome} step {s+1}: vel {vel}")
                if sub not in (0, 1, 2, 3, 4):
                    erros.append(f"{nome} step {s+1}: sub {sub}")
                if not (prob == 100 or 10 <= prob <= 100):
                    erros.append(f"{nome} step {s+1}: prob {prob}")
    if erros:
        raise ValueError(f"{pat.get('id', '?')}: " + "; ".join(erros))


def por_estilo():
    """{estilo: [patterns]}, na ordem em que aparecem."""
    grupos = {}
    for p in PATTERNS:
        grupos.setdefault(p["estilo"], []).append(p)
    return grupos


def preview_ascii(pat):
    n = pat.get("last_var", 16)
    linhas = [f"{pat['nome']}  ({pat['estilo']}, {pat['bpm']} bpm, "
              f"kit: {pat['kit']})"]
    if pat.get("obs"):
        linhas.append(f"  obs: {pat['obs']}")
    dados = expandir(pat)
    regua = "".join("|" if s % 4 == 0 else "." for s in range(n))
    linhas.append(f"        {regua}")
    for i, nome in enumerate(INSTRUMENTOS):
        steps = dados[i][:n]
        if not any(v for v, _, _, _ in steps):
            continue
        desenho = ""
        for vel, sub, prob, alt in steps:
            if not vel:            desenho += "."
            elif sub:              desenho += "/"
            elif alt:              desenho += "a"
            elif prob < 100:       desenho += "?"
            elif vel >= FORTE:     desenho += "X"
            else:                  desenho += "o"
        linhas.append(f"  {nome:4}  {desenho}")
    if pat.get("accent"):
        acc = "".join("A" if pat["accent"] >> s & 1 else "."
                      for s in range(n))
        linhas.append(f"  ACC   {acc}")
    return "\n".join(linhas)


if __name__ == "__main__":
    ids = set()
    for p in PATTERNS:
        validar(p)
        if p["id"] in ids:
            raise ValueError(f"id duplicado: {p['id']}")
        ids.add(p["id"])
        print(preview_ascii(p))
        print()
    estilos = por_estilo()
    print(f"ok: {len(PATTERNS)} patterns em {len(estilos)} estilos "
          f"({', '.join(estilos)})")
