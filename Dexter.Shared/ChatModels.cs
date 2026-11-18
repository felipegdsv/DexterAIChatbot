namespace Dexter.Shared;

public sealed class ChatRequest
{
    public string Message { get; set; } = string.Empty;
}

public sealed class ChatResponse
{
    public string Response { get; set; } = string.Empty;
    public string? PokemonImageUrl { get; set; }
    public string? PokemonName { get; set; }
    public int? PokemonNumber { get; set; }
}

public sealed class ChatMessage
{
    public string Role { get; set; } = "user";
    public string Content { get; set; } = string.Empty;
}
