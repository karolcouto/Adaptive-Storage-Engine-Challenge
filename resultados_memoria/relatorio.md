# Resultados dos experimentos locais

Todas as respostas foram comparadas com um oráculo independente no processo coordenador.
Cada medição usa uma base nova e um processo separado. O tempo inclui abertura, recuperação,
JSONL, execução e escrita das respostas. A preparação e o oráculo ficam fora do tempo medido.

Ambiente: Windows-11-10.0.26200-SP0; Python 3.14.4; 6 CPUs lógicas disponíveis.
SHA256 de engine.py: `dcd3b5b5ae9ecd85b05e89c5d60a93e087b83732c3d854bdc987e4392731262f`.

| Cenário | N | Repetições | Tempo mediano s | Operações/s medianas | Pico memória máximo MiB | Base final MiB | Crescimento MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| memoria | 14000 | 1 | 15.305441 | 916.0 | 22.03 | 55.0213 | 55.0213 |

## Memória e validade das medições

O pico inclui o interpretador e a preparação do processo medido. O oráculo usa RAM em outro processo.
No Windows, a métrica é PeakWorkingSetSize; no Unix, ru_maxrss. As métricas não incluem o cache global do SO.
A base maior que o pico observado demonstra uso de memória menor que o tamanho da base;
somente uma execução com limite aplicado e base maior que esse limite demonstra o caso sob limite imposto.

Base final: 55.02 MiB.
Pico medido: 22.03 MiB.
Base maior que o pico medido: True.
Limite virtual aplicado: não aplicado neste sistema.
Base maior que o limite: None.

## Limitações

Os resultados são deste computador e desta execução. Não são notas nem resultados do ED2Bench oficial.
O limite Linux RLIMIT_AS limita espaço de endereçamento virtual, não somente RSS. No Windows este script mede memória, mas não impõe limite.
Não limpamos o cache do sistema operacional. As repetições de um caso usam a mesma seed e a mesma carga.
O tempo inclui a verificação inicial do arquivo; execuções curtas sofrem influência maior desse custo.
Não há comparação com outras arquiteturas; leituras sequenciais e versões antigas limitam o desempenho e o espaço.
Os JSONs e as cargas de cada execução ficam nas subpastas para reprodução e auditoria.
