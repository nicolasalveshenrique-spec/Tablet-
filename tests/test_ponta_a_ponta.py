"""Do PNG à nota inserida, passando por todos os comandos.

É o teste que pega o tipo de quebra que os testes de unidade não pegam: um
comando que grava um plano que o comando seguinte não consegue ler.
"""

import shutil
import sys
from pathlib import Path

import pytest

from ocluir.cli import principal
from ocluir.plano import Grupo, Plano

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exemplos"))

from tests.test_anki import AnkiFalso, servidor  # noqa: F401,E402

precisa_de_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract não instalado"
)


@pytest.fixture
def diagrama(tmp_path):
    from gerar_exemplos import gerar_encefalo

    destino = tmp_path / "encefalo.png"
    shutil.copy(gerar_encefalo(), destino)
    return destino


@precisa_de_tesseract
class TestFluxoCompleto:
    def test_ler_produz_plano_com_candidatos(self, diagrama, tmp_path, capsys):
        codigo = principal(
            [
                "ler",
                str(diagrama),
                "--titulo",
                "Divisões do encéfalo",
                "--pergunta",
                "divisoes-encefalo",
                "--disciplina",
                "anatomia",
                "--aula",
                "2026-08-10",
            ]
        )
        assert codigo == 0

        plano_json = diagrama.with_suffix(".plano.json")
        assert plano_json.exists()

        plano = Plano.carregar(plano_json)
        assert plano.imagem == "encefalo.png"
        assert plano.tamanho == [1400, 900]
        assert plano.grupos == []  # a decisão continua em aberto, de propósito

        textos = {c["texto"] for c in plano.candidatos}
        # Os rótulos que interessam foram achados e não vieram grudados.
        assert "Telencefalo" in textos
        assert "Bulbo" in textos
        assert "Tronco encefalico" in textos

        for candidato in plano.candidatos:
            assert len(candidato["caixa_px"]) == 4

    def test_previa_desenha_uma_mascara_por_grupo(self, diagrama, capsys):
        principal(["ler", str(diagrama), "--titulo", "T", "--pergunta", "p"])
        plano_json = diagrama.with_suffix(".plano.json")

        plano = Plano.carregar(plano_json)
        alvos = {c["texto"]: c["id"] for c in plano.candidatos}
        plano.grupos = [
            Grupo(rotulo="Telencéfalo", tokens=[alvos["Telencefalo"]]),
            Grupo(rotulo="Bulbo", tokens=[alvos["Bulbo"]]),
        ]
        plano.salvar(plano_json)

        assert principal(["previa", str(plano_json)]) == 0
        assert diagrama.with_name("encefalo-previa.png").exists()
        assert diagrama.with_name("encefalo-previa-conferencia.png").exists()
        assert "2 cartões" in capsys.readouterr().out

    def test_enviar_monta_a_nota_certa(self, diagrama, servidor, capsys):  # noqa: F811
        endereco, falso = servidor

        principal(
            [
                "ler",
                str(diagrama),
                "--titulo",
                "Divisões do encéfalo",
                "--pergunta",
                "divisoes-encefalo",
                "--disciplina",
                "anatomia",
                "--aula",
                "2026-08-10",
                "--deck",
                "Medicina::Anatomia",
            ]
        )
        plano_json = diagrama.with_suffix(".plano.json")
        plano = Plano.carregar(plano_json)
        alvos = {c["texto"]: c["id"] for c in plano.candidatos}
        plano.grupos = [
            Grupo(rotulo="Telencéfalo", tokens=[alvos["Telencefalo"]]),
            Grupo(rotulo="Diencéfalo", tokens=[alvos["Diencefalo"]]),
            Grupo(rotulo="Bulbo", tokens=[alvos["Bulbo"]]),
        ]
        plano.salvar(plano_json)

        assert principal(["enviar", str(plano_json), "--endereco", endereco]) == 0

        nota = [p for p in falso.recebidas if p["action"] == "addNote"][0]["params"]["note"]

        assert nota["deckName"] == "Medicina::Anatomia"
        assert nota["tags"] == [
            "oclusao",
            "pergunta::divisoes-encefalo",
            "disc::anatomia",
            "aula::2026-08-10",
        ]

        occlusion = nota["fields"]["Occlusion"]
        assert occlusion.count("<br>") == 2
        for ordinal in (1, 2, 3):
            assert f"{{{{c{ordinal}::image-occlusion:rect:" in occlusion
        assert ":oi=1" in occlusion  # esconder-tudo é o padrão

        assert nota["fields"]["Header"] == "Divisões do encéfalo"
        assert nota["fields"]["Image"].startswith('<img src="ocluir-2026-08-10-')

        media = [p for p in falso.recebidas if p["action"] == "storeMediaFile"][0]
        assert media["params"]["filename"].endswith(".png")

    def test_enviar_barra_plano_que_fere_o_contrato(self, diagrama, servidor, capsys):  # noqa: F811
        endereco, falso = servidor

        principal(["ler", str(diagrama), "--titulo", "T", "--pergunta", "p"])
        plano_json = diagrama.with_suffix(".plano.json")
        plano = Plano.carregar(plano_json)
        alvos = {c["texto"]: c["id"] for c in plano.candidatos}
        # Mesmo rótulo duas vezes: dois cartões competindo pela mesma resposta.
        plano.grupos = [
            Grupo(rotulo="Bulbo", tokens=[alvos["Bulbo"]]),
            Grupo(rotulo="Bulbo", tokens=[alvos["Ponte"]]),
        ]
        plano.salvar(plano_json)

        assert principal(["enviar", str(plano_json), "--endereco", endereco]) == 1
        assert not [p for p in falso.recebidas if p["action"] == "addNote"]

    def test_forcar_passa_por_cima_do_contrato(self, diagrama, servidor):  # noqa: F811
        endereco, falso = servidor

        principal(["ler", str(diagrama), "--titulo", "T", "--pergunta", "p"])
        plano_json = diagrama.with_suffix(".plano.json")
        plano = Plano.carregar(plano_json)
        alvos = {c["texto"]: c["id"] for c in plano.candidatos}
        plano.grupos = [
            Grupo(rotulo="Bulbo", tokens=[alvos["Bulbo"]]),
            Grupo(rotulo="Bulbo", tokens=[alvos["Ponte"]]),
        ]
        plano.salvar(plano_json)

        assert (
            principal(["enviar", str(plano_json), "--endereco", endereco, "--forcar"]) == 0
        )
        assert [p for p in falso.recebidas if p["action"] == "addNote"]


class TestErrosDeUso:
    def test_plano_com_json_quebrado(self, tmp_path, capsys):
        """Falha com mensagem, não com stack trace."""
        ruim = tmp_path / "p.json"
        ruim.write_text("{isso não é json", encoding="utf-8")

        assert principal(["verificar", str(ruim)]) == 1
        assert "Plano inválido" in capsys.readouterr().err

    def test_plano_sem_grupo_na_previa(self, tmp_path, capsys):
        imagem = tmp_path / "x.png"
        from PIL import Image

        Image.new("RGB", (100, 100), "white").save(imagem)
        plano = Plano(imagem="x.png", tamanho=[100, 100])
        caminho = tmp_path / "x.plano.json"
        plano.salvar(caminho)

        assert principal(["previa", str(caminho)]) == 1
        assert "ainda não tem grupos" in capsys.readouterr().err
