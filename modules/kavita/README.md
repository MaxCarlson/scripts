# Kavita Python Module

`kavita` is a dependency-free Python client for Kavita's authenticated API, plus exact path matching and a durable store for pending MangaDL collection assignments.

## Safety and configuration

Create `KavitaConfig` from an explicit base URL and API key, preferably read from an environment variable:

```python
from kavita import KavitaClient, KavitaConfig

config = KavitaConfig.from_env("http://192.168.50.100:5000", api_key_env="KAVITA_API_KEY")
client = KavitaClient(config)
```

The key is sent only in Kavita's `x-api-key` header. The library does not print or persist it. Add operations preview by default; callers must pass `apply=True` to make API writes. Collection and reading-list updates are additive.

## Supported operations

- List series, collections, and reading lists.
- Add series IDs to a collection, creating that collection when absent.
- Add series IDs to a reading list, creating it when absent.
- Match local series directories to Kavita using a unique exact folder path, optionally translated with explicit local-to-server path mappings.
- Persist URL, expected local path, collection names, server URL, and reconciliation state atomically in JSON.

Missing or duplicate path matches remain pending. The module does not use title similarity or remove items from Kavita.

## Kavita API references

The API contract was checked against the official [Kavita repository's OpenAPI setup](https://github.com/Kareadita/Kavita/blob/develop/Kavita.Server/Startup.cs), [CollectionController](https://github.com/Kareadita/Kavita/blob/develop/Kavita.Server/Controllers/CollectionController.cs), and [ReadingListController](https://github.com/Kareadita/Kavita/blob/develop/Kavita.Server/Controllers/ReadingListController.cs). Kavita documents Auth Key authentication through the `x-api-key` header. Pin/test compatibility against the server version in use because the API evolves.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m ruff check kavita tests
```
