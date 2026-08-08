"""O script de arquivo único não pode divergir dos módulos.

Ele é gerado a partir de `ocluir/`, mas nada impede alguém de editar o arquivo
gerado direto. Este teste regenera e compara: se o commit tiver um script
desatualizado, ele falha e diz o comando que conserta.

O segundo grupo de testes roda o script *isolado* — importado por caminho, sem
o pacote `ocluir` disponível — porque é assim que ele vai rodar no chat.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "chat" / "ocluir_chat.py"
GERADOR = RAIZ / "ferramentas" / "gerar_script_de_chat.py"

try:
    import anki.collection  # noqa: F401

    from ocluir import pacote

    TEM_ANKI = True
except ImportError:  # pragma: no cover
    TEM_ANKI = False


def carregar_isolado():
    """Importa o script por caminho, como se o repositório não existisse.

    O registro em sys.modules antes do exec não é cerimônia: @dataclass procura
    o módulo da classe em sys.modules durante a decoração, e sem isso falha com
    um AttributeError obscuro. É exigência do Python, não do script.
    """
    especificacao = importlib.util.spec_from_file_location("ocluir_chat_teste", SCRIPT)
    modulo = importlib.util.module_from_spec(especificacao)
    sys.modules["ocluir_chat_teste"] = modulo
    try:
        especificacao.loader.exec_module(modulo)
    except Exception:
        del sys.modules["ocluir_chat_teste"]
        raise
    return modulo


@pytest.fixture
def diagrama(tmp_path):
    caminho = tmp_path / "via.png"
    imagem = Image.new("RGB", (700, 500), "white")
    desenho = ImageDraw.Draw(imagem)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except OSError:  # pragma: no cover
        f = ImageFont.load_default()

    desenho.text((80, 80), "Glicose", font=f, fill="black")
    desenho.text((80, 220), "Hexoquinase", font=f, fill="black")
    desenho.text((80, 360), "Glicose-6-fosfato", font=f, fill="black")
    imagem.save(caminho)
    return caminho


class TestNaoDivergiu:
    def test_o_arquivo_gerado_esta_atualizado(self):
        antes = SCRIPT.read_text(encoding="utf-8")
        subprocess.run(
            [sys.executable, str(GERADOR)], check=True, capture_output=True, cwd=RAIZ
        )
        depois = SCRIPT.read_text(encoding="utf-8")
        assert antes == depois, (
            "chat/ocluir_chat.py está desatualizado em relação a ocluir/.\n"
            "Rode: python3 ferramentas/gerar_script_de_chat.py"
        )

    def test_nao_sobrou_import_relativo(self):
        texto = SCRIPT.read_text(encoding="utf-8")
        assert "from ." not in texto
        assert "import ocluir" not in texto


class TestRodandoIsolado:
    def test_importa_sem_o_pacote(self):
        modulo = carregar_isolado()
        for nome in (
            "detectar",
            "desenhar_numeradas",
            "criar_apkg",
            "previa_das_mascaras",
            "ESCONDER_TUDO",
            "ESCONDER_UMA",
        ):
            assert hasattr(modulo, nome), f"faltou {nome}"

    def test_detecta_as_caixas(self, diagrama):
        modulo = carregar_isolado()
        caixas, tamanho = modulo.detectar(diagrama)
        assert tamanho == (700, 500)
        assert len(caixas) == 3

    def test_gera_apkg_com_mascaras_uniformes(self, diagrama, tmp_path):
        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)

        destino, cartoes = modulo.criar_apkg(
            diagrama,
            caixas,
            [
                {"rotulo": "Glicose", "caixas": [1]},
                {"rotulo": "Hexoquinase", "caixas": [2]},
            ],
            tmp_path / "chat.apkg",
            titulo="Glicólise",
            deck="Medicina::Bioquímica",
            tags=["oclusao", "disc::bioquimica"],
        )
        assert cartoes == 2
        assert destino.exists()

    def test_caixa_inexistente_da_erro_util(self, diagrama, tmp_path):
        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)
        with pytest.raises(ValueError, match="a caixa 99 não existe"):
            modulo.criar_apkg(
                diagrama, caixas, [{"rotulo": "X", "caixas": [99]}], tmp_path / "x.apkg"
            )

    def test_grupo_sem_alvo_da_erro_util(self, diagrama, tmp_path):
        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)
        with pytest.raises(ValueError, match="nem 'caixas' nem 'caixa'"):
            modulo.criar_apkg(
                diagrama, caixas, [{"rotulo": "X"}], tmp_path / "x.apkg"
            )

    def test_previa_sai_do_mesmo_tamanho_da_imagem(self, diagrama, tmp_path):
        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)
        destino = modulo.previa_das_mascaras(
            diagrama, caixas, [{"rotulo": "Glicose", "caixas": [1]}], tmp_path / "p.png"
        )
        with Image.open(destino) as imagem:
            assert imagem.size == (700, 500)


@pytest.mark.skipif(not TEM_ANKI, reason="biblioteca anki ausente")
class TestPacoteDoChatEValido:
    def test_o_apkg_do_chat_importa_no_anki(self, diagrama, tmp_path):
        """Escrito pelo script solto, lido pela biblioteca oficial."""
        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)

        destino, _ = modulo.criar_apkg(
            diagrama,
            caixas,
            [
                {"rotulo": "Glicose", "caixas": [1]},
                {"rotulo": "Hexoquinase", "caixas": [2]},
                {"rotulo": "Glicose-6-fosfato", "caixas": [3]},
            ],
            tmp_path / "chat.apkg",
            titulo="Glicólise",
            deck="Medicina::Bioquímica",
            tags=["oclusao", "pergunta::glicolise"],
        )

        relatorio = pacote.conferir(destino)
        assert relatorio["notas"] == 1
        assert relatorio["cartoes"] == 3
        assert relatorio["stock_kind"] == 6
        assert "Medicina::Bioquímica" in relatorio["decks"]

    def test_uniformidade_chega_ate_o_campo_final(self, diagrama, tmp_path):
        """As três máscaras precisam sair do pacote com o mesmo tamanho."""
        import re

        modulo = carregar_isolado()
        caixas, _ = modulo.detectar(diagrama)
        destino, _ = modulo.criar_apkg(
            diagrama,
            caixas,
            [
                {"rotulo": "Glicose", "caixas": [1]},
                {"rotulo": "Hexoquinase", "caixas": [2]},
                {"rotulo": "Glicose-6-fosfato", "caixas": [3]},
            ],
            tmp_path / "chat.apkg",
        )

        frente = pacote.conferir(destino)["frente_renderizada"]
        larguras = set(re.findall(r'data-width="([\d.]+)"', frente))
        alturas = set(re.findall(r'data-height="([\d.]+)"', frente))
        assert len(larguras) == 1, f"larguras diferentes: {larguras}"
        assert len(alturas) == 1, f"alturas diferentes: {alturas}"
