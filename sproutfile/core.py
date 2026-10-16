"""The small Sproutfile runtime. Manifests are data, never executable code."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from typing import Any, Callable

FORMAT = "sprout/0.1"
MAX_BYTES = 2_000_000
MAX_BLOCKS = 100
STATE_ID = "sprout-state"
RESERVED = ".sprout-grants.json"


class SproutError(ValueError):
    """An actionable refusal. The last valid snapshot is preserved."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SproutError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(text: str) -> Any:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SproutError("File exceeds the 2 MB experimental limit")
    try:
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(SproutError("Non-finite number")))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise SproutError("Invalid JSON") from exc


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SproutError("Expected finite JSON data") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pointer(value: Any, path: str = "") -> Any:
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise SproutError("References use JSON pointers, e.g. /forecast/rain")
    try:
        for raw in path.split("/")[1:] if path else []:
            if re.search(r"~(?![01])", raw):
                raise SproutError("Invalid JSON pointer escape")
            key = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise SproutError("Invalid array index")
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise SproutError("Pointer crosses a scalar")
        return copy.deepcopy(value)
    except (KeyError, IndexError, ValueError) as exc:
        raise SproutError(f"Source no longer has pointer {path!r}") from exc


def safe_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise SproutError("Paths must be relative, with forward slashes")
    path = Path(relative)
    if path.is_absolute() or any(part in ("..", ".") for part in path.parts):
        raise SproutError("Paths must stay inside the chosen folder")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise SproutError("Symlinks and junctions are not supported")
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise SproutError("Path escaped the chosen folder")
    if path.name in (RESERVED, ".sprout.lock"):
        raise SproutError("Runtime control files cannot be document sources or outputs")
    return resolved


def read_bytes(path: Path) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise SproutError(f"Missing, non-regular or oversized file: {path.name}")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SproutError("File exceeds the 2 MB experimental limit")
        return data
    except OSError as exc:
        raise SproutError(f"Cannot read {path.name}") from exc


class _StateParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside = False
        self.count = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == STATE_ID:
            if attributes.get("type") != "application/json":
                raise SproutError("Sprout state must be inert JSON")
            self.count += 1
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def load(data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SproutError("Sproutfiles must be UTF-8") from exc
    parser = _StateParser()
    parser.feed(text)
    if parser.count != 1:
        raise SproutError("Expected one embedded Sprout state")
    document = decode("".join(parser.parts))
    if not isinstance(document, dict) or set(document) != {"format", "manifest", "state"}:
        raise SproutError("Invalid Sprout document")
    if document["format"] != FORMAT:
        raise SproutError("Unsupported Sprout version")
    validate_manifest(document["manifest"])
    if not isinstance(document["state"], dict):
        raise SproutError("Invalid document state")
    # A manual HTML edit must not be silently overwritten by regeneration.
    if render(document) != data:
        raise SproutError("Generated HTML was edited; preserve your edits and recreate from the spec")
    return document


def references(block: dict) -> dict[str, dict]:
    kind = block["kind"]
    if kind in ("value", "table"):
        return {"value": block["ref"]}
    if kind == "choose":
        return {"condition": block["condition"]["ref"]}
    return block.get("inputs", {})


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or set(manifest) != {"title", "goal", "sources", "blocks"}:
        raise SproutError("Manifest requires exactly title, goal, sources and blocks")
    if any(not isinstance(manifest[k], str) or not manifest[k] or len(manifest[k]) > 2000
           for k in ("title", "goal")):
        raise SproutError("Title and goal must be short nonempty strings")
    if not isinstance(manifest["sources"], dict) or len(manifest["sources"]) > 50:
        raise SproutError("Expected at most 50 named sources")
    if not isinstance(manifest["blocks"], list) or not 1 <= len(manifest["blocks"]) <= MAX_BLOCKS:
        raise SproutError("Expected 1 to 100 blocks")
    for alias, path in manifest["sources"].items():
        if not isinstance(alias, str) or not isinstance(path, str) or not path.endswith((".json", ".sprout.html")):
            raise SproutError("Sources must be named JSON files or Sproutfiles")
    seen = set()
    allowed = {
        "value": {"id", "kind", "label", "ref"},
        "table": {"id", "kind", "label", "ref", "columns"},
        "choose": {"id", "kind", "label", "condition", "then", "else"},
        "template": {"id", "kind", "label", "text", "inputs"},
        "agent": {"id", "kind", "label", "prompt", "inputs", "max_length"},
    }
    for block in manifest["blocks"]:
        if not isinstance(block, dict) or block.get("kind") not in allowed:
            raise SproutError("Unknown block kind")
        kind = block["kind"]
        if set(block) != allowed[kind]:
            raise SproutError(f"Unexpected or missing fields in {kind} block")
        identifier = block["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier) or identifier in seen:
            raise SproutError("Block IDs must be unique lowercase names")
        if not isinstance(block["label"], str) or len(block["label"]) > 200:
            raise SproutError("Expected a short block label")
        if kind in ("template", "agent"):
            field = "text" if kind == "template" else "prompt"
            if not isinstance(block[field], str) or len(block[field]) > 10000:
                raise SproutError("Block text is too long")
        if kind == "agent" and (type(block["max_length"]) is not int or not 1 <= block["max_length"] <= 10000):
            raise SproutError("Agent max_length must be between 1 and 10000")
        if kind == "table" and (not isinstance(block["columns"], list) or not block["columns"]
                               or any(not isinstance(c, str) for c in block["columns"])):
            raise SproutError("Table columns must be strings")
        if kind == "choose":
            condition = block["condition"]
            if not isinstance(condition, dict) or set(condition) != {"ref", "op", "value"} or condition["op"] not in ("eq", "gte", "lte"):
                raise SproutError("Invalid choose condition")
        refs = references(block)
        if not isinstance(refs, dict):
            raise SproutError("Inputs must be a named reference map")
        for name, ref in refs.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise SproutError("Input names must be simple identifiers")
            if not isinstance(ref, dict) or set(ref) not in ({"source", "pointer"}, {"block", "pointer"}):
                raise SproutError("Each reference names a source or an earlier block and a pointer")
            if not isinstance(ref["pointer"], str) or (ref["pointer"] and not ref["pointer"].startswith("/")):
                raise SproutError("Invalid reference pointer")
            if "source" in ref and ref["source"] not in manifest["sources"]:
                raise SproutError("Reference names an undeclared source")
            if "block" in ref and ref["block"] not in seen:
                raise SproutError("Internal references must name an earlier block")
        seen.add(identifier)
    canonical(manifest)


def _display(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)


def render(document: dict) -> bytes:
    # The embedded JSON is canonical, so the visible view must use the same order.
    document = decode(canonical(document))
    manifest, state = document["manifest"], document["state"]
    esc = lambda x: html.escape(str(x), quote=True)
    sections = []
    for spec in manifest["blocks"]:
        block = state.get("blocks", {}).get(spec["id"])
        if block is None:
            body = '<p class="pending">Waiting to grow. Run sprout refresh.</p>'
        elif spec["kind"] == "table":
            columns, rows = block["value"]["columns"], block["value"]["rows"]
            body = "<table><thead><tr>" + "".join(f"<th>{esc(c)}</th>" for c in columns) + "</tr></thead><tbody>"
            body += "".join("<tr>" + "".join(f"<td>{esc(_display(row[c]))}</td>" for c in columns) + "</tr>" for row in rows)
            body += "</tbody></table>"
        else:
            body = f'<p class="value">{esc(_display(block["value"]))}</p>'
        if block:
            evidence = [{"input": name, "ref": ref, "hash": block["input_hashes"][name]}
                        for name, ref in references(spec).items()]
            body += f'<details><summary>Why is this here?</summary><pre>{esc(json.dumps(evidence, indent=2))}</pre>'
            body += f'<p class="muted">Last changed {esc(block["updated"])}</p></details>'
        sections.append(f'<section><div class="eyebrow">{esc(spec["kind"])} / {esc(spec["id"])}</div><h2>{esc(spec["label"])}</h2>{body}</section>')
    history = state.get("history", [])
    entries = "".join(f'<li><time>{esc(e["time"])}</time> {esc(e["reason"])}<details><summary>Inspect the change</summary><pre>{esc(json.dumps(e["changes"], ensure_ascii=False, indent=2))}</pre></details></li>' for e in reversed(history))
    packed = canonical(document).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{esc(manifest['title'])} · Sproutfile</title>
<style>
:root{{color-scheme:light;--ink:#173f35;--paper:#f3f2e9;--line:#d3dbce;--green:#2c6651}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:17px/1.6 system-ui,sans-serif}}
main{{max-width:1000px;margin:auto;padding:56px 28px 80px}}header{{border-bottom:2px solid var(--ink);padding-bottom:36px}}
.brand,.eyebrow{{font:12px/1.6 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.14em}}.brand{{display:flex;justify-content:space-between;gap:20px}}
h1{{font:clamp(42px,7vw,78px)/1.05 Georgia,serif;letter-spacing:-.04em;margin:32px 0 20px}}h2{{font:29px/1.2 Georgia,serif;margin:8px 0 18px}}
.goal{{max-width:650px;font-size:20px}}.muted,time,.pending{{color:#587368;font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,350px),1fr));gap:20px;margin:30px 0}}
section{{background:#fffef8;border:1px solid var(--line);border-radius:12px;padding:26px;min-width:0}}.value{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:19px}}
details{{border-top:1px solid var(--line);padding-top:12px;margin-top:18px}}summary{{cursor:pointer;font-size:13px;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace;background:#eaf0e6;padding:16px;border-radius:6px}}
table{{width:100%;border-collapse:collapse;font-size:14px;overflow-wrap:anywhere}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px 4px}}ol{{padding-left:20px}}li{{padding:12px 0}}time{{display:block}}footer{{border-top:1px solid var(--line);padding-top:20px;margin-top:36px;font-size:13px}}
</style></head><body><main>
<header><div class="brand"><span>✳ sproutfile / a small living file</span><span>snapshot {esc(state.get('revision', 0)):s}</span></div>
<h1>{esc(manifest['title'])}</h1><p class="goal">{esc(manifest['goal'])}</p>
<p class="muted">Last refreshed: {esc(state.get('updated', 'not yet'))}. This is a snapshot; updates require the runtime or an agent. No code runs when you open this file.</p></header>
<div class="grid">{''.join(sections)}</div>
<details><summary>What changed? ({len(history)} retained updates)</summary><ol>{entries or '<li>No updates yet.</li>'}</ol></details>
<details><summary>Purpose, sources & continuation recipe</summary><pre>{esc(json.dumps(manifest, ensure_ascii=False, indent=2))}</pre>
<p>To continue this file: inspect its recipe, trust only the local sources you intend, then run sprout refresh. Agent blocks accept source-bound proposals through sprout jobs / sprout submit.</p></details>
<footer>A readable file with a future. Source hashes and recipes travel with it; local permissions do not. Sproutfile 0.1 · experimental</footer>
</main><script id="sprout-state" type="application/json">{packed}</script></body></html>\n'''
    result = page.encode("utf-8")
    if len(result) > MAX_BYTES:
        raise SproutError("Rendered document exceeds 2 MB; reduce data or history")
    return result


def create(manifest: dict, target: Path) -> dict:
    validate_manifest(manifest)
    if not target.name.endswith(".sprout.html"):
        raise SproutError("Output must end with .sprout.html")
    document = {"format": FORMAT, "manifest": copy.deepcopy(manifest),
                "state": {"blocks": {}, "history": [], "revision": 0}}
    data = render(document)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise SproutError("Output exists; create never overwrites a file") from exc
    return document


def atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".sprout-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _trust(root: Path, relative: str) -> dict:
    path = safe_path(root, relative)
    document = load(read_bytes(path))
    for source in document["manifest"]["sources"].values():
        safe_path(root, source)
    grants_path = root.resolve() / RESERVED
    if grants_path.is_symlink():
        raise SproutError("Grant store must not be a symlink")
    grants = decode(read_bytes(grants_path).decode("utf-8")) if grants_path.exists() else {"root": str(root.resolve()), "files": {}}
    if grants.get("root") != str(root.resolve()):
        raise SproutError("Permissions do not travel: remove the copied grant store and trust locally")
    # Imported caches are never accepted merely because their recipe is trusted.
    grants["files"][relative] = {"manifest_hash": digest(document["manifest"]), "cache_hash": None}
    atomic_write(grants_path, (canonical(grants) + "\n").encode("utf-8"))
    return {"trusted": relative, "sources": document["manifest"]["sources"], "manifest_hash": digest(document["manifest"])}


class Runtime:
    """One bounded refresh. Sources and destinations are pinned before writes."""

    def __init__(self, root: Path, generator: Callable | None = None):
        self.root = root.resolve()
        self.generator = generator
        self.originals: dict[Path, bytes] = {}
        self.virtual: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.active: set[str] = set()
        self.grants = None
        self.jobs: list[dict] = []

    def _read(self, path: Path) -> bytes:
        if path not in self.originals:
            self.originals[path] = read_bytes(path)
        return self.originals[path]

    def _authorized(self, relative: str, document: dict):
        if self.grants is None:
            path = self.root / RESERVED
            if path.is_symlink():
                raise SproutError("Grant store must not be a symlink")
            self.grants = decode(self._read(path).decode("utf-8"))
        if self.grants.get("root") != str(self.root):
            raise SproutError("This folder needs local trust")
        grant = self.grants.get("files", {}).get(relative, {})
        if not isinstance(grant, dict) or grant.get("manifest_hash") != digest(document["manifest"]):
            raise SproutError(f"Recipe is not trusted locally: {relative}; inspect it, then run sprout trust")
        return grant.get("cache_hash") != digest(document["state"])

    def _source(self, relative: str) -> Any:
        path = safe_path(self.root, relative)
        if relative.endswith(".sprout.html"):
            self.refresh(relative)
            return self.virtual[relative]["state"]
        return decode(self._read(path).decode("utf-8"))

    def refresh(self, relative: str) -> dict:
        if relative in self.results:
            return self.results[relative]
        if relative in self.active:
            raise SproutError("Living files form a cycle; no files were written")
        self.active.add(relative)
        path = safe_path(self.root, relative)
        old = load(self._read(path))
        force = self._authorized(relative, old)
        document = copy.deepcopy(old)
        manifest, state = document["manifest"], document["state"]
        sources = {alias: self._source(name) for alias, name in manifest["sources"].items()}
        changes, pending, touched = {}, [], []
        timestamp = now()
        for spec in manifest["blocks"]:
            identifier = spec["id"]
            refs = references(spec)
            inputs = {}
            for name, ref in refs.items():
                if "source" in ref:
                    inputs[name] = pointer(sources[ref["source"]], ref["pointer"])
                else:
                    upstream = state["blocks"].get(ref["block"])
                    if not upstream or ref["block"] in pending:
                        raise SproutError("A dependent block is waiting for an agent")
                    inputs[name] = pointer(upstream["value"], ref["pointer"])
            signature = digest({"recipe": spec, "inputs": inputs})
            previous = state["blocks"].get(identifier)
            if not force and previous and previous["signature"] == signature:
                continue
            if spec["kind"] == "agent":
                job = {"file": relative, "block": identifier, "input_hash": signature,
                       "goal": manifest["goal"], "prompt": spec["prompt"], "inputs": inputs,
                       "max_length": spec["max_length"],
                       "response_format": {"text": "your prose", "quotes": {"input_name": "exact nonempty substring from that input's JSON representation"}}}
                self.jobs.append(job)
                if self.generator is None:
                    pending.append(identifier)
                    continue
                proposal = self.generator(copy.deepcopy(job))
                value = validate_proposal(job, proposal)
            else:
                value = evaluate(spec, inputs)
            canonical(value)
            state["blocks"][identifier] = {"value": value, "signature": signature,
                                            "input_hashes": {k: digest(v) for k, v in inputs.items()},
                                            "updated": timestamp}
            if spec["kind"] == "agent":
                state["blocks"][identifier]["quotes"] = proposal["quotes"]
            touched.append(identifier)
            before = previous["value"] if previous else None
            if previous is None or canonical(before) != canonical(value):
                changes[identifier] = {"before": before, "after": value}
        # A file is the unit of publication: never publish half of its new blocks.
        if pending:
            self.active.remove(relative)
            raise SproutError(f"{relative}: waiting for an agent on {', '.join(pending)}; use sprout jobs")
        if touched:
            state["revision"] += 1
            state["updated"] = timestamp
            entry = {"time": timestamp, "reason": "Source-bound refresh: " + ", ".join(touched), "changes": changes}
            state["history"] = (state["history"] + [entry])[-20:]
        self.virtual[relative] = document
        result = {"file": relative, "status": "changed" if touched else "unchanged", "blocks": touched,
                  "revision": state["revision"], "changes": changes}
        self.results[relative] = result
        self.active.remove(relative)
        return result

    def commit(self) -> list[dict]:
        prepared = {relative: render(document) for relative, document in self.virtual.items()
                    if self.results[relative]["status"] == "changed"}
        # Optimistic checks catch changes while planning, including changed trust.
        # The root lock serializes cooperating Sprout processes, not external editors.
        for path, expected in self.originals.items():
            if read_bytes(path) != expected:
                raise SproutError(f"{path.name} changed during planning; refresh again")
        for relative, document in self.virtual.items():
            if self.results[relative]["status"] == "changed":
                path = safe_path(self.root, relative)
                if read_bytes(path) != self.originals[path]:
                    raise SproutError("Destination changed before commit")
                atomic_write(path, prepared[relative])
            self.grants["files"][relative]["cache_hash"] = digest(document["state"])
        if prepared:
            atomic_write(self.root / RESERVED, (canonical(self.grants) + "\n").encode("utf-8"))
        return list(self.results.values())


def evaluate(spec: dict, inputs: dict) -> Any:
    kind = spec["kind"]
    if kind == "value":
        return inputs["value"]
    if kind == "template":
        try:
            return Template(spec["text"]).substitute({k: _display(v) for k, v in inputs.items()})
        except (KeyError, ValueError) as exc:
            raise SproutError("Template placeholder is not a declared input") from exc
    if kind == "table":
        rows = inputs["value"]
        if not isinstance(rows, list) or len(rows) > 1000:
            raise SproutError("Table source must contain at most 1000 rows")
        if any(not isinstance(row, dict) or any(c not in row for c in spec["columns"]) for row in rows):
            raise SproutError("Table source lost a required column")
        return {"columns": spec["columns"], "rows": [{c: row[c] for c in spec["columns"]} for row in rows]}
    if kind == "choose":
        left, right, op = inputs["condition"], spec["condition"]["value"], spec["condition"]["op"]
        if op == "eq":
            condition = canonical(left) == canonical(right)
        else:
            if type(left) not in (int, float) or type(right) not in (int, float) or not math.isfinite(left) or not math.isfinite(right):
                raise SproutError("Numeric comparisons require finite numbers, never booleans")
            condition = left >= right if op == "gte" else left <= right
        return copy.deepcopy(spec["then"] if condition else spec["else"])
    raise SproutError("Unsupported block")


def validate_proposal(job: dict, proposal: dict) -> str:
    if not isinstance(proposal, dict) or set(proposal) != {"text", "quotes"}:
        raise SproutError("Agent proposal requires exactly text and quotes")
    text, quotes = proposal["text"], proposal["quotes"]
    if not isinstance(text, str) or not text.strip() or len(text) > job["max_length"]:
        raise SproutError("Agent text is empty or too long")
    if not isinstance(quotes, dict) or set(quotes) != set(job["inputs"]):
        raise SproutError("Agent must provide an exact quote for every declared input")
    for name, quote in quotes.items():
        if not isinstance(quote, str) or not quote.strip() or quote not in _display(job["inputs"][name]):
            raise SproutError(f"Agent quote does not match input {name}")
    # This checks source binding and quotation. It does NOT verify every prose claim.
    return text


class FolderLock:
    def __init__(self, root: Path):
        self.path = root.resolve() / ".sprout.lock"

    def __enter__(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(str(os.getpid()))
        except FileExistsError as exc:
            raise SproutError("Another refresh holds .sprout.lock; after a crash, verify it stopped before removing the lock") from exc
        return self

    def __exit__(self, *_):
        self.path.unlink()


def run(root: Path, files: list[str], *, apply: bool = False, generator: Callable | None = None) -> list[dict]:
    with FolderLock(root):
        runtime = Runtime(root, generator)
        for relative in files:
            runtime.refresh(relative)
        return runtime.commit() if apply else list(runtime.results.values())


def trust(root: Path, relative: str) -> dict:
    with FolderLock(root):
        return _trust(root, relative)
