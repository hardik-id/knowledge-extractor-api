# Documents

The Studio's document list comes from this API. Where the list and the content come from is chosen by two settings, so the endpoints stay the same when the sources change. Nothing outside `apps/documents` knows which implementation runs: other apps use `apps/documents/selectors.py`.

## The two interfaces

Both are in `apps/documents/interfaces.py`.

| Interface | Setting | Job |
| --- | --- | --- |
| Catalog | `DOCUMENT_CATALOG` | `list(user)`: the documents a person may open. Each entry has `id`, `name`, `type`, `size_bytes`, `location` (for display), `modified_at`, `etag` (the version) and `storage_location` (where the content is). |
| Storage | `DOCUMENT_STORAGE` | `read(storage_location)`: the content bytes, the content type and the ETag. Raises `FileNotFoundError` when there is nothing there. |

An unknown value for either setting stops the app at start with a message naming the setting. A value with a dot is read as the dotted path of a class, which is how tests swap in fakes (`apps/documents/tests/fakes.py`).

| Setting | Values | Default |
| --- | --- | --- |
| `DOCUMENT_CATALOG` | `samples`, later `http` | `samples` |
| `DOCUMENT_CATALOG_URL` | URL of the catalog service, for `http` | empty |
| `DOCUMENT_STORAGE` | `samples`, later `azure` | `samples` |
| `AZURE_STORAGE_ACCOUNT_URL` | storage account URL, for `azure` | empty |

## Selectors

- `list_documents(user, query)`: the catalog's entries, filtered on name and location (substring, case does not matter), newest first.
- `get_document(user, document_id)`: one entry, or 404 `document_not_found`.
- `read_document(user, document_id)`: the text, the content type and the ETag. The catalog is asked first, so a person cannot read what the catalog does not list for them.

## Endpoint

`GET /api/v1/documents?q=` answers `{ "items": [...] }`, newest first, at most 100 items, no cursor. Each item: `id`, `name`, `source` (`"storage"`), `type`, `size_bytes`, `location`, `modified_at`, `etag`.

## The samples

`samples` is the built-in pair. The files are in `apps/documents/samples/`, with a `manifest.json` (id, name, display location, modified time). The text is the UI mock's enriched Markdown (YAML front matter, then the body); two documents hold ADRs that the default extraction definition finds. The id is the path of the file under `samples/`, shaped like a container path (`enriched/engineering/architecture/platform-adrs.md`), and doubles as the storage location. The ETag is a hash of the content.

## Plugging in Azure (not built yet)

1. `DOCUMENT_CATALOG=http`: a catalog class calls the external catalog service at `DOCUMENT_CATALOG_URL` with the person's identity and maps each answer to a `CatalogEntry`, with the blob path as `storage_location`.
2. `DOCUMENT_STORAGE=azure`: a storage class reads `storage_location` with `azure-storage-blob`'s `BlobClient`, signed in with `azure-identity`'s `DefaultAzureCredential` (the app's managed identity), against `AZURE_STORAGE_ACCOUNT_URL`. It returns the bytes, the blob's content type and its ETag.
3. Register both in `_BUILT_IN` in `apps/documents/backends.py`. Endpoints and selectors do not change.
