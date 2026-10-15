# Resultados dos experimentos locais

Todas as respostas foram comparadas com um oráculo independente no processo coordenador.
Cada medição usa uma base nova e um processo separado. O tempo inclui abertura, recuperação,
JSONL, execução e escrita das respostas. A preparação e o oráculo ficam fora do tempo medido.

Ambiente: Windows-11-10.0.26200-SP0; Python 3.14.4; 6 CPUs lógicas disponíveis.
SHA256 de engine.py: `dcd3b5b5ae9ecd85b05e89c5d60a93e087b83732c3d854bdc987e4392731262f`.

| Cenário | N | Repetições | Tempo mediano s | Operações/s medianas | Pico memória máximo MiB | Base final MiB | Crescimento MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| insercoes | 200 | 3 | 0.083108 | 2406.5 | 22.04 | 0.0283 | 0.0283 |
| leituras | 200 | 3 | 0.082094 | 2436.2 | 21.98 | 0.0283 | 0.0000 |
| mista | 200 | 3 | 0.100420 | 1991.6 | 21.97 | 0.0383 | 0.0100 |
| insercoes | 800 | 3 | 0.330156 | 2423.1 | 22.02 | 0.1155 | 0.1155 |
| leituras | 800 | 3 | 1.225000 | 653.1 | 22.05 | 0.1155 | 0.0000 |
| mista | 800 | 3 | 1.037179 | 771.3 | 22.02 | 0.1592 | 0.0437 |

## Memória e validade das medições

O pico inclui o interpretador e a preparação do processo medido. O oráculo usa RAM em outro processo.
No Windows, a métrica é PeakWorkingSetSize; no Unix, ru_maxrss. As métricas não incluem o cache global do SO.
A base maior que o pico observado demonstra uso de memória menor que o tamanho da base;
somente uma execução com limite aplicado e base maior que esse limite demonstra o caso sob limite imposto.

## Limitações

Os resultados são deste computador e desta execução. Não são notas nem resultados do ED2Bench oficial.
O limite Linux RLIMIT_AS limita espaço de endereçamento virtual, não somente RSS. No Windows este script mede memória, mas não impõe limite.
Não limpamos o cache do sistema operacional. As repetições de um caso usam a mesma seed e a mesma carga.
O tempo inclui a verificação inicial do arquivo; execuções curtas sofrem influência maior desse custo.
Não há comparação com outras arquiteturas; leituras sequenciais e versões antigas limitam o desempenho e o espaço.
Os JSONs e as cargas de cada execução ficam nas subpastas para reprodução e auditoria.
