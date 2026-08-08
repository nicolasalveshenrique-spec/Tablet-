"""O formato do campo Occlusion é a parte que precisa estar exatamente certa.

Se ela estiver errada, o Anki aceita a nota e gera cartão nenhum, ou gera um
cartão com a máscara no lugar errado — e a falha só aparece na revisão, dias
depois. Por isso estes testes checam o texto literal, não só o comportamento.
"""

import pytest

from ocluir.oclusao import (
    ESCONDER_TUDO,
    ESCONDER_UMA,
    Forma,
    contar_cartoes,
    formatar_numero,
    montar_campo,
)


class TestFormatarNumero:
    def test_corta_em_quatro_casas(self):
        assert formatar_numero(0.123456789) == "0.1235"

    def test_remove_zeros_a_toa(self):
        assert formatar_numero(0.5) == "0.5"
        assert formatar_numero(0.1000) == "0.1"

    def test_inteiro_nao_vira_decimal(self):
        assert formatar_numero(1.0) == "1"
        assert formatar_numero(0.0) == "0"


class TestForma:
    def test_texto_da_cloze_bate_com_o_formato_do_anki(self):
        forma = Forma(esquerda=0.1, topo=0.2, largura=0.3, altura=0.05)
        assert forma.para_cloze(1, ocultar_inativas=True) == (
            "{{c1::image-occlusion:rect:left=0.1:top=0.2:width=0.3:height=0.05:oi=1}}"
        )

    def test_sem_oi_no_modo_esconder_uma(self):
        forma = Forma(0.1, 0.2, 0.3, 0.05)
        texto = forma.para_cloze(2, ocultar_inativas=False)
        assert ":oi=" not in texto
        assert texto.startswith("{{c2::image-occlusion:rect:")

    def test_ordinal_aparece_no_lugar_certo(self):
        forma = Forma(0.0, 0.0, 0.1, 0.1)
        assert forma.para_cloze(7, False).startswith("{{c7::")

    @pytest.mark.parametrize(
        "entrada,esperado_largura",
        [
            (Forma(0.9, 0.0, 0.5, 0.1), 0.1),  # estoura à direita
            (Forma(0.0, 0.0, 2.0, 0.1), 1.0),  # largura absurda
        ],
    )
    def test_mascara_nao_escapa_da_imagem(self, entrada, esperado_largura):
        assert entrada.limitada().largura == pytest.approx(esperado_largura)

    def test_coordenada_negativa_vira_zero(self):
        limitada = Forma(-0.2, -0.3, 0.5, 0.5).limitada()
        assert limitada.esquerda == 0.0
        assert limitada.topo == 0.0


class TestMontarCampo:
    def test_um_grupo_por_cartao(self):
        grupos = [[Forma(0.1, 0.1, 0.1, 0.1)], [Forma(0.5, 0.5, 0.1, 0.1)]]
        campo = montar_campo(grupos, ESCONDER_TUDO)
        assert contar_cartoes(campo) == 2
        assert campo.count("<br>") == 1

    def test_formas_do_mesmo_grupo_dividem_o_ordinal(self):
        """É assim que se revela um passo inteiro de uma vez."""
        grupos = [[Forma(0.1, 0.1, 0.1, 0.1), Forma(0.3, 0.1, 0.1, 0.1)]]
        campo = montar_campo(grupos, ESCONDER_TUDO)
        assert campo.count("{{c1::") == 2
        assert contar_cartoes(campo) == 1

    def test_modo_esconder_uma_nao_marca_oi(self):
        campo = montar_campo([[Forma(0.1, 0.1, 0.1, 0.1)]], ESCONDER_UMA)
        assert ":oi=1" not in campo

    def test_modo_invalido_reclama(self):
        with pytest.raises(ValueError, match="Modo desconhecido"):
            montar_campo([[Forma(0, 0, 1, 1)]], "esconder-metade")

    def test_sem_grupo_nao_gera_nota_muda(self):
        with pytest.raises(ValueError, match="nenhum grupo|Nenhum grupo"):
            montar_campo([], ESCONDER_TUDO)

    def test_grupo_vazio_reclama(self):
        with pytest.raises(ValueError, match="grupo 1 está vazio"):
            montar_campo([[]], ESCONDER_TUDO)


class TestContarCartoes:
    def test_ordinais_repetidos_contam_uma_vez(self):
        campo = (
            "{{c1::image-occlusion:rect:left=0:top=0:width=1:height=1}}<br>"
            "{{c1::image-occlusion:rect:left=0:top=0:width=1:height=1}}<br>"
            "{{c2::image-occlusion:rect:left=0:top=0:width=1:height=1}}"
        )
        assert contar_cartoes(campo) == 2

    def test_campo_vazio(self):
        assert contar_cartoes("") == 0
