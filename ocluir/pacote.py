"""Gera um arquivo `.apkg` — o caminho que chega no AnkiDroid sem passar por PC.

Por que este módulo existe, já que já havia o `anki.py`:

O AnkiConnect **não existe no AnkiDroid**. Ele é um complemento do Anki de
computador, e complementos são código Python que o app Android não roda. Então
o caminho `Claude → AnkiConnect → Anki` só funciona com o computador ligado, o
Anki aberto, e depois ainda depende de sincronizar para o tablet.

O `.apkg` é o caminho direto: um arquivo que carrega as notas *e* as imagens
dentro dele. Você toca nele no Android e o AnkiDroid importa. Nenhum
computador, nenhum servidor, nenhuma conta.

A construção usa a biblioteca oficial do Anki em vez de montar o SQLite à mão.
A diferença importa: o notetype de oclusão é um *stock notetype* com
`originalStockKind = 6`, e é essa marca que faz o revisor tratar o campo
Occlusion como oclusão em vez de texto. Um notetype montado à mão com os mesmos
campos e os mesmos templates não tem essa marca, e o cartão importa mas não
desenha máscara nenhuma.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path


class AnkiLibAusente(RuntimeError):
    def __init__(self):
        super().__init__(
            "Este comando precisa da biblioteca oficial do Anki:\n"
            "  pip install anki\n"
            "(é a mesma engine do programa, usada aqui só para escrever o "
            "arquivo .apkg — não precisa do Anki instalado)"
        )


@dataclass
class NotaDeOclusao:
    """Uma nota pronta para virar cartões dentro do pacote."""

    imagem: Path
    campo_occlusion: str
    cabecalho: str = ""
    verso_extra: str = ""
    comentarios: str = ""
    tags: list[str] | None = None
    deck: str = "Medicina::Anatomia"


def _abrir_colecao(caminho: Path):
    try:
        import anki.collection
    except ImportError as erro:
        raise AnkiLibAusente() from erro
    return anki.collection.Collection(str(caminho))


def _notetype_de_oclusao(colecao):
    """Acha o notetype nativo pela marca de origem, não pelo nome.

    Procurar por "Image Occlusion" pelo nome quebra se a coleção estiver em
    outro idioma. `originalStockKind` é um número e não é traduzido.
    """
    from anki import notetypes_pb2

    esperado = notetypes_pb2.StockNotetype.OriginalStockKind.Value(
        "ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION"
    )

    for referencia in colecao.models.all_names_and_ids():
        notetype = colecao.models.get(referencia.id)
        if notetype and notetype.get("originalStockKind") == esperado:
            return notetype

    raise RuntimeError(
        "Notetype de oclusão não encontrado na coleção recém-criada. "
        "Isso indica uma versão da biblioteca anki anterior à 23.10."
    )


def montar(
    notas: list[NotaDeOclusao],
    destino: Path | str,
    deck: str | None = None,
) -> tuple[Path, int]:
    """Escreve o `.apkg` e devolve (caminho, quantidade de cartões gerados)."""
    if not notas:
        raise ValueError("Nenhuma nota para empacotar.")

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    from anki import generic_pb2, import_export_pb2

    with tempfile.TemporaryDirectory() as temporario:
        colecao = _abrir_colecao(Path(temporario) / "montagem.anki2")
        try:
            notetype = _notetype_de_oclusao(colecao)
            nomes_dos_campos = [c["name"] for c in notetype["flds"]]
            # `deck` como argumento sobrepõe o de cada nota; sem ele, cada uma
            # vai para o seu, que é o que permite empacotar anatomia e
            # bioquímica no mesmo arquivo.
            ids_de_decks: dict[str, int] = {}

            cartoes = 0
            for nota in notas:
                if not nota.imagem.exists():
                    raise FileNotFoundError(f"Imagem não encontrada: {nota.imagem}")

                # add_file copia para a pasta de mídia e devolve o nome final,
                # que pode diferir do original se houver colisão.
                nome_na_midia = colecao.media.add_file(str(nota.imagem))

                registro = colecao.new_note(notetype)
                valores = [
                    nota.campo_occlusion,
                    f'<img src="{nome_na_midia}">',
                    nota.cabecalho,
                    nota.verso_extra,
                    nota.comentarios,
                ]
                for posicao, valor in enumerate(valores):
                    if posicao < len(nomes_dos_campos):
                        registro[nomes_dos_campos[posicao]] = valor

                registro.tags = list(nota.tags or [])
                nome_do_deck = deck or nota.deck
                if nome_do_deck not in ids_de_decks:
                    ids_de_decks[nome_do_deck] = colecao.decks.id(nome_do_deck)
                colecao.add_note(registro, ids_de_decks[nome_do_deck])
                cartoes += len(registro.card_ids())

            opcoes = import_export_pb2.ExportAnkiPackageOptions(
                with_scheduling=False,
                with_deck_configs=False,
                with_media=True,
                # legacy=False produz o formato novo (.colpkg/zstd). O AnkiDroid
                # lê os dois, mas o antigo é aceito por mais versões.
                legacy=True,
            )
            limite = colecao.export_anki_package(
                out_path=str(destino),
                options=opcoes,
                limit=import_export_pb2.ExportLimit(
                    whole_collection=generic_pb2.Empty()
                ),
            )
            del limite
        finally:
            colecao.close()

    return destino, cartoes


def conferir(caminho: Path | str) -> dict:
    """Reimporta o pacote numa coleção limpa e relata o que de fato entrou.

    É a única verificação que vale: um `.apkg` malformado é aceito na escrita e
    só falha na importação, no aparelho, quando já não dá para consertar.
    """
    caminho = Path(caminho)
    from anki import generic_pb2, import_export_pb2

    with tempfile.TemporaryDirectory() as temporario:
        colecao = _abrir_colecao(Path(temporario) / "conferencia.anki2")
        try:
            pedido = import_export_pb2.ImportAnkiPackageRequest(
                package_path=str(caminho),
                options=import_export_pb2.ImportAnkiPackageOptions(
                    merge_notetypes=False,
                    update_notes=import_export_pb2.ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    update_notetypes=import_export_pb2.ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    with_scheduling=False,
                    with_deck_configs=False,
                ),
            )
            colecao.import_anki_package(pedido)

            ids_de_notas = colecao.find_notes("")
            ids_de_cartoes = colecao.find_cards("")
            notetype = _notetype_de_oclusao(colecao)

            midias = []
            pasta = Path(colecao.media.dir())
            if pasta.exists():
                midias = sorted(p.name for p in pasta.iterdir() if p.is_file())

            amostra = None
            if ids_de_cartoes:
                cartao = colecao.get_card(ids_de_cartoes[0])
                amostra = cartao.render_output().question_text

            return {
                "notas": len(ids_de_notas),
                "cartoes": len(ids_de_cartoes),
                "notetype": notetype["name"],
                "stock_kind": notetype.get("originalStockKind"),
                "midias": midias,
                "decks": [d.name for d in colecao.decks.all_names_and_ids()],
                "frente_renderizada": amostra,
            }
        finally:
            colecao.close()
