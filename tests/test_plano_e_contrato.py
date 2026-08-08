"""Plano, tags e o contrato do cartão."""

import json

import pytest

from ocluir.contrato import ERRO, TETO_DURO, tem_erro, verificar
from ocluir.ocr import Token
from ocluir.plano import Grupo, Plano, slugificar


def token(identificador, x=100, y=100, largura=80, altura=20):
    return Token(id=identificador, texto=f"t{identificador}", caixa=(x, y, largura, altura), confianca=90.0)


@pytest.fixture
def tokens():
    return {i: token(i, x=100 * i) for i in range(1, 6)}


@pytest.fixture
def plano_base():
    return Plano(
        imagem="aula.png",
        titulo="Divisões do encéfalo",
        pergunta="divisoes-encefalo",
        disciplina="anatomia",
        aula="2026-08-10",
        tamanho=[1000, 1000],
        grupos=[Grupo(rotulo="Telencéfalo", tokens=[1])],
    )


class TestSlug:
    def test_tira_acento_e_espaco(self):
        assert slugificar("Divisões do Encéfalo") == "divisoes-do-encefalo"

    def test_colapsa_pontuacao(self):
        assert slugificar("Frutose-1,6-bisfosfato") == "frutose-1-6-bisfosfato"

    def test_texto_vazio_tem_saida_utilizavel(self):
        assert slugificar("!!!") == "sem-titulo"


class TestTags:
    def test_monta_o_esquema_do_vault(self, plano_base):
        assert plano_base.tags() == [
            "oclusao",
            "pergunta::divisoes-encefalo",
            "disc::anatomia",
            "aula::2026-08-10",
        ]

    def test_campos_vazios_nao_viram_tag_solta(self):
        plano = Plano(imagem="x.png")
        assert plano.tags() == ["oclusao"]


class TestGrupo:
    def test_caixa_manual_tem_precedencia(self, tokens):
        grupo = Grupo(rotulo="Seta sem legenda", tokens=[1], caixa=[0.1, 0.2, 0.3, 0.4])
        formas = grupo.formas(tokens, (1000, 1000), folga=0.0)
        assert len(formas) == 1
        assert formas[0].esquerda == pytest.approx(0.1)

    def test_varios_tokens_viram_varias_formas_do_mesmo_cartao(self, tokens):
        grupo = Grupo(rotulo="Etapa", tokens=[1, 2, 3])
        assert len(grupo.formas(tokens, (1000, 1000), folga=0.0)) == 3

    def test_token_inexistente_da_erro_util(self, tokens):
        grupo = Grupo(rotulo="X", tokens=[99])
        with pytest.raises(ValueError, match="token 99"):
            grupo.formas(tokens, (1000, 1000), folga=0.0)

    def test_grupo_sem_nada_para_ocluir(self, tokens):
        with pytest.raises(ValueError, match="não tem 'tokens' nem 'caixa'"):
            Grupo(rotulo="X").formas(tokens, (1000, 1000), folga=0.0)

    def test_caixa_com_tamanho_errado(self, tokens):
        grupo = Grupo(rotulo="X", caixa=[0.1, 0.2])
        with pytest.raises(ValueError, match="4 números"):
            grupo.formas(tokens, (1000, 1000), folga=0.0)


class TestSerializacao:
    def test_ida_e_volta_preserva_tudo(self, tmp_path, plano_base):
        caminho = tmp_path / "p.json"
        plano_base.salvar(caminho)
        recarregado = Plano.carregar(caminho)
        assert recarregado.titulo == plano_base.titulo
        assert recarregado.grupos[0].rotulo == "Telencéfalo"
        assert recarregado.tags() == plano_base.tags()

    def test_acento_fica_legivel_no_arquivo(self, tmp_path, plano_base):
        caminho = tmp_path / "p.json"
        plano_base.salvar(caminho)
        assert "Telencéfalo" in caminho.read_text(encoding="utf-8")

    def test_campo_desconhecido_reclama_em_vez_de_ignorar(self, tmp_path):
        caminho = tmp_path / "p.json"
        caminho.write_text(
            json.dumps({"imagem": "x.png", "tituIo": "erro de digitação"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Campos desconhecidos"):
            Plano.carregar(caminho)


class TestContrato:
    def test_plano_bem_formado_passa_limpo(self, plano_base, tokens):
        achados = verificar(plano_base, tokens)
        assert not tem_erro(achados)

    def test_sem_grupo_e_erro(self, tokens):
        plano = Plano(imagem="x.png", grupos=[])
        assert tem_erro(verificar(plano, tokens))

    def test_teto_duro_bloqueia_a_prancha_inteira(self, tokens):
        muitos = {i: token(i, x=10 * i, y=10 * i) for i in range(1, TETO_DURO + 3)}
        plano = Plano(
            imagem="x.png",
            titulo="Prancha",
            pergunta="p",
            tamanho=[1000, 1000],
            grupos=[
                Grupo(rotulo=f"Rotulo {i}", tokens=[i]) for i in range(1, TETO_DURO + 2)
            ],
        )
        achados = verificar(plano, muitos)
        assert tem_erro(achados)
        assert any("prancha virando baralho" in a.mensagem for a in achados)

    def test_rotulo_repetido_e_erro(self, tokens):
        plano = Plano(
            imagem="x.png",
            titulo="T",
            pergunta="p",
            tamanho=[1000, 1000],
            grupos=[Grupo(rotulo="Bulbo", tokens=[1]), Grupo(rotulo="bulbo", tokens=[2])],
        )
        achados = verificar(plano, tokens)
        assert tem_erro(achados)
        assert any("competem" in a.mensagem for a in achados)

    def test_rotulo_longo_vira_aviso_nao_erro(self, tokens):
        plano = Plano(
            imagem="x.png",
            titulo="T",
            pergunta="p",
            tamanho=[1000, 1000],
            grupos=[
                Grupo(
                    rotulo="a via que converte glicose em piruvato no citosol",
                    tokens=[1],
                )
            ],
        )
        achados = verificar(plano, tokens)
        assert not tem_erro(achados)
        assert any("mecanismo disfarçado" in a.mensagem for a in achados)

    def test_falta_de_pergunta_avisa(self, tokens):
        plano = Plano(
            imagem="x.png",
            titulo="T",
            tamanho=[1000, 1000],
            grupos=[Grupo(rotulo="Bulbo", tokens=[1])],
        )
        achados = verificar(plano, tokens)
        assert any("pergunta::" in a.mensagem for a in achados)
        assert not tem_erro(achados)

    def test_grupo_sem_rotulo_e_erro(self, tokens):
        plano = Plano(
            imagem="x.png",
            titulo="T",
            pergunta="p",
            tamanho=[1000, 1000],
            grupos=[Grupo(rotulo="   ", tokens=[1])],
        )
        assert tem_erro(verificar(plano, tokens))
