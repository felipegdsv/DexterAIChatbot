import argparse
import csv
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path


REPOSITORY = "PokeAPI/pokeapi"
API = f"https://api.github.com/repos/{REPOSITORY}"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}"
BOOL_FIELDS = {
    "always_shiny",
    "forms_switchable",
    "has_gender_differences",
    "is_alpha",
    "is_baby",
    "is_battle_only",
    "is_default",
    "is_hidden",
    "is_legendary",
    "is_main_series",
    "is_mega",
    "is_mythical",
    "is_shiny",
    "needs_multiplayer",
    "needs_overworld_rain",
    "never_shiny",
    "official",
    "turn_upside_down",
}


def fetch(url):
    return subprocess.check_output(
        [
            "curl.exe",
            "-4",
            "-fLsS",
            "--connect-timeout",
            "15",
            "--max-time",
            "180",
            "-H",
            "User-Agent: Dexter-Pokemon-Importer",
            url,
        ]
    )


def camel_case(value):
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def scalar(key, value):
    if value == "":
        return None
    if key in BOOL_FIELDS or key.startswith(("is_", "has_", "needs_")):
        if value in ("0", "1"):
            return value == "1"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def document(row):
    return {camel_case(key): scalar(key, value) for key, value in row.items()}


def main():
    parser = argparse.ArgumentParser(
        description="Import structured Pokemon reference data into MongoDB."
    )
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://localhost:27017/dexter",
        help="MongoDB connection URI, including the database name.",
    )
    parser.add_argument(
        "--mongosh",
        default=shutil.which("mongosh")
        or r"C:\Users\Galmir\AppData\Local\Programs\mongosh\mongosh.exe",
        help="Path to mongosh.exe.",
    )
    args = parser.parse_args()
    if not Path(args.mongosh).is_file():
        parser.error(f"mongosh was not found: {args.mongosh}")

    cache = {}

    def raw_table(name):
        if name not in cache:
            url = f"{RAW}/{commit}/data/v2/csv/{name}.csv"
            cache[name] = fetch(url).decode("utf-8-sig")
        return cache[name]

    def rows(name):
        return list(csv.DictReader(io.StringIO(raw_table(name))))

    def iter_rows(name):
        return csv.DictReader(io.StringIO(raw_table(name)))

    commit_info = json.loads(fetch(f"{API}/commits/master"))
    commit = commit_info["sha"]
    languages = {
        int(row["id"]): row["identifier"] for row in rows("languages")
    }

    def translations(table, owner_field, value_fields):
        result = defaultdict(dict)
        for row in rows(table):
            owner = int(row[owner_field])
            language = languages.get(int(row["local_language_id"]))
            if language:
                values = {
                    camel_case(field): row[field]
                    for field in value_fields
                    if row[field]
                }
                if values:
                    result[owner][language] = values
        return result

    def named_entities(table, name_table, owner_field, value_fields):
        names = translations(name_table, owner_field, value_fields)
        result = []
        for row in rows(table):
            item = document(row)
            identifier = int(row["id"])
            item["_id"] = identifier
            item["localizedNames"] = names.get(identifier, {})
            english = names.get(identifier, {}).get("en", {})
            item["name"] = english.get(value_fields[-1]) or row.get("identifier")
            item["normalizedName"] = re.sub(
                r"[^a-z0-9]", "", (item["name"] or row["identifier"]).lower()
            )
            result.append(item)
        return result

    stat_rows = rows("stats")
    stat_names = translations("stat_names", "stat_id", ["name"])
    stat_ids = {int(row["id"]): row["identifier"] for row in stat_rows}
    stat_entities = []
    for row in stat_rows:
        item = document(row)
        item["_id"] = int(row["id"])
        item["localizedNames"] = stat_names.get(item["_id"], {})
        item["name"] = item["localizedNames"].get("en", {}).get("name", row["identifier"])
        item["normalizedName"] = re.sub(r"[^a-z0-9]", "", item["name"].lower())
        stat_entities.append(item)

    pokemon_rows = rows("pokemon")
    pokemon_by_id = {int(row["id"]): row for row in pokemon_rows}
    species_rows = rows("pokemon_species")
    species_by_id = {int(row["id"]): row for row in species_rows}
    species_names = translations(
        "pokemon_species_names", "pokemon_species_id", ["name", "genus"]
    )
    type_rows = rows("types")
    type_ids = {int(row["id"]): row["identifier"] for row in type_rows}
    type_names = translations("type_names", "type_id", ["name"])

    type_relations = defaultdict(
        lambda: {"doubleDamageTo": [], "halfDamageTo": [], "noDamageTo": []}
    )
    type_relations_from = defaultdict(
        lambda: {"doubleDamageFrom": [], "halfDamageFrom": [], "noDamageFrom": []}
    )
    for row in rows("type_efficacy"):
        attack = int(row["damage_type_id"])
        target = int(row["target_type_id"])
        factor = int(row["damage_factor"])
        relation = {200: "doubleDamageTo", 50: "halfDamageTo", 0: "noDamageTo"}.get(factor)
        inverse = {200: "doubleDamageFrom", 50: "halfDamageFrom", 0: "noDamageFrom"}.get(factor)
        if relation:
            type_relations[attack][relation].append(type_ids[target])
            type_relations_from[target][inverse].append(type_ids[attack])
    type_entities = []
    for row in type_rows:
        identifier = int(row["id"])
        names = type_names.get(identifier, {})
        name = names.get("en", {}).get("name", row["identifier"])
        type_entities.append(
            {
                **document(row),
                "_id": identifier,
                "name": name,
                "normalizedName": re.sub(r"[^a-z0-9]", "", name.lower()),
                "localizedNames": names,
                "damageRelations": {
                    **type_relations[identifier],
                    **type_relations_from[identifier],
                },
            }
        )

    ability_rows = rows("abilities")
    ability_names = translations("ability_names", "ability_id", ["name"])
    ability_ids = {int(row["id"]): row["identifier"] for row in ability_rows}
    abilities_by_pokemon = defaultdict(list)
    pokemon_ids_by_ability = defaultdict(set)
    for row in rows("pokemon_abilities"):
        pokemon_id = int(row["pokemon_id"])
        ability_id = int(row["ability_id"])
        ability = {
            "id": ability_id,
            "name": ability_ids[ability_id],
            "hidden": row["is_hidden"] == "1",
            "slot": int(row["slot"]),
        }
        abilities_by_pokemon[pokemon_id].append(ability)
        pokemon_ids_by_ability[ability_id].add(pokemon_id)
    ability_entities = []
    for row in ability_rows:
        identifier = int(row["id"])
        names = ability_names.get(identifier, {})
        name = names.get("en", {}).get("name", row["identifier"])
        ability_entities.append(
            {
                **document(row),
                "_id": identifier,
                "name": name,
                "normalizedName": re.sub(r"[^a-z0-9]", "", name.lower()),
                "localizedNames": names,
                "pokemonIds": sorted(pokemon_ids_by_ability[identifier]),
            }
        )

    types_by_pokemon = defaultdict(list)
    for row in rows("pokemon_types"):
        pokemon_id = int(row["pokemon_id"])
        type_id = int(row["type_id"])
        types_by_pokemon[pokemon_id].append((int(row["slot"]), type_id))

    stats_by_pokemon = defaultdict(dict)
    effort_by_pokemon = defaultdict(dict)
    for row in rows("pokemon_stats"):
        pokemon_id = int(row["pokemon_id"])
        stat = stat_ids[int(row["stat_id"])].replace("-", "_")
        stats_by_pokemon[pokemon_id][camel_case(stat)] = int(row["base_stat"])
        effort_by_pokemon[pokemon_id][camel_case(stat)] = int(row["effort"])

    pokemon_types_past = defaultdict(list)
    for row in rows("pokemon_types_past"):
        pokemon_types_past[int(row["pokemon_id"])].append(document(row))
    pokemon_stats_past = defaultdict(list)
    for row in rows("pokemon_stats_past"):
        pokemon_stats_past[int(row["pokemon_id"])].append(document(row))
    pokemon_abilities_past = defaultdict(list)
    for row in rows("pokemon_abilities_past"):
        pokemon_abilities_past[int(row["pokemon_id"])].append(document(row))

    eggs_by_species = defaultdict(list)
    egg_group_rows = rows("egg_groups")
    egg_group_ids = {int(row["id"]): row["identifier"] for row in egg_group_rows}
    for row in rows("pokemon_egg_groups"):
        group_id = int(row["egg_group_id"])
        eggs_by_species[int(row["species_id"])].append(
            {"id": group_id, "name": egg_group_ids[group_id]}
        )

    dex_numbers = defaultdict(list)
    for row in rows("pokemon_dex_numbers"):
        dex_numbers[int(row["species_id"])].append(
            {"pokedexId": int(row["pokedex_id"]), "number": int(row["pokedex_number"])}
        )

    form_names = defaultdict(dict)
    for row in rows("pokemon_form_names"):
        language = languages.get(int(row["local_language_id"]))
        if language:
            values = {
                key: row[column]
                for key, column in (
                    ("formName", "form_name"),
                    ("pokemonName", "pokemon_name"),
                )
                if row[column]
            }
            if values:
                form_names[int(row["pokemon_form_id"])][language] = values
    forms_by_pokemon = defaultdict(list)
    forms_by_id = {int(row["id"]): row for row in rows("pokemon_forms")}
    form_types = defaultdict(list)
    for row in rows("pokemon_form_types"):
        form_types[int(row["pokemon_form_id"])].append(
            (int(row["slot"]), int(row["type_id"]))
        )
    form_generations = defaultdict(list)
    for row in rows("pokemon_form_generations"):
        form_generations[int(row["pokemon_form_id"])].append(document(row))
    form_conditions = defaultdict(list)
    for row in rows("pokemon_form_conditions"):
        form_conditions[int(row["pokemon_form_id"])].append(document(row))

    def types_for(pokemon_id):
        entries = sorted(types_by_pokemon.get(pokemon_id, []))
        return {
            "typeIds": [type_id for _, type_id in entries],
            "types": [type_ids[type_id] for _, type_id in entries],
        }

    def pokemon_details(row):
        pokemon_id = int(row["id"])
        species_id = int(row["species_id"])
        species_names_for_pokemon = species_names.get(species_id, {})
        return {
            "_id": pokemon_id,
            "name": row["identifier"],
            "normalizedName": re.sub(r"[^a-z0-9]", "", row["identifier"].lower()),
            "speciesId": species_id,
            "pokedexNumber": species_id,
            "speciesName": species_names_for_pokemon.get("en", {}).get("name")
            or species_by_id[species_id]["identifier"],
            "isDefault": row["is_default"] == "1",
            "order": int(row["order"]) if row["order"] else None,
            "heightDecimeters": int(row["height"]),
            "weightHectograms": int(row["weight"]),
            "baseExperience": int(row["base_experience"])
            if row["base_experience"]
            else None,
            "stats": stats_by_pokemon[pokemon_id],
            "effortYield": effort_by_pokemon[pokemon_id],
            **types_for(pokemon_id),
            "abilities": sorted(abilities_by_pokemon[pokemon_id], key=lambda x: x["slot"]),
            "pastTypes": pokemon_types_past[pokemon_id],
            "pastStats": pokemon_stats_past[pokemon_id],
            "pastAbilities": pokemon_abilities_past[pokemon_id],
        }

    all_pokemon = [pokemon_details(row) for row in pokemon_rows]
    base_pokemon_by_species = {
        int(row["species_id"]): int(row["id"])
        for row in pokemon_rows
        if row["is_default"] == "1"
    }
    for form_id, row in forms_by_id.items():
        pokemon_id = int(row["pokemon_id"])
        species_id = int(pokemon_by_id[pokemon_id]["species_id"])
        forms_by_pokemon[pokemon_id].append(form_id)
    pokemon_forms = []
    for form_id, row in forms_by_id.items():
        pokemon_id = int(row["pokemon_id"])
        species_id = int(pokemon_by_id[pokemon_id]["species_id"])
        form_type_entries = sorted(form_types.get(form_id, []))
        type_info = (
            {
                "typeIds": [type_id for _, type_id in form_type_entries],
                "types": [type_ids[type_id] for _, type_id in form_type_entries],
            }
            if form_type_entries
            else types_for(pokemon_id)
        )
        localized = form_names.get(form_id, {})
        english = localized.get("en", {})
        pokemon_forms.append(
            {
                **document(row),
                "_id": form_id,
                "name": english.get("formName")
                or row["form_identifier"]
                or pokemon_by_id[pokemon_id]["identifier"],
                "normalizedName": re.sub(
                    r"[^a-z0-9]",
                    "",
                    (
                        english.get("formName")
                        or row["form_identifier"]
                        or pokemon_by_id[pokemon_id]["identifier"]
                    ).lower(),
                ),
                "localizedNames": localized,
                "pokemonId": pokemon_id,
                "speciesId": species_id,
                **type_info,
                "generations": form_generations[form_id],
                "conditions": form_conditions[form_id],
            }
        )

    evolution_rows = rows("pokemon_evolution")
    evolution_docs = []
    evolutions_by_chain = defaultdict(list)
    for row in evolution_rows:
        target_id = int(row["evolved_species_id"])
        target = species_by_id[target_id]
        chain_id = int(target["evolution_chain_id"])
        item = {
            **document(row),
            "_id": int(row["id"]),
            "evolutionChainId": chain_id,
            "evolvesFromSpeciesId": int(target["evolves_from_species_id"])
            if target["evolves_from_species_id"]
            else None,
            "evolvedSpeciesName": species_names.get(target_id, {})
            .get("en", {})
            .get("name", target["identifier"]),
        }
        evolution_docs.append(item)
        evolutions_by_chain[chain_id].append(item)

    species_docs = []
    species_by_chain = defaultdict(list)
    for row in species_rows:
        species_id = int(row["id"])
        localized = species_names.get(species_id, {})
        name = localized.get("en", {}).get("name", row["identifier"])
        base_id = base_pokemon_by_species[species_id]
        base = next(p for p in all_pokemon if p["_id"] == base_id)
        species = {
            **document(row),
            "_id": species_id,
            "pokedexNumber": species_id,
            "name": name,
            "normalizedName": re.sub(r"[^a-z0-9]", "", row["identifier"].lower()),
            "localizedNames": localized,
            "basePokemonId": base_id,
            "stats": base["stats"],
            "effortYield": base["effortYield"],
            "types": base["types"],
            "typeIds": base["typeIds"],
            "abilities": base["abilities"],
            "heightDecimeters": base["heightDecimeters"],
            "weightHectograms": base["weightHectograms"],
            "baseExperience": base["baseExperience"],
            "eggGroups": eggs_by_species[species_id],
            "regionalDexNumbers": dex_numbers[species_id],
            "pokemonIds": sorted(
                pokemon_id
                for pokemon_id, pokemon_row in pokemon_by_id.items()
                if int(pokemon_row["species_id"]) == species_id
            ),
            "formIds": sorted(
                form_id
                for form_id, form_row in forms_by_id.items()
                if int(pokemon_by_id[int(form_row["pokemon_id"])]["species_id"])
                == species_id
            ),
        }
        species_docs.append(species)
        species_by_chain[int(row["evolution_chain_id"])].append(species)
    for chain in species_by_chain.values():
        chain.sort(key=lambda item: item["order"] or 0)
    evolution_chains = []
    for row in rows("evolution_chains"):
        chain_id = int(row["id"])
        evolution_chains.append(
            {
                **document(row),
                "_id": chain_id,
                "species": [
                    {
                        "speciesId": item["_id"],
                        "name": item["name"],
                        "evolvesFromSpeciesId": item["evolvesFromSpeciesId"],
                    }
                    for item in species_by_chain[chain_id]
                ],
                "evolutions": evolutions_by_chain[chain_id],
            }
        )

    moves_names = translations("move_names", "move_id", ["name"])
    move_meta = {
        int(row["move_id"]): document(row) for row in rows("move_meta")
    }
    move_stat_changes = defaultdict(list)
    for row in rows("move_meta_stat_changes"):
        move_stat_changes[int(row["move_id"])].append(document(row))
    ailment_entities = named_entities(
        "move_meta_ailments", "move_meta_ailment_names", "move_meta_ailment_id", ["name"]
    )
    ailment_by_id = {item["_id"]: item for item in ailment_entities}
    category_entities = [
        {**document(row), "_id": int(row["id"])} for row in rows("move_meta_categories")
    ]
    category_by_id = {item["_id"]: item for item in category_entities}
    damage_classes = [
        {**document(row), "_id": int(row["id"])} for row in rows("move_damage_classes")
    ]
    damage_class_by_id = {item["_id"]: item for item in damage_classes}
    move_targets = [
        {**document(row), "_id": int(row["id"])} for row in rows("move_targets")
    ]
    move_target_by_id = {item["_id"]: item for item in move_targets}
    move_entities = []
    for row in rows("moves"):
        move_id = int(row["id"])
        localized = moves_names.get(move_id, {})
        name = localized.get("en", {}).get("name", row["identifier"])
        meta = move_meta.get(move_id)
        if meta:
            meta["ailment"] = ailment_by_id.get(meta.get("metaAilmentId"))
            meta["category"] = category_by_id.get(meta.get("metaCategoryId"))
        move_entities.append(
            {
                **document(row),
                "_id": move_id,
                "name": name,
                "normalizedName": re.sub(r"[^a-z0-9]", "", row["identifier"].lower()),
                "localizedNames": localized,
                "typeName": type_ids.get(int(row["type_id"]), "unknown"),
                "damageClassName": damage_class_by_id.get(
                    int(row["damage_class_id"]), {}
                ).get("identifier"),
                "targetName": move_target_by_id.get(int(row["target_id"]), {}).get(
                    "identifier"
                ),
                "meta": meta,
                "statChanges": move_stat_changes[move_id],
            }
        )

    items_names = translations("item_names", "item_id", ["name"])
    item_categories = {
        int(row["id"]): row["identifier"] for row in rows("item_categories")
    }
    item_entities = []
    for row in rows("items"):
        item_id = int(row["id"])
        localized = items_names.get(item_id, {})
        name = localized.get("en", {}).get("name", row["identifier"])
        item_entities.append(
            {
                **document(row),
                "_id": item_id,
                "name": name,
                "normalizedName": re.sub(r"[^a-z0-9]", "", row["identifier"].lower()),
                "localizedNames": localized,
                "categoryName": item_categories.get(int(row["category_id"])),
            }
        )

    natures_names = translations("nature_names", "nature_id", ["name"])
    natures = []
    for row in rows("natures"):
        nature_id = int(row["id"])
        localized = natures_names.get(nature_id, {})
        name = localized.get("en", {}).get("name", row["identifier"])
        natures.append(
            {
                **document(row),
                "_id": nature_id,
                "name": name,
                "normalizedName": re.sub(r"[^a-z0-9]", "", row["identifier"].lower()),
                "localizedNames": localized,
                "increasedStatName": stat_ids.get(int(row["increased_stat_id"])),
                "decreasedStatName": stat_ids.get(int(row["decreased_stat_id"])),
            }
        )

    learnsets = defaultdict(list)
    learnset_rows = 0
    for row in iter_rows("pokemon_moves"):
        pokemon_id = int(row["pokemon_id"])
        learnsets[pokemon_id].append(
            {
                "moveId": int(row["move_id"]),
                "versionGroupId": int(row["version_group_id"]),
                "methodId": int(row["pokemon_move_method_id"]),
                "level": int(row["level"]),
                "order": int(row["order"]) if row["order"] else None,
                "enhancementLevel": int(row["enhancement_level"])
                if row["enhancement_level"]
                else None,
            }
        )
        learnset_rows += 1
    learnset_docs = []
    for pokemon_id, pokemon_moves in learnsets.items():
        pokemon_moves.sort(
            key=lambda move: (
                move["versionGroupId"],
                move["methodId"],
                move["level"],
                move["moveId"],
            )
        )
        learnset_docs.append(
            {
                "_id": pokemon_id,
                "pokemonId": pokemon_id,
                "speciesId": int(pokemon_by_id[pokemon_id]["species_id"]),
                "moves": pokemon_moves,
            }
        )

    conditions_by_encounter = defaultdict(list)
    for row in rows("encounter_condition_value_map"):
        conditions_by_encounter[int(row["encounter_id"])].append(
            int(row["encounter_condition_value_id"])
        )
    encounter_details = {
        int(row["encounter_id"]): document(row)
        for row in rows("encounter_pokemon_details")
    }

    def encounters():
        for row in iter_rows("encounters"):
            encounter_id = int(row["id"])
            yield {
                **document(row),
                "_id": encounter_id,
                "conditionValueIds": conditions_by_encounter[encounter_id],
                "details": encounter_details.get(encounter_id),
            }

    def simple_entities(table, id_field="id"):
        for row in rows(table):
            item = document(row)
            raw_id = row[id_field]
            item["_id"] = int(raw_id) if raw_id.isdigit() else raw_id
            yield item

    def composite_entities(table, id_fields):
        for row in rows(table):
            item = document(row)
            item["_id"] = ":".join(row[field] for field in id_fields)
            yield item

    def entity_names(table, name_table, key_field, name_fields):
        name_map = translations(name_table, key_field, name_fields)
        for row in rows(table):
            item = document(row)
            raw_id = row["id"]
            identifier = int(raw_id) if raw_id.isdigit() else raw_id
            item["_id"] = identifier
            item["localizedNames"] = name_map.get(identifier, {})
            english = name_map.get(identifier, {}).get("en", {})
            item["name"] = english.get(name_fields[0]) or row.get("identifier")
            yield item

    held_items = (
        {
            **document(row),
            "_id": f"{row['pokemon_id']}:{row['version_id']}:{row['item_id']}",
        }
        for row in rows("pokemon_items")
    )
    machines = (
        {
            **document(row),
            "_id": f"{row['version_group_id']}:{row['machine_number']}",
        }
        for row in rows("machines")
    )
    game_indices = (
        {
            **document(row),
            "_id": f"{row['pokemon_id']}:{row['version_id']}",
        }
        for row in rows("pokemon_game_indices")
    )

    collections = {
        "pokedex": species_docs,
        "pokemon": all_pokemon,
        "pokemon_forms": pokemon_forms,
        "pokemon_learnsets": learnset_docs,
        "moves": move_entities,
        "abilities": ability_entities,
        "types": type_entities,
        "items": item_entities,
        "natures": natures,
        "evolutions": evolution_docs,
        "evolution_chains": evolution_chains,
        "pokemon_held_items": held_items,
        "machines": machines,
        "encounters": encounters(),
        "encounter_slots": simple_entities("encounter_slots"),
        "encounter_methods": simple_entities("encounter_methods"),
        "encounter_conditions": simple_entities("encounter_conditions"),
        "encounter_condition_values": simple_entities("encounter_condition_values"),
        "locations": entity_names("locations", "location_names", "location_id", ["name"]),
        "location_areas": simple_entities("location_areas"),
        "regions": entity_names("regions", "region_names", "region_id", ["name"]),
        "versions": simple_entities("versions"),
        "version_groups": simple_entities("version_groups"),
        "pokemon_move_methods": simple_entities("pokemon_move_methods"),
        "generations": entity_names(
            "generations", "generation_names", "generation_id", ["name"]
        ),
        "egg_groups": simple_entities("egg_groups"),
        "growth_rates": simple_entities("growth_rates"),
        "experience": composite_entities("experience", ["growth_rate_id", "level"]),
        "stats": stat_entities,
        "move_meta_ailments": ailment_entities,
        "move_meta_categories": category_entities,
        "move_damage_classes": damage_classes,
        "move_targets": move_targets,
        "pokemon_game_indices": game_indices,
    }

    indexes = {
        "pokedex": [
            ({"pokedexNumber": 1}, {"unique": True}),
            ({"normalizedName": 1}, {}),
            ({"types": 1}, {}),
            ({"abilities.name": 1}, {}),
            ({"generationId": 1}, {}),
            ({"evolutionChainId": 1}, {}),
        ],
        "pokemon": [
            ({"speciesId": 1}, {}),
            ({"normalizedName": 1}, {}),
            ({"types": 1}, {}),
            ({"abilities.name": 1}, {}),
        ],
        "pokemon_forms": [
            ({"pokemonId": 1}, {}),
            ({"speciesId": 1}, {}),
            ({"normalizedName": 1}, {}),
            ({"types": 1}, {}),
        ],
        "pokemon_learnsets": [
            ({"speciesId": 1}, {}),
            ({"moves.moveId": 1}, {}),
            ({"moves.versionGroupId": 1}, {}),
        ],
        "moves": [
            ({"normalizedName": 1}, {}),
            ({"typeId": 1}, {}),
            ({"damageClassId": 1}, {}),
        ],
        "abilities": [
            ({"normalizedName": 1}, {}),
            ({"pokemonIds": 1}, {}),
        ],
        "types": [({"normalizedName": 1}, {})],
        "items": [
            ({"normalizedName": 1}, {}),
            ({"categoryId": 1}, {}),
        ],
        "natures": [({"normalizedName": 1}, {})],
        "evolutions": [
            ({"evolutionChainId": 1}, {}),
            ({"evolvedSpeciesId": 1}, {}),
        ],
        "pokemon_held_items": [
            ({"pokemonId": 1, "versionId": 1}, {}),
            ({"itemId": 1}, {}),
        ],
        "machines": [
            ({"moveId": 1, "versionGroupId": 1}, {}),
            ({"itemId": 1}, {}),
        ],
        "encounters": [
            ({"pokemonId": 1, "versionId": 1}, {}),
            ({"locationAreaId": 1, "versionId": 1}, {}),
        ],
        "locations": [({"regionId": 1}, {})],
        "location_areas": [({"locationId": 1}, {})],
    }

    with tempfile.TemporaryDirectory(prefix="pokemon-import-") as directory:
        temp = Path(directory)
        manifest_collections = []
        counts = {}
        for name, docs in collections.items():
            chunks = []
            batch = []
            count = 0
            for item in docs:
                batch.append(item)
                count += 1
                if len(batch) == 1000:
                    chunk = temp / f"{name}-{len(chunks):04d}.json"
                    chunk.write_text(
                        json.dumps(batch, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    chunks.append(str(chunk))
                    batch = []
            if batch:
                chunk = temp / f"{name}-{len(chunks):04d}.json"
                chunk.write_text(
                    json.dumps(batch, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                chunks.append(str(chunk))
            if count == 0:
                raise ValueError(f"Source collection '{name}' is empty.")
            counts[name] = count
            manifest_collections.append(
                {
                    "name": name,
                    "count": count,
                    "files": chunks,
                    "indexes": [
                        {"keys": keys, "options": options}
                        for keys, options in indexes.get(name, [])
                    ],
                }
            )

        if counts["pokedex"] != len(species_rows):
            raise ValueError("Pokédex records do not match the source species count.")
        if counts["pokemon"] != len(pokemon_rows):
            raise ValueError("Pokemon records do not match the source Pokemon count.")
        if learnset_rows == 0 or counts["encounters"] == 0:
            raise ValueError("Learnset or encounter source data is unexpectedly empty.")
        if [item["_id"] for item in species_docs] != list(
            range(1, len(species_docs) + 1)
        ):
            raise ValueError("National Pokédex IDs are not complete and contiguous.")

        metadata = [
            {
                "_id": "pokeapi",
                "repository": REPOSITORY,
                "commit": commit,
                "source": f"https://github.com/{REPOSITORY}/tree/{commit}/data/v2/csv",
                "importedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "scope": "Structured game data; descriptive prose and flavor text excluded.",
                "counts": counts,
                "pokemonMoveRows": learnset_rows,
            }
        ]
        metadata_file = temp / "pokemon-dataset-metadata.json"
        metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        manifest_collections.append(
            {
                "name": "pokemon_dataset_metadata",
                "count": 1,
                "files": [str(metadata_file)],
                "indexes": [],
            }
        )

        manifest_file = temp / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest_collections, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest_path = json.dumps(str(manifest_file))
        script = f"""
const fs = require('fs');
const collections = JSON.parse(fs.readFileSync({manifest_path}, 'utf8'));
for (const item of collections) {{
  const stage = db.getCollection('__staging_' + item.name);
  stage.drop();
  let inserted = 0;
  for (const file of item.files) {{
    const docs = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (docs.length) {{
      stage.insertMany(docs, {{ ordered: true }});
      inserted += docs.length;
    }}
  }}
  if (inserted !== item.count || stage.countDocuments() !== item.count) {{
    throw new Error('Import count mismatch for ' + item.name);
  }}
  for (const index of item.indexes) {{
    stage.createIndex(index.keys, index.options);
  }}
}}
for (const item of collections) {{
  const result = db.getCollection('__staging_' + item.name)
    .renameCollection(item.name, true);
  if (!result.ok) throw new Error('Could not replace collection ' + item.name);
  print(item.name + ': ' + item.count);
}}
"""
        print(f"Source commit: {commit}")
        print(f"National Pokedex: {counts['pokedex']} species")
        print(f"Pokemon move rows: {learnset_rows}")
        print(f"Encounter rows: {counts['encounters']}")
        subprocess.run(
            [args.mongosh, args.mongo_uri, "--quiet", "--eval", script],
            check=True,
        )


if __name__ == "__main__":
    main()
