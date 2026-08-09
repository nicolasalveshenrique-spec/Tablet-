"""Gerador de `.apkg` sem dependência nenhuma — só a biblioteca padrão.

Existe porque o `pacote.py` depende da biblioteca oficial do Anki, e no chat do
Claude o sandbox que roda Python nem sempre consegue instalar pacote. Este
módulo escreve o mesmo arquivo usando apenas `sqlite3`, `zipfile`, `json` e
`hashlib`, que existem em qualquer Python.

O formato é o `.apkg` legado (esquema 11): um ZIP com

    collection.anki2   o SQLite da coleção
    media              um JSON {"0": "encefalo.png"}
    0, 1, 2 …          os arquivos de mídia, renomeados para o índice

A parte que não dá para improvisar é o notetype. O revisor só desenha máscara
quando a nota usa o notetype nativo de oclusão, identificado por
`originalStockKind = 6`. Os templates e o CSS abaixo foram extraídos de uma
coleção real criada pela biblioteca oficial, não escritos à mão — e o resultado
deste módulo é conferido, nos testes, reimportando o pacote com essa mesma
biblioteca.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

SEPARADOR_DE_CAMPOS = "\x1f"
ESQUEMA = 11
ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION = 6

# O `meta` é um protobuf de um campo só: `version = 2`, que é o "Legacy2".
# Sem ele o importador cai no caminho "Legacy1", e foi exatamente aí que o
# AnkiDroid quebrou com "stream did not contain valid UTF-8" — um pacote que a
# biblioteca de computador lia sem reclamar.
#
# Legacy2 é a forma que o próprio Anki exporta com `legacy=True`: os dados vão
# em `collection.anki21` e `collection.anki2` fica como resquício para clientes
# muito antigos. Imitar o que o Anki produz é mais seguro que imitar o que a
# documentação permite.
META_LEGACY2 = b"\x08\x02"
NOME_DA_COLECAO = "collection.anki21"
NOME_DA_COLECAO_ANTIGA = "collection.anki2"

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
        pacote.writestr("meta", META_LEGACY2)
        # A mesma base entra com os dois nomes: o importador moderno lê
        # `collection.anki21` porque o `meta` diz versão 2, e o antigo lê
        # `collection.anki2`. Duplicar comprimido custa pouco e evita ter de
        # decidir o que um cliente de 2018 deveria ver.
        pacote.write(caminho_sqlite, NOME_DA_COLECAO)
        pacote.write(caminho_sqlite, NOME_DA_COLECAO_ANTIGA)
        pacote.writestr("media", json.dumps(midias, separators=(",", ":")))
        for indice, caminho in caminhos_de_midia.items():
            pacote.write(caminho, indice)

    caminho_sqlite.unlink()
    return destino, total_de_cartoes
