# Dexter — agente local com LLM e MCP

Aplicação web de chat em português que usa um modelo local servido pelo Ollama. O agente consulta dados por ferramentas MCP; o servidor MCP acessa MongoDB (configuração padrão) ou, para consultas genéricas, Oracle.

O repositório também inclui um importador que carrega dados estruturados de Pokémon da PokeAPI para coleções MongoDB, além de ferramentas MCP especializadas para consultar a Pokédex.

## Índice

- [Componentes](#componentes)
- [Requisitos](#requisitos)
- [Instalação do ambiente no Windows](#instalação-do-ambiente-no-windows)
- [Configuração e carga dos dados Pokémon](#configuração-e-carga-dos-dados-pokémon)
- [Executar a aplicação](#executar-a-aplicação)
- [Consultar e testar](#consultar-e-testar)
- [Configurações](#configurações)
- [Solução de problemas](#solução-de-problemas)
- [Estrutura do projeto](#estrutura-do-projeto)

## Componentes

| Componente | Função | Obrigatório |
|---|---|---|
| .NET SDK 10 | Compilar e executar a aplicação | Sim |
| MongoDB Community Server | Armazenar os dados consultados pelo MCP | Sim para a configuração padrão e para a Pokédex |
| MongoDB Shell (`mongosh`) | Importar e verificar os dados | Sim para importar os dados Pokémon |
| Python 3 | Executar o importador de dados Pokémon | Sim para importar os dados Pokémon |
| Ollama | Servir o modelo de linguagem local | Sim para conversar com o agente |
| Modelo `llama3.2` no Ollama | Gerar as respostas do chat | Sim, salvo se outro modelo for configurado |
| Studio 3T ou MongoDB Compass | Inspecionar visualmente o MongoDB | Não; ferramenta de administração opcional |

O chat e o modelo executam localmente depois que o Ollama e o modelo já foram instalados. A instalação inicial, a restauração de pacotes .NET e a importação da PokeAPI precisam de acesso à internet.

## Requisitos

- Windows 10/11 64-bit.
- Acesso à internet durante a instalação e a importação inicial.
- Espaço livre para o modelo Ollama e para as coleções Pokémon. Learnsets e encontros são as coleções maiores.
- As portas locais `27017` (MongoDB), `11434` (Ollama), `5071` (MCP) e `5226` (Web) disponíveis.

## Instalação do ambiente no Windows

Instale os componentes abaixo. Use os instaladores oficiais e mantenha os padrões, a menos que tenha uma configuração própria.

### 1. .NET SDK 10

Baixe e instale o **SDK** do .NET 10:

<https://dotnet.microsoft.com/download/dotnet/10.0>

Abra um novo PowerShell e confirme:

```powershell
dotnet --version
```

O projeto tem como alvo `net10.0`; instale o SDK, não apenas o runtime.

### 2. MongoDB Community Server

Baixe o MongoDB Community Server para Windows:

<https://www.mongodb.com/try/download/community>

No instalador, pode habilitar a execução do MongoDB como serviço do Windows. A configuração padrão do projeto espera o servidor em `localhost:27017`.

Verifique se o serviço está ativo:

```powershell
Get-Service MongoDB
```

Se estiver parado, abra o PowerShell como administrador e inicie-o:

```powershell
Start-Service MongoDB
```

### 3. MongoDB Shell (`mongosh`)

Instale o MongoDB Shell:

<https://www.mongodb.com/try/download/shell>

Confirme que `mongosh` está no `PATH`:

```powershell
mongosh --version
```

Se o comando não for encontrado, adicione a pasta que contém `mongosh.exe` ao `PATH` ou informe o caminho completo ao executar o importador, conforme a seção [Configuração e carga dos dados Pokémon](#configuração-e-carga-dos-dados-pokémon).

### 4. Python

Instale Python 3 para Windows:

<https://www.python.org/downloads/windows/>

Durante a instalação, habilite **Add Python to PATH**. Confirme em um novo PowerShell:

```powershell
python --version
```

O importador usa apenas a biblioteca padrão do Python; não é necessário instalar pacotes com `pip`.

### 5. Ollama e modelo

Instale o Ollama para Windows:

<https://ollama.com/download/windows>

Depois, em um PowerShell, baixe o modelo configurado por padrão:

```powershell
ollama pull llama3.2
ollama list
```

O Ollama precisa estar ativo enquanto o chat estiver sendo usado. No Windows, normalmente ele permanece em execução em segundo plano após a instalação. Para conferir a API local:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

O download do modelo exige internet. Depois de baixado, o Ollama executa a inferência localmente; o chat não envia as mensagens para uma API de LLM na nuvem.

### 6. Studio 3T (opcional)

O Studio 3T é uma interface gráfica opcional para explorar e administrar o MongoDB:

<https://studio3t.com/download/>

Também é possível usar o MongoDB Compass:

<https://www.mongodb.com/products/tools/compass>

Para conectar, use:

```text
mongodb://localhost:27017
```

Selecione o banco `dexter`. A importação cria esse banco se ele ainda não existir.

## Configuração e carga dos dados Pokémon

O banco `dexter` contém uma cópia das 35 coleções e índices encontrados no antigo banco local `chat_mvp`. O banco antigo foi mantido como cópia de segurança. O servidor Dexter e o importador agora usam `dexter`.

O script `Dexter.Mcp/tools/import_pokemon_data.py` baixa os arquivos CSV estruturados da PokeAPI, prepara coleções e índices e grava os dados no MongoDB. Ele também baixa os sprites básicos da Pokédex e os armazena como dados binários na coleção `pokemon_images`. Ele consulta a revisão atual de `master` da PokeAPI e registra o commit utilizado em `pokemon_dataset_metadata`.

O importador requer conexão com a internet para acessar a API, os arquivos CSV e os sprites do GitHub. Ele usa `curl.exe` (disponível por padrão em versões atuais do Windows), Python e `mongosh`.

### Executar a importação

Na raiz do projeto:

```powershell
python .\Dexter.Mcp\tools\import_pokemon_data.py
```

Por padrão, o destino é `mongodb://localhost:27017/dexter`. O processo imprime o progresso dos sprites e a contagem importada de cada coleção; aguarde a conclusão antes de iniciar o Dexter.

Se a Pokédex já está carregada no Mongo, baixe e importe somente os sprites, sem substituir as outras coleções:

```powershell
python .\Dexter.Mcp\tools\import_pokemon_data.py --images-only
```

Se `mongosh` não estiver no `PATH`, passe seu caminho completo:

```powershell
python .\Dexter.Mcp\tools\import_pokemon_data.py `
  --mongosh "C:\Program Files\MongoDB\mongosh\current\bin\mongosh.exe"
```

Se estiver usando outra instância ou banco:

```powershell
python .\Dexter.Mcp\tools\import_pokemon_data.py `
  --mongo-uri "mongodb://localhost:27017/dexter" `
  --mongosh "C:\Program Files\MongoDB\mongosh\current\bin\mongosh.exe"
```

O script recebe uma URI MongoDB que inclui o nome do banco. Ajuste-a também na configuração do MCP para que a aplicação consulte o mesmo destino.

### Dados importados

A carga contém espécies, Pokémon e formas, atributos, tipos e efetividades, habilidades, itens, naturezas, movimentos, relações de aprendizado por Pokémon e versão, evoluções, encontros, locais, versões e tabelas de apoio. Também cria índices para as consultas mais usadas.

Ao consultar um Pokémon pelo chat, o sprite básico armazenado em `pokemon_images` aparece na tela verde do Dexter.

Na última carga validada deste projeto, os dados incluíram 1.025 espécies, 1.351 registros Pokémon, 1.579 formas, 665.810 relações de aprendizado e 117.137 encontros. As contagens podem mudar quando a PokeAPI for atualizada.

São criadas 36 coleções relacionadas à importação, incluindo `pokemon_images`. O importador monta coleções temporárias, verifica as contagens e então substitui as coleções de destino com os mesmos nomes. Ele não apaga o banco inteiro; coleções não relacionadas à carga, como `produtos`, são preservadas.

Os dados são estruturados e não incluem descrições narrativas ou textos de jogos. Os nomes são majoritariamente identificadores em inglês, conforme os CSVs da fonte.

### Verificar o banco

Abra:

```powershell
mongosh "mongodb://localhost:27017/dexter"
```

No prompt do `mongosh`:

```javascript
db.pokedex.countDocuments()
db.pokemon.countDocuments()
db.pokemon_learnsets.countDocuments()
db.encounters.countDocuments()
db.pokemon_dataset_metadata.findOne()
```

Para sair do `mongosh`, execute `exit`.

## Executar a aplicação

Restaure e compile as dependências a partir da raiz:

```powershell
dotnet restore .\Dexter.slnx
dotnet build .\Dexter.slnx
```

Inicie cada serviço em um terminal PowerShell separado. Mantenha os dois terminais abertos enquanto usar o chat.

**Terminal 1 — servidor MCP:**

```powershell
dotnet run --project .\Dexter.Mcp\Dexter.Mcp.csproj
```

O MCP ficará disponível em `http://localhost:5071/mcp`.

**Terminal 2 — aplicação web:**

```powershell
dotnet run --project .\Dexter.Web\Dexter.Web.csproj
```

Abra no navegador:

<http://localhost:5226>

Ordem recomendada: iniciar MongoDB, confirmar que o Ollama está ativo e que o modelo foi baixado, iniciar o MCP e, por fim, iniciar a aplicação Web.

### Monitor local

Para iniciar, reiniciar ou parar os processos Web e MCP pelo navegador, abra um PowerShell na raiz e execute:

```powershell
.\Monitor.ps1
```

O script abre `monitor.html` em `http://127.0.0.1:4862`. Mantenha esse PowerShell aberto enquanto usar o painel; Ctrl+C encerra somente o monitor. Os comandos controlam apenas os projetos Dexter e os logs de inicialização são gravados em `%TEMP%\DexterMonitor`. O monitor fica disponível apenas neste computador.

## Consultar e testar

Experimente perguntas como:

- `Quais são os tipos do Pikachu?`
- `Pikachu pode aprender Thunderbolt?`
- `Quais movimentos o Pikachu pode aprender?`
- `Qual é a cadeia evolutiva do Bulbasaur?`
- `Em quais jogos e locais posso encontrar Pikachu?`
- `Quais Pokémon são do tipo fire?`

O MCP disponibiliza as ferramentas `get_pokemon`, `get_pokemon_learnset`, `can_pokemon_learn_move`, `get_move`, `get_ability`, `get_type_info`, `get_evolution_chain`, `search_pokemon_by_type` e `get_pokemon_encounters`, além de `list_records` e `search_records` para consultas genéricas.

## Configurações

Os valores padrão ficam em:

- `Dexter.Web/appsettings.json`: URL e modelo do Ollama e URL do MCP.
- `Dexter.Mcp/appsettings.json`: provider e conexão do banco de dados.
- `Dexter.Web/Properties/launchSettings.json`: porta HTTP da aplicação web (`5226`).
- `Dexter.Mcp/Properties/launchSettings.json`: porta HTTP do MCP (`5071`).

Configuração padrão do Ollama e do MCP:

```json
{
  "Ollama": {
    "BaseUrl": "http://localhost:11434",
    "Model": "llama3.2"
  },
  "Mcp": {
    "BaseUrl": "http://localhost:5071/mcp"
  }
}
```

Configuração padrão do banco no MCP:

```json
{
  "Database": {
    "Provider": "mongo",
    "MongoConnection": "mongodb://localhost:27017",
    "MongoDatabase": "dexter"
  }
}
```

Para evitar alterações nos arquivos versionados, as configurações .NET também podem ser fornecidas por variáveis de ambiente. Por exemplo, no PowerShell:

```powershell
$env:Ollama__Model = "llama3.2"
$env:Ollama__BaseUrl = "http://localhost:11434"
$env:Mcp__BaseUrl = "http://localhost:5071/mcp"
$env:Database__MongoConnection = "mongodb://localhost:27017"
$env:Database__MongoDatabase = "dexter"
```

Essas variáveis valem para os processos iniciados naquela sessão do PowerShell. Defina-as também no terminal em que executar o MCP. Para usar outro modelo, baixe-o com `ollama pull nome-do-modelo` e configure `Ollama__Model` com o nome retornado por `ollama list`.

O projeto mantém suporte genérico a Oracle para operações de listagem e pesquisa, mas as ferramentas específicas da Pokédex exigem o provider MongoDB. Oracle não é necessário para executar a configuração padrão.

## Solução de problemas

### `dotnet` não é reconhecido ou o build não encontra o framework

Instale o **.NET SDK 10**, abra um novo terminal e confira:

```powershell
dotnet --list-sdks
```

### Não conecta ao MongoDB

Confirme que o serviço está em execução e que a porta padrão responde:

```powershell
Get-Service MongoDB
Test-NetConnection localhost -Port 27017
```

Se o MongoDB foi instalado sem serviço do Windows, inicie-o conforme a opção escolhida no instalador.

### `mongosh` não é reconhecido

Confira com `mongosh --version`. Se não estiver no `PATH`, use `--mongosh` seguido do caminho completo para `mongosh.exe` ao executar o importador.

### O importador falha ao baixar os dados

O importador precisa de acesso HTTPS ao GitHub e usa `curl.exe` com IPv4. Verifique a conexão, a disponibilidade do GitHub e a presença de `curl.exe`:

```powershell
curl.exe --version
```

Execute novamente o comando de importação após resolver o problema. A carga pode substituir as coleções Pokémon existentes.

### O chat não consegue chamar o MCP

Inicie o servidor MCP e confira a saída do terminal. Verifique se a configuração `Mcp:BaseUrl` aponta para `http://localhost:5071/mcp` e se a porta `5071` não está sendo usada por outro processo.

### O modelo não responde

Confirme que o Ollama está ativo, que o modelo foi baixado e que o nome configurado corresponde ao nome listado:

```powershell
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

Se alterar a URL ou o modelo, reinicie a aplicação Web para carregar a nova configuração.

### Porta `5226` ou `5071` já está em uso

Feche a aplicação que está ocupando a porta ou altere `applicationUrl` no `launchSettings.json` correspondente. Se alterar a porta do MCP, atualize também `Mcp:BaseUrl` em `Dexter.Web/appsettings.json` ou pela variável de ambiente `Mcp__BaseUrl`.

## Estrutura do projeto

```text
.
├── Dexter.slnx
├── Dexter.Shared/                  Modelos compartilhados
├── Dexter.Web/                     Interface web e agente Ollama
└── Dexter.Mcp/                     Servidor MCP e acesso a dados
    └── tools/
        └── import_pokemon_data.py  Dados e sprites da PokeAPI para MongoDB
```
