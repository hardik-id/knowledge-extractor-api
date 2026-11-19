# Extraction

What turns a document into records is replaceable, and running it again never undoes a person's work. The pieces are in `apps/extraction`.

## The extractor interface

`extractors/base.py`. An extractor takes the text of a document, a `Definition` (a definition version as plain data: `version`, `prompt`, `record_types`) and the example records (accepted records marked `use_as_example`), and returns raw records: a `RawRecord` has its record type id, its span and, per field, `RawValue`s with the quotes they came from. A field that was not found is one value that is `None` with no spans. Nothing in the interface touches the database or the network.

Spans are `{start, end, quote}` and offsets count code points (Python `str` indexing, `end` exclusive).

## Choosing one

`EXTRACTOR` selects the implementation through `get_extractor()`: `scripted`, or the dotted path of a class (how tests swap in a fake). Any other value stops the app at start. An extractor that calls a model, or a bridge to the existing extraction service, comes later behind the same interface.

## The scripted extractor

`extractors/scripted.py`, a port of the UI's `src/services/mock/mock-extractor.ts`; no model, the same answer every time.

- A record is a `## ` heading that starts with the record type's name (case does not matter), down to the next `## ` heading.
- A field comes from the heading (a `title` field: the text after `ADR-012: `), from a `**Label:** value` line or from a `### Label` section (down to the next heading). The label matches the field's name or key, ignoring case, `_`, `-` and runs of spaces; a `decided_on` field also matches `Date`.
- A `multiple` field on a `**Label:**` line gives one value per comma-separated item.
- A `quote` field carries the exact text and its span. An `inferred` field carries the evidence span and a tidied value: the first matching choice for a `choice` field, an ISO date for a `date` field (`3 November 2026`, `November 3, 2026`, `2026-11-03`).

The port was checked against the TypeScript: both give the same records for the sample documents, for hand-made edge cases and for 300 generated documents.

## From raw to stored records

`extractors/records.py`, `stored_records(text, raw_records)`. For one file it checks every span against the text, anchors a quote whose offsets do not fit (`spans.resolve_span`), keeps a quote that is not in the text with `anchored: false`, and marks every record and value `llm` and `suggested`. A record whose own span cannot be placed is kept without a span. It returns plain `StoredRecord` and `StoredValue` objects; writing them is the caller's job.

## The merge rule

`merge.py`, a port of `src/services/mock/extraction-merge.ts`. `merge_extracted_records(previous, fresh)`:

- keeps every record a person touched: human origin, or reviewed (not `suggested`), or with a value that has a human origin or was reviewed;
- drops the untouched suggestions of the earlier run;
- drops a fresh record whose span overlaps a kept record of the same record type (spans that only touch do not overlap); a record without a span blocks nothing;
- orders by span start, records without a span last, otherwise in the order given.

It works on stored `ExtractionRecord`s (with their values prefetched) as well as on `StoredRecord`s.
