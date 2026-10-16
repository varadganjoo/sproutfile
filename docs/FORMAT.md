# Sprout format 0.1

A UTF-8 `.sprout.html` contains a readable snapshot and exactly one inert `<script id="sprout-state" type="application/json">` payload. The payload has `format: "sprout/0.1"`, `manifest`, and `state`. It contains no runnable JavaScript. The runtime regenerates the complete HTML and refuses a manually modified view rather than silently overwriting it. Preserve edits and create a new artifact from an updated spec.

The manifest has exactly `title`, `goal`, `sources`, and `blocks`. This complete recipe needs only a local `weather.json` containing `{"rain_chance": 0.1}`:

```json
{
  "title": "A very small picnic",
  "goal": "Keep the venue consistent with the supplied forecast.",
  "sources": {"weather": "weather.json"},
  "blocks": [
    {
      "id": "place",
      "kind": "choose",
      "label": "Where?",
      "condition": {
        "ref": {"source": "weather", "pointer": "/rain_chance"},
        "op": "gte",
        "value": 0.5
      },
      "then": "Moss Library (indoors)",
      "else": "Fern Park (outdoors)"
    }
  ]
}
```

Save it as `picnic.spec.json`, then run from the folder containing both JSON files:

```sh
python -m sproutfile create picnic.spec.json picnic.sprout.html
python -m sproutfile trust picnic.sprout.html
python -m sproutfile plan picnic.sprout.html
python -m sproutfile refresh picnic.sprout.html
```

When using a different folder, place `--root FOLDER` before the command. Spec and proposal arguments are normal paths relative to the shell's current directory. Artifact and source paths are relative to `--root`.

## References and block types

Every block has `id`, `kind`, and `label`. IDs are unique lowercase names. Source references are `{"source":"alias","pointer":"/some/key"}`. Internal references are `{"block":"earlier_id","pointer":""}` and can only point to an earlier block. Pointers follow JSON Pointer escaping (`~0` for `~`, `~1` for `/`). An empty pointer selects the entire value.

| Kind | Additional fields | Result |
| --- | --- | --- |
| `value` | `ref` | Selected JSON value |
| `table` | `ref`, `columns` | Selected row fields, rendered as a table |
| `choose` | `condition`, `then`, `else` | A declared branch value |
| `template` | `text`, `inputs` | Python `string.Template` substitution, such as `${place}` |
| `agent` | `prompt`, `inputs`, `max_length` | Source-bound prose proposal |

`inputs` maps simple names to references. `condition` has exactly `ref`, `op`, and `value`; operations are `eq`, `gte`, and `lte`. Equality compares canonical JSON (so `1` and `1.0` differ). Numeric comparisons accept finite numbers and reject booleans. Tables support up to 1,000 rows.

For a Sproutfile source, the pointer addresses its **state**. For example, `/blocks/place/value` reads the latest venue from another file. The runtime refreshes producer files before consumers. Cycles are refused.

## Invalidation and publication

Each block signature is SHA-256 of its canonical recipe and selected input values. Changes to an unselected field do not rebuild a block. A changed input can cause evaluation even if the resulting output is identical; it updates the evidence and revision. Imported or tampered state is recomputed against locally trusted recipes.

State records block values, signatures, per-input hashes, timestamps, agent quotations, a revision, and up to 20 update records. History records changed values; it is not a complete source archive or a rollback facility. The document contains source **paths and hashes**, not necessarily every original source value.

No file is published with an unresolved agent block. A plan validates without publishing document changes. All sources and destinations read during planning are compared with their original bytes before commit. Writes use atomic replacement per file. There is no all-or-nothing guarantee across files or external processes.

Experimental bounds: 2 MB per input or rendered artifact, at most 50 sources and 100 blocks per file. Unknown manifest/block fields and duplicate JSON keys are refused. Paths stay inside the chosen folder; absolute paths, traversal, symlinks, and junctions are unsupported. Grants are a local sidecar, never embedded permissions.
