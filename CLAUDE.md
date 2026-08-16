# TR-8S Grid — contexto para o agente

## Leia a `REFERENCIA.md` antes de agir

Ela é a fonte da verdade do projeto e **separa o que está provado do que é dedução** —
essa distinção é o que impede retrabalho caro. O protocolo SysEx da TR-8S não é
documentado pela Roland; tudo o que sabemos foi levantado empiricamente e está lá, com a
seção 3 dizendo o que foi testado com hardware e o que não foi.

A seção **"Método"** dela vale ler mesmo para tarefas que não são de engenharia reversa:
as armadilhas ali derrubaram conclusões que já tinham entrado no documento como fato.

## Quem opera o hardware

**O Luan.** Eu não aperto pad, não vejo LED e não escuto a caixa. Isso muda como o
trabalho é entregue:

- Passos **exatos** para ele executar, um por vez, com o que esperar de cada um
- Dizer sempre, e sem ser perguntado, **o que não foi testado em hardware**
- Quando algo depende de julgamento visual (cor de LED, sincronia do playhead), pedir a
  observação em vez de afirmar que está certo
- "Compila" e "roda sem exceção" **não** são "funciona" — e a diferença já apareceu várias
  vezes neste projeto

## Três armadilhas que já custaram caro

1. **RQ1 em endereço inválido derruba a porta CTRL.** Depois de ~60–75 sondas em
   endereços que não existem, a TR-8S para de responder a qualquer leitura e só volta
   religando. Leitura válida não faz isso. Ver REFERENCIA 3.1 — o erro produziu um mapa de
   15 endereços que parecia perfeito e era uma máquina morrendo.
2. **A TR-8S manda MIDI clock mesmo parada.** "Chegou clock" não prova que ela está
   tocando; só `start`/`continue` provam, e quem sobe o grid com ela já rodando nunca
   recebe um. Ver REFERENCIA 2.8.
3. **O mido não enxerga os quatro Launchpad.** Ele deduplica portas por nome e sempre abre
   a primeira ocorrência, então os dois aparelhos viram um. Toda enumeração e abertura usa
   **rtmidi cru por índice**; o mido fica só para montar e parsear mensagens. Ver
   REFERENCIA 7 — e não "simplificar" isso de volta.

## Ambiente

- Python 3.9 do Command Line Tools, com `mido` + `python-rtmidi` em `~/Library/Python/3.9`
- `export PYTHONPATH=~/Library/Python/3.9/lib/python/site-packages` antes de rodar
- **Não usar `--break-system-packages`**: o pip é 21.2.4 e não suporta
- PDFs: `pdftotext` não existe aqui. Usar `fitz` (PyMuPDF), que já está instalado

## Depois de editar

O código roda em **três cópias**, e nenhuma delas é a pasta do projeto. Editar sem
atualizar a cópia certa faz testar a versão velha — que é o jeito mais fácil de tirar
uma conclusão falsa sobre o hardware.

- Mexeu em `lp_tr8s.py`, `servidor.py`, `web/`, `efeitos.py`, `ferramentas.py`,
  `biblioteca.py` ou `tones.py`:
  - `python3 instalar_agente.py` → atualiza `~/Library/Application Support/tr8s-grid/`
    e **reinicia o agente do launchd**, que é quem está no ar no dia a dia (é o que o
    app da Dock abre). Reiniciar **desliga o motor**: apertar ON de novo na tela
  - `python3 criar_app.py` → atualiza o `TR-8S Grid.app` do Desktop, que tem a sua
    própria cópia
  - o terceiro caminho é rodar da pasta do projeto (`python3 lp_tr8s.py ...`), que usa
    o código editado direto — é por onde as sessões de hardware acontecem
- Mexeu em `gen_layout.py` ou `gen_adesivo.py` → regerar. O adesivo precisa da
  compensação de impressora: `python3 gen_adesivo.py --medido 93`
- **Só um processo por vez fala com a porta CTRL** — e o modo como isso falha é
  traiçoeiro: no CoreMIDI a porta aceita vários clientes, então nada dá erro; os dois
  só passam a consumir a resposta um do outro e a medida sai errada **sem sintoma**.
  Quem segura a CTRL é o **motor**, não o servidor: com o motor em OFF o agente pode
  ficar no ar. As sessões guiadas (`pattern_watch` e companhia) checam isso sozinhas
  pelo `/ping` e se recusam a medir

## Idioma

Código, comentários e documentação em **português**, sem acento nos identificadores e nos
comentários do código (o resto do projeto segue essa convenção). A conversa também é em
português.
