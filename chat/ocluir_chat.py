"""ocluir — versão de arquivo único, para rodar no chat do Claude.

Gerado por ferramentas/gerar_script_de_chat.py. NÃO EDITE À MÃO:
edite os módulos em ocluir/ e gere de novo.

Depende só da biblioteca padrão do Python, mais o Pillow para achar as caixas
de texto. Gerar o .apkg em si não precisa nem do Pillow.

Uso típico, em três passos:

    # 1. medir — escreve uma imagem com as caixas numeradas
    caixas, tamanho = detectar("slide.png")
    desenhar_numeradas("slide.png", caixas, "slide-caixas.png")

    # 2. ler a imagem numerada e dizer qual número é qual rótulo
    grupos = [
        {"rotulo": "Hexoquinase", "caixas": [3]},
        {"rotulo": "Aldolase",    "caixas": [9]},
    ]

    # 3. gerar o pacote para o AnkiDroid
    criar_apkg(
        "slide.png", caixas, grupos, "cartoes.apkg",
        titulo="Glicólise — fase preparatória",
        deck="Medicina::Bioquímica",
        modo=ESCONDER_UMA,
        tags=["oclusao", "pergunta::glicolise", "disc::bioquimica"],
    )
"""

from __future__ import annotations


import base64
import hashlib
import json
import re
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


# ==========================================================================
# de ocluir/oclusao.py
# ==========================================================================

# Modos, com os nomes que o Anki usa na interface.
ESCONDER_TUDO = "esconder-tudo"  # Hide All, Guess One  -> oi=1
ESCONDER_UMA = "esconder-uma"  # Hide One, Guess One  -> sem oi

MODOS = (ESCONDER_TUDO, ESCONDER_UMA)

# Nomes dos campos do notetype nativo, em inglês. Se o Anki estiver em
# português os nomes mudam, e por isso `anki.py` detecta por posição.
CAMPOS_PADRAO = ["Occlusion", "Image", "Header", "Back Extra", "Comments"]


def formatar_numero(valor: float) -> str:
    """Reproduz o `floatToDisplay` do Anki: 4 casas, sem zeros à toa."""
    texto = f"{round(valor, 4):.4f}".rstrip("0").rstrip(".")
    return texto or "0"


def _escapar(valor: str) -> str:
    # O parser do Anki separa propriedades por ":" e usa "\" como escape.
    return valor.replace("\\", "\\\\").replace(":", "\\:")


@dataclass
class Forma:
    """Um retângulo de máscara, em coordenadas normalizadas (0–1)."""

    esquerda: float
    topo: float
    largura: float
    altura: float

    def limitada(self) -> "Forma":
        """Impede que a máscara escape da imagem por causa da folga."""
        esq = min(max(self.esquerda, 0.0), 1.0)
        topo = min(max(self.topo, 0.0), 1.0)
        return Forma(
            esquerda=esq,
            topo=topo,
            largura=min(max(self.largura, 0.0), 1.0 - esq),
            altura=min(max(self.altura, 0.0), 1.0 - topo),
        )

    def para_cloze(self, ordinal: int, ocultar_inativas: bool) -> str:
        f = self.limitada()
        propriedades = [
            ("left", formatar_numero(f.esquerda)),
            ("top", formatar_numero(f.topo)),
            ("width", formatar_numero(f.largura)),
            ("height", formatar_numero(f.altura)),
        ]
        if ocultar_inativas:
            propriedades.append(("oi", "1"))

        corpo = "".join(f":{chave}={_escapar(valor)}" for chave, valor in propriedades)
        return f"{{{{c{ordinal}::image-occlusion:rect{corpo}}}}}"


def uniformizar(
    grupos: list[list[Forma]], alvo: tuple[float, float] | None = None
) -> list[list[Forma]]:
    """Iguala o tamanho de todas as máscaras, mantendo cada uma centrada.

    Por que isto importa, e não é estética: **a largura da máscara entrega o
    tamanho da palavra.** Numa prancha com "Ponte" e "Fosfofrutoquinase-1"
    ocluídas, o retângulo curto só pode ser a primeira. O cartão passa a ser
    respondível pela geometria, sem saber anatomia — e a revisão vira treino de
    reconhecer o formato do borrão.

    Com todas do mesmo tamanho, a única informação que sobra é a posição, que é
    exatamente a que o cartão deveria estar cobrando.

    `alvo` em frações de 0 a 1. Sem ele, usa a maior largura e a maior altura
    encontradas, para que nenhuma máscara fique menor que o texto que cobre.
    """
    todas = [forma for grupo in grupos for forma in grupo]
    if not todas:
        return grupos

    if alvo is None:
        largura_alvo = max(f.largura for f in todas)
        altura_alvo = max(f.altura for f in todas)
    else:
        largura_alvo, altura_alvo = alvo

    uniformes: list[list[Forma]] = []
    for grupo in grupos:
        novo = []
        for forma in grupo:
            centro_x = forma.esquerda + forma.largura / 2
            centro_y = forma.topo + forma.altura / 2
            novo.append(
                Forma(
                    esquerda=centro_x - largura_alvo / 2,
                    topo=centro_y - altura_alvo / 2,
                    largura=largura_alvo,
                    altura=altura_alvo,
                ).limitada()
            )
        uniformes.append(novo)

    return uniformes


def sobreposicao(a: Forma, b: Forma) -> float:
    """Fração da menor das duas caixas que está dentro da outra."""
    a, b = a.limitada(), b.limitada()
    x1 = max(a.esquerda, b.esquerda)
    y1 = max(a.topo, b.topo)
    x2 = min(a.esquerda + a.largura, b.esquerda + b.largura)
    y2 = min(a.topo + a.altura, b.topo + b.altura)
    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersecao = (x2 - x1) * (y2 - y1)
    menor = min(a.largura * a.altura, b.largura * b.altura)
    return intersecao / menor if menor > 0 else 0.0


def montar_campo(grupos: list[list[Forma]], modo: str = ESCONDER_TUDO) -> str:
    """Monta o conteúdo completo do campo `Occlusion`.

    Cada elemento de `grupos` é um cartão. Um grupo com mais de uma forma
    revela todas as suas formas ao mesmo tempo — é o mecanismo para "esta
    etapa da via tem enzima e cofator, e os dois aparecem juntos".
    """
    if modo not in MODOS:
        raise ValueError(f"Modo desconhecido: {modo!r}. Use um de {MODOS}.")
    if not grupos:
        raise ValueError("Nenhum grupo de oclusão: a nota não geraria cartão nenhum.")

    ocultar = modo == ESCONDER_TUDO
    linhas = []
    for ordinal, formas in enumerate(grupos, start=1):
        if not formas:
            raise ValueError(f"O grupo {ordinal} está vazio.")
        for forma in formas:
            linhas.append(forma.para_cloze(ordinal, ocultar))

    return "<br>".join(linhas)


def contar_cartoes(campo: str) -> int:
    """Quantos cartões o Anki vai gerar a partir deste campo."""
    import re

    ordinais = {int(n) for n in re.findall(r"\{\{c(\d+)::image-occlusion:", campo)}
    return len(ordinais)


# ==========================================================================
# de ocluir/caixas.py
# ==========================================================================

# Um pixel conta como tinta quando se afasta do fundo mais que isto, numa
# escala de 0 a 255. Baixo demais pega ruído de compressão de vídeo.
LIMIAR_DE_TINTA = 60
# Faixa ou trecho com menos pixels de tinta que isto é ruído, não texto.
MINIMO_DE_TINTA_NA_LINHA = 2
# Vão em branco, em pixels, que separa dois rótulos vizinhos na horizontal.
# Proporcional à altura da faixa, porque texto grande tem espaço maior.
FATOR_DE_VAO = 0.6


@dataclass
class CaixaDetectada:
    id: int
    caixa: tuple[int, int, int, int]  # esquerda, topo, largura, altura em px
    densidade: float  # fração de tinta dentro da caixa

    def normalizada(
        self, largura: int, altura: int, folga: float = 0.0
    ) -> tuple[float, float, float, float]:
        esq, topo, larg, alt = self.caixa
        mx, my = larg * folga, alt * folga
        esq = max(0.0, esq - mx)
        topo = max(0.0, topo - my)
        larg = min(largura - esq, larg + 2 * mx)
        alt = min(altura - topo, alt + 2 * my)
        return (esq / largura, topo / altura, larg / largura, alt / altura)


def _mascara_de_tinta(imagem: Image.Image) -> tuple[list[int], int, int]:
    """Devolve 1 para pixel de tinta e 0 para fundo, achatado em uma lista."""
    cinza = imagem.convert("L")
    largura, altura = cinza.size
    # Em modo "L" cada pixel é um byte, então tobytes() já é a lista de tons —
    # sem o custo (nem a depreciação) de getdata().
    pixels = cinza.tobytes()

    # O fundo é o tom mais frequente. Em slide e diagrama isso é quase sempre
    # verdade, e é mais robusto que assumir branco — fundo escuro funciona
    # igual.
    histograma = [0] * 256
    for valor in pixels:
        histograma[valor] += 1
    fundo = histograma.index(max(histograma))

    tinta = [1 if abs(p - fundo) > LIMIAR_DE_TINTA else 0 for p in pixels]
    return tinta, largura, altura


def _apagar_linhas(
    tinta: list[int], largura: int, altura: int, limite: int
) -> list[int]:
    """Remove traços longos — bordas de caixa, setas, réguas, sublinhados.

    Sem isto, a projeção de perfil não funciona em fluxograma: a borda vertical
    de um retângulo põe tinta em todas as linhas que ele ocupa, e a imagem
    inteira vira uma faixa só. Foi exatamente o que aconteceu na primeira
    versão — duas "caixas" cobrindo o diagrama inteiro.

    A distinção que sustenta o corte: um traço de letra é curto nas duas
    direções; moldura e seta são longos em uma delas.
    """
    limpo = list(tinta)

    for y in range(altura):
        base = y * largura
        inicio = None
        for x in range(largura + 1):
            aceso = x < largura and tinta[base + x]
            if aceso and inicio is None:
                inicio = x
            elif not aceso and inicio is not None:
                if x - inicio > limite:
                    for k in range(inicio, x):
                        limpo[base + k] = 0
                inicio = None

    for x in range(largura):
        inicio = None
        for y in range(altura + 1):
            aceso = y < altura and tinta[y * largura + x]
            if aceso and inicio is None:
                inicio = y
            elif not aceso and inicio is not None:
                if y - inicio > limite:
                    for k in range(inicio, y):
                        limpo[k * largura + x] = 0
                inicio = None

    return limpo


def _trechos(contagens: list[int], minimo: int, vao_maximo: int) -> list[tuple[int, int]]:
    """Trechos contíguos com tinta, tolerando buracos até `vao_maximo`."""
    trechos: list[tuple[int, int]] = []
    inicio = None
    branco = 0

    for indice, contagem in enumerate(contagens):
        if contagem >= minimo:
            if inicio is None:
                inicio = indice
            branco = 0
        elif inicio is not None:
            branco += 1
            if branco > vao_maximo:
                trechos.append((inicio, indice - branco))
                inicio = None
                branco = 0

    if inicio is not None:
        trechos.append((inicio, len(contagens) - 1 - branco))

    return [(a, b) for a, b in trechos if b >= a]


def detectar(
    caminho: Path | str,
    altura_minima: int = 12,
    largura_minima: int = 18,
    densidade_minima: float = 0.06,
    densidade_maxima: float = 0.92,
    limite_de_linha: int | None = None,
) -> tuple[list[CaixaDetectada], tuple[int, int]]:
    """Acha as caixas de texto prováveis e o tamanho da imagem.

    Os filtros de densidade são o que separa rótulo de moldura: a borda de um
    retângulo tem densidade altíssima na sua caixa (é quase toda tinta), e uma
    região vazia tem densidade quase nula. Texto fica no meio.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Imagem não encontrada: {caminho}")

    with Image.open(caminho) as arquivo:
        imagem = arquivo.convert("RGB")

    tinta, largura, altura = _mascara_de_tinta(imagem)

    if limite_de_linha is None:
        # Acima de ~5% do lado menor, um traço contínuo não é letra.
        limite_de_linha = max(25, int(min(largura, altura) * 0.05))
    tinta = _apagar_linhas(tinta, largura, altura, limite_de_linha)

    por_linha = [
        sum(tinta[y * largura : (y + 1) * largura]) for y in range(altura)
    ]
    faixas = _trechos(por_linha, MINIMO_DE_TINTA_NA_LINHA, vao_maximo=1)

    caixas: list[CaixaDetectada] = []
    for topo, base in faixas:
        alt_faixa = base - topo + 1
        if alt_faixa < altura_minima:
            continue

        por_coluna = [0] * largura
        for y in range(topo, base + 1):
            deslocamento = y * largura
            for x in range(largura):
                if tinta[deslocamento + x]:
                    por_coluna[x] += 1

        vao = max(3, int(alt_faixa * FATOR_DE_VAO))
        for esquerda, direita in _trechos(por_coluna, 1, vao_maximo=vao):
            larg = direita - esquerda + 1
            if larg < largura_minima:
                continue

            total = sum(por_coluna[esquerda : direita + 1])
            densidade = total / (larg * alt_faixa)
            if not (densidade_minima <= densidade <= densidade_maxima):
                continue

            caixas.append(
                CaixaDetectada(
                    id=0, caixa=(esquerda, topo, larg, alt_faixa),
                    densidade=round(densidade, 3),
                )
            )

    caixas.sort(key=lambda c: (c.caixa[1], c.caixa[0]))
    for numero, caixa in enumerate(caixas, start=1):
        caixa.id = numero

    return caixas, (largura, altura)


def desenhar_numeradas(
    caminho_imagem: Path | str,
    caixas: list[CaixaDetectada],
    destino: Path | str,
) -> Path:
    """Escreve a imagem com cada caixa contornada e numerada.

    É esta imagem que se olha para dizer "a caixa 7 é o mesencéfalo" — o passo
    que precisa de leitura, e que nenhuma medição resolve.
    """
    from PIL import ImageDraw, ImageFont

    caminho_imagem = Path(caminho_imagem)
    destino = Path(destino)

    with Image.open(caminho_imagem) as arquivo:
        imagem = arquivo.convert("RGB")

    desenho = ImageDraw.Draw(imagem)
    tamanho = max(11, int(imagem.height * 0.02))
    try:
        fonte = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", tamanho
        )
    except OSError:
        fonte = ImageFont.load_default()

    espessura = max(2, int(min(imagem.size) * 0.0025))

    for caixa in caixas:
        esq, topo, larg, alt = caixa.caixa
        desenho.rectangle(
            (esq, topo, esq + larg, topo + alt), outline=(220, 30, 90), width=espessura
        )
        etiqueta = str(caixa.id)
        limites = desenho.textbbox((0, 0), etiqueta, font=fonte)
        larg_txt = limites[2] - limites[0]
        alt_txt = limites[3] - limites[1]
        y = max(0, topo - alt_txt - 6)
        desenho.rectangle(
            (esq, y, esq + larg_txt + 8, y + alt_txt + 6), fill=(220, 30, 90)
        )
        desenho.text((esq + 4, y + 2), etiqueta, font=fonte, fill=(255, 255, 255))

    destino.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(destino)
    return destino


# ==========================================================================
# de ocluir/portatil.py
# ==========================================================================

SEPARADOR_DE_CAMPOS = "\x1f"
ESQUEMA = 11
ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION = 6

CAMPOS = ["Occlusion", "Image", "Header", "Back Extra", "Comments"]

_QFMT = """{{#Header}}<div>{{Header}}</div>{{/Header}}
<div style="display: none">{{cloze:Occlusion}}</div>
<div id="err"></div>
<div id="image-occlusion-container">
    {{Image}}
    <canvas id="image-occlusion-canvas"></canvas>
</div>
<script>
try {
    anki.imageOcclusion.setup();
} catch (exc) {
    document.getElementById("err").innerHTML = `Error loading image occlusion. \
Is your Anki version up to date?<br><br>${exc}`;
}
</script>
"""

_AFMT = (
    _QFMT
    + """
<div><button id="toggle">Toggle Masks</button></div>
{{#Back Extra}}<div>{{Back Extra}}</div>{{/Back Extra}}
"""
)

# A cor de destaque da forma perguntada (#ff8e8e) e a das demais (#ffeba2) vêm
# daqui. É o que faz a máscara "da vez" aparecer avermelhada e as outras
# amarelas no modo "esconder tudo".
_CSS = """#image-occlusion-canvas {
    --inactive-shape-color: #ffeba2;
    --active-shape-color: #ff8e8e;
    --inactive-shape-border: 1px #212121;
    --active-shape-border: 1px #212121;
    --highlight-shape-color: #ff8e8e00;
    --highlight-shape-border: 1px #ff8e8e;
}

.card {
    font-family: arial;
    font-size: 20px;
    text-align: center;
    color: black;
    background-color: white;
}
"""

_ESQUEMA_SQL = """
CREATE TABLE col (
    id integer primary key, crt integer not null, mod integer not null,
    scm integer not null, ver integer not null, dty integer not null,
    usn integer not null, ls integer not null, conf text not null,
    models text not null, decks text not null, dconf text not null,
    tags text not null
);
CREATE TABLE notes (
    id integer primary key, guid text not null, mid integer not null,
    mod integer not null, usn integer not null, tags text not null,
    flds text not null, sfld integer not null, csum integer not null,
    flags integer not null, data text not null
);
CREATE TABLE cards (
    id integer primary key, nid integer not null, did integer not null,
    ord integer not null, mod integer not null, usn integer not null,
    type integer not null, queue integer not null, due integer not null,
    ivl integer not null, factor integer not null, reps integer not null,
    lapses integer not null, left integer not null, odue integer not null,
    odid integer not null, flags integer not null, data text not null
);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE TABLE revlog (
    id integer primary key, cid integer not null, usn integer not null,
    ease integer not null, ivl integer not null, lastIvl integer not null,
    factor integer not null, time integer not null, type integer not null
);
CREATE INDEX ix_notes_usn on notes (usn);
CREATE INDEX ix_cards_usn on cards (usn);
CREATE INDEX ix_cards_nid on cards (nid);
CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_revlog_cid on revlog (cid);
CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_notes_csum on notes (csum);
"""

_CONF_PADRAO = {
    "activeDecks": [1], "curDeck": 1, "newSpread": 0, "collapseTime": 1200,
    "timeLim": 0, "estTimes": True, "dueCounts": True, "curModel": None,
    "nextPos": 1, "sortType": "noteFld", "sortBackwards": False,
    "addToCur": True, "dayLearnFirst": False, "schedVer": 2,
}

_DCONF_PADRAO = {
    "1": {
        "id": 1, "mod": 0, "name": "Default", "usn": 0, "maxTaken": 60,
        "autoplay": True, "timer": 0, "replayq": True,
        "new": {"bury": False, "delays": [1.0, 10.0], "initialFactor": 2500,
                "ints": [1, 4, 0], "order": 1, "perDay": 20},
        "rev": {"bury": False, "ease4": 1.3, "ivlFct": 1.0, "maxIvl": 36500,
                "perDay": 200, "hardFactor": 1.2},
        "lapse": {"delays": [10.0], "leechAction": 1, "leechFails": 8,
                  "minInt": 1, "mult": 0.0},
        "dyn": False, "newMix": 0, "newPerDayMinimum": 0, "interdayLearningMix": 0,
        "reviewOrder": 0, "newSortOrder": 0, "newGatherPriority": 0,
        "buryInterdayLearning": False, "fsrsWeights": [], "desiredRetention": 0.9,
        "ignoreRevlogsBeforeDate": "", "stopTimerOnAnswer": False,
        "secondsToShowQuestion": 0.0, "secondsToShowAnswer": 0.0,
        "questionAction": 0, "answerAction": 0, "waitForAudio": True,
        "sm2Retention": 0.9, "weightSearch": "",
    }
}


def _agora_ms() -> int:
    return int(time.time() * 1000)


def _guid(semente: str) -> str:
    """Identificador estável da nota, derivado do conteúdo.

    Base91 do jeito do Anki seria mais fiel, mas qualquer texto único serve —
    o que importa é que reimportar o mesmo pacote reconheça a mesma nota em vez
    de duplicá-la.
    """
    import base64

    digest = hashlib.sha1(semente.encode("utf-8")).digest()[:8]
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def _checksum(primeiro_campo: str) -> int:
    """Os 8 primeiros dígitos hex do sha1 do primeiro campo, como inteiro."""
    import re

    texto = re.sub(r"<[^>]+>", "", primeiro_campo)
    return int(hashlib.sha1(texto.encode("utf-8")).hexdigest()[:8], 16)


def _ordinais(campo_occlusion: str) -> list[int]:
    import re

    return sorted({int(n) for n in re.findall(r"\{\{c(\d+)::", campo_occlusion)})


def _montar_notetype(id_do_notetype: int) -> dict:
    return {
        "id": id_do_notetype,
        "name": "Image Occlusion",
        "type": 1,  # cloze
        "mod": int(time.time()),
        "usn": -1,
        "sortf": 0,
        "did": 1,
        "originalStockKind": ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION,
        "tmpls": [
            {
                "name": "Image Occlusion", "ord": 0,
                "qfmt": _QFMT, "afmt": _AFMT,
                "bqfmt": "", "bafmt": "", "did": None,
                "bfont": "", "bsize": 0, "id": id_do_notetype + 1,
            }
        ],
        "flds": [
            {
                "name": nome, "ord": posicao, "sticky": False, "rtl": False,
                "font": "Arial", "size": 20, "description": "",
                "plainText": posicao == 0, "collapsed": False,
                "excludeFromSearch": False, "id": None, "tag": None,
                "preventDeletion": posicao < 4,
            }
            for posicao, nome in enumerate(CAMPOS)
        ],
        "css": _CSS,
        "latexPre": "\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n"
        "\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n"
        "\\setlength{\\parindent}{0in}\n\\begin{document}\n",
        "latexPost": "\\end{document}",
        "latexsvg": False,
        "req": [[0, "any", [0, 1, 2]]],
    }


def _montar_decks(nomes: list[str]) -> tuple[dict, dict[str, int]]:
    """Cria o deck e todos os pais implícitos de um nome com `::`."""
    decks = {
        "1": {
            "id": 1, "name": "Default", "mod": 0, "usn": 0, "desc": "",
            "dyn": 0, "collapsed": False, "browserCollapsed": False,
            "extendNew": 0, "extendRev": 0, "conf": 1,
            "newToday": [0, 0], "revToday": [0, 0], "lrnToday": [0, 0],
            "timeToday": [0, 0],
        }
    }
    por_nome: dict[str, int] = {"Default": 1}
    proximo = _agora_ms()

    caminhos: list[str] = []
    for nome in nomes:
        partes = nome.split("::")
        for indice in range(1, len(partes) + 1):
            caminho = "::".join(partes[:indice])
            if caminho not in caminhos:
                caminhos.append(caminho)

    for caminho in caminhos:
        if caminho in por_nome:
            continue
        proximo += 1
        decks[str(proximo)] = {
            "id": proximo, "name": caminho, "mod": 0, "usn": 0, "desc": "",
            "dyn": 0, "collapsed": False, "browserCollapsed": False,
            "extendNew": 0, "extendRev": 0, "conf": 1,
            "newToday": [0, 0], "revToday": [0, 0], "lrnToday": [0, 0],
            "timeToday": [0, 0],
        }
        por_nome[caminho] = proximo

    return decks, por_nome


@dataclass
class NotaPortatil:
    imagem: Path
    campo_occlusion: str
    cabecalho: str = ""
    verso_extra: str = ""
    comentarios: str = ""
    tags: list[str] | None = None
    deck: str = "Medicina::Anatomia"


def gerar_apkg(notas: list[NotaPortatil], destino: Path | str) -> tuple[Path, int]:
    """Escreve o `.apkg` e devolve (caminho, total de cartões)."""
    if not notas:
        raise ValueError("Nenhuma nota para empacotar.")

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    agora_ms = _agora_ms()
    agora_s = int(time.time())
    id_do_notetype = agora_ms

    decks, id_por_deck = _montar_decks(sorted({n.deck for n in notas}))
    notetype = _montar_notetype(id_do_notetype)

    caminho_sqlite = destino.with_suffix(".tmp.anki2")
    if caminho_sqlite.exists():
        caminho_sqlite.unlink()

    conexao = sqlite3.connect(caminho_sqlite)
    try:
        conexao.executescript(_ESQUEMA_SQL)
        conexao.execute(
            "INSERT INTO col VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                agora_s - 86400 * 3,  # início do dia da coleção, no passado
                agora_ms,
                agora_ms,
                ESQUEMA,
                0,
                0,
                0,
                json.dumps(_CONF_PADRAO),
                json.dumps({str(id_do_notetype): notetype}),
                json.dumps(decks),
                json.dumps(_DCONF_PADRAO),
                json.dumps({}),
            ),
        )

        midias: dict[str, str] = {}
        total_de_cartoes = 0
        id_da_nota = agora_ms
        id_do_cartao = agora_ms

        for nota in notas:
            imagem = Path(nota.imagem)
            if not imagem.exists():
                raise FileNotFoundError(f"Imagem não encontrada: {imagem}")

            ordinais = _ordinais(nota.campo_occlusion)
            if not ordinais:
                raise ValueError(
                    "O campo de oclusão não tem nenhuma cloze — a nota não "
                    "geraria cartão nenhum."
                )

            if imagem.name not in midias.values():
                midias[str(len(midias))] = imagem.name
            nome_na_midia = imagem.name

            valores = [
                nota.campo_occlusion,
                f'<img src="{nome_na_midia}">',
                nota.cabecalho,
                nota.verso_extra,
                nota.comentarios,
            ]
            campos = SEPARADOR_DE_CAMPOS.join(valores)

            id_da_nota += 1
            conexao.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    id_da_nota,
                    _guid(campos),
                    id_do_notetype,
                    agora_s,
                    -1,
                    " " + " ".join(nota.tags or []) + " " if nota.tags else "",
                    campos,
                    valores[0],
                    _checksum(valores[0]),
                    0,
                    "",
                ),
            )

            id_do_deck = id_por_deck[nota.deck]
            for ordinal in ordinais:
                id_do_cartao += 1
                conexao.execute(
                    "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        id_do_cartao, id_da_nota, id_do_deck,
                        ordinal - 1,  # `ord` é base zero; a cloze é base um
                        agora_s, -1,
                        0,  # type: novo
                        0,  # queue: novo
                        total_de_cartoes + 1,  # due: posição na fila de novos
                        0, 0, 0, 0, 0, 0, 0, 0, "",
                    ),
                )
                total_de_cartoes += 1

        conexao.commit()
    finally:
        conexao.close()

    caminhos_de_midia = {}
    for indice, nome in midias.items():
        for nota in notas:
            if Path(nota.imagem).name == nome:
                caminhos_de_midia[indice] = Path(nota.imagem)
                break

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.write(caminho_sqlite, "collection.anki2")
        pacote.writestr("media", json.dumps(midias))
        for indice, caminho in caminhos_de_midia.items():
            pacote.write(caminho, indice)

    caminho_sqlite.unlink()
    return destino, total_de_cartoes



# ==========================================================================
# Fachada — o que se chama no chat
# ==========================================================================


def criar_apkg(
    imagem,
    caixas_detectadas,
    grupos,
    destino,
    titulo="",
    deck="Medicina::Anatomia",
    modo=ESCONDER_TUDO,
    tags=None,
    verso_extra="",
    folga=0.06,
    uniforme=True,
):
    """Monta o .apkg a partir das caixas medidas e dos grupos que você decidiu.

    `grupos` é uma lista de dicionários. Cada um vira **um cartão**:

        {"rotulo": "Hexoquinase", "caixas": [3]}          # por número de caixa
        {"rotulo": "Etapa 3", "caixas": [7, 8]}           # duas máscaras juntas
        {"rotulo": "Sem legenda", "caixa": [.1,.2,.3,.05]}  # à mão, em frações

    O `rotulo` não aparece no cartão — o cartão mostra a imagem com a máscara.
    Ele existe para você conferir o que decidiu e para as mensagens de erro.
    """
    from pathlib import Path as _Path

    imagem = _Path(imagem)
    with Image.open(imagem) as arquivo:
        largura, altura = arquivo.size

    por_id = {c.id: c for c in caixas_detectadas}
    formas_por_grupo = []

    for indice, grupo in enumerate(grupos, start=1):
        rotulo = grupo.get("rotulo", f"grupo {indice}")
        formas = []

        if grupo.get("caixa"):
            valores = grupo["caixa"]
            if len(valores) != 4:
                raise ValueError(
                    f"{rotulo!r}: 'caixa' precisa de 4 números "
                    f"[esquerda, topo, largura, altura] em frações de 0 a 1."
                )
            formas.append(Forma(*(float(v) for v in valores)))
        else:
            numeros = grupo.get("caixas") or []
            if not numeros:
                raise ValueError(
                    f"{rotulo!r}: nem 'caixas' nem 'caixa' — não há o que ocluir."
                )
            for numero in numeros:
                if numero not in por_id:
                    disponiveis = ", ".join(str(i) for i in sorted(por_id))
                    raise ValueError(
                        f"{rotulo!r}: a caixa {numero} não existe. "
                        f"Disponíveis: {disponiveis}"
                    )
                formas.append(
                    Forma(*por_id[numero].normalizada(largura, altura, folga))
                )

        formas_por_grupo.append(formas)

    # Máscaras do mesmo tamanho: sem isto, a largura do retângulo entrega o
    # comprimento da palavra e o cartão fica respondível pela geometria.
    if uniforme:
        formas_por_grupo = uniformizar(
            formas_por_grupo, uniforme if isinstance(uniforme, tuple) else None
        )

    campo = montar_campo(formas_por_grupo, modo)

    nota = NotaPortatil(
        imagem=imagem,
        campo_occlusion=campo,
        cabecalho=titulo,
        verso_extra=verso_extra,
        tags=list(tags or ["oclusao"]),
        deck=deck,
    )
    return gerar_apkg([nota], destino)


def previa_das_mascaras(
    imagem, caixas_detectadas, grupos, destino, folga=0.06, uniforme=True
):
    """Desenha as máscaras sobre a imagem, para conferir antes de gerar.

    Vale o mesmo que no fluxo do computador: máscara torta é invisível numa
    lista de números e óbvia numa imagem.
    """
    from pathlib import Path as _Path
    from PIL import ImageDraw

    imagem = _Path(imagem)
    with Image.open(imagem) as arquivo:
        base = arquivo.convert("RGB")
    largura, altura = base.size
    desenho = ImageDraw.Draw(base)
    por_id = {c.id: c for c in caixas_detectadas}

    por_grupo = []
    for grupo in grupos:
        alvos = []
        if grupo.get("caixa"):
            alvos.append(Forma(*(float(v) for v in grupo["caixa"])))
        else:
            for numero in grupo.get("caixas") or []:
                if numero in por_id:
                    alvos.append(
                        Forma(*por_id[numero].normalizada(largura, altura, folga))
                    )
        por_grupo.append(alvos)

    if uniforme:
        por_grupo = uniformizar(
            por_grupo, uniforme if isinstance(uniforme, tuple) else None
        )

    for alvos in por_grupo:
        for forma in alvos:
            f = forma.limitada()
            desenho.rectangle(
                (
                    int(f.esquerda * largura),
                    int(f.topo * altura),
                    int((f.esquerda + f.largura) * largura),
                    int((f.topo + f.altura) * altura),
                ),
                fill=(255, 202, 0),
            )

    destino = _Path(destino)
    base.save(destino)
    return destino
