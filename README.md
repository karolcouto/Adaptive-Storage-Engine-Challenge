# Entrega 1 do mecanismo de armazenamento de ED2

Este projeto implementa um mecanismo persistente de chave e valor em Python. O núcleo usa um histórico de operações em arquivo binário, sem banco de dados pronto e sem carregar todas as chaves na RAM. Inclui PUT, GET, DELETE, valores de tamanho variável, verificação com CRC32, recuperação de cauda incompleta e execução de workloads JSONL.

A interface segue a referência inicial do enunciado Adaptive Storage Engine Challenge. O JSON Schema definitivo, o ambiente oficial, os limites e a rubrica precisam ser conferidos quando publicados pela disciplina. Os testes e experimentos deste projeto são locais, independentes do ED2Bench oficial.

## Execução

Requer Python 3.10 ou superior. Todas as dependências fazem parte da biblioteca padrão. O código foi testado com Python 3.12.14 em Linux. O núcleo e os 26 testes também foram executados pela integrante no Windows. Seu relatório de experimentos identifica Windows 11, Python 3.14.4 e 6 CPUs lógicas. As medições Windows fornecidas e a referência Linux estão identificadas separadamente em RESULTADOS.md.

No Windows, dentro da pasta do projeto:

```powershell
py engine.py init --data-dir base_demo
py engine.py run --data-dir base_demo --input workload_exemplo.jsonl --output resultados.jsonl
py engine.py verify --data-dir base_demo
py engine.py describe
py -m unittest -v test_engine.py
```

`init` recusa substituir uma base existente. Para outro teste independente, escolha outro diretório.

No Linux, substitua `py` por `python3`. O launcher `engine`, mantido na mesma pasta de `engine.py`, também aceita essa interface:

```bash
chmod +x engine
./engine init --data-dir base_demo_linux
./engine run --data-dir base_demo_linux --input workload_exemplo.jsonl --output resultados_linux.jsonl
./engine verify --data-dir base_demo_linux
./engine describe
```

O prefixo `/engine` do enunciado depende do empacotamento oficial. Este projeto fornece um executável local e código Python, sem presumir que Docker já é obrigatório.

## Usar um arquivo diretamente

```powershell
py engine.py put dados_v2.bin 91 "Karoline"
py engine.py get dados_v2.bin 91
py engine.py delete dados_v2.bin 91
py engine.py verify dados_v2.bin
py engine.py recover dados_v2.bin
py engine.py run --file dados_v2.bin --input workload_exemplo.jsonl --output resultados.jsonl
```

O cabeçalho determina a versão, não o nome do arquivo. Em `--data-dir`, o arquivo interno se chama `dados.bin`, mas usa o formato v2. O antigo arquivo dos primeiros passos só precisa de migração se ainda usar v1:

```powershell
py engine.py migrate dados.bin dados_v2.bin
```

A migração conserva a origem e recusa substituir um destino existente. Uma base v2 não precisa ser migrada novamente.

## Protocolo JSONL

Um objeto JSON UTF-8 por linha. Operações são processadas na ordem e respostas copiam o `id` recebido. A unicidade dos IDs é uma precondição do workload, conforme o enunciado; o engine não mantém um conjunto de todos os IDs na RAM.

```json
{"id":1,"op":"put","key":91,"value":"Karoline"}
{"id":2,"op":"get","key":91}
{"id":3,"op":"delete","key":91}
{"id":4,"op":"get","key":91}
```

Respostas correspondentes:

```json
{"id":1,"status":"ok"}
{"id":2,"status":"ok","value":"Karoline"}
{"id":3,"status":"ok"}
{"id":4,"status":"not_found"}
```

A chave é um inteiro entre 0 e 18446744073709551615, sem conversão por ponto flutuante. PUT exige texto UTF-8 de tamanho variável; valor vazio é válido. Valores binários arbitrários não são expostos nesta interface inicial. O enunciado usa strings nos exemplos; o tipo definitivo deve ser confirmado no schema final.

DELETE ausente retorna `ok` e grava uma tombstone, decisão provisória a confirmar no protocolo formal. SCAN pertence à entrega 2 e ainda não é suportado.

O lote lê uma linha e escreve uma resposta por vez. Uma única instância do engine permanece aberta durante o lote. Respostas ficam em `--output`; diagnósticos de `run` vão para stderr. Base, entrada e saída devem ser arquivos distintos. A saída de uma execução anterior pode ser substituída.

Entrada inválida interrompe o lote com código diferente de zero e diagnóstico. As operações anteriores confirmadas e suas respostas são preservadas. Não é inventado um status de erro fora da referência inicial.

## Organização do arquivo

Cada mutação acrescenta um registro ao final. A última operação válida da chave determina seu estado: PUT define seu valor e DELETE a torna ausente. Versões antigas continuam no histórico.

| Elemento do formato v2 | Bytes | Função |
|---|---:|---|
| Identificação `ED2KV002`, uma vez por arquivo | 8 | Reconhecer o formato |
| Tipo, por registro | 1 | PUT = 1; DELETE = 2 |
| Chave | 8 | uint64 sem sinal |
| Tamanho do valor | 8 | Quantidade de bytes UTF-8 |
| CRC32 do cabeçalho | 4 | Proteger tipo, chave e tamanho |
| Valor | N | Conteúdo variável; DELETE tem N = 0 |
| CRC32 do cabeçalho e valor | 4 | Detectar alteração no registro |

Inteiros usam little-endian. Cada registro ocupa `25 + N` bytes; a base ocupa `8 + soma(25 + N)` bytes. O cabeçalho de registro usa `struct.Struct("<BQQ")` e os CRCs usam `struct.Struct("<I")`.

CRC32 fornece integridade básica, sem autenticação criptográfica. O CRC do cabeçalho é conferido antes de confiar no comprimento declarado. Isso ajuda a distinguir tamanho danificado de gravação final incompleta.

## Algoritmos e memória

| Operação | Estratégia e custo principal |
|---|---|
| Abertura | Valida todo o histórico; custo proporcional ao tamanho da base |
| PUT | Acrescenta um registro; custo proporcional ao valor, mais fsync |
| DELETE | Acrescenta registro fixo de 25 bytes, mais fsync |
| GET | Percorre cabeçalhos e lê o último valor; custo proporcional ao histórico, mais valor retornado |
| verify | Confere cabeçalhos, CRCs e UTF-8; custo proporcional ao tamanho da base |

A validação lê valores em blocos de até 64 KiB. GET não constrói um dicionário ou índice de todas as chaves. O consumo depende de buffers e do valor corrente, não de toda a base. Um valor individual e sua linha JSONL ainda precisam caber na memória disponível.

A classe `Engine` abre e recupera uma vez para várias operações. Os atalhos Python `put(caminho, ...)`, `get(caminho, ...)` e `delete(caminho, ...)` abrem uma instância por chamada. O benchmark usa `run` e reutiliza a instância durante cada lote.

A organização foi escolhida por simplificar valores variáveis, atualizações e recuperação. Seus custos são consultas sequenciais e crescimento do histórico. Não há compactação ou reaproveitamento de registros antigos nesta entrega.

## Persistência e recuperação

Cada mutação executa `flush()` e `os.fsync()` antes da resposta de sucesso. Uma operação interrompida antes de ser confirmada pode sobreviver integralmente ou ser descartada se estiver incompleta.

Na abertura, o engine valida a identificação e os registros. Se o último estiver incompleto, trunca somente a partir do fim do último registro válido e sincroniza. Checksum incorreto, tipo inválido ou UTF-8 inválido causam erro e preservação do arquivo. Valores danificados arbitrariamente não são reconstruídos.

`verify` apenas examina e falha diante de cauda incompleta. `recover` executa explicitamente o mesmo reparo de cauda usado na abertura. Após falha de escrita, a instância recusa novas operações; deve ser fechada e reaberta para recuperar.

Criação e migração montam uma base temporária antes da publicação. No Linux a publicação também sincroniza o diretório. Os testes cobrem interrupção abrupta de processo; não foi realizado corte de energia ou teste de falha física do dispositivo. Não há ACID completo.

Uma única instância deve acessar cada base por vez. Não há coordenação entre processos concorrentes, múltiplos escritores ou transações com várias operações.

## Testes

```powershell
py -m unittest -v test_engine.py
```

São 26 testes, incluindo atualizações, exclusões, reinserções, valores vazios e UTF-8, valores que cruzam blocos de validação, extremos uint64, reabertura, corrupção de cabeçalho e valor, fsync, migração, JSONL e processos separados.

A recuperação é testada cortando o último PUT e o último DELETE em cada byte possível. Outro teste encerra um processo filho durante escrita parcial. Os testes usam diretórios temporários próprios.

## Experimentos reproduzíveis

```powershell
py experimentos.py
```

Gera inserções, leituras e operações mistas em N = 200 e N = 800, com três repetições e seed 20261015. Repetições de um caso têm a mesma carga; cada medição usa processo e base novos. Valores variam aproximadamente entre 64 e 192 bytes. A pasta padrão `resultados_experimentos` não pode existir previamente.

```powershell
py experimentos.py --output-dir resultados_experimentos_2
py experimentos.py --sizes 500 2000 --repetitions 3 --seed 42 --output-dir outro_cenario
```

O runner gera JSONL e executa o engine em outro processo. Um oráculo de dicionário no coordenador confere todas as respostas, fora da memória atribuída ao engine. O tempo inclui abertura e validação inicial, JSONL, operações e respostas; exclui preparação inicial e conferência pelo oráculo.

A métrica de disco é o tamanho lógico da base. Cada pasta contém `ambiente.json`, `resultados.json`, `relatorio.md` e subpastas com cargas, bases, respostas e métricas. O relatório usa medianas; o JSON preserva cada repetição.

## Experimento de memória

```powershell
py experimentos.py --memory-test
```

Grava 14.000 valores de 4.096 bytes e consulta 20 chaves de amostra, produzindo base de aproximadamente 55 MiB. Usa a pasta separada `resultados_memoria`.

No Linux, o processo medido recebe limite de 48 MiB de espaço de endereçamento com RLIMIT_AS. No Windows, o script mede PeakWorkingSetSize por GetProcessMemoryInfo, mas não impõe esse limite. O relatório registra se houve limite e se a base excedeu o limite e o pico observado.

No ensaio Windows informado pela integrante, a base de 55,02 MiB foi processada com pico de 22,04 MiB e tempo de 10,593645 s. O ensaio Linux de referência operou com limite virtual imposto de 48 MiB. Os resultados completos e suas condições estão em RESULTADOS.md.

O oráculo pode usar mais RAM em outro processo. Picos incluem interpretador e preparação do processo medido; não incluem todo o cache global do SO. Execução sem limite aplicado não deve ser apresentada como prova sob limite imposto.

## Resultados e limites

Consulte [RESULTADOS.md](RESULTADOS.md). O pacote inclui ambiente e métricas brutas Linux em `resultados_referencia`, além dos resumos Windows de desempenho e memória fornecidos pela integrante. Os arquivos brutos do Windows permanecem na pasta de resultados gerada no computador da integrante. Arquivos grandes de trabalho podem ser reproduzidos com os parâmetros e a seed registrados.

Esses números não substituem medições do laboratório nem garantem pontuação no ED2Bench. Não houve limpeza de cache do SO e as cargas de desempenho são pequenas. Throughput maior em uma escala de inserção não comprova melhora assintótica: custos fixos, cache e variação influenciam medições curtas.

## Cobertura da entrega 1

| Requisito | Evidência |
|---|---|
| PUT, GET e DELETE | Implementação, testes e oráculo |
| Persistência após reinício | Arquivo binário, fsync e processos distintos |
| Valores variáveis | Tamanho em bytes, testes de comprimentos e UTF-8 |
| Integridade básica | CRCs, UTF-8 e comando verify |
| Recuperação básica | Reparo de cauda e testes de interrupção |
| Base maior que memória do engine | Linux: base maior que limite virtual de 48 MiB; Windows: base de 55,02 MiB e pico observado de 22,04 MiB, sem limite imposto |
| Interface de referência | init, run, verify, describe e JSONL |
| Documentação e experimentos | README, RESULTADOS, runner e métricas |

Antes da submissão, conferir schema final, DELETE ausente, tipo dos valores, limites, workloads públicos, artefato de execução, datas e rubrica. A execução no ED2Bench oficial depende da disponibilização das ferramentas. Docker não foi exigido nem validado nesta versão.

A entrega 2 deverá acrescentar SCAN ordenado e índice de memória secundária. Uma evolução possível é manter o log e adicionar índice em disco; a escolha deve ser fundamentada com novos experimentos.

## AI-Assisted Engineering

Implementação, testes e documentação foram desenvolvidos com assistência de IA durante o estudo. A integrante executou e conferiu os testes e o workload no Windows. Compreensão, revisão e defesa são responsabilidade do grupo. Os números Linux foram medidos no ambiente do assistente e estão identificados como tal.

## Referências

- Enunciado da disciplina: Adaptive Storage Engine Challenge, entrega 1.
- Slides fornecidos: manipulação de arquivos e busca sequencial.
- [Python resource e RLIMIT_AS](https://docs.python.org/pt-br/3/library/resource.html).
- [Microsoft PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/pt-br/windows/win32/api/psapi/ns-psapi-process_memory_counters).
