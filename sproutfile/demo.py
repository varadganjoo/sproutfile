"""A real deterministic refresh, not prerecorded model output."""

from pathlib import Path

from .core import SproutError, canonical, create, run, trust


def source(alias, path):
    return {"source": alias, "pointer": path}


def recipe(title, goal, sources, blocks):
    return {"title": title, "goal": goal, "sources": sources, "blocks": blocks}


def demo(folder: Path) -> dict:
    if folder.exists():
        raise SproutError("sprout-demo already exists; use a fresh --root to preserve the previous demo")
    folder.mkdir(parents=True)
    weather = folder / "weather.json"
    weather.write_text(canonical({"rain_chance": 0.1, "temperature_c": 22, "station_note": "synthetic demo data"}) + "\n", encoding="utf-8")
    (folder / "friends.json").write_text(canonical({"people": [
        {"name": "Mina", "bringing": "bread"}, {"name": "Theo", "bringing": "soup"},
        {"name": "Jo", "bringing": "a suspiciously large spoon"}]}), encoding="utf-8")
    plan = recipe("The extremely serious picnic", "Keep one readable plan consistent with the weather. All data is fictional.",
                  {"weather": "weather.json", "friends": "friends.json"}, [
        {"id": "place", "kind": "choose", "label": "Where are we going?",
         "condition": {"ref": source("weather", "/rain_chance"), "op": "gte", "value": 0.5},
         "then": "Moss Library (indoors)", "else": "Fern Park (outdoors)"},
        {"id": "rain", "kind": "value", "label": "Chance of rain", "ref": source("weather", "/rain_chance")},
        {"id": "people", "kind": "table", "label": "The expedition", "ref": source("friends", "/people"),
         "columns": ["name", "bringing"]},
    ])
    packing = recipe("Things the bag should know", "Keep the packing list consistent with the plan.",
                     {"plan": "picnic.sprout.html"}, [
        {"id": "kit", "kind": "choose", "label": "Packing list",
         "condition": {"ref": source("plan", "/blocks/place/value"), "op": "eq", "value": "Fern Park (outdoors)"},
         "then": "Blanket, sunscreen, cups, and the suspicious spoon.",
         "else": "Board games, mugs, and the suspicious spoon. Leave the blanket at home."},
    ])
    invite = recipe("An invitation that can change its mind", "Keep a draft invitation consistent with the venue and packing list. Never send it.",
                    {"plan": "picnic.sprout.html", "packing": "packing.sprout.html"}, [
        {"id": "message", "kind": "template", "label": "Draft, not sent",
         "text": "Tiny expedition update: meet at ${place}. Bring: ${kit} See you Saturday!",
         "inputs": {"place": source("plan", "/blocks/place/value"), "kit": source("packing", "/blocks/kit/value")}},
    ])
    for name, spec in (("picnic", plan), ("packing", packing), ("invitation", invite)):
        create(spec, folder / f"{name}.sprout.html")
        trust(folder, f"{name}.sprout.html")
    first = run(folder, ["invitation.sprout.html"], apply=True)
    (folder / "before").mkdir()
    for name in ("picnic", "packing", "invitation"):
        (folder / "before" / f"{name}.sprout.html").write_bytes((folder / f"{name}.sprout.html").read_bytes())
    weather.write_text(canonical({"rain_chance": 0.9, "temperature_c": 22, "station_note": "synthetic demo data"}) + "\n", encoding="utf-8")
    changed = run(folder, ["invitation.sprout.html"], apply=True)
    # Change a field no block reads. No document or model work should be needed.
    weather.write_text(canonical({"rain_chance": 0.9, "temperature_c": 22, "station_note": "unrelated observation changed"}) + "\n", encoding="utf-8")
    unrelated = run(folder, ["invitation.sprout.html"], apply=True)
    if not all(row["status"] == "unchanged" for row in unrelated):
        raise AssertionError("Unrelated source edits must not rebuild the documents")
    report = {"folder": str(folder.resolve()), "model_calls": 0, "network_calls": 0,
              "data": "synthetic", "initial_growth": first, "weather_change": changed,
              "irrelevant_change": unrelated,
              "open": str((folder / "invitation.sprout.html").resolve())}
    (folder / "demo-result.json").write_text(canonical(report) + "\n", encoding="utf-8")
    return report
