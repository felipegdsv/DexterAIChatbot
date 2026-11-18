using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Dexter.Shared;
using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

namespace Dexter.Web.Services;

public sealed class ChatAgentService(IConfiguration configuration, ILogger<ChatAgentService> logger)
{
    private readonly HttpClient _ollama = new();

    public async Task<ChatResponse> SendAsync(string message, CancellationToken cancellationToken)
    {
        var ollamaBaseUrl = configuration["Ollama:BaseUrl"] ?? "http://localhost:11434";
        var model = configuration["Ollama:Model"] ?? "llama3.2";
        var mcpUrl = configuration["Mcp:BaseUrl"] ?? "http://localhost:5071/mcp";
        PokemonDisplay? pokemonDisplay = null;

        await using var mcpTransport = new HttpClientTransport(new HttpClientTransportOptions
        {
            Endpoint = new Uri(mcpUrl),
            TransportMode = HttpTransportMode.StreamableHttp
        });
        await using var mcpClient = await McpClient.CreateAsync(mcpTransport, cancellationToken: cancellationToken);

        var mcpTools = await mcpClient.ListToolsAsync(cancellationToken: cancellationToken);
        var ollamaTools = mcpTools.Select(tool => new
        {
            type = "function",
            function = new
            {
                name = tool.Name,
                description = tool.Description,
                parameters = tool.JsonSchema
            }
        }).ToArray();

        var messages = new JsonArray
        {
            new JsonObject
            {
                ["role"] = "system",
                ["content"] = "Você é um assistente. Responda em português. Use as ferramentas MCP para fatos específicos e não invente valores nem estatísticas a partir dos resultados. Para Pokémon, use `get_pokemon`; para verificar se aprende um movimento, `can_pokemon_learn_move`; para listar movimentos aprendíveis, `get_pokemon_learnset`; para atributos de um movimento, `get_move`; para habilidades, `get_ability`; para efetividade de tipos, `get_type_info` ou `search_pokemon_by_type`; para evoluções, `get_evolution_chain`; e para locais/encontros, `get_pokemon_encounters`. Use `search_records` com o nome exato da coleção para outros dados estruturados. Resuma apenas informações presentes no resultado da ferramenta."
            },
            new JsonObject
            {
                ["role"] = "user",
                ["content"] = message
            }
        };

        for (var turn = 0; turn < 5; turn++)
        {
            var request = new
            {
                model,
                messages,
                tools = ollamaTools,
                stream = false
            };

            using var response = await _ollama.PostAsync(
                $"{ollamaBaseUrl.TrimEnd('/')}/api/chat",
                new StringContent(JsonSerializer.Serialize(request), Encoding.UTF8, "application/json"),
                cancellationToken);

            var json = await response.Content.ReadAsStringAsync(cancellationToken);
            if (!response.IsSuccessStatusCode)
                throw new InvalidOperationException($"Ollama respondeu {(int)response.StatusCode}: {json}");

            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            var assistant = root.GetProperty("message");
            var content = assistant.TryGetProperty("content", out var contentElement)
                ? contentElement.GetString() ?? string.Empty
                : string.Empty;

            var toolCalls = assistant.TryGetProperty("tool_calls", out var callsElement)
                ? callsElement.EnumerateArray().ToArray()
                : [];

            messages.Add(JsonNode.Parse(assistant.GetRawText())!);

            if (toolCalls.Length == 0)
            {
                return new ChatResponse
                {
                    Response = content,
                    PokemonImageUrl = pokemonDisplay?.ImageUrl,
                    PokemonName = pokemonDisplay?.Name,
                    PokemonNumber = pokemonDisplay?.Number
                };
            }

            foreach (var call in toolCalls)
            {
                var function = call.GetProperty("function");
                var name = function.GetProperty("name").GetString()!;
                var arguments = function.TryGetProperty("arguments", out var argumentsElement)
                    ? JsonSerializer.Deserialize<Dictionary<string, object?>>(
                        argumentsElement.GetRawText(),
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? []
                    : [];

                try
                {
                    var result = await mcpClient.CallToolAsync(name, arguments, cancellationToken: cancellationToken);
                    var text = result.Content
                        .OfType<TextContentBlock>()
                        .Select(block => block.Text)
                        .FirstOrDefault() ?? "Ferramenta concluída sem conteúdo textual.";
                    if (name == "get_pokemon")
                    {
                        var display = GetPokemonDisplay(text, mcpUrl);
                        if (display is not null)
                            pokemonDisplay = display;
                    }

                    messages.Add(new JsonObject
                    {
                        ["role"] = "tool",
                        ["content"] = text,
                        ["tool_name"] = name
                    });
                }
                catch (Exception exception)
                {
                    logger.LogError(exception, "Falha ao executar ferramenta MCP {ToolName}", name);
                    messages.Add(new JsonObject
                    {
                        ["role"] = "tool",
                        ["content"] = $"Erro ao executar a ferramenta: {exception.Message}",
                        ["tool_name"] = name
                    });
                }
            }
        }

        return new ChatResponse
        {
            Response = "Não foi possível concluir a execução das ferramentas após o limite de tentativas.",
            PokemonImageUrl = pokemonDisplay?.ImageUrl,
            PokemonName = pokemonDisplay?.Name,
            PokemonNumber = pokemonDisplay?.Number
        };
    }

    private static PokemonDisplay? GetPokemonDisplay(string result, string mcpUrl)
    {
        using var document = JsonDocument.Parse(result);
        var pokemon = document.RootElement;
        if (pokemon.ValueKind != JsonValueKind.Object
            || !pokemon.TryGetProperty("pokedexNumber", out var number)
            || !number.TryGetInt32(out var pokedexNumber)
            || !pokemon.TryGetProperty("name", out var name)
            || name.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(name.GetString()))
            return null;

        var imageUri = new UriBuilder(mcpUrl)
        {
            Path = $"/pokemon-image/{pokedexNumber}",
            Query = string.Empty,
            Fragment = string.Empty
        };
        return new PokemonDisplay(imageUri.Uri.ToString(), name.GetString()!, pokedexNumber);
    }

    private sealed record PokemonDisplay(string ImageUrl, string Name, int Number);
}
