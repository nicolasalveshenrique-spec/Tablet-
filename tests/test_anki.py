"""Integração com o AnkiConnect, contra um servidor falso.

O caminho de inserção é o único que não dá para conferir olhando: se o
mapeamento de campos estiver errado, o Anki aceita a nota e cria um cartão
vazio. O servidor falso abaixo responde como o AnkiConnect responde e guarda o
que recebeu, para os testes checarem o corpo exato da requisição.

O caso do Anki traduzido é testado de propósito: com a interface em português
os campos do notetype se chamam outra coisa, e procurar por "Occlusion" pelo
nome falharia silenciosamente.
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ocluir.anki import Anki, AnkiErro, AnkiIndisponivel, montar_campos

CAMPOS_EM_INGLES = ["Occlusion", "Image", "Header", "Back Extra", "Comments"]
CAMPOS_EM_PORTUGUES = ["Oclusão", "Imagem", "Cabeçalho", "Verso Extra", "Comentários"]


class AnkiFalso(BaseHTTPRequestHandler):
    recebidas: list = []
    modelos = ["Basic", "Cloze", "Image Occlusion"]
    campos = CAMPOS_EM_INGLES
    decks = ["Default"]
    erro_para_devolver = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        tamanho = int(self.headers["Content-Length"])
        pedido = json.loads(self.rfile.read(tamanho))
        AnkiFalso.recebidas.append(pedido)

        acao = pedido["action"]
        parametros = pedido.get("params", {})
        resultado, erro = None, AnkiFalso.erro_para_devolver

        if erro is None:
            if acao == "version":
                resultado = 6
            elif acao == "modelNames":
                resultado = AnkiFalso.modelos
            elif acao == "modelFieldNames":
                resultado = AnkiFalso.campos
            elif acao == "deckNames":
                resultado = AnkiFalso.decks
            elif acao == "createDeck":
                AnkiFalso.decks.append(parametros["deck"])
                resultado = 1
            elif acao == "storeMediaFile":
                resultado = parametros["filename"]
            elif acao == "addNote":
                resultado = 1700000000123
            elif acao == "findNotes":
                resultado = []

        corpo = json.dumps({"result": resultado, "error": erro}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


@pytest.fixture
def servidor():
    AnkiFalso.recebidas = []
    AnkiFalso.modelos = ["Basic", "Cloze", "Image Occlusion"]
    AnkiFalso.campos = CAMPOS_EM_INGLES
    AnkiFalso.decks = ["Default"]
    AnkiFalso.erro_para_devolver = None

    httpd = HTTPServer(("127.0.0.1", 0), AnkiFalso)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", AnkiFalso
    httpd.shutdown()


class TestConversa:
    def test_version(self, servidor):
        endereco, _ = servidor
        assert Anki(endereco).versao() == 6

    def test_erro_do_anki_vira_excecao(self, servidor):
        endereco, falso = servidor
        falso.erro_para_devolver = "collection is not open"
        with pytest.raises(AnkiErro, match="collection is not open"):
            Anki(endereco).versao()

    def test_anki_fechado_da_mensagem_acionavel(self):
        # Porta fechada: simula o Anki não estar aberto.
        anki = Anki("http://127.0.0.1:1", tempo_limite=1.0)
        with pytest.raises(AnkiIndisponivel, match="2055492159"):
            anki.versao()


class TestDeteccaoDoModelo:
    def test_acha_o_notetype_nativo(self, servidor):
        endereco, _ = servidor
        nome, campos = Anki(endereco).detectar_modelo_de_oclusao()
        assert nome == "Image Occlusion"
        assert campos == CAMPOS_EM_INGLES

    def test_acha_o_notetype_com_a_interface_em_portugues(self, servidor):
        endereco, falso = servidor
        falso.modelos = ["Básico", "Oclusão de Imagem"]
        falso.campos = CAMPOS_EM_PORTUGUES
        nome, campos = Anki(endereco).detectar_modelo_de_oclusao()
        assert nome == "Oclusão de Imagem"
        assert campos == CAMPOS_EM_PORTUGUES

    def test_sem_notetype_explica_o_que_fazer(self, servidor):
        endereco, falso = servidor
        falso.modelos = ["Basic", "Cloze"]
        with pytest.raises(AnkiErro, match="23.10"):
            Anki(endereco).detectar_modelo_de_oclusao()

    def test_addon_antigo_e_recusado(self, servidor):
        endereco, falso = servidor
        falso.modelos = ["Image Occlusion Enhanced"]
        falso.campos = ["ID", "Header", "Image", "Question Mask"]
        with pytest.raises(AnkiErro, match="Enhanced"):
            Anki(endereco).detectar_modelo_de_oclusao()


class TestMontarCampos:
    def test_mapeia_por_posicao_em_ingles(self):
        campos = montar_campos(
            CAMPOS_EM_INGLES,
            occlusion="{{c1::image-occlusion:rect:left=0:top=0:width=1:height=1}}",
            html_da_imagem='<img src="a.png">',
            cabecalho="Divisões do encéfalo",
        )
        assert campos["Occlusion"].startswith("{{c1::")
        assert campos["Image"] == '<img src="a.png">'
        assert campos["Header"] == "Divisões do encéfalo"

    def test_mapeia_por_posicao_em_portugues(self):
        """A razão de existir do mapeamento posicional."""
        campos = montar_campos(
            CAMPOS_EM_PORTUGUES,
            occlusion="{{c1::image-occlusion:rect:left=0:top=0:width=1:height=1}}",
            html_da_imagem='<img src="a.png">',
            cabecalho="Cabeça",
        )
        assert campos["Oclusão"].startswith("{{c1::")
        assert campos["Imagem"] == '<img src="a.png">'
        assert campos["Cabeçalho"] == "Cabeça"

    def test_campos_de_menos_reclamam(self):
        with pytest.raises(AnkiErro, match="5 campos"):
            montar_campos(["A", "B"], occlusion="x", html_da_imagem="y")

    def test_campos_extras_ficam_vazios_sem_quebrar(self):
        campos = montar_campos(
            CAMPOS_EM_INGLES + ["Fonte"], occlusion="x", html_da_imagem="y"
        )
        assert campos["Fonte"] == ""


class TestEscrita:
    def test_media_vai_em_base64(self, servidor, tmp_path):
        endereco, falso = servidor
        arquivo = tmp_path / "slide.png"
        arquivo.write_bytes(b"\x89PNG conteudo")

        Anki(endereco).guardar_midia(arquivo, "ocluir-aula.png")

        pedido = [p for p in falso.recebidas if p["action"] == "storeMediaFile"][0]
        assert pedido["params"]["filename"] == "ocluir-aula.png"
        assert base64.b64decode(pedido["params"]["data"]) == b"\x89PNG conteudo"

    def test_deck_so_e_criado_se_faltar(self, servidor):
        endereco, falso = servidor
        falso.decks = ["Default", "Medicina::Anatomia"]
        Anki(endereco).garantir_deck("Medicina::Anatomia")
        assert not [p for p in falso.recebidas if p["action"] == "createDeck"]

        Anki(endereco).garantir_deck("Medicina::Bioquímica")
        criados = [p for p in falso.recebidas if p["action"] == "createDeck"]
        assert criados[0]["params"]["deck"] == "Medicina::Bioquímica"

    def test_nota_leva_deck_modelo_campos_e_tags(self, servidor):
        endereco, falso = servidor
        Anki(endereco).adicionar_nota(
            deck="Medicina::Anatomia",
            modelo="Image Occlusion",
            campos={"Occlusion": "{{c1::x}}"},
            tags=["oclusao", "disc::anatomia"],
        )
        nota = [p for p in falso.recebidas if p["action"] == "addNote"][0]["params"]["note"]
        assert nota["deckName"] == "Medicina::Anatomia"
        assert nota["modelName"] == "Image Occlusion"
        assert nota["tags"] == ["oclusao", "disc::anatomia"]
        assert nota["options"]["allowDuplicate"] is False
