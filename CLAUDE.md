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

## Fluxo de trabalho

**Toda edição sai de uma branch e entra na `main` por PR.** Nunca commitar direto na
`main` — em 17/08/2026 sete commits foram parar lá por pura inércia, depois de um PR
mergeado.

```bash
python3 instalar_hooks.py   # uma vez por clone; liga os hooks de .githooks/
```

- `pre-commit` recusa commit na `main` e diz como levar o trabalho para uma branch
- `pre-push` roda `python3 testes.py`; falhou, não empurra
- Para escapar de um deles, quando você sabe o que está fazendo: `--no-verify`
- O `/ship` já cria a branch, abre o PR, roda a revisão e mergeia — o hook é a rede para
  quando ninguém está usando o `/ship`

O CI (`.github/workflows/testes.yml`) roda os mesmos testes a cada push e PR. **Verde não
significa "funciona"**: significa "não quebrou o que já estava provado". Quem diz que
funciona é o Luan, na frente da máquina.

## Depois de editar

- Mexeu em `servidor.py`, `lp_tr8s.py`, `ferramentas.py`, `efeitos.py`, `biblioteca.py`,
  `tones.py` ou em `web/` → rodar **os dois**:
  `python3 instalar_agente.py` **e** `python3 criar_app.py`.
  Cada um mantém uma **cópia** dos scripts, e são cópias diferentes: o
  `instalar_agente.py` atualiza `~/Library/Application Support/tr8s-grid/`, que é de
  onde o LaunchAgent (quem responde em `127.0.0.1:8733`) roda; o `criar_app.py`
  atualiza o bundle do Desktop. Rodar só um deixa o outro na versão velha —
  e o que está no ar costuma ser o do LaunchAgent
- **Mexeu só em `web/`** (html/css/mjs) → `python3 instalar_agente.py --so-web`:
  copia sem reiniciar o agente, e um Cmd+R na página pega a versão nova **com o
  motor ainda ligado**. Reiniciar no meio de uma sessão de hardware derruba o
  motor e obriga a reler tudo do zero (aconteceu três vezes em 17/08/2026)
- `gui.py` (Tk) **não é copiado por nenhum dos dois** — é legado; a tela viva é a web
- Rodar os testes de mesa: `python3 testes.py` (sem porta MIDI, sem hardware). Desde
  17/08/2026 eles cobrem também os **contratos entre as camadas** — ação que a página
  chama e o servidor não tem, ação do servidor sem botão, chave de estado lida sem
  existir, nome de parâmetro de FX renomeado, sintaxe dos `.mjs` — que é a classe de bug
  que passa por todo teste de Python e só aparece com a página aberta
- Mexeu em `gen_layout.py` ou `gen_adesivo.py` → regerar. O adesivo precisa da
  compensação de impressora: `python3 gen_adesivo.py --medido 93`
- Só um processo por vez pode usar a porta CTRL. Um `run` esquecido em background impede
  o `.app` de abrir

## Idioma

Código, comentários e documentação em **português**, sem acento nos identificadores e nos
comentários do código (o resto do projeto segue essa convenção). A conversa também é em
português.
