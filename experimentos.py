"""Experimentos locais reproduziveis da entrega 1, somente com biblioteca padrao.

    py experimentos.py
    py experimentos.py --memory-test
    py experimentos.py --sizes 200 800 --repetitions 3 --seed 20261015 --output-dir outra_execucao

Cada medicao usa outro processo, uma base nova e arquivos proprios. O oracle
usa um dicionario no processo coordenador, fora do processo medido. O programa
recusa reutilizar uma pasta de resultados existente. Nao e o ED2Bench oficial.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import zip_longest
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

import engine


MIB = 1024 * 1024
RAIZ = Path(__file__).resolve().parent


def _salvar_json(caminho, objeto):
    Path(caminho).write_text(json.dumps(objeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _pico_memoria():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Contadores(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (nome, ctypes.c_size_t) for nome in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage",
                )
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        contadores = Contadores()
        contadores.cb = ctypes.sizeof(contadores)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(contadores), contadores.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(contadores.PeakWorkingSetSize), "Windows PeakWorkingSetSize"

    import resource
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(pico * (1 if sys.platform == "darwin" else 1024)), "getrusage ru_maxrss"


def _aplicar_limite(mib):
    if not mib or not sys.platform.startswith("linux"):
        return None
    import resource
    solicitado = mib * MIB
    atual, maximo = resource.getrlimit(resource.RLIMIT_AS)
    candidatos = [solicitado] + [x for x in (atual, maximo) if x != resource.RLIM_INFINITY]
    aplicado = min(candidatos)
    resource.setrlimit(resource.RLIMIT_AS, (aplicado, maximo))
    return aplicado


def _worker(configuracao):
    configuracao = Path(configuracao)
    config = json.loads(configuracao.read_text(encoding="utf-8"))
    pasta = configuracao.parent
    limite = _aplicar_limite(config["memory_limit_mib"])
    base = pasta / "base.bin"
    engine.inicializar(base)
    engine.executar_workload(base, pasta / "preparo.jsonl", pasta / "respostas_preparo.jsonl")
    bytes_antes = base.stat().st_size
    inicio = time.perf_counter()
    quantidade = engine.executar_workload(base, pasta / "workload.jsonl", pasta / "respostas.jsonl")
    segundos = time.perf_counter() - inicio
    pico, metodo = _pico_memoria()
    integridade = engine.verificar(base)
    bytes_depois = base.stat().st_size
    _salvar_json(pasta / "metricas_worker.json", {
        "operacoes": quantidade,
        "segundos": segundos,
        "operacoes_por_segundo": quantidade / segundos,
        "pico_memoria_bytes": pico,
        "metodo_memoria": metodo,
        "limite_virtual_bytes": limite,
        "bytes_base_antes": bytes_antes,
        "bytes_base_depois": bytes_depois,
        "crescimento_bytes": bytes_depois - bytes_antes,
        "registros_historicos": integridade["registros"],
        "base_maior_que_pico_memoria": bytes_depois > pico,
        "base_maior_que_limite_virtual": None if limite is None else bytes_depois > limite,
    })


def _valor(chave, tamanho):
    prefixo = f"{chave}:ação|"
    return prefixo + "x" * max(0, tamanho - len(prefixo.encode("utf-8")))


def _gerar(pasta, cenario, tamanho, seed, bytes_valor):
    rng = random.Random(seed)
    identificador = 0
    contagem = {"put": 0, "get": 0, "delete": 0}

    def emitir(arquivo, op, chave, valor=None, medir=True):
        nonlocal identificador
        identificador += 1
        objeto = {"id": identificador, "op": op, "key": chave}
        if op == "put":
            objeto["value"] = valor
        arquivo.write(json.dumps(objeto, ensure_ascii=False, separators=(",", ":")) + "\n")
        if medir:
            contagem[op] += 1

    def valor_variavel(chave):
        return _valor(chave, rng.randint(max(16, bytes_valor // 2), max(16, bytes_valor * 3 // 2)))

    with (pasta / "preparo.jsonl").open("w", encoding="utf-8", newline="\n") as preparo:
        if cenario in ("leituras", "mista"):
            for chave in range(tamanho):
                emitir(preparo, "put", chave, valor_variavel(chave), medir=False)

    with (pasta / "workload.jsonl").open("w", encoding="utf-8", newline="\n") as carga:
        if cenario in ("insercoes", "memoria"):
            for chave in range(tamanho):
                valor = _valor(chave, bytes_valor) if cenario == "memoria" else valor_variavel(chave)
                emitir(carga, "put", chave, valor)
            if cenario == "memoria":
                consultas = [0, tamanho - 1] + rng.sample(range(1, tamanho - 1), min(18, tamanho - 2))
                for chave in consultas:
                    emitir(carga, "get", chave)
        elif cenario == "leituras":
            for _ in range(tamanho):
                emitir(carga, "get", rng.randrange(tamanho + max(1, tamanho // 10)))
        else:
            for _ in range(tamanho):
                chave = rng.randrange(tamanho + max(1, tamanho // 5))
                sorteio = rng.random()
                op = "put" if sorteio < 0.35 else "get" if sorteio < 0.85 else "delete"
                emitir(carga, op, chave, valor_variavel(chave) if op == "put" else None)
    return contagem


def _conferir_com_oracle(pasta):
    estado = {}
    total = 0
    for entrada, saida in [("preparo.jsonl", "respostas_preparo.jsonl"),
                          ("workload.jsonl", "respostas.jsonl")]:
        with (pasta / entrada).open(encoding="utf-8") as operacoes:
            with (pasta / saida).open(encoding="utf-8") as respostas:
                for numero, (linha, resposta) in enumerate(zip_longest(operacoes, respostas), 1):
                    if linha is None or resposta is None:
                        raise RuntimeError(f"Quantidade de respostas diferente em {saida}, linha {numero}.")
                    op = json.loads(linha)
                    obtido = json.loads(resposta)
                    esperado = {"id": op["id"], "status": "ok"}
                    if op["op"] == "put":
                        estado[op["key"]] = op["value"]
                    elif op["op"] == "delete":
                        estado.pop(op["key"], None)
                    elif op["key"] in estado:
                        esperado["value"] = estado[op["key"]]
                    else:
                        esperado["status"] = "not_found"
                    if obtido != esperado:
                        raise RuntimeError(f"Resposta incorreta em {saida}, linha {numero}: id={op['id']}")
                    total += 1
    return {"respostas_conferidas": total, "chaves_vivas": len(estado),
            "bytes_valores_vivos": sum(len(valor.encode("utf-8")) for valor in estado.values())}


def _relatorio(pasta, ambiente, resultados):
    linhas = ["# Resultados dos experimentos locais", "",
              "Todas as respostas foram comparadas com um oráculo independente no processo coordenador.",
              "Cada medição usa uma base nova e um processo separado. O tempo inclui abertura, recuperação,",
              "JSONL, execução e escrita das respostas. A preparação e o oráculo ficam fora do tempo medido.", "",
              f"Ambiente: {ambiente['sistema']}; Python {ambiente['python']}; "
              f"{ambiente['cpus_logicas']} CPUs lógicas disponíveis.",
              f"SHA256 de engine.py: `{ambiente['engine_sha256']}`.", "",
              "| Cenário | N | Repetições | Tempo mediano s | Operações/s medianas | Pico memória máximo MiB | Base final MiB | Crescimento MiB |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    grupos = {}
    for resultado in resultados:
        grupos.setdefault((resultado["cenario"], resultado["tamanho"]), []).append(resultado)
    for (cenario, tamanho), grupo in grupos.items():
        mediana = lambda campo: statistics.median(x[campo] for x in grupo)
        linhas.append(f"| {cenario} | {tamanho} | {len(grupo)} | {mediana('segundos'):.6f} | "
                      f"{mediana('operacoes_por_segundo'):.1f} | "
                      f"{max(x['pico_memoria_bytes'] for x in grupo) / MIB:.2f} | "
                      f"{mediana('bytes_base_depois') / MIB:.4f} | {mediana('crescimento_bytes') / MIB:.4f} |")
    linhas += ["", "## Memória e validade das medições", "",
               "O pico inclui o interpretador e a preparação do processo medido. O oráculo usa RAM em outro processo.",
               "No Windows, a métrica é PeakWorkingSetSize; no Unix, ru_maxrss. As métricas não incluem o cache global do SO.",
               "A base maior que o pico observado demonstra uso de memória menor que o tamanho da base;",
               "somente uma execução com limite aplicado e base maior que esse limite demonstra o caso sob limite imposto."]
    for resultado in resultados:
        if resultado["cenario"] == "memoria":
            limite = resultado["limite_virtual_bytes"]
            linhas += ["", f"Base final: {resultado['bytes_base_depois'] / MIB:.2f} MiB.",
                       f"Pico medido: {resultado['pico_memoria_bytes'] / MIB:.2f} MiB.",
                       f"Base maior que o pico medido: {resultado['base_maior_que_pico_memoria']}.",
                       f"Limite virtual aplicado: {'não aplicado neste sistema' if limite is None else str(limite / MIB) + ' MiB (Linux RLIMIT_AS)' }.",
                       f"Base maior que o limite: {resultado['base_maior_que_limite_virtual']}."]
    linhas += ["", "## Limitações", "",
               "Os resultados são deste computador e desta execução. Não são notas nem resultados do ED2Bench oficial.",
               "O limite Linux RLIMIT_AS limita espaço de endereçamento virtual, não somente RSS. No Windows este script mede memória, mas não impõe limite.",
               "Não limpamos o cache do sistema operacional. As repetições de um caso usam a mesma seed e a mesma carga.",
               "O tempo inclui a verificação inicial do arquivo; execuções curtas sofrem influência maior desse custo.",
               "Não há comparação com outras arquiteturas; leituras sequenciais e versões antigas limitam o desempenho e o espaço.",
               "Os JSONs e as cargas de cada execução ficam nas subpastas para reprodução e auditoria.", ""]
    (pasta / "relatorio.md").write_text("\n".join(linhas), encoding="utf-8")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        _worker(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description="Experimentos locais reprodutiveis da entrega 1.")
    parser.add_argument("--sizes", nargs="+", type=int, default=[200, 800])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261015)
    parser.add_argument("--value-bytes", type=int, default=128)
    parser.add_argument("--output-dir")
    parser.add_argument("--memory-test", action="store_true")
    parser.add_argument("--memory-records", type=int, default=14000)
    parser.add_argument("--memory-value-bytes", type=int, default=4096)
    parser.add_argument("--memory-limit-mib", type=int, default=48)
    args = parser.parse_args()
    if (min(args.sizes) <= 0 or args.repetitions <= 0 or args.value_bytes < 32
            or args.memory_records < 2 or args.memory_value_bytes < 32 or args.memory_limit_mib <= 0):
        parser.error("Use escalas/repeticoes positivas, valores >= 32 bytes e pelo menos 2 registros no teste de memoria.")
    pasta = Path(args.output_dir or ("resultados_memoria" if args.memory_test else "resultados_experimentos")).resolve()
    try:
        pasta.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"A pasta ja existe; escolha outra com --output-dir: {pasta}")
    ambiente = {
        "data_utc": datetime.now(timezone.utc).isoformat(),
        "sistema": platform.platform(), "python": platform.python_version(),
        "cpus_logicas": os.cpu_count(), "processador": platform.processor(),
        "engine_sha256": hashlib.sha256((RAIZ / "engine.py").read_bytes()).hexdigest(),
        "parametros": vars(args),
    }
    _salvar_json(pasta / "ambiente.json", ambiente)
    casos = [("memoria", args.memory_records, 1)] if args.memory_test else [
        (cenario, tamanho, repeticao) for tamanho in args.sizes
        for cenario in ("insercoes", "leituras", "mista")
        for repeticao in range(1, args.repetitions + 1)
    ]
    resultados = []
    for cenario, tamanho, repeticao in casos:
        destino = pasta / f"{cenario}_n{tamanho}_r{repeticao}"
        destino.mkdir()
        contagem = _gerar(destino, cenario, tamanho, args.seed,
                         args.memory_value_bytes if args.memory_test else args.value_bytes)
        config = {"memory_limit_mib": args.memory_limit_mib if args.memory_test else None}
        _salvar_json(destino / "config.json", config)
        print(f"Executando {cenario}: N={tamanho}, repeticao={repeticao}", flush=True)
        processo = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(destino / "config.json")],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if processo.returncode != 0:
            raise RuntimeError(f"O processo medido falhou:\n{processo.stderr}")
        resultado = json.loads((destino / "metricas_worker.json").read_text(encoding="utf-8"))
        resultado.update(_conferir_com_oracle(destino))
        resultado.update(cenario=cenario, tamanho=tamanho, repeticao=repeticao,
                         seed=args.seed, contagem_operacoes=contagem, correto=True)
        resultados.append(resultado)
        _salvar_json(pasta / "resultados.json", resultados)
        print(f"  correto; {resultado['segundos']:.4f} s; "
              f"{resultado['operacoes_por_segundo']:.1f} op/s; "
              f"pico={resultado['pico_memoria_bytes'] / MIB:.2f} MiB", flush=True)
    _relatorio(pasta, ambiente, resultados)
    print(f"Concluido: {len(resultados)} medicoes corretas. Consulte {pasta / 'relatorio.md'}")


if __name__ == "__main__":
    main()
