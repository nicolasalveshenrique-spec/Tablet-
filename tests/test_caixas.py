"""Detecção de caixas de texto sem OCR.

Os testes usam imagens desenhadas na hora, com posições conhecidas, para que a
verificação seja sobre coordenada e não sobre "achou alguma coisa".
"""

import pytest
from PIL import Image, ImageDraw, ImageFont

from ocluir.caixas import _apagar_linhas, _trechos, detectar, desenhar_numeradas


def fonte(tamanho=28):
    for nome in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


@pytest.fixture
def imagem_com_dois_rotulos(tmp_path):
    caminho = tmp_path / "dois.png"
    imagem = Image.new("RGB", (800, 400), "white")
    desenho = ImageDraw.Draw(imagem)
    f = fonte()
    desenho.text((100, 100), "Telencefalo", font=f, fill="black")
    desenho.text((500, 100), "Bulbo", font=f, fill="black")
    imagem.save(caminho)
    return caminho


class TestTrechos:
    def test_trecho_unico(self):
        assert _trechos([0, 0, 5, 5, 5, 0, 0], minimo=1, vao_maximo=1) == [(2, 4)]

    def test_vao_grande_separa(self):
        contagens = [5, 5, 0, 0, 0, 0, 5, 5]
        assert len(_trechos(contagens, minimo=1, vao_maximo=2)) == 2

    def test_vao_pequeno_nao_separa(self):
        contagens = [5, 5, 0, 5, 5]
        assert len(_trechos(contagens, minimo=1, vao_maximo=2)) == 1

    def test_tudo_vazio(self):
        assert _trechos([0, 0, 0], minimo=1, vao_maximo=1) == []


class TestApagarLinhas:
    def test_linha_horizontal_longa_some(self):
        largura, altura = 50, 3
        tinta = [0] * (largura * altura)
        for x in range(largura):  # linha inteira acesa
            tinta[1 * largura + x] = 1

        limpo = _apagar_linhas(tinta, largura, altura, limite=20)
        assert sum(limpo) == 0

    def test_traco_curto_sobrevive(self):
        largura, altura = 50, 3
        tinta = [0] * (largura * altura)
        for x in range(5, 12):
            tinta[1 * largura + x] = 1

        limpo = _apagar_linhas(tinta, largura, altura, limite=20)
        assert sum(limpo) == 7

    def test_coluna_longa_some(self):
        largura, altura = 3, 50
        tinta = [0] * (largura * altura)
        for y in range(altura):
            tinta[y * largura + 1] = 1

        assert sum(_apagar_linhas(tinta, largura, altura, limite=20)) == 0


class TestDetectar:
    def test_acha_os_dois_rotulos_separados(self, imagem_com_dois_rotulos):
        caixas, tamanho = detectar(imagem_com_dois_rotulos)
        assert tamanho == (800, 400)
        assert len(caixas) == 2

    def test_as_caixas_ficam_onde_o_texto_esta(self, imagem_com_dois_rotulos):
        caixas, _ = detectar(imagem_com_dois_rotulos)
        esquerda, direita = sorted(caixas, key=lambda c: c.caixa[0])

        # Desenhados em x=100 e x=500, y=100, com fonte de 28 px.
        assert 95 <= esquerda.caixa[0] <= 115
        assert 495 <= direita.caixa[0] <= 515
        for caixa in caixas:
            assert 95 <= caixa.caixa[1] <= 125
            assert 15 <= caixa.caixa[3] <= 45

    def test_ids_seguem_a_ordem_de_leitura(self, tmp_path):
        caminho = tmp_path / "ordem.png"
        imagem = Image.new("RGB", (600, 400), "white")
        desenho = ImageDraw.Draw(imagem)
        f = fonte()
        desenho.text((400, 50), "primeiro", font=f, fill="black")
        desenho.text((50, 250), "segundo", font=f, fill="black")
        imagem.save(caminho)

        caixas, _ = detectar(caminho)
        assert caixas[0].caixa[1] < caixas[1].caixa[1]
        assert [c.id for c in caixas] == [1, 2]

    def test_moldura_nao_vira_caixa(self, tmp_path):
        """A regressão que motivou o `_apagar_linhas`.

        Antes da remoção de traços longos, um retângulo em volta do texto fazia
        a projeção enxergar o diagrama inteiro como uma faixa só — o resultado
        era uma "caixa" cobrindo tudo.
        """
        caminho = tmp_path / "moldura.png"
        imagem = Image.new("RGB", (800, 400), "white")
        desenho = ImageDraw.Draw(imagem)
        desenho.rectangle((50, 50, 750, 350), outline="black", width=3)
        desenho.text((300, 180), "Bulbo", font=fonte(), fill="black")
        imagem.save(caminho)

        caixas, _ = detectar(caminho)
        assert len(caixas) == 1
        assert caixas[0].caixa[2] < 200  # a largura da palavra, não da moldura

    def test_imagem_em_branco_nao_acha_nada(self, tmp_path):
        caminho = tmp_path / "vazia.png"
        Image.new("RGB", (400, 300), "white").save(caminho)
        caixas, _ = detectar(caminho)
        assert caixas == []

    def test_fundo_escuro_funciona_igual(self, tmp_path):
        """O fundo é o tom mais frequente, não necessariamente o branco."""
        caminho = tmp_path / "escura.png"
        imagem = Image.new("RGB", (600, 300), (20, 20, 24))
        ImageDraw.Draw(imagem).text((100, 120), "Mesencefalo", font=fonte(), fill="white")
        imagem.save(caminho)

        caixas, _ = detectar(caminho)
        assert len(caixas) == 1
        assert 95 <= caixas[0].caixa[0] <= 115

    def test_arquivo_ausente(self):
        with pytest.raises(FileNotFoundError):
            detectar("/nao/existe.png")


class TestNormalizada:
    def test_converte_para_fracao(self, imagem_com_dois_rotulos):
        caixas, (largura, altura) = detectar(imagem_com_dois_rotulos)
        esq, topo, larg, alt = caixas[0].normalizada(largura, altura)
        assert 0.0 <= esq <= 1.0
        assert 0.0 <= topo <= 1.0
        assert esq + larg <= 1.0
        assert topo + alt <= 1.0

    def test_folga_nao_estoura_a_borda(self, tmp_path):
        caminho = tmp_path / "canto.png"
        imagem = Image.new("RGB", (400, 200), "white")
        ImageDraw.Draw(imagem).text((2, 2), "Ponte", font=fonte(20), fill="black")
        imagem.save(caminho)

        caixas, (largura, altura) = detectar(caminho)
        esq, topo, larg, alt = caixas[0].normalizada(largura, altura, folga=0.5)
        assert esq >= 0.0 and topo >= 0.0
        assert esq + larg <= 1.0 and topo + alt <= 1.0


class TestDesenho:
    def test_escreve_a_imagem_numerada(self, imagem_com_dois_rotulos, tmp_path):
        caixas, _ = detectar(imagem_com_dois_rotulos)
        destino = desenhar_numeradas(
            imagem_com_dois_rotulos, caixas, tmp_path / "num.png"
        )
        assert destino.exists()
        with Image.open(destino) as imagem:
            assert imagem.size == (800, 400)
