# Resultados da entrega 1

O núcleo e os 26 testes passaram no Linux e no Windows da integrante. As dez respostas do workload de exemplo também foram conferidas no Windows. Este relatório reúne os resumos de desempenho e memória Windows fornecidos pela integrante e medições Linux de referência, identificadas por ambiente. Nenhuma destas execuções é o ED2Bench oficial.

## Resultados no Windows da integrante

Medições agregadas fornecidas pela integrante. O runner informou que todas as respostas coincidiram com o oráculo. Foram resumidas 18 medições, em seis casos com três repetições. Os arquivos brutos das repetições não foram enviados; por isso não se acrescentam mínimos, máximos de tempo ou intervalos estatísticos a estes dados.

Ambiente: Windows-11-10.0.26200-SP0; Python 3.14.4; 6 CPUs lógicas disponíveis.
SHA256 informado de engine.py: `dcd3b5b5ae9ecd85b05e89c5d60a93e087b83732c3d854bdc987e4392731262f`. Esse hash coincide com o código do pacote.

| Carga | N | Repetições | Tempo mediano s | Operações/s medianas | Pico memória máximo MiB | Base final MiB | Crescimento MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| insercoes | 200 | 3 | 0.083108 | 2406.5 | 22.04 | 0.0283 | 0.0283 |
| leituras | 200 | 3 | 0.082094 | 2436.2 | 21.98 | 0.0283 | 0.0000 |
| mista | 200 | 3 | 0.100420 | 1991.6 | 21.97 | 0.0383 | 0.0100 |
| insercoes | 800 | 3 | 0.330156 | 2423.1 | 22.02 | 0.1155 | 0.1155 |
| leituras | 800 | 3 | 1.225000 | 653.1 | 22.05 | 0.1155 | 0.0000 |
| mista | 800 | 3 | 1.037179 | 771.3 | 22.02 | 0.1592 | 0.0437 |

A taxa de inserções variou apenas 0.69%: de 2.406,5 para 2.423,1 operações/s. O tempo passou de 0,083108 s para 0,330156 s, aproximadamente quatro vezes maior para quatro vezes mais operações. Isso é coerente com escritas por acréscimo, com fsync a cada mutação, sem provar por si só uma complexidade assintótica.

A taxa de leituras caiu 73.2%, de 2.436,2 para 653,1 operações/s. O tempo total foi 14.92 vezes maior. Além de haver quatro vezes mais consultas, cada GET percorre um histórico maior. Esse comportamento é coerente com o custo sequencial e reforça a necessidade de um índice na próxima entrega.

Na carga mista, a taxa caiu 61.3%, de 1.991,6 para 771,3 operações/s. As consultas contribuem para a degradação e as mutações acrescentam registros ao histórico. A base cresceu 0,0100 MiB em N = 200 e 0,0437 MiB em N = 800; leituras isoladas tiveram crescimento zero.

Os picos ficaram próximos de 22 MiB nas duas escalas, sem crescimento proporcional a N. Isso é compatível com processamento incremental nessas cargas. Contudo, a maior base deste ensaio tem só 0,1592 MiB, menor que o pico do processo: esses seis casos não demonstram uma base maior que a memória. O teste separado de memória, apresentado a seguir, trata essa questão.

A semente e o timestamp não constam do trecho recebido. O script entregue usa seed padrão 20261015; o grupo deve conservar ambiente.json e resultados.json da execução para registrar os parâmetros efetivamente usados. O resumo recebido está em resultados_referencia/windows_desempenho/resumo_recebido.json.

As taxas Windows e Linux não devem ser atribuídas isoladamente ao sistema operacional: mudaram computador, Python, armazenamento e condições de cache. Os ambientes são apresentados separadamente.

### Memória no Windows

A integrante executou também o cenário separado de memória. O script informou sucesso e comparação das respostas com o oráculo. O resumo corresponde a uma única execução, com 14.000 registros; o script padrão inclui 20 consultas de amostra após as inserções.

| Métrica | Resultado Windows |
|---|---:|
| Registros inseridos | 14.000 |
| Base final | 55,0213 MiB |
| Pico de working set | 22,04 MiB |
| Tempo desta execução | 10,593645 s |
| Operações/s | 1.323,4 |
| Base maior que o pico observado | Sim |
| Limite de memória imposto | Não aplicado |
| Comparação com limite imposto | Não se aplica |

A base foi aproximadamente 2.50 vezes maior que o pico medido do processo. Isso reforça a evidência de que o engine processa o histórico sem mantê-lo inteiro na memória residente. O pico inclui o interpretador; o oráculo fica fora do processo medido. Esse resultado não significa que o computador tinha somente 22,04 MiB disponíveis.

O campo `Base maior que o limite: None` significa que não houve limite aplicado para comparar. Portanto, este ensaio Windows demonstra base maior que o pico observado, enquanto o ensaio Linux abaixo acrescenta evidência de execução sob limite virtual imposto de 48 MiB. Não se apresenta a execução Windows como se tivesse esse limite.

O resumo fornecido foi preservado em `resultados_referencia/windows_memoria/resumo_recebido.json`. Os arquivos originais `ambiente.json` e `resultados.json` permanecem na pasta `resultados_memoria` do computador da integrante. Só houve uma repetição, sem estimativa de variabilidade neste cenário.

## Referência Linux do ambiente de desenvolvimento

### Ambiente e método

Ambiente: Linux-6.18.44-x86_64-with-glibc2.39; Python 3.12.14; 9 CPUs lógicas disponíveis.
Início registrado em UTC: 2026-10-15T20:32:20.148420+00:00.
SHA256 de engine.py: `dcd3b5b5ae9ecd85b05e89c5d60a93e087b83732c3d854bdc987e4392731262f`.

- Seed 20261015; três repetições com a mesma carga por caso, em processos e bases novos.
- Escalas de 200 e 800 operações medidas. Leituras e carga mista têm N inserções de preparo, excluídas do tempo.
- Valores variam aproximadamente entre 64 e 192 bytes. Leituras usam distribuição uniforme com algumas chaves ausentes. A carga mista usa probabilidades de 35% PUT, 50% GET e 15% DELETE.
- Tempo inclui abertura/validação da base, JSONL, operações e respostas. Preparação e oráculo ficam fora do tempo.
- Disco é o tamanho lógico da base. O pico de memória inclui interpretador e preparo, sem o dicionário do oráculo nem o cache global do SO.

### Desempenho

| Carga | N | Repetições | Tempo mediano s | Faixa min–max s | Operações/s medianas | Base final KiB | Crescimento KiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| insercoes | 200 | 3 | 0.007066 | 0.005800–0.010027 | 28302.8 | 28.99 | 28.98 |
| leituras | 200 | 3 | 0.092156 | 0.086939–0.132904 | 2170.2 | 28.99 | 0.00 |
| mista | 200 | 3 | 0.052224 | 0.047057–0.054257 | 3829.7 | 39.20 | 10.21 |
| insercoes | 800 | 3 | 0.013949 | 0.013303–0.017630 | 57352.0 | 118.27 | 118.26 |
| leituras | 800 | 3 | 1.025406 | 0.979735–1.082790 | 780.2 | 118.27 | 0.00 |
| mista | 800 | 3 | 0.666014 | 0.598295–0.756502 | 1201.2 | 163.06 | 44.79 |

Leituras passaram de 2170.2 para 780.2 operações/s quando N aumentou de 200 para 800. O resultado é coerente com busca sequencial: cada consulta percorre os cabeçalhos históricos. Isso identifica o principal alvo de evolução para a entrega 2.

Inserções acrescentam ao final e tiveram tempos curtos e variáveis. Throughput maior em N = 800 não comprova melhora com a escala; custos fixos, cache e condições da execução influenciam esses números. Três repetições são uma caracterização inicial, sem pretensão de significância estatística.

A carga de leituras não aumentou o arquivo. A carga mista aumentou o histórico mesmo sobrescrevendo ou excluindo chaves. O compromisso da arquitetura é escrita simples com manutenção de versões antigas e tombstones.

### Base maior que o limite de memória

Ensaio separado com 14000 valores de 4.096 bytes e 20 consultas de amostra, totalizando 14020 operações medidas. Houve uma única execução neste cenário.

| Métrica | Resultado |
|---|---:|
| Base final | 57,694,008 bytes (55.02 MiB) |
| Limite virtual Linux RLIMIT_AS | 48 MiB |
| Pico residente medido | 14.00 MiB |
| Tempo | 1.663634 s |
| Operações/s | 8427.3 |
| Base maior que limite aplicado | Sim |
| Base maior que pico medido | Sim |

O engine operou com uma base maior que seu limite de espaço virtual. A integridade percorreu todos os registros; as consultas de amostra devolveram os valores esperados. RLIMIT_AS limita endereçamento virtual, não apenas RSS. Este ensaio não demonstra eficiência sob qualquer limite ou tamanho de valor.

No Windows, o runner registra PeakWorkingSetSize, mas não aplica RLIMIT_AS. Uma repetição no Windows só deve ser descrita como execução sob limite imposto se outro mecanismo efetivamente aplicar e registrar esse limite.

### Correção e recuperação

As 18 medições de desempenho e a medição de memória tiveram 29,020 respostas conferidas contra um oráculo independente, incluindo preparação. Todas coincidiram. O oráculo usa dicionário fora do processo medido e verifica cada resposta na ordem da carga.

Os 26 testes complementam os experimentos com reabertura, exclusão e reinserção, UTF-8, uint64, cauda incompleta, corrupção, interrupção real de processo durante PUT, falha de fsync, migração e erros de JSONL. Esses testes não equivalem a prova formal e não incluem corte físico de energia.

### Reprodução

```powershell
py -m unittest -v test_engine.py
py experimentos.py
py experimentos.py --memory-test
```

Os comandos criam pastas novas para seus próprios dados. Para outra rodada use `--output-dir outro_nome`. No Linux, use `python3` em lugar de `py`. Ambiente, seeds e métricas individuais ficam registrados em JSON. As medições de referência estão em `resultados_referencia/desempenho` e `resultados_referencia/memoria`.

### Limitações e próximos passos

- Ambiente virtualizado e armazenamento/cache não controlados; as taxas não devem ser extrapoladas para o laboratório.
- Cargas pequenas de desempenho e apenas uma repetição de memória. Ampliar escalas, seeds e repetições quando os limites oficiais forem conhecidos.
- Sem comparação com índices em disco; GET é sequencial e o histórico cresce sem compactação.
- Um valor individual precisa caber na memória, embora a base completa possa excedê-la.
- Uma instância por base, sem concorrência ou transações de várias operações.
- Recuperação automática limitada à cauda incompleta; corrupção completa é detectada e preservada para investigação.
- Schema final, semântica de DELETE ausente, rubrica, limites e ED2Bench oficial precisam ser conferidos antes da submissão.

### Referências das métricas

- [Python resource](https://docs.python.org/pt-br/3/library/resource.html).
- [Microsoft PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/pt-br/windows/win32/api/psapi/ns-psapi-process_memory_counters).
