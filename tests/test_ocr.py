"""Testes do agrupamento geométrico, sem depender do Tesseract.

O agrupamento é onde mora o bug que custa caro: uma máscara que cobre dois
rótulos distantes e o vão entre eles some com a resposta certa junto. Estes
testes fixam o comportamento com caixas construídas à mão.
"""

import pytest

from ocluir.ocr import (
    SO_SIMBOLOS,
    Token,
    _agrupar_em_linhas,
    _sobreposicao,
    _unir,
)


def palavra(texto, x, y, largura=60, altura=20, conf=90.0):
    return {"texto": texto, "conf": conf, "caixa": (x, y, largura, altura)}


class TestSobreposicao:
    def test_caixas_iguais(self):
        assert _sobreposicao((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)

    def test_caixas_disjuntas(self):
        assert _sobreposicao((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0

    def test_sobreposicao_parcial(self):
        # Metade da área em comum.
        assert _sobreposicao((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(1 / 3)


class TestUnir:
    def test_mesma_palavra_em_duas_passagens_conta_uma_vez(self):
        passagens = [
            [palavra("Bulbo", 100, 100, conf=80)],
            [palavra("Bulbo", 101, 100, conf=95)],
        ]
        unidas = _unir(passagens)
        assert len(unidas) == 1

    def test_mantem_a_leitura_de_maior_confianca(self):
        passagens = [
            [palavra("Buibo", 100, 100, conf=60)],
            [palavra("Bulbo", 100, 100, conf=95)],
        ]
        assert _unir(passagens)[0]["texto"] == "Bulbo"

    def test_palavras_distantes_sobrevivem_as_duas(self):
        passagens = [[palavra("Ponte", 100, 100)], [palavra("Bulbo", 900, 100)]]
        assert len(_unir(passagens)) == 2


class TestAgruparEmLinhas:
    def test_palavras_vizinhas_viram_um_rotulo(self):
        palavras = [palavra("Tronco", 100, 100), palavra("encefalico", 165, 100)]
        linhas = _agrupar_em_linhas(palavras, fator_de_vao=1.2)
        assert len(linhas) == 1
        assert [p["texto"] for p in linhas[0]] == ["Tronco", "encefalico"]

    def test_rotulos_distantes_na_mesma_altura_ficam_separados(self):
        """O bug que motivou este módulo: máscara cobrindo meio diagrama."""
        palavras = [palavra("Mesencefalo", 100, 100), palavra("Bulbo", 900, 100)]
        linhas = _agrupar_em_linhas(palavras, fator_de_vao=1.2)
        assert len(linhas) == 2

    def test_ordem_invertida_pelo_topo_ainda_agrupa(self):
        """Passagens diferentes devolvem topos com fração de pixel de diferença.

        Se o agrupamento processasse em ordem de topo, a palavra da direita
        entraria antes da esquerda e as duas virariam linhas separadas — foi
        exatamente o que aconteceu com "Tronco encefalico".
        """
        palavras = [
            palavra("encefalico", 165, 99.7, largura=80),
            palavra("Tronco", 100, 100.0, largura=60),
        ]
        linhas = _agrupar_em_linhas(palavras, fator_de_vao=1.2)
        assert len(linhas) == 1
        assert [p["texto"] for p in linhas[0]] == ["Tronco", "encefalico"]

    def test_alturas_diferentes_ficam_em_faixas_diferentes(self):
        palavras = [palavra("Cerebro", 100, 100), palavra("Talamo", 100, 400)]
        assert len(_agrupar_em_linhas(palavras, 1.2)) == 2

    def test_vao_mais_apertado_separa_mais(self):
        palavras = [palavra("Ponte", 100, 100), palavra("Bulbo", 175, 100)]
        assert len(_agrupar_em_linhas(palavras, fator_de_vao=1.2)) == 1
        assert len(_agrupar_em_linhas(palavras, fator_de_vao=0.5)) == 2

    def test_lista_vazia(self):
        assert _agrupar_em_linhas([], 1.2) == []


class TestFiltroDeSimbolos:
    @pytest.mark.parametrize("lixo", ["|", "||", "(", "—", "___", "..."])
    def test_borda_de_caixa_e_descartada(self, lixo):
        assert SO_SIMBOLOS.match(lixo)

    @pytest.mark.parametrize(
        "valido", ["Bulbo", "Glicose-6-fosfato", "C1", "Frutose-1,6-bisfosfato"]
    )
    def test_rotulo_de_verdade_passa(self, valido):
        assert not SO_SIMBOLOS.match(valido)

    def test_acentuado_passa(self):
        assert not SO_SIMBOLOS.match("Telencéfalo")


class TestCaixaNormalizada:
    def test_converte_para_fracao(self):
        token = Token(id=1, texto="x", caixa=(100, 50, 200, 25), confianca=90)
        esq, topo, larg, alt = token.caixa_normalizada(1000, 500)
        assert (esq, topo, larg, alt) == pytest.approx((0.1, 0.1, 0.2, 0.05))

    def test_folga_alarga_a_mascara(self):
        token = Token(id=1, texto="x", caixa=(100, 100, 100, 20), confianca=90)
        _, _, larg_sem, _ = token.caixa_normalizada(1000, 1000, folga=0.0)
        _, _, larg_com, _ = token.caixa_normalizada(1000, 1000, folga=0.1)
        assert larg_com > larg_sem

    def test_folga_nao_ultrapassa_a_borda(self):
        token = Token(id=1, texto="x", caixa=(0, 0, 100, 20), confianca=90)
        esq, topo, _, _ = token.caixa_normalizada(1000, 1000, folga=0.5)
        assert esq == 0.0
        assert topo == 0.0
