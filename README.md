# TR-8S Grid

Dois **Launchpad Mini MK3** viram um grid 16×8 que liga e desliga steps **no sequenciador
interno da Roland TR-8S**, em tempo real, por SysEx.

Não é um sequenciador externo disparando notas na máquina: o que se edita é o pattern
dela, e o que soa é a TR-8S tocando sozinha. Desligue o computador e o pattern continua lá.

```
launchpads (nota/CC via USB) → Mac (Python + mido) → SysEx → TR-8S
Mac (velocity = cor)         → launchpads (LEDs)
```

A TR-8S é USB *device*, não host — nada pluga direto nela. O Mac é sempre o cérebro.

## O protocolo não é documentado pela Roland

Esta é a parte que não existe em outro lugar. O formato dos patterns da TR-8S nunca foi
publicado, e nenhum projeto público conhecido o havia decodificado — o mais próximo
([compuphonic/TR-8S-SysEx](https://github.com/compuphonic/TR-8S-SysEx)) parou nos kits,
antes dos patterns.

Tudo aqui foi levantado empiricamente, com hardware, e está em **[`REFERENCIA.md`](REFERENCIA.md)** —
que separa explicitamente **o que foi provado do que é dedução**.

| O que foi decifrado | Onde |
|---|---|
| Formato da mensagem, checksum, aritmética de endereço com carry de 7 bits | 2.2 |
| Mapa de endereços: kit, pattern, variações, TRG | 2.3 |
| Layout do step: velocity, flam, sub steps, **probability**, **ALT** | 2.4 |
| ACCENT como máscara de 16 bits em nibbles | 2.5 |
| **LAST STEP** da variação e do track | 2.3.1 |
| **MUTE de track** — estado de sistema, fora do pattern | 2.7 |
| **Step atual do sequenciador** | 2.8 |
| O que ainda falta: bytes 0–2 do step, WRITE, SCALE/SHUFFLE | 3 |

A seção **3.2 (Método)** vale por si: as regras que fizeram a diferença entre meses de
itens parados e três achados numa tarde.

## O que o grid faz que o painel não faz

- **Editar uma variação enquanto outra toca.** O recurso mais valioso, e a TR-8S não tem
  nativamente
- **Velocity contínua por step** — a máquina aceita, mas o painel só dá dois níveis
  cômodos
- Flam, sub steps e ALT em um toque, sem gesto de dois botões
- Ver o pattern inteiro de uma vez, com as linhas mutadas escondidas ou marcadas

## Uso

```bash
export PYTHONPATH=~/Library/Python/3.9/lib/python/site-packages

python3 lp_tr8s.py ports    # lista as portas MIDI com indice
python3 lp_tr8s.py learn    # descobre esquerdo/direito e a rotacao de cada um
python3 lp_tr8s.py run      # o grid ao vivo
python3 lp_tr8s.py standby  # so as ondas coloridas; nem precisa da TR-8S ligada
```

`python3 criar_app.py` monta um **`TR-8S Grid.app`** no Desktop, com janela e ícone, no
lugar do comando no terminal.

Feche o **TR-EDITOR** antes: ele segura a porta `TR-8S CTRL`, e só um processo por vez a
usa.

### Engenharia reversa

```bash
python3 lp_tr8s.py snap base.json      # le o estado da maquina
python3 lp_tr8s.py snapdiff a.json b.json
python3 lp_tr8s.py escutar             # tudo que a maquina transmite
python3 lp_tr8s.py varrer mapa.json    # que enderecos existem (leia a 3.1 antes!)
```

> **Aviso:** RQ1 em endereço inválido **derruba a porta CTRL** depois de ~60–75 sondas, e
> só volta religando a máquina. Ver REFERENCIA 3.1.

## Requisitos

- macOS, Python 3.9+ com `mido` e `python-rtmidi`
- Dois Launchpad Mini MK3 e uma TR-8S

**Armadilha do mido:** ele deduplica portas MIDI por nome e sempre abre a primeira
ocorrência, então os dois Launchpad viram um só. Por isso a enumeração e a abertura usam
`rtmidi` cru **por índice**, e o `mido` fica só para montar mensagens (REFERENCIA 7).

## Arquivos

| Arquivo | O que é |
|---|---|
| `lp_tr8s.py` | O motor e a CLI: launchpads, SysEx, grid ao vivo, sessões de hardware (`prob_watch`, `pattern`, `pc`, `var_mask`) |
| `web/` | A interface: HTML/CSS/módulos ES sem build nem dependência. Aba **Pattern** com o grid 12×16 editável (espelho do TR-EDITOR, com probability que o hardware não exibe), barra de estado com displays e LEDs, Mixer & FX, Instrumento, Biblioteca, Chain, Estocástica, Avançado |
| `servidor.py` + `pagina.html` | A tela: servidor local (só stdlib, 127.0.0.1, com token/Origin/CSP) + página no navegador, com o que o grid físico não tem — Mixer & FX (sends/knobs/LFO por captura guiada + probability), Instrumento (troca de tone), Biblioteca, Chain, Estocástica, Avançado. Log em `~/Library/Logs/TR8S-Grid-app.log`. Saiu do Tkinter porque o Tk 8.5.9 do Python do CLT trava no macOS atual (medições na REFERENCIA §4) |
| `efeitos.py` | Mapa dos parâmetros de kit/FX decodificados por observação (captura no app + sniff do TR-EDITOR) |
| `biblioteca.py` | 20 patterns clássicos em 14 estilos musicais, com kit sugerido — `python3 biblioteca.py` valida e mostra previews |
| `gen_tones.py` → `tones.py` | Preset Tone List da Roland como dados, para a aba Instrumento (trocar o tone de cada track) |
| `ferramentas.py` | Chain de patterns e ferramenta estocástica (probabilidade, densidade, humanize, ghosts) |
| `criar_app.py` | Monta o `.app` do Desktop |
| `apc_tr8s.py` | Versão anterior, para APC40 mkII — funcionando |
| `tr8s_sysex.py` | Parser/diff de capturas do MIDI Monitor |
| `gen_layout.py` → `layout.html` | Referência visual do mapeamento dos botões |
| `gen_adesivo.py` → `adesivo.pdf` | 34 etiquetas em tamanho real para colar nos botões |

**Os manuais da Roland não estão no repositório** — são obra de terceiros. Baixe em
[roland.com/support](https://www.roland.com/support/): *TR-8S Reference Manual*,
*MIDI Implementation Chart*, *Preset Tone List* e o manual do *TR-EDITOR*. A REFERENCIA
cita cada um por página.

## Licença

Sem licença definida ainda — pergunte antes de reutilizar.
