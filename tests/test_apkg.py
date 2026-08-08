"""O `.apkg` gerado sem dependência, conferido pela biblioteca oficial do Anki.

Esta é a validação que importa. Um pacote malformado é aceito na escrita e só
falha na importação — no tablet, quando já não há como consertar. Escrever com
uma implementação e ler com outra, independente, é o que dá confiança de que o
arquivo chega inteiro no AnkiDroid.

Os testes que dependem da biblioteca `anki` são pulados quando ela não está
instalada, porque a geração em si não precisa dela — esse é o ponto.
"""

from pathlib import Path

import pytest
from PIL import Image

from ocluir.oclusao import ESCONDER_TUDO, ESCONDER_UMA, Forma, montar_campo
from ocluir.portatil import NotaPortatil, _checksum, _montar_decks, _ordinais, gerar_apkg

try:
    import anki.collection  # noqa: F401

    from ocluir import pacote

    TEM_ANKI = True
except ImportError:  # pragma: no cover
    TEM_ANKI = False

precisa_da_lib = pytest.mark.skipif(not TEM_ANKI, reason="biblioteca anki ausente")


@pytest.fixture
def imagem(tmp_path):
    caminho = tmp_path / "diagrama.png"
    Image.new("RGB", (800, 600), "white").save(caminho)
    return caminho


@pytest.fixture
def campo_com_tres_cartoes():
    return montar_campo(
        [
            [Forma(0.1, 0.1, 0.2, 0.05)],
            [Forma(0.4, 0.1, 0.2, 0.05)],
            [Forma(0.7, 0.1, 0.2, 0.05)],
        ],
        ESCONDER_TUDO,
    )


class TestPecasInternas:
    def test_ordinais_ignora_repeticao(self):
        campo = (
            "{{c1::image-occlusion:rect:left=0}}<br>"
            "{{c1::image-occlusion:rect:left=1}}<br>"
            "{{c3::image-occlusion:rect:left=2}}"
        )
        assert _ordinais(campo) == [1, 3]

    def test_checksum_ignora_html(self):
        assert _checksum("<b>abc</b>") == _checksum("abc")

    def test_checksum_cabe_em_inteiro(self):
        assert 0 <= _checksum("Telencéfalo") < 2**32

    def test_decks_criam_os_pais_implicitos(self):
        decks, por_nome = _montar_decks(["Medicina::Anatomia::Cabeça"])
        assert set(por_nome) == {
            "Default",
            "Medicina",
            "Medicina::Anatomia",
            "Medicina::Anatomia::Cabeça",
        }
        assert len(decks) == 4

    def test_decks_nao_duplicam_pai_compartilhado(self):
        _, por_nome = _montar_decks(["Medicina::Anatomia", "Medicina::Bioquímica"])
        assert len(por_nome) == 4  # Default + Medicina + os dois filhos


class TestGeracao:
    def test_escreve_um_zip_com_as_pecas_certas(self, imagem, campo_com_tres_cartoes, tmp_path):
        import zipfile

        destino, cartoes = gerar_apkg(
            [NotaPortatil(imagem=imagem, campo_occlusion=campo_com_tres_cartoes)],
            tmp_path / "saida.apkg",
        )
        assert cartoes == 3

        with zipfile.ZipFile(destino) as pacote_zip:
            nomes = set(pacote_zip.namelist())
            assert "collection.anki2" in nomes
            assert "media" in nomes
            assert "0" in nomes  # a imagem, renomeada para o índice

    def test_nao_deixa_sqlite_temporario_para_tras(self, imagem, campo_com_tres_cartoes, tmp_path):
        destino, _ = gerar_apkg(
            [NotaPortatil(imagem=imagem, campo_occlusion=campo_com_tres_cartoes)],
            tmp_path / "saida.apkg",
        )
        assert not destino.with_suffix(".tmp.anki2").exists()

    def test_sem_nota_reclama(self, tmp_path):
        with pytest.raises(ValueError, match="Nenhuma nota"):
            gerar_apkg([], tmp_path / "x.apkg")

    def test_campo_sem_cloze_reclama(self, imagem, tmp_path):
        with pytest.raises(ValueError, match="nenhuma cloze"):
            gerar_apkg(
                [NotaPortatil(imagem=imagem, campo_occlusion="texto qualquer")],
                tmp_path / "x.apkg",
            )

    def test_imagem_ausente_reclama(self, campo_com_tres_cartoes, tmp_path):
        with pytest.raises(FileNotFoundError):
            gerar_apkg(
                [
                    NotaPortatil(
                        imagem=Path("/nao/existe.png"),
                        campo_occlusion=campo_com_tres_cartoes,
                    )
                ],
                tmp_path / "x.apkg",
            )


@precisa_da_lib
class TestConferidoPelaLibOficial:
    def test_ida_e_volta_preserva_notas_cartoes_e_midia(
        self, imagem, campo_com_tres_cartoes, tmp_path
    ):
        destino, _ = gerar_apkg(
            [
                NotaPortatil(
                    imagem=imagem,
                    campo_occlusion=campo_com_tres_cartoes,
                    cabecalho="Divisões do encéfalo",
                    verso_extra="uma observação",
                    tags=["oclusao", "disc::anatomia"],
                    deck="Medicina::Anatomia",
                )
            ],
            tmp_path / "saida.apkg",
        )

        relatorio = pacote.conferir(destino)
        assert relatorio["notas"] == 1
        assert relatorio["cartoes"] == 3
        assert relatorio["midias"] == ["diagrama.png"]
        assert "Medicina::Anatomia" in relatorio["decks"]

    def test_usa_o_notetype_nativo_de_oclusao(
        self, imagem, campo_com_tres_cartoes, tmp_path
    ):
        """`originalStockKind = 6` é o que faz o revisor desenhar máscara.

        Um notetype com os mesmos campos e templates, mas sem essa marca,
        importa sem erro e mostra a imagem sem oclusão nenhuma.
        """
        destino, _ = gerar_apkg(
            [NotaPortatil(imagem=imagem, campo_occlusion=campo_com_tres_cartoes)],
            tmp_path / "saida.apkg",
        )
        relatorio = pacote.conferir(destino)
        assert relatorio["stock_kind"] == 6

    def test_a_frente_renderiza_a_forma_ativa_e_as_inativas(
        self, imagem, campo_com_tres_cartoes, tmp_path
    ):
        """No modo esconder-tudo, uma forma é a perguntada e as outras cobrem.

        A forma ativa recebe `class="cloze"` e é desenhada com a cor de
        destaque; as demais recebem `cloze-inactive`. É o comportamento que o
        Nicolas descreveu como "a que fica vermelhinha".
        """
        destino, _ = gerar_apkg(
            [NotaPortatil(imagem=imagem, campo_occlusion=campo_com_tres_cartoes)],
            tmp_path / "saida.apkg",
        )
        frente = pacote.conferir(destino)["frente_renderizada"]

        assert 'class="cloze" data-ordinal="1"' in frente
        assert frente.count('class="cloze-inactive"') == 2
        assert 'data-occludeInactive="1"' in frente
        assert 'data-shape="rect"' in frente

    def test_modo_esconder_uma_nao_oculta_as_outras(self, imagem, tmp_path):
        campo = montar_campo(
            [[Forma(0.1, 0.1, 0.2, 0.05)], [Forma(0.4, 0.1, 0.2, 0.05)]],
            ESCONDER_UMA,
        )
        destino, _ = gerar_apkg(
            [NotaPortatil(imagem=imagem, campo_occlusion=campo)],
            tmp_path / "saida.apkg",
        )
        frente = pacote.conferir(destino)["frente_renderizada"]
        assert "data-occludeInactive" not in frente

    def test_varias_notas_em_decks_diferentes(self, imagem, campo_com_tres_cartoes, tmp_path):
        outra = tmp_path / "outra.png"
        Image.new("RGB", (400, 300), "white").save(outra)

        destino, cartoes = gerar_apkg(
            [
                NotaPortatil(
                    imagem=imagem,
                    campo_occlusion=campo_com_tres_cartoes,
                    deck="Medicina::Anatomia",
                ),
                NotaPortatil(
                    imagem=outra,
                    campo_occlusion=montar_campo(
                        [[Forma(0.1, 0.1, 0.2, 0.05)]], ESCONDER_TUDO
                    ),
                    deck="Medicina::Bioquímica",
                ),
            ],
            tmp_path / "saida.apkg",
        )
        assert cartoes == 4

        relatorio = pacote.conferir(destino)
        assert relatorio["notas"] == 2
        assert relatorio["cartoes"] == 4
        assert sorted(relatorio["midias"]) == ["diagrama.png", "outra.png"]
        assert {"Medicina::Anatomia", "Medicina::Bioquímica"} <= set(relatorio["decks"])

    def test_tags_chegam_do_outro_lado(self, imagem, campo_com_tres_cartoes, tmp_path):
        destino, _ = gerar_apkg(
            [
                NotaPortatil(
                    imagem=imagem,
                    campo_occlusion=campo_com_tres_cartoes,
                    tags=["oclusao", "pergunta::divisoes-encefalo", "disc::anatomia"],
                )
            ],
            tmp_path / "saida.apkg",
        )

        import tempfile

        with tempfile.TemporaryDirectory() as temporario:
            colecao = pacote._abrir_colecao(Path(temporario) / "c.anki2")
            try:
                from anki import import_export_pb2 as iep

                colecao.import_anki_package(
                    iep.ImportAnkiPackageRequest(
                        package_path=str(destino),
                        options=iep.ImportAnkiPackageOptions(
                            merge_notetypes=False,
                            with_scheduling=False,
                            with_deck_configs=False,
                        ),
                    )
                )
                assert colecao.find_notes("tag:pergunta::divisoes-encefalo")
                assert colecao.find_notes("tag:disc::anatomia")
            finally:
                colecao.close()
