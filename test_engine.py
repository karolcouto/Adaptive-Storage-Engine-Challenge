"""Testes do armazenamento e de JSONL. Execute: py -m unittest -v test_engine.py.

Todos os arquivos de dados sao criados numa pasta temporaria. Os testes nao
tocam no dados.bin nem no dados_v2.bin usados no terminal.
"""

import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import engine


RAIZ = Path(__file__).resolve().parent


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.base = Path(self.pasta.name) / "dados.bin"

    def test_operacoes_e_reabertura(self):
        engine.put(self.base, 91, "Ana")
        engine.put(self.base, 91, "Karoline")
        engine.put(self.base, 25, "Computação")
        self.assertEqual(engine.get(self.base, 91), "Karoline")
        engine.delete(self.base, 91)
        self.assertIsNone(engine.get(self.base, 91))
        self.assertEqual(engine.get(self.base, 25), "Computação")
        engine.put(self.base, 91, "Novo valor")
        self.assertEqual(engine.get(self.base, 91), "Novo valor")
        self.assertEqual(engine.verificar(self.base)["registros"], 5)

    def test_valor_vazio_nao_e_exclusao(self):
        engine.put(self.base, 0, "")
        self.assertEqual(engine.get(self.base, 0), "")
        engine.delete(self.base, 0)
        engine.delete(self.base, 0)
        self.assertIsNone(engine.get(self.base, 0))
        self.assertIsNone(engine.get(self.base, 999))

    def test_chaves_uint64_sem_perda_de_precisao(self):
        for chave in (0, 2**53 + 1, 2**64 - 1):
            engine.put(self.base, chave, str(chave))
            self.assertEqual(engine.get(self.base, chave), str(chave))
        antes = self.base.read_bytes()
        for chave in (-1, 2**64, True, 1.5):
            for operacao in (engine.get, engine.delete):
                with self.assertRaises(ValueError):
                    operacao(self.base, chave)
            with self.assertRaises(ValueError):
                engine.put(self.base, chave, "invalido")
        self.assertEqual(self.base.read_bytes(), antes)

    def test_valor_grande_utf8_cruza_blocos_de_verificacao(self):
        texto = "á" * 40001 + "😀" * 25003 + '\n"fim"'
        engine.put(self.base, 1, texto)
        self.assertGreater(len(texto.encode("utf-8")), engine.TAMANHO_BLOCO)
        self.assertEqual(engine.verificar(self.base)["registros"], 1)
        self.assertEqual(engine.get(self.base, 1), texto)

    def test_operacoes_mistas_contra_oracle(self):
        esperado = {}
        rng = random.Random(20261015)
        chaves = (0, 25, 91, 2**53 + 1, 2**64 - 1)
        valores = ("", "ação", 'aspas "a"', "linha\nseguinte", "x" * 1000)
        with engine.Engine(self.base, criar=True) as banco:
            for _ in range(160):
                chave = rng.choice(chaves)
                if rng.random() < 0.6:
                    valor = rng.choice(valores)
                    banco.put(chave, valor)
                    esperado[chave] = valor
                else:
                    banco.delete(chave)
                    esperado.pop(chave, None)
                for consulta in chaves:
                    self.assertEqual(banco.get(consulta), esperado.get(consulta))
        for chave in chaves:
            self.assertEqual(engine.get(self.base, chave), esperado.get(chave))

    def _testar_todos_os_cortes(self, excluir):
        engine.put(self.base, 91, "valor confirmado")
        prefixo = self.base.read_bytes()
        if excluir:
            engine.delete(self.base, 91)
        else:
            engine.put(self.base, 91, "valor ainda sem resposta")
        completo = self.base.read_bytes()
        registro = completo[len(prefixo):]

        # Interrompe em cada byte possivel do registro final.
        for corte in range(1, len(registro)):
            with self.subTest(excluir=excluir, corte=corte):
                interrompido = prefixo + registro[:corte]
                self.base.write_bytes(interrompido)
                with self.assertRaises(engine.CaudaIncompleta):
                    engine.verificar(self.base)
                self.assertEqual(self.base.read_bytes(), interrompido)
                resultado = engine.recuperar(self.base)
                self.assertEqual(resultado["bytes_removidos"], corte)
                self.assertEqual(self.base.read_bytes(), prefixo)
                self.assertEqual(engine.get(self.base, 91), "valor confirmado")
                engine.put(self.base, 25, "apos recuperar")
                self.assertEqual(engine.get(self.base, 25), "apos recuperar")

        # Registro integral e valido pode sobreviver sem a resposta ter chegado.
        self.base.write_bytes(completo)
        self.assertEqual(engine.recuperar(self.base)["bytes_removidos"], 0)
        self.assertEqual(
            engine.get(self.base, 91), None if excluir else "valor ainda sem resposta"
        )

    def test_recuperacao_em_todos_os_cortes_de_put(self):
        self._testar_todos_os_cortes(excluir=False)

    def test_recuperacao_em_todos_os_cortes_de_delete(self):
        self._testar_todos_os_cortes(excluir=True)

    def test_abertura_recupera_automaticamente(self):
        engine.put(self.base, 91, "confirmado")
        original = self.base.read_bytes()
        with self.base.open("ab") as arquivo:
            arquivo.write(b"\x01\x00\x00")
        with engine.Engine(self.base) as banco:
            self.assertEqual(banco.recuperacao["bytes_removidos"], 3)
            self.assertEqual(banco.get(91), "confirmado")
        self.assertEqual(self.base.read_bytes(), original)

    def test_checksum_incorreto_no_ultimo_valor_nao_apaga_dados(self):
        engine.put(self.base, 91, "seguro")
        dados = bytearray(self.base.read_bytes())
        posicao_valor = len(engine.MAGIC) + engine.CABECALHO.size + engine.CRC.size
        dados[posicao_valor] ^= 1
        self.base.write_bytes(dados)
        for funcao in (engine.verificar, engine.recuperar):
            with self.assertRaises(engine.ErroIntegridade):
                funcao(self.base)
            self.assertEqual(self.base.read_bytes(), bytes(dados))
        with self.assertRaises(engine.ErroIntegridade):
            engine.put(self.base, 25, "nao deve gravar")
        self.assertEqual(self.base.read_bytes(), bytes(dados))

    def test_corrupcao_no_meio_nao_apaga_registros_posteriores(self):
        engine.put(self.base, 1, "primeiro")
        inicio_segundo = self.base.stat().st_size
        engine.put(self.base, 2, "segundo")
        engine.put(self.base, 3, "terceiro")
        dados = bytearray(self.base.read_bytes())
        dados[inicio_segundo + engine.CABECALHO.size + engine.CRC.size] ^= 1
        self.base.write_bytes(dados)
        with self.assertRaises(engine.ErroIntegridade):
            engine.recuperar(self.base)
        self.assertEqual(self.base.read_bytes(), bytes(dados))

    def test_tamanho_corrompido_nao_parece_cauda_incompleta(self):
        engine.put(self.base, 91, "confirmado")
        dados = bytearray(self.base.read_bytes())
        dados[len(engine.MAGIC) + 1 + 8] ^= 128
        self.base.write_bytes(dados)
        with self.assertRaisesRegex(engine.ErroIntegridade, "Checksum do cabecalho"):
            engine.recuperar(self.base)
        self.assertEqual(self.base.read_bytes(), bytes(dados))

    def test_cabecalho_da_base_corrompido_nao_e_recriado(self):
        self.base.write_bytes(b"ED2")
        with self.assertRaises(engine.ErroIntegridade):
            engine.recuperar(self.base)
        self.assertEqual(self.base.read_bytes(), b"ED2")

    def test_falha_de_sync_impede_mais_operacoes_na_instancia(self):
        with engine.Engine(self.base, criar=True) as banco:
            banco.put(91, "confirmado")
            with mock.patch.object(engine.os, "fsync", side_effect=OSError("falha")):
                with self.assertRaises(OSError):
                    banco.put(91, "sem confirmacao")
            with self.assertRaises(OSError):
                banco.put(25, "outro")
        # A operacao sem confirmacao pode sobreviver ou nao; o prefixo e valido.
        engine.verificar(self.base)

    def test_migracao_preserva_origem_historico_e_estado(self):
        registros = [(1, 91, "Ana"), (1, 91, "Karoline"), (1, 25, "Computação"),
                     (2, 91, ""), (1, 91, "Novo valor")]
        antigo = b"".join(
            struct.pack("<BQQ", tipo, chave, len(valor.encode("utf-8")))
            + valor.encode("utf-8") for tipo, chave, valor in registros
        )
        origem = Path(self.pasta.name) / "antigo.bin"
        origem.write_bytes(antigo)
        self.assertEqual(engine.migrar(origem, self.base), len(registros))
        self.assertEqual(origem.read_bytes(), antigo)
        self.assertEqual(engine.get(self.base, 91), "Novo valor")
        self.assertEqual(engine.get(self.base, 25), "Computação")
        self.assertEqual(engine.verificar(self.base)["registros"], len(registros))
        antes = self.base.read_bytes()
        with self.assertRaises(FileExistsError):
            engine.migrar(origem, self.base)
        self.assertEqual(self.base.read_bytes(), antes)

    def test_migracao_incompleta_nao_publica_base_parcial(self):
        origem = Path(self.pasta.name) / "antigo.bin"
        antigo = struct.pack("<BQQ", 1, 91, 10) + b"curto"
        origem.write_bytes(antigo)
        with self.assertRaises(engine.ErroIntegridade):
            engine.migrar(origem, self.base)
        self.assertFalse(self.base.exists())
        self.assertEqual(origem.read_bytes(), antigo)

    def test_init_recusa_apagar_base_existente(self):
        engine.inicializar(self.base)
        self.assertEqual(engine.verificar(self.base)["registros"], 0)
        antes = self.base.read_bytes()
        with self.assertRaises(FileExistsError):
            engine.inicializar(self.base)
        self.assertEqual(self.base.read_bytes(), antes)

    def test_cli_em_processos_separados(self):
        for operacao, argumentos, esperado in [
            ("put", ["91", "Karoline"], "PUT gravado: chave=91, tamanho=8 bytes"),
            ("get", ["91"], "Valor encontrado: Karoline"),
            ("delete", ["91"], "DELETE gravado: chave=91"),
            ("get", ["91"], "not_found"),
        ]:
            resultado = subprocess.run(
                [sys.executable, str(RAIZ / "engine.py"), operacao, str(self.base), *argumentos],
                capture_output=True, text=True, encoding="utf-8", check=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(resultado.stdout.strip(), esperado)

    def test_interrupcao_real_de_processo_durante_put(self):
        engine.put(self.base, 91, "confirmado")
        original = self.base.read_bytes()
        pronto = Path(self.pasta.name) / "pronto.txt"
        codigo = '''
import pathlib, sys
import engine
def escrita_interrompida(arquivo, dados):
    arquivo.write(dados[:5])
    arquivo.flush()
    pathlib.Path(sys.argv[2]).write_text("pronto", encoding="utf-8")
    sys.stdin.read()
engine._escrever_tudo = escrita_interrompida
with engine.Engine(sys.argv[1]) as banco:
    banco.put(91, "operacao interrompida")
'''
        processo = subprocess.Popen(
            [sys.executable, "-c", codigo, str(self.base), str(pronto)],
            cwd=RAIZ, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            limite = time.monotonic() + 10
            while not pronto.exists() and processo.poll() is None and time.monotonic() < limite:
                time.sleep(0.01)
            self.assertTrue(pronto.exists(), "O processo filho nao chegou a escrita parcial.")
            processo.kill()
            processo.communicate(timeout=5)
        finally:
            if processo.poll() is None:
                processo.kill()
                processo.communicate(timeout=5)
        with engine.Engine(self.base) as banco:
            self.assertEqual(banco.recuperacao["bytes_removidos"], 5)
            self.assertEqual(banco.get(91), "confirmado")
        self.assertEqual(self.base.read_bytes(), original)


class TestWorkloadJSONL(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.raiz = Path(self.pasta.name)
        self.base = self.raiz / "dados.bin"
        self.entrada = self.raiz / "entrada.jsonl"
        self.saida = self.raiz / "saida.jsonl"
        engine.inicializar(self.base)

    def _escrever_operacoes(self, operacoes):
        with self.entrada.open("w", encoding="utf-8") as arquivo:
            for operacao in operacoes:
                arquivo.write(json.dumps(operacao, ensure_ascii=False) + "\n")

    def _ler_respostas(self):
        return [json.loads(linha) for linha in self.saida.read_text(encoding="utf-8").splitlines()]

    def test_workload_exemplo_e_persistencia(self):
        exemplo = RAIZ / "workload_exemplo.jsonl"
        antes = exemplo.read_bytes()
        quantidade = engine.executar_workload(self.base, exemplo, self.saida)
        self.assertEqual(quantidade, 10)
        self.assertEqual(self._ler_respostas(), [
            {"id": 1, "status": "ok"},
            {"id": 2, "status": "ok"},
            {"id": 3, "status": "ok", "value": "Karoline"},
            {"id": 4, "status": "ok"},
            {"id": 5, "status": "ok"},
            {"id": 6, "status": "not_found"},
            {"id": 7, "status": "ok"},
            {"id": 8, "status": "ok", "value": "Novo valor"},
            {"id": 9, "status": "ok", "value": "Computação"},
            {"id": 10, "status": "not_found"},
        ])
        self.assertEqual(engine.get(self.base, 91), "Novo valor")
        self.assertEqual(engine.get(self.base, 25), "Computação")
        self.assertEqual(engine.verificar(self.base)["registros"], 5)
        self.assertEqual(exemplo.read_bytes(), antes)

    def test_jsonl_chaves_uint64_valores_e_ids(self):
        texto = 'ação\n"linha seguinte"'
        self._escrever_operacoes([
            {"id": 10**30 + 1, "op": "put", "key": 2**64 - 1, "value": ""},
            {"id": "consulta vazia", "op": "get", "key": 2**64 - 1},
            {"id": 10**30 + 2, "op": "put", "key": 2**53 + 1, "value": texto},
            {"id": "consulta ação", "op": "get", "key": 2**53 + 1},
        ])
        self.assertEqual(engine.executar_workload(self.base, self.entrada, self.saida), 4)
        respostas = self._ler_respostas()
        self.assertEqual(respostas[0]["id"], 10**30 + 1)
        self.assertEqual(respostas[1]["value"], "")
        self.assertEqual(respostas[3], {"id": "consulta ação", "status": "ok", "value": texto})
        self.assertEqual(len(self.saida.read_text(encoding="utf-8").splitlines()), 4)

    def test_linhas_invalidas_param_no_prefixo_valido(self):
        invalidas = [
            "", "{", "[]", "null",
            '{"id":2,"op":"get","key":true}',
            '{"id":2,"op":"get","key":91.0}',
            '{"id":2,"op":"get","key":18446744073709551616}',
            '{"id":2,"op":"put","key":2,"value":null}',
            '{"id":2,"op":"scan","key":2}',
            '{"op":"get","key":2}',
            '{"id":2,"op":"get","key":91,"key":92}',
            '{"id":NaN,"op":"get","key":2}',
            r'{"id":2,"op":"put","key":2,"value":"\ud800"}',
            r'{"id":"\ud800","op":"get","key":2}',
        ]
        prefixo = '{"id":1,"op":"put","key":91,"value":"confirmado"}\n'
        depois = '{"id":3,"op":"put","key":3,"value":"nao executar"}\n'
        for invalida in invalidas:
            with self.subTest(linha=invalida):
                self.base.write_bytes(engine.MAGIC)
                self.entrada.write_text(prefixo + invalida + "\n" + depois, encoding="utf-8")
                with self.assertRaisesRegex(engine.ErroWorkload, "Linha 2:"):
                    engine.executar_workload(self.base, self.entrada, self.saida)
                self.assertEqual(self._ler_respostas(), [{"id": 1, "status": "ok"}])
                self.assertEqual(engine.get(self.base, 91), "confirmado")
                self.assertIsNone(engine.get(self.base, 3))
                self.assertEqual(engine.verificar(self.base)["registros"], 1)

    def test_run_recupera_cauda_antes_do_lote(self):
        engine.put(self.base, 91, "confirmado")
        original = self.base.read_bytes()
        with self.base.open("ab") as arquivo:
            arquivo.write(b"\x01\x00")
        self._escrever_operacoes([{"id": 1, "op": "get", "key": 91}])
        engine.executar_workload(self.base, self.entrada, self.saida)
        self.assertEqual(self.base.read_bytes(), original)
        self.assertEqual(self._ler_respostas(), [{"id": 1, "status": "ok", "value": "confirmado"}])

    def test_saida_nao_substitui_base_ou_workload(self):
        self._escrever_operacoes([{"id": 1, "op": "get", "key": 91}])
        original_base = self.base.read_bytes()
        original_entrada = self.entrada.read_bytes()
        for base, entrada, saida in [
            (self.base, self.entrada, self.base),
            (self.base, self.entrada, self.entrada),
            (self.base, self.base, self.saida),
        ]:
            with self.subTest(saida=str(saida)):
                with self.assertRaisesRegex(ValueError, "arquivos diferentes"):
                    engine.executar_workload(base, entrada, saida)
                self.assertEqual(self.base.read_bytes(), original_base)
                self.assertEqual(self.entrada.read_bytes(), original_entrada)

    def test_hardlink_nao_permite_apagar_workload(self):
        self._escrever_operacoes([{"id": 1, "op": "get", "key": 91}])
        original = self.entrada.read_bytes()
        try:
            os.link(self.entrada, self.saida)
        except OSError as erro:
            self.skipTest(f"Sistema de arquivos sem hardlink disponivel: {erro}")
        with self.assertRaises(ValueError):
            engine.executar_workload(self.base, self.entrada, self.saida)
        self.assertEqual(self.entrada.read_bytes(), original)

    def test_cli_data_dir_run_describe_verify(self):
        pasta_base = self.raiz / "base_demo"

        def executar(*argumentos, sucesso=True):
            resultado = subprocess.run(
                [sys.executable, str(RAIZ / "engine.py"), *map(str, argumentos)],
                capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(resultado.returncode == 0, sucesso, resultado.stderr)
            return resultado

        executar("init", "--data-dir", pasta_base)
        resultado = executar("run", "--data-dir", pasta_base,
                             "--input", RAIZ / "workload_exemplo.jsonl", "--output", self.saida)
        self.assertEqual(resultado.stdout, "")
        self.assertIn("operacoes=10", resultado.stderr)
        self.assertEqual(len(self._ler_respostas()), 10)
        self.assertIn("Integridade OK", executar("verify", "--data-dir", pasta_base).stdout)
        descricao = json.loads(executar("describe").stdout)
        self.assertEqual(descricao["operacoes"], ["put", "get", "delete"])
        self.assertEqual(descricao["formato_arquivo"], 2)
        base = pasta_base / engine.NOME_ARQUIVO_BASE
        antes = base.read_bytes()
        executar("init", "--data-dir", pasta_base, sucesso=False)
        self.assertEqual(base.read_bytes(), antes)

    def test_cli_run_file_e_erro_com_saida_nao_zero(self):
        self._escrever_operacoes([{"id": 1, "op": "put", "key": 91, "value": "ação"},
                                 {"id": 2, "op": "get", "key": 91}])
        argumentos = [sys.executable, str(RAIZ / "engine.py"), "run", "--file", str(self.base),
                      "--input", str(self.entrada), "--output", str(self.saida)]
        resultado = subprocess.run(argumentos, capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(resultado.stdout, "")
        self.assertEqual(self._ler_respostas()[1]["value"], "ação")
        self.entrada.write_text("{}\n", encoding="utf-8")
        resultado = subprocess.run(argumentos, capture_output=True, text=True)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("Linha 1:", resultado.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
