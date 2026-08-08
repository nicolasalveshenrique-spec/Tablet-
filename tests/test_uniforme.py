"""Máscaras de tamanho igual.

O motivo é de método, não de aparência: a largura da máscara é informação. Numa
imagem com "Ponte" e "Fosfofrutoquinase-1" ocluídas, o retângulo curto só pode
ser a primeira, e o cartão passa a ser respondível sem saber anatomia.
"""

import pytest

from ocluir.oclusao import Forma, sobreposicao, uniformizar
from ocluir.ocr import Token
from ocluir.plano import Grupo, Plano


class TestUniformizar:
    def test_todas_ficam_do_mesmo_tamanho(self):
        grupos = [
            [Forma(0.1, 0.1, 0.05, 0.02)],
            [Forma(0.5, 0.1, 0.30, 0.04)],
            [Forma(0.1, 0.5, 0.12, 0.03)],
        ]
        resultado = uniformizar(grupos)
        larguras = {round(f.largura, 6) for g in resultado for f in g}
        alturas = {round(f.altura, 6) for g in resultado for f in g}
        assert len(larguras) == 1
        assert len(alturas) == 1

    def test_o_tamanho_e_o_da_maior(self):
        grupos = [[Forma(0.1, 0.1, 0.05, 0.02)], [Forma(0.5, 0.1, 0.30, 0.04)]]
        resultado = uniformizar(grupos)
        assert resultado[0][0].largura == pytest.approx(0.30)
        assert resultado[0][0].altura == pytest.approx(0.04)

    def test_nenhuma_mascara_encolhe_abaixo_do_texto(self):
        """Usar a maior, e não a média, garante que nada fique descoberto."""
        original = [[Forma(0.1, 0.1, 0.05, 0.02)], [Forma(0.5, 0.1, 0.30, 0.04)]]
        resultado = uniformizar(original)
        for antes, depois in zip(original, resultado):
            assert depois[0].largura >= antes[0].largura
            assert depois[0].altura >= antes[0].altura

    def test_cada_mascara_continua_centrada_no_rotulo(self):
        grupos = [[Forma(0.10, 0.20, 0.05, 0.02)], [Forma(0.60, 0.20, 0.20, 0.04)]]
        resultado = uniformizar(grupos)

        for antes, depois in zip(grupos, resultado):
            centro_antes = antes[0].esquerda + antes[0].largura / 2
            centro_depois = depois[0].esquerda + depois[0].largura / 2
            assert centro_depois == pytest.approx(centro_antes, abs=1e-6)

    def test_tamanho_explicito_e_respeitado(self):
        resultado = uniformizar([[Forma(0.4, 0.4, 0.05, 0.02)]], alvo=(0.2, 0.06))
        assert resultado[0][0].largura == pytest.approx(0.2)
        assert resultado[0][0].altura == pytest.approx(0.06)

    def test_mascara_na_borda_e_aparada_e_nao_estoura(self):
        resultado = uniformizar(
            [[Forma(0.95, 0.5, 0.04, 0.02)], [Forma(0.2, 0.5, 0.30, 0.02)]]
        )
        forma = resultado[0][0]
        assert forma.esquerda >= 0.0
        assert forma.esquerda + forma.largura <= 1.0 + 1e-9

    def test_grupo_com_duas_formas_uniformiza_as_duas(self):
        resultado = uniformizar([[Forma(0.1, 0.1, 0.05, 0.02), Forma(0.3, 0.1, 0.2, 0.05)]])
        assert resultado[0][0].largura == resultado[0][1].largura

    def test_lista_vazia_passa_direto(self):
        assert uniformizar([]) == []


class TestSobreposicao:
    def test_disjuntas(self):
        assert sobreposicao(Forma(0, 0, 0.1, 0.1), Forma(0.5, 0.5, 0.1, 0.1)) == 0.0

    def test_identicas(self):
        assert sobreposicao(
            Forma(0.1, 0.1, 0.2, 0.2), Forma(0.1, 0.1, 0.2, 0.2)
        ) == pytest.approx(1.0)

    def test_pequena_dentro_da_grande_conta_como_total(self):
        """A fração é sobre a menor das duas — é ela que fica coberta."""
        grande = Forma(0.0, 0.0, 0.5, 0.5)
        pequena = Forma(0.1, 0.1, 0.1, 0.1)
        assert sobreposicao(grande, pequena) == pytest.approx(1.0)


class TestNoPlano:
    def _plano(self, uniforme):
        tokens = {
            1: Token(id=1, texto="Ponte", caixa=(100, 100, 50, 20), confianca=90),
            2: Token(id=2, texto="Fosfofrutoquinase-1", caixa=(400, 100, 300, 20), confianca=90),
        }
        plano = Plano(
            imagem="x.png",
            titulo="T",
            pergunta="p",
            tamanho=[1000, 500],
            mascara_uniforme=uniforme,
            grupos=[Grupo(rotulo="Ponte", tokens=[1]), Grupo(rotulo="PFK-1", tokens=[2])],
        )
        return plano, tokens

    def test_ligado_por_padrao(self):
        assert Plano(imagem="x.png").mascara_uniforme == "maior"

    def test_maior_iguala(self):
        plano, tokens = self._plano("maior")
        formas = plano.formas(tokens)
        assert formas[0][1][0].largura == pytest.approx(formas[1][1][0].largura)

    def test_desligado_preserva_os_tamanhos_originais(self):
        plano, tokens = self._plano("")
        formas = plano.formas(tokens)
        assert formas[0][1][0].largura < formas[1][1][0].largura

    def test_tamanho_fixo(self):
        plano, tokens = self._plano("0.15x0.05")
        formas = plano.formas(tokens)
        for _, grupo in formas:
            assert grupo[0].largura == pytest.approx(0.15)
            assert grupo[0].altura == pytest.approx(0.05)

    def test_valor_invalido_reclama_com_instrucao(self):
        plano, tokens = self._plano("gigante")
        with pytest.raises(ValueError, match="mascara_uniforme inválido"):
            plano.formas(tokens)

    def test_sobrevive_ao_salvar_e_carregar(self, tmp_path):
        plano, _ = self._plano("0.15x0.05")
        caminho = tmp_path / "p.json"
        plano.salvar(caminho)
        assert Plano.carregar(caminho).mascara_uniforme == "0.15x0.05"


class TestAvisoDeSobreposicao:
    def test_mascaras_uniformes_que_colidem_geram_aviso(self):
        from ocluir.contrato import tem_erro, verificar

        # Dois rótulos vizinhos, um curto e um muito longo: ao igualar, o curto
        # cresce e invade o vizinho.
        tokens = {
            1: Token(id=1, texto="Ponte", caixa=(100, 100, 40, 20), confianca=90),
            2: Token(id=2, texto="Bulbo", caixa=(160, 100, 40, 20), confianca=90),
            3: Token(id=3, texto="Fosfofrutoquinase", caixa=(500, 300, 400, 20), confianca=90),
        }
        plano = Plano(
            imagem="x.png", titulo="T", pergunta="p", tamanho=[1000, 500],
            mascara_uniforme="maior",
            grupos=[
                Grupo(rotulo="Ponte", tokens=[1]),
                Grupo(rotulo="Bulbo", tokens=[2]),
                Grupo(rotulo="PFK", tokens=[3]),
            ],
        )
        achados = verificar(plano, tokens)
        assert any("se sobrepõem" in a.mensagem for a in achados)
        assert not tem_erro(achados)  # é aviso, não bloqueio

    def test_sem_uniformizar_nao_ha_colisao(self):
        from ocluir.contrato import verificar

        tokens = {
            1: Token(id=1, texto="Ponte", caixa=(100, 100, 40, 20), confianca=90),
            2: Token(id=2, texto="Bulbo", caixa=(160, 100, 40, 20), confianca=90),
            3: Token(id=3, texto="Fosfofrutoquinase", caixa=(500, 300, 400, 20), confianca=90),
        }
        plano = Plano(
            imagem="x.png", titulo="T", pergunta="p", tamanho=[1000, 500],
            mascara_uniforme="",
            grupos=[
                Grupo(rotulo="Ponte", tokens=[1]),
                Grupo(rotulo="Bulbo", tokens=[2]),
                Grupo(rotulo="PFK", tokens=[3]),
            ],
        )
        assert not any("se sobrepõem" in a.mensagem for a in verificar(plano, tokens))
