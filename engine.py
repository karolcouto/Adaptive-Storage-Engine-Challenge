"""ED2 - Passo 5: operacoes persistentes, recuperacao e workloads JSONL.

Exemplos:
    py engine.py migrate dados.bin dados_v2.bin
    py engine.py verify dados_v2.bin
    py engine.py put dados_v2.bin 91 "Karoline"
    py engine.py get dados_v2.bin 91
    py engine.py delete dados_v2.bin 91
    py engine.py recover dados_v2.bin
    py engine.py run --file dados_v2.bin --input workload_exemplo.jsonl --output resultados.jsonl
    py engine.py init --data-dir base_demo
    py engine.py run --data-dir base_demo --input workload_exemplo.jsonl --output resultados.jsonl
    py engine.py verify --data-dir base_demo
    py engine.py describe

Formato v2: identificacao ED2KV002 no inicio do arquivo. Cada registro tem:
    tipo (1) | chave (8) | tamanho (8) | CRC do cabecalho (4)
    | valor (N) | CRC do cabecalho e valor (4)

Inteiros em little-endian; valores em UTF-8. Uma unica instancia escreve
na base por vez. O engine valida e recupera na abertura; um lote JSONL
reutiliza a mesma instancia de Engine para muitas operacoes.
A interface segue a referencia inicial do enunciado; o schema final e o
ambiente oficial da disciplina ainda precisam ser conferidos quando publicados.
"""

import argparse
import codecs
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib


TIPO_PUT = 1
TIPO_DELETE = 2
MAX_CHAVE = 2**64 - 1
MAGIC = b"ED2KV002"
CABECALHO = struct.Struct("<BQQ")
CRC = struct.Struct("<I")
TAMANHO_BLOCO = 64 * 1024
NOME_ARQUIVO_BASE = "dados.bin"


class ErroIntegridade(ValueError):
    """O arquivo tem conteudo invalido; nao deve ser apagado automaticamente."""


class CaudaIncompleta(ErroIntegridade):
    """O ultimo registro terminou antes de todos os seus bytes serem gravados."""

    def __init__(self, posicao):
        self.posicao = posicao
        super().__init__(f"Registro incompleto no final, a partir do byte {posicao}.")


class ErroWorkload(ValueError):
    """Uma linha de entrada nao representa uma operacao suportada."""


def validar_chave(chave):
    if type(chave) is not int or not 0 <= chave <= MAX_CHAVE:
        raise ValueError("A chave deve ser um inteiro entre 0 e 2**64 - 1.")


def _escrever_tudo(arquivo, dados):
    if arquivo.write(dados) != len(dados):
        raise OSError("Nao foi possivel gravar todos os bytes.")


def _sincronizar(arquivo):
    arquivo.flush()
    os.fsync(arquivo.fileno())


def _sincronizar_pasta(pasta):
    # No Linux, confirma tambem a criacao/renomeacao da entrada no diretorio.
    if os.name == "posix":
        descritor = os.open(pasta, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descritor)
        finally:
            os.close(descritor)


def _publicar_base(destino, preencher):
    """Monta uma base temporaria e a publica completa, sem substituir dados."""
    destino = Path(destino)
    if os.path.lexists(destino):
        raise FileExistsError(f"O destino ja existe: {destino}")

    descritor, temporario = tempfile.mkstemp(
        prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent
    )
    try:
        with os.fdopen(descritor, "w+b") as arquivo:
            _escrever_tudo(arquivo, MAGIC)
            resultado = preencher(arquivo)
            _sincronizar(arquivo)
        # O uso concorrente da mesma base nao e suportado nesta entrega inicial.
        if os.path.lexists(destino):
            raise FileExistsError(f"O destino ja existe: {destino}")
        os.replace(temporario, destino)
        _sincronizar_pasta(destino.parent)
        return resultado
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def inicializar(caminho):
    """Cria uma base vazia; recusa substituir um arquivo existente."""
    _publicar_base(caminho, lambda arquivo: None)


def _checar_formato(arquivo):
    arquivo.seek(0)
    if arquivo.read(len(MAGIC)) != MAGIC:
        raise ErroIntegridade(
            "Formato antigo ou cabecalho da base invalido. "
            "Para dados da versao anterior, use: migrate origem destino."
        )


def _ler_registro(arquivo, tamanho_arquivo, verificar_valor=True):
    """Le um registro; valida em blocos para nao carregar o historico na RAM."""
    inicio = arquivo.tell()
    cabecalho = arquivo.read(CABECALHO.size)
    if cabecalho == b"":
        return None
    crc_cabecalho = arquivo.read(CRC.size)
    if len(cabecalho) != CABECALHO.size or len(crc_cabecalho) != CRC.size:
        raise CaudaIncompleta(inicio)

    # Confere o tamanho antes de confiar nele para decidir onde o registro acaba.
    if CRC.unpack(crc_cabecalho)[0] != zlib.crc32(cabecalho):
        raise ErroIntegridade(f"Checksum do cabecalho incorreto no byte {inicio}.")
    tipo, chave, tamanho = CABECALHO.unpack(cabecalho)
    if tipo not in (TIPO_PUT, TIPO_DELETE):
        raise ErroIntegridade(f"Tipo de registro invalido no byte {inicio}.")
    if tipo == TIPO_DELETE and tamanho != 0:
        raise ErroIntegridade(f"DELETE com valor no byte {inicio}.")

    posicao_valor = arquivo.tell()
    if tamanho + CRC.size > tamanho_arquivo - posicao_valor:
        raise CaudaIncompleta(inicio)

    if verificar_valor:
        checksum = zlib.crc32(cabecalho)
        decoder = codecs.getincrementaldecoder("utf-8")()
        restante = tamanho
        try:
            while restante:
                bloco = arquivo.read(min(restante, TAMANHO_BLOCO))
                if not bloco:
                    raise CaudaIncompleta(inicio)
                checksum = zlib.crc32(bloco, checksum)
                decoder.decode(bloco)
                restante -= len(bloco)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as erro:
            raise ErroIntegridade(f"Valor UTF-8 invalido no byte {inicio}.") from erro
        crc_registro = arquivo.read(CRC.size)
        if len(crc_registro) != CRC.size:
            raise CaudaIncompleta(inicio)
        if CRC.unpack(crc_registro)[0] != checksum:
            raise ErroIntegridade(f"Checksum do registro incorreto no byte {inicio}.")
    else:
        arquivo.seek(tamanho + CRC.size, os.SEEK_CUR)

    return tipo, chave, tamanho, posicao_valor, cabecalho


def _examinar(arquivo, recuperar=False):
    """Valida tudo; recuperacao so permite remover a cauda incompleta."""
    _checar_formato(arquivo)
    tamanho_original = os.fstat(arquivo.fileno()).st_size
    ultimo_fim_valido = len(MAGIC)
    quantidade = 0
    removidos = 0
    try:
        while _ler_registro(arquivo, tamanho_original) is not None:
            quantidade += 1
            ultimo_fim_valido = arquivo.tell()
    except CaudaIncompleta:
        if not recuperar:
            raise
        arquivo.truncate(ultimo_fim_valido)
        arquivo.seek(ultimo_fim_valido)
        _sincronizar(arquivo)
        removidos = tamanho_original - ultimo_fim_valido

    return {
        "registros": quantidade,
        "bytes": ultimo_fim_valido,
        "bytes_removidos": removidos,
    }


def verificar(caminho):
    """Somente le: se houver erro, o arquivo continua intacto."""
    with open(caminho, "rb") as arquivo:
        return _examinar(arquivo)


def recuperar(caminho):
    """Trunca apenas uma cauda incompleta; checksum incorreto causa erro."""
    with open(caminho, "r+b") as arquivo:
        return _examinar(arquivo, recuperar=True)


class Engine:
    """Abre e recupera uma vez; pode executar muitas operacoes em seguida."""

    def __init__(self, caminho, criar=False):
        if criar and not os.path.lexists(caminho):
            inicializar(caminho)
        self.arquivo = open(caminho, "r+b")
        self.falhou = False
        try:
            self.recuperacao = _examinar(self.arquivo, recuperar=True)
        except BaseException:
            self.arquivo.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        self.arquivo.close()

    def _checar_estado(self):
        if self.falhou:
            raise OSError("A escrita falhou. Feche e reabra o engine para recuperar.")

    def _anexar(self, tipo, chave, dados):
        self._checar_estado()
        cabecalho = CABECALHO.pack(tipo, chave, len(dados))
        checksum = zlib.crc32(dados, zlib.crc32(cabecalho))
        try:
            self.arquivo.seek(0, os.SEEK_END)
            _escrever_tudo(self.arquivo, cabecalho)
            _escrever_tudo(self.arquivo, CRC.pack(zlib.crc32(cabecalho)))
            _escrever_tudo(self.arquivo, dados)
            _escrever_tudo(self.arquivo, CRC.pack(checksum))
            _sincronizar(self.arquivo)
        except BaseException:
            self.falhou = True
            raise

    def put(self, chave, valor):
        validar_chave(chave)
        if not isinstance(valor, str):
            raise TypeError("O valor deve ser texto.")
        self._anexar(TIPO_PUT, chave, valor.encode("utf-8"))

    def delete(self, chave):
        validar_chave(chave)
        self._anexar(TIPO_DELETE, chave, b"")

    def get(self, chave):
        validar_chave(chave)
        self._checar_estado()
        self.arquivo.seek(len(MAGIC))
        tamanho_arquivo = os.fstat(self.arquivo.fileno()).st_size
        ultima_ocorrencia = None
        while True:
            registro = _ler_registro(self.arquivo, tamanho_arquivo, verificar_valor=False)
            if registro is None:
                break
            tipo, chave_lida, tamanho, posicao_valor, cabecalho = registro
            if chave_lida == chave:
                ultima_ocorrencia = None if tipo == TIPO_DELETE else registro

        if ultima_ocorrencia is None:
            return None
        _, _, tamanho, posicao_valor, cabecalho = ultima_ocorrencia
        self.arquivo.seek(posicao_valor)
        dados = self.arquivo.read(tamanho)
        crc_registro = self.arquivo.read(CRC.size)
        if len(dados) != tamanho or len(crc_registro) != CRC.size:
            raise CaudaIncompleta(posicao_valor - CABECALHO.size - CRC.size)
        checksum = zlib.crc32(dados, zlib.crc32(cabecalho))
        if CRC.unpack(crc_registro)[0] != checksum:
            raise ErroIntegridade("Checksum incorreto durante GET.")
        return dados.decode("utf-8")


# Mantem a interface Python dos passos anteriores.
def put(caminho, chave, valor):
    validar_chave(chave)
    if not isinstance(valor, str):
        raise TypeError("O valor deve ser texto.")
    with Engine(caminho, criar=True) as engine:
        engine.put(chave, valor)


def get(caminho, chave):
    validar_chave(chave)
    with Engine(caminho) as engine:
        return engine.get(chave)


def delete(caminho, chave):
    validar_chave(chave)
    with Engine(caminho, criar=True) as engine:
        engine.delete(chave)


def migrar(origem, destino):
    """Copia o historico v1 para v2 em blocos, sem modificar o arquivo antigo."""
    origem = Path(origem)
    destino = Path(destino)
    if origem.resolve() == destino.resolve():
        raise ValueError("Origem e destino devem ser arquivos diferentes.")

    def preencher(saida):
        quantidade = 0
        with open(origem, "rb") as entrada:
            if entrada.read(len(MAGIC)) == MAGIC:
                raise ValueError("A origem ja usa o formato v2.")
            entrada.seek(0)
            tamanho_arquivo = os.fstat(entrada.fileno()).st_size
            while True:
                inicio = entrada.tell()
                cabecalho = entrada.read(CABECALHO.size)
                if not cabecalho:
                    break
                if len(cabecalho) != CABECALHO.size:
                    raise ErroIntegridade("A origem antiga termina com cabecalho incompleto.")
                tipo, chave, tamanho = CABECALHO.unpack(cabecalho)
                if tipo not in (TIPO_PUT, TIPO_DELETE) or (tipo == TIPO_DELETE and tamanho):
                    raise ErroIntegridade(f"Registro antigo invalido no byte {inicio}.")
                if tamanho > tamanho_arquivo - entrada.tell():
                    raise ErroIntegridade("A origem antiga termina com valor incompleto.")
                _escrever_tudo(saida, cabecalho)
                _escrever_tudo(saida, CRC.pack(zlib.crc32(cabecalho)))
                checksum = zlib.crc32(cabecalho)
                decoder = codecs.getincrementaldecoder("utf-8")()
                restante = tamanho
                try:
                    while restante:
                        bloco = entrada.read(min(restante, TAMANHO_BLOCO))
                        if not bloco:
                            raise ErroIntegridade("A origem mudou durante a migracao.")
                        decoder.decode(bloco)
                        checksum = zlib.crc32(bloco, checksum)
                        _escrever_tudo(saida, bloco)
                        restante -= len(bloco)
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError as erro:
                    raise ErroIntegridade("A origem contem texto UTF-8 invalido.") from erro
                _escrever_tudo(saida, CRC.pack(checksum))
                quantidade += 1
        return quantidade

    return _publicar_base(destino, preencher)


def _objeto_sem_campos_repetidos(pares):
    objeto = {}
    for campo, valor in pares:
        if campo in objeto:
            raise ValueError(f"Campo JSON repetido: {campo}")
        objeto[campo] = valor
    return objeto


def _rejeitar_constante_json(valor):
    raise ValueError(f"Constante nao permitida em JSON: {valor}")


def _ler_operacao(linha, numero):
    try:
        operacao = json.loads(
            linha,
            object_pairs_hook=_objeto_sem_campos_repetidos,
            parse_constant=_rejeitar_constante_json,
        )
        if not isinstance(operacao, dict):
            raise ValueError("Cada linha deve conter um objeto JSON.")
        for campo in ("id", "op", "key"):
            if campo not in operacao:
                raise ValueError(f"Campo obrigatorio ausente: {campo}")
        if operacao["op"] not in ("put", "get", "delete"):
            raise ValueError("Operacao suportada nesta entrega: put, get ou delete.")
        validar_chave(operacao["key"])
        if operacao["op"] == "put" and not isinstance(operacao.get("value"), str):
            raise ValueError("PUT precisa de value do tipo texto.")
        # O id e copiado sem conversao; verifica se pode sair em JSON UTF-8.
        json.dumps(operacao["id"], ensure_ascii=False, allow_nan=False).encode("utf-8")
        return operacao
    except (ValueError, TypeError) as erro:
        raise ErroWorkload(f"Linha {numero}: {erro}") from erro


def _executar_operacao(banco, operacao):
    resposta = {"id": operacao["id"], "status": "ok"}
    if operacao["op"] == "put":
        banco.put(operacao["key"], operacao["value"])
    elif operacao["op"] == "delete":
        banco.delete(operacao["key"])
    else:
        valor = banco.get(operacao["key"])
        if valor is None:
            resposta["status"] = "not_found"
        else:
            resposta["value"] = valor
    return resposta


def _mesmo_arquivo(primeiro, segundo):
    if Path(primeiro).resolve() == Path(segundo).resolve():
        return True
    if os.path.exists(primeiro) and os.path.exists(segundo):
        return os.path.samefile(primeiro, segundo)
    return False


def executar_workload(caminho, entrada, saida):
    """Processa uma linha por vez, mantendo a base aberta durante todo o lote.

    A unicidade dos ids e uma precondicao do workload, conforme o enunciado.
    Nao guarda um conjunto de todos os ids ou das chaves na memoria.
    Entrada invalida interrompe o lote com erro; as respostas do prefixo valido
    ficam no arquivo de saida. Nao inventa um status de erro fora do protocolo.
    """
    if (_mesmo_arquivo(caminho, entrada) or _mesmo_arquivo(caminho, saida)
            or _mesmo_arquivo(entrada, saida)):
        raise ValueError("Base, entrada e saida devem ser arquivos diferentes.")

    quantidade = 0
    # Aceita UTF-8 com ou sem BOM inicial e finais de linha Windows/Linux.
    with open(entrada, "r", encoding="utf-8-sig") as arquivo_entrada:
        with Engine(caminho) as banco:
            with open(saida, "w", encoding="utf-8", newline="\n") as arquivo_saida:
                for numero, linha in enumerate(arquivo_entrada, 1):
                    operacao = _ler_operacao(linha, numero)
                    try:
                        resposta = _executar_operacao(banco, operacao)
                    except (OSError, ValueError, TypeError) as erro:
                        raise ErroWorkload(f"Linha {numero}: {erro}") from erro
                    texto = json.dumps(resposta, ensure_ascii=False, allow_nan=False) + "\n"
                    if arquivo_saida.write(texto) != len(texto):
                        raise OSError("Nao foi possivel gravar a resposta completa.")
                    # As mutacoes ja passaram por fsync antes da resposta.
                    arquivo_saida.flush()
                    quantidade += 1
    return quantidade


def descrever():
    return {
        "nome": "ED2 Python Storage Engine",
        "entrega": 1,
        "formato_arquivo": 2,
        "chave": "uint64",
        "valor": "texto UTF-8 de tamanho variavel",
        "operacoes": ["put", "get", "delete"],
        "organizacao": "historico append-only com busca sequencial",
        "integridade": "CRC32 do cabecalho e do registro; validacao UTF-8",
        "durabilidade": "flush e fsync antes de confirmar cada mutacao",
        "recuperacao": "remove cauda incompleta na abertura; checksum incorreto causa erro",
        "concorrencia": "uma instancia por base",
        "protocolo": "JSONL UTF-8; ids copiados das operacoes",
        "delete_ausente": "ok; decisao provisoria ate o schema final",
    }


def _caminho_base(argumentos, parser):
    arquivo = getattr(argumentos, "arquivo", None)
    pasta = getattr(argumentos, "data_dir", None)
    if (arquivo is None) == (pasta is None):
        parser.error("Informe um arquivo ou --data-dir, escolhendo apenas um.")
    return Path(arquivo) if arquivo is not None else Path(pasta) / NOME_ARQUIVO_BASE


def main():
    parser = argparse.ArgumentParser(description="ED2 - Passo 5: Storage Engine e JSONL.")
    comandos = parser.add_subparsers(dest="operacao", required=True)
    for nome in ("put", "get", "delete"):
        comando = comandos.add_parser(nome)
        comando.add_argument("arquivo")
        comando.add_argument("chave", type=int)
        if nome == "put":
            comando.add_argument("valor")
    for nome in ("init", "verify", "recover"):
        comando = comandos.add_parser(nome)
        comando.add_argument("arquivo", nargs="?")
        comando.add_argument("--data-dir")
    comando = comandos.add_parser("migrate")
    comando.add_argument("origem")
    comando.add_argument("destino")
    comando = comandos.add_parser("run")
    base = comando.add_mutually_exclusive_group(required=True)
    base.add_argument("--file", dest="arquivo")
    base.add_argument("--data-dir")
    comando.add_argument("--input", dest="entrada", required=True)
    comando.add_argument("--output", dest="saida", required=True)
    comandos.add_parser("describe")
    argumentos = parser.parse_args()

    try:
        if argumentos.operacao == "init":
            caminho = _caminho_base(argumentos, parser)
            if argumentos.data_dir is not None:
                caminho.parent.mkdir(parents=True, exist_ok=True)
            inicializar(caminho)
            print(f"Base inicializada: {caminho}")
        elif argumentos.operacao == "migrate":
            quantidade = migrar(argumentos.origem, argumentos.destino)
            print(f"Migracao concluida: registros={quantidade}, destino={argumentos.destino}")
        elif argumentos.operacao in ("verify", "recover"):
            caminho = _caminho_base(argumentos, parser)
            funcao = verificar if argumentos.operacao == "verify" else recuperar
            resultado = funcao(caminho)
            print(
                f"{'Integridade OK' if argumentos.operacao == 'verify' else 'Recuperacao concluida'}: "
                f"registros={resultado['registros']}, bytes={resultado['bytes']}, "
                f"bytes_removidos={resultado['bytes_removidos']}"
            )
        elif argumentos.operacao == "run":
            caminho = _caminho_base(argumentos, parser)
            quantidade = executar_workload(caminho, argumentos.entrada, argumentos.saida)
            print(f"Workload concluido: operacoes={quantidade}", file=sys.stderr)
        elif argumentos.operacao == "describe":
            print(json.dumps(descrever(), ensure_ascii=False, indent=2))
        elif argumentos.operacao == "put":
            put(argumentos.arquivo, argumentos.chave, argumentos.valor)
            print(f"PUT gravado: chave={argumentos.chave}, tamanho={len(argumentos.valor.encode('utf-8'))} bytes")
        elif argumentos.operacao == "delete":
            delete(argumentos.arquivo, argumentos.chave)
            print(f"DELETE gravado: chave={argumentos.chave}")
        else:
            valor = get(argumentos.arquivo, argumentos.chave)
            print("not_found" if valor is None else f"Valor encontrado: {valor}")
    except (OSError, ValueError, TypeError) as erro:
        parser.exit(1, f"Erro: {erro}\n")


if __name__ == "__main__":
    main()
