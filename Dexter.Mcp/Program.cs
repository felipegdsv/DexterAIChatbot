using System.ComponentModel;
using ModelContextProtocol.Server;
using MongoDB.Bson;
using MongoDB.Driver;
using Oracle.ManagedDataAccess.Client;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddSingleton<DatabaseService>();
builder.Services
    .AddMcpServer(options => options.ServerInfo = new()
    {
        Name = "dexter-database-mcp",
        Version = "1.0.0"
    })
    .WithHttpTransport()
    .WithTools<DatabaseTools>();

builder.Logging.AddConsole(options =>
    options.LogToStandardErrorThreshold = LogLevel.Trace);

var app = builder.Build();
app.MapMcp("/mcp");
app.MapGet("/pokemon-image/{id:int}", async (
    int id,
    DatabaseService database,
    CancellationToken cancellationToken) =>
{
    var image = await database.FindPokemonImageAsync(id, cancellationToken);
    return image is null
        ? Results.NotFound()
        : Results.File(image.Value.Data, image.Value.ContentType);
});
app.Run();

[McpServerToolType]
public sealed class DatabaseTools(DatabaseService database)
{
    [McpServerTool(Name = "list_records")]
    [Description("Lista registros de uma coleção ou tabela. Use limit para limitar o resultado.")]
    public async Task<string> ListRecordsAsync(
        [Description("Nome da coleção MongoDB ou tabela Oracle")]
        string collection,
        [Description("Quantidade máxima de registros")]
        int? limit = null,
        CancellationToken cancellationToken = default)
        => await database.ListAsync(collection, limit, cancellationToken);

    [McpServerTool(Name = "search_records")]
    [Description("Pesquisa registros por texto em uma coleção ou tabela.")]
    public async Task<string> SearchRecordsAsync(
        [Description("Nome da coleção MongoDB ou tabela Oracle")]
        string collection,
        [Description("Texto a pesquisar")]
        string text,
        [Description("Quantidade máxima de registros")]
        int? limit = null,
        CancellationToken cancellationToken = default)
        => await database.SearchAsync(collection, text, limit, cancellationToken);

    [McpServerTool(Name = "get_pokemon")]
    [Description("Busca um Pokémon na Pokédex pelo número nacional ou nome exato.")]
    public async Task<string> GetPokemonAsync(
        [Description("Número nacional (ex.: 25 ou #25) ou nome do Pokémon (ex.: Pikachu)")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindPokemonAsync(query, cancellationToken);

    [McpServerTool(Name = "get_pokemon_learnset")]
    [Description("Lista movimentos que um Pokémon pode aprender nas versões incluídas na base.")]
    public async Task<string> GetPokemonLearnsetAsync(
        [Description("Número nacional ou nome do Pokémon")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindPokemonLearnsetAsync(query, cancellationToken);

    [McpServerTool(Name = "can_pokemon_learn_move")]
    [Description("Verifica se um Pokémon pode aprender um movimento e em quais grupos de jogos.")]
    public async Task<string> CanPokemonLearnMoveAsync(
        [Description("Número nacional ou nome do Pokémon")]
        string pokemon,
        [Description("Nome ou ID do movimento")]
        string move,
        CancellationToken cancellationToken = default)
        => await database.CanPokemonLearnMoveAsync(pokemon, move, cancellationToken);

    [McpServerTool(Name = "get_move")]
    [Description("Consulta atributos de um movimento Pokémon pelo nome ou ID.")]
    public async Task<string> GetMoveAsync(
        [Description("Nome ou ID do movimento")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindByNameOrIdAsync("moves", query, cancellationToken);

    [McpServerTool(Name = "get_ability")]
    [Description("Consulta uma habilidade Pokémon pelo nome ou ID.")]
    public async Task<string> GetAbilityAsync(
        [Description("Nome ou ID da habilidade")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindByNameOrIdAsync("abilities", query, cancellationToken);

    [McpServerTool(Name = "get_type_info")]
    [Description("Consulta efetividade, resistências e imunidades de um tipo.")]
    public async Task<string> GetTypeInfoAsync(
        [Description("Nome ou ID do tipo")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindByNameOrIdAsync("types", query, cancellationToken);

    [McpServerTool(Name = "get_evolution_chain")]
    [Description("Consulta a cadeia evolutiva completa de um Pokémon pelo nome ou número.")]
    public async Task<string> GetEvolutionChainAsync(
        [Description("Número nacional ou nome do Pokémon")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindEvolutionChainAsync(query, cancellationToken);

    [McpServerTool(Name = "search_pokemon_by_type")]
    [Description("Lista Pokémon de um tipo pelo nome do tipo, como fire ou water.")]
    public async Task<string> SearchPokemonByTypeAsync(
        [Description("Nome do tipo")]
        string type,
        CancellationToken cancellationToken = default)
        => await database.FindPokemonByTypeAsync(type, cancellationToken);

    [McpServerTool(Name = "get_pokemon_encounters")]
    [Description("Consulta jogos e locais em que um Pokémon pode ser encontrado.")]
    public async Task<string> GetPokemonEncountersAsync(
        [Description("Número nacional ou nome do Pokémon")]
        string query,
        CancellationToken cancellationToken = default)
        => await database.FindPokemonEncountersAsync(query, cancellationToken);
}

public sealed class DatabaseService(IConfiguration configuration)
{
    private string Provider => configuration["Database:Provider"]?.Trim().ToLowerInvariant() ?? "mongo";
    private readonly MongoClient _mongoClient = new(
        configuration["Database:MongoConnection"] ?? "mongodb://localhost:27017");
    private IMongoDatabase MongoDatabase =>
        _mongoClient.GetDatabase(configuration["Database:MongoDatabase"] ?? "dexter");

    public async Task<string> ListAsync(string collection, int? limit, CancellationToken cancellationToken)
    {
        var safeLimit = Math.Clamp(limit ?? 20, 1, 100);

        if (Provider == "oracle")
        {
            await using var connection = new OracleConnection(configuration["Database:OracleConnection"]);
            await connection.OpenAsync(cancellationToken);
            await using var command = connection.CreateCommand();
            command.BindByName = true;
            command.CommandText = $"SELECT * FROM \"{SafeIdentifier(collection)}\" FETCH FIRST :limit ROWS ONLY";
            command.Parameters.Add("limit", safeLimit);
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            return ReadRows(reader);
        }

        var collectionName = MongoDatabase.GetCollection<BsonDocument>(SafeMongoCollection(collection));
        var documents = await collectionName.Find(FilterDefinition<BsonDocument>.Empty)
            .Limit(safeLimit)
            .ToListAsync(cancellationToken);
        return documents.Count == 0 ? "[]" : documents.ToJson();
    }

    public async Task<string> FindPokemonAsync(string query, CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A busca da Pokédex requer o provider MongoDB.");

        var pokemon = await FindPokemonRecordAsync(query, cancellationToken);
        return pokemon?.ToJson() ?? "[]";
    }

    public async Task<(byte[] Data, string ContentType)?> FindPokemonImageAsync(
        int pokedexNumber,
        CancellationToken cancellationToken)
    {
        if (Provider == "oracle" || pokedexNumber < 1)
            return null;

        var image = await MongoDatabase.GetCollection<BsonDocument>("pokemon_images")
            .Find(Builders<BsonDocument>.Filter.Eq("_id", pokedexNumber))
            .FirstOrDefaultAsync(cancellationToken);
        if (image is null
            || !image.TryGetValue("imageData", out var imageData)
            || !imageData.IsBsonBinaryData)
            return null;

        return (
            imageData.AsBsonBinaryData.Bytes,
            image.GetValue("contentType", "image/png").AsString);
    }

    public async Task<string> FindPokemonLearnsetAsync(string query, CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A consulta de movimentos requer o provider MongoDB.");

        var pokemon = await FindPokemonRecordAsync(query, cancellationToken);
        if (pokemon is null)
            return "[]";

        var pokemonId = pokemon.TryGetValue("basePokemonId", out var basePokemonId)
            ? basePokemonId.AsInt32
            : pokemon["_id"].AsInt32;
        var learnset = await MongoDatabase.GetCollection<BsonDocument>("pokemon_learnsets")
            .Find(Builders<BsonDocument>.Filter.Eq("_id", pokemonId))
            .FirstOrDefaultAsync(cancellationToken);
        if (learnset is null)
            return "[]";

        var moveIds = learnset["moves"].AsBsonArray
            .Select(move => move["moveId"].AsInt32)
            .Distinct()
            .ToArray();
        var moves = await MongoDatabase.GetCollection<BsonDocument>("moves")
            .Find(Builders<BsonDocument>.Filter.In("_id", moveIds))
            .Project(Builders<BsonDocument>.Projection.Include("name"))
            .Sort(Builders<BsonDocument>.Sort.Ascending("name"))
            .ToListAsync(cancellationToken);

        return new BsonDocument
        {
            ["pokemon"] = pokemon["name"],
            ["uniqueMoveCount"] = moves.Count,
            ["moves"] = new BsonArray(moves.Select(move => move["name"]))
        }.ToJson();
    }

    public async Task<string> CanPokemonLearnMoveAsync(
        string pokemonQuery,
        string moveQuery,
        CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A consulta de movimentos requer o provider MongoDB.");

        var pokemon = await FindPokemonRecordAsync(pokemonQuery, cancellationToken);
        if (pokemon is null)
            return "[]";

        var pokemonId = pokemon.TryGetValue("basePokemonId", out var basePokemonId)
            ? basePokemonId.AsInt32
            : pokemon["_id"].AsInt32;
        var move = await FindByNameOrIdDocumentAsync("moves", moveQuery, cancellationToken);
        if (move is null)
            return "[]";

        var learnset = await MongoDatabase.GetCollection<BsonDocument>("pokemon_learnsets")
            .Find(Builders<BsonDocument>.Filter.Eq("_id", pokemonId))
            .FirstOrDefaultAsync(cancellationToken);
        if (learnset is null)
            return "[]";

        var matches = learnset["moves"].AsBsonArray
            .Where(entry => entry["moveId"].AsInt32 == move["_id"].AsInt32)
            .ToArray();
        var versionGroupIds = matches
            .Select(entry => entry["versionGroupId"].AsInt32)
            .Distinct()
            .ToArray();
        var versionGroups = await MongoDatabase.GetCollection<BsonDocument>("version_groups")
            .Find(Builders<BsonDocument>.Filter.In("_id", versionGroupIds))
            .ToListAsync(cancellationToken);
        var versionGroupsById = versionGroups.ToDictionary(group => group["_id"].AsInt32);
        var methods = await MongoDatabase.GetCollection<BsonDocument>("pokemon_move_methods")
            .Find(Builders<BsonDocument>.Filter.In(
                "_id",
                matches.Select(entry => entry["methodId"].AsInt32).Distinct()))
            .ToListAsync(cancellationToken);
        var methodsById = methods.ToDictionary(method => method["_id"].AsInt32);

        var learnMethods = matches.Select(entry =>
        {
            var versionId = entry["versionGroupId"].AsInt32;
            var methodId = entry["methodId"].AsInt32;
            return new BsonDocument
            {
                ["versionGroup"] = versionGroupsById.TryGetValue(versionId, out var versionGroup)
                    ? versionGroup["identifier"]
                    : BsonNull.Value,
                ["method"] = methodsById.TryGetValue(methodId, out var method)
                    ? method["identifier"]
                    : BsonNull.Value,
                ["level"] = entry["level"]
            };
        });

        return new BsonDocument
        {
            ["pokemon"] = pokemon["name"],
            ["move"] = move["name"],
            ["canLearn"] = matches.Length > 0,
            ["learnMethods"] = new BsonArray(learnMethods)
        }.ToJson();
    }

    public async Task<string> FindByNameOrIdAsync(
        string collection,
        string query,
        CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("Esta consulta de dados Pokémon requer MongoDB.");

        var result = await FindByNameOrIdDocumentAsync(collection, query, cancellationToken);
        return result?.ToJson() ?? "[]";
    }

    private async Task<BsonDocument?> FindByNameOrIdDocumentAsync(
        string collection,
        string query,
        CancellationToken cancellationToken)
    {
        var value = NormalizePokemonName(query);
        var filter = int.TryParse(query.Trim().TrimStart('#'), out var id)
            ? Builders<BsonDocument>.Filter.Eq("_id", id)
            : Builders<BsonDocument>.Filter.Eq("normalizedName", value);
        var result = await MongoDatabase.GetCollection<BsonDocument>(collection)
            .Find(filter)
            .FirstOrDefaultAsync(cancellationToken);
        return result;
    }

    public async Task<string> FindEvolutionChainAsync(string query, CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A consulta de evoluções requer o provider MongoDB.");

        var pokemon = await FindPokemonRecordAsync(query, cancellationToken);
        if (pokemon is null)
            return "[]";

        var speciesId = pokemon.TryGetValue("pokedexNumber", out var dexNumber)
            ? dexNumber.AsInt32
            : pokemon["speciesId"].AsInt32;
        var species = await MongoDatabase.GetCollection<BsonDocument>("pokedex")
            .Find(Builders<BsonDocument>.Filter.Eq("_id", speciesId))
            .FirstOrDefaultAsync(cancellationToken);
        if (species is null || !species.TryGetValue("evolutionChainId", out var chainId))
            return "[]";

        var chain = await MongoDatabase.GetCollection<BsonDocument>("evolution_chains")
            .Find(Builders<BsonDocument>.Filter.Eq("_id", chainId.AsInt32))
            .FirstOrDefaultAsync(cancellationToken);
        return chain?.ToJson() ?? "[]";
    }

    public async Task<string> FindPokemonByTypeAsync(string type, CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A busca por tipo requer o provider MongoDB.");

        var normalizedType = NormalizePokemonName(type);
        var typeDocument = await MongoDatabase.GetCollection<BsonDocument>("types")
            .Find(Builders<BsonDocument>.Filter.Eq("normalizedName", normalizedType))
            .FirstOrDefaultAsync(cancellationToken);
        if (typeDocument is null)
            return "[]";

        var pokemonCollection = MongoDatabase.GetCollection<BsonDocument>("pokedex");
        var filter = Builders<BsonDocument>.Filter.AnyEq("types", typeDocument["identifier"].AsString);
        var count = await pokemonCollection.CountDocumentsAsync(filter, cancellationToken: cancellationToken);
        var pokemon = await pokemonCollection.Find(filter)
            .Project(Builders<BsonDocument>.Projection
                .Include("pokedexNumber")
                .Include("name")
                .Include("types")
                .Include("stats"))
            .Limit(100)
            .ToListAsync(cancellationToken);

        return new BsonDocument
        {
            ["type"] = typeDocument["name"],
            ["count"] = count,
            ["pokemon"] = new BsonArray(pokemon)
        }.ToJson();
    }

    public async Task<string> FindPokemonEncountersAsync(string query, CancellationToken cancellationToken)
    {
        if (Provider == "oracle")
            throw new InvalidOperationException("A consulta de encontros requer o provider MongoDB.");

        var pokemon = await FindPokemonRecordAsync(query, cancellationToken);
        if (pokemon is null)
            return "[]";

        var pokemonIds = pokemon.TryGetValue("pokemonIds", out var ids)
            ? ids.AsBsonArray.Select(id => id.AsInt32).ToArray()
            : [pokemon["_id"].AsInt32];
        var filter = Builders<BsonDocument>.Filter.In("pokemonId", pokemonIds);
        var encountersCollection = MongoDatabase.GetCollection<BsonDocument>("encounters");
        var count = await encountersCollection.CountDocumentsAsync(filter, cancellationToken: cancellationToken);
        var encounters = await encountersCollection.Find(filter)
            .Limit(100)
            .ToListAsync(cancellationToken);

        var areaIds = encounters.Select(item => item["locationAreaId"].AsInt32).Distinct().ToArray();
        var versionIds = encounters.Select(item => item["versionId"].AsInt32).Distinct().ToArray();
        var areas = await MongoDatabase.GetCollection<BsonDocument>("location_areas")
            .Find(Builders<BsonDocument>.Filter.In("_id", areaIds))
            .ToListAsync(cancellationToken);
        var locationsById = areas.Select(area => area["locationId"].AsInt32).Distinct().ToArray();
        var locations = await MongoDatabase.GetCollection<BsonDocument>("locations")
            .Find(Builders<BsonDocument>.Filter.In("_id", locationsById))
            .ToListAsync(cancellationToken);
        var versions = await MongoDatabase.GetCollection<BsonDocument>("versions")
            .Find(Builders<BsonDocument>.Filter.In("_id", versionIds))
            .ToListAsync(cancellationToken);
        var areasById = areas.ToDictionary(area => area["_id"].AsInt32);
        var locationsByKey = locations.ToDictionary(location => location["_id"].AsInt32);
        var versionsById = versions.ToDictionary(version => version["_id"].AsInt32);

        var results = encounters.Select(encounter =>
        {
            var area = areasById[encounter["locationAreaId"].AsInt32];
            var location = locationsByKey[area["locationId"].AsInt32];
            var version = versionsById[encounter["versionId"].AsInt32];
            return new BsonDocument
            {
                ["version"] = version["identifier"],
                ["location"] = location["name"],
                ["area"] = area["identifier"],
                ["minLevel"] = encounter["minLevel"],
                ["maxLevel"] = encounter["maxLevel"]
            };
        });

        return new BsonDocument
        {
            ["pokemon"] = pokemon["name"],
            ["totalEncounters"] = count,
            ["returnedEncounters"] = encounters.Count,
            ["encounters"] = new BsonArray(results)
        }.ToJson();
    }

    private async Task<BsonDocument?> FindPokemonRecordAsync(
        string query,
        CancellationToken cancellationToken)
    {
        var value = query.Trim().TrimStart('#');
        var filter = int.TryParse(value, out var pokedexNumber)
            ? Builders<BsonDocument>.Filter.Eq("pokedexNumber", pokedexNumber)
            : Builders<BsonDocument>.Filter.Eq("normalizedName", NormalizePokemonName(value));
        var species = await MongoDatabase.GetCollection<BsonDocument>("pokedex")
            .Find(filter)
            .FirstOrDefaultAsync(cancellationToken);
        if (species is not null)
            return species;

        return await MongoDatabase.GetCollection<BsonDocument>("pokemon")
            .Find(Builders<BsonDocument>.Filter.Eq("normalizedName", NormalizePokemonName(value)))
            .FirstOrDefaultAsync(cancellationToken);
    }

    private static string NormalizePokemonName(string value)
        => string.Concat(value.Trim().ToLowerInvariant().Where(char.IsLetterOrDigit));

    public async Task<string> SearchAsync(
        string collection,
        string text,
        int? limit,
        CancellationToken cancellationToken)
    {
        var safeLimit = Math.Clamp(limit ?? 20, 1, 100);

        if (Provider == "oracle")
        {
            await using var connection = new OracleConnection(configuration["Database:OracleConnection"]);
            await connection.OpenAsync(cancellationToken);

            var tableName = SafeIdentifier(collection).ToUpperInvariant();
            await using var columnsCommand = connection.CreateCommand();
            columnsCommand.CommandText = """
                SELECT COLUMN_NAME
                FROM USER_TAB_COLUMNS
                WHERE TABLE_NAME = :tableName
                  AND DATA_TYPE IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB')
                """;
            columnsCommand.Parameters.Add("tableName", tableName);

            var textColumns = new List<string>();
            await using (var columnsReader = await columnsCommand.ExecuteReaderAsync(cancellationToken))
            {
                while (await columnsReader.ReadAsync(cancellationToken))
                    textColumns.Add(SafeIdentifier(columnsReader.GetString(0)));
            }

            if (textColumns.Count == 0)
                return "[]";

            await using var command = connection.CreateCommand();
            command.BindByName = true;
            var predicates = textColumns.Select(column =>
                $"LOWER(TO_CHAR(\"{column}\")) LIKE :text");
            command.CommandText = $"SELECT * FROM \"{tableName}\" WHERE ({string.Join(" OR ", predicates)}) FETCH FIRST :limit ROWS ONLY";
            command.Parameters.Add("text", $"%{text.ToLowerInvariant()}%");
            command.Parameters.Add("limit", safeLimit);

            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            return ReadRows(reader);
        }

        var mongoCollection = MongoDatabase.GetCollection<BsonDocument>(SafeMongoCollection(collection));
        var filter = new BsonDocument("$or", new BsonArray
        {
            new BsonDocument("$expr", new BsonDocument("$regexMatch", new BsonDocument
            {
                ["input"] = new BsonDocument("$toString", "$$ROOT"),
                ["regex"] = System.Text.RegularExpressions.Regex.Escape(text),
                ["options"] = "i"
            }))
        });
        var documents = await mongoCollection.Find(filter).Limit(safeLimit).ToListAsync(cancellationToken);
        return documents.Count == 0 ? "[]" : documents.ToJson();
    }

    private static string ReadRows(OracleDataReader reader)
    {
        var rows = new System.Text.Json.Nodes.JsonArray();
        while (reader.Read())
        {
            var row = new System.Text.Json.Nodes.JsonObject();
            for (var i = 0; i < reader.FieldCount; i++)
                row[reader.GetName(i)] = reader.IsDBNull(i) ? null : reader.GetValue(i)?.ToString();
            rows.Add(row);
        }
        return rows.ToJsonString();
    }

    private static string SafeIdentifier(string value)
        => new(value.Where(char.IsLetterOrDigit).ToArray());

    private static string SafeMongoCollection(string value)
    {
        if (string.IsNullOrWhiteSpace(value)
            || value.Any(character => !char.IsLetterOrDigit(character) && character != '_'))
            throw new ArgumentException("Nome inválido para coleção MongoDB.", nameof(value));

        return value;
    }
}
