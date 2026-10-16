import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sproutfile.cli import main
from sproutfile.core import (FolderLock, Runtime, SproutError, canonical, create,
                            decode, load, pointer, render, run, safe_path, trust)
from sproutfile.demo import demo, recipe, source


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        scratch = (Path(__file__).resolve().parents[1] / ".qa" / "tests").resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        def cleanup():
            if not self.root.resolve().is_relative_to(scratch):
                raise RuntimeError("Test cleanup escaped its workspace")
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.write("data.json", {"name": "Mina", "rain": 0.1, "unrelated": 1})

    def write(self, name, value):
        (self.root / name).write_text(canonical(value), encoding="utf-8")

    def make(self, name="note", blocks=None, sources=None, grant=True):
        if blocks is None:
            blocks = [{"id": "name", "kind": "value", "label": "Name", "ref": source("data", "/name")}]
        spec = recipe("A small file", "Stay consistent with the selected source.", sources or {"data": "data.json"}, blocks)
        target = f"{name}.sprout.html"
        create(spec, self.root / target)
        if grant:
            trust(self.root, target)
        return target

    def test_refresh_and_irrelevant_edit_does_no_work(self):
        target = self.make()
        self.assertEqual(run(self.root, [target], apply=True)[0]["status"], "changed")
        before = (self.root / target).read_bytes()
        self.write("data.json", {"name": "Mina", "rain": 0.8, "unrelated": 99})
        self.assertEqual(run(self.root, [target], apply=True)[0]["status"], "unchanged")
        self.assertEqual(before, (self.root / target).read_bytes())

    def test_preview_preserves_outputs_and_grants(self):
        target = self.make()
        originals = {p.name: p.read_bytes() for p in self.root.iterdir()}
        run(self.root, [target])
        self.assertEqual(originals, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_dependency_closure_and_selective_cascade(self):
        report = demo(self.root / "world")
        self.assertEqual(len(report["weather_change"]), 3)
        self.assertEqual(report["weather_change"][0]["blocks"], ["place", "rain"])
        self.assertTrue(all(r["status"] == "unchanged" for r in report["irrelevant_change"]))
        self.assertEqual(report["model_calls"], 0)

    def test_dormant_file_roundtrips_and_carries_history(self):
        target = self.make()
        run(self.root, [target], apply=True)
        data = (self.root / target).read_bytes()
        document = load(data)
        self.assertEqual(render(document), data)
        self.assertEqual(document["state"]["history"][0]["changes"]["name"]["after"], "Mina")

    def test_missing_source_never_changes_last_snapshot(self):
        target = self.make()
        run(self.root, [target], apply=True)
        before = (self.root / target).read_bytes()
        (self.root / "data.json").unlink()
        with self.assertRaises(SproutError):
            run(self.root, [target], apply=True)
        self.assertEqual(before, (self.root / target).read_bytes())

    def test_source_change_during_planning_is_rejected(self):
        target = self.make()
        runtime = Runtime(self.root)
        runtime.refresh(target)
        self.write("data.json", {"name": "Jo"})
        before = (self.root / target).read_bytes()
        with self.assertRaisesRegex(SproutError, "changed during planning"):
            runtime.commit()
        self.assertEqual(before, (self.root / target).read_bytes())

    def test_manual_html_edit_is_not_overwritten(self):
        target = self.make()
        path = self.root / target
        path.write_bytes(path.read_bytes().replace(b"A small file", b"My manual edit", 1))
        before = path.read_bytes()
        with self.assertRaisesRegex(SproutError, "HTML was edited"):
            run(self.root, [target], apply=True)
        self.assertEqual(before, path.read_bytes())

    def test_untrusted_recipe_and_recipe_changes_are_rejected(self):
        target = self.make(grant=False)
        with self.assertRaises(SproutError):
            run(self.root, [target], apply=True)
        trust(self.root, target)
        document = load((self.root / target).read_bytes())
        document["manifest"]["goal"] = "A different task"
        (self.root / target).write_bytes(render(document))
        with self.assertRaisesRegex(SproutError, "not trusted"):
            run(self.root, [target], apply=True)

    def test_foreign_or_tampered_cache_is_recomputed(self):
        target = self.make()
        run(self.root, [target], apply=True)
        document = load((self.root / target).read_bytes())
        document["state"]["blocks"]["name"]["value"] = "forged"
        (self.root / target).write_bytes(render(document))
        run(self.root, [target], apply=True)
        self.assertEqual(load((self.root / target).read_bytes())["state"]["blocks"]["name"]["value"], "Mina")

    def test_permissions_do_not_travel_with_copied_folder(self):
        target = self.make()
        run(self.root, [target], apply=True)
        destination = self.root / "copy"
        destination.mkdir()
        for name in (target, "data.json", ".sprout-grants.json"):
            shutil.copyfile(self.root / name, destination / name)
        with self.assertRaisesRegex(SproutError, "local trust"):
            run(destination, [target], apply=True)
        (destination / ".sprout-grants.json").unlink()
        trust(destination, target)
        run(destination, [target], apply=True)
        self.assertEqual(load((destination / target).read_bytes())["state"]["blocks"]["name"]["value"], "Mina")

    def test_cycle_is_rejected_before_any_write(self):
        a = self.make("a", sources={"data": "b.sprout.html"})
        b = self.make("b", sources={"data": "a.sprout.html"})
        originals = [(self.root / p).read_bytes() for p in (a, b)]
        with self.assertRaisesRegex(SproutError, "cycle"):
            run(self.root, [a], apply=True)
        self.assertEqual(originals, [(self.root / p).read_bytes() for p in (a, b)])

    def test_numeric_rules_reject_booleans(self):
        target = self.make(blocks=[{"id": "place", "kind": "choose", "label": "Place",
            "condition": {"ref": source("data", "/rain"), "op": "gte", "value": 0.5}, "then": "inside", "else": "outside"}])
        self.write("data.json", {"name": "Mina", "rain": True})
        with self.assertRaisesRegex(SproutError, "never booleans"):
            run(self.root, [target], apply=True)

    def test_paths_cannot_escape_or_read_control_files(self):
        for name in ("../secret.json", "C:/secret.json", "data\\secret.json", ".sprout-grants.json", ".sprout.lock"):
            with self.subTest(name=name), self.assertRaises(SproutError):
                safe_path(self.root, name)

    def test_symlink_sources_rejected_when_supported(self):
        link = self.root / "link.json"
        try:
            link.symlink_to(self.root / "data.json")
        except OSError:
            self.skipTest("Creating symlinks requires a host permission")
        with self.assertRaisesRegex(SproutError, "Symlinks"):
            safe_path(self.root, "link.json")

    def test_source_text_is_inert_in_view_and_metadata(self):
        payload = '</script><script>alert("hello")</script><img src=x onerror=alert(1)>'
        self.write("data.json", {"name": payload})
        target = self.make()
        run(self.root, [target], apply=True)
        text = (self.root / target).read_text(encoding="utf-8")
        self.assertNotIn(payload, text)
        self.assertIn("&lt;img", text)
        self.assertEqual(load(text.encode("utf-8"))["state"]["blocks"]["name"]["value"], payload)

    def test_json_rejects_duplicate_keys_and_nonfinite(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(SproutError):
                decode(text)

    def test_pointer_escaping_and_array_bounds(self):
        self.assertEqual(pointer({"a/b": {"~": [3]}}, "/a~1b/~0/0"), 3)
        for path in ("/a~2b", "/x/-1", "/x/01", "/x/9"):
            with self.assertRaises(SproutError):
                pointer({"x": [1]}, path)

    def agent(self):
        return self.make(blocks=[{"id": "summary", "kind": "agent", "label": "A living summary",
            "prompt": "Describe the name without inventing anything.", "inputs": {"name": source("data", "/name")}, "max_length": 100}])

    def test_agent_generation_is_cached_by_selected_input(self):
        target = self.agent()
        calls = []
        def generate(job):
            calls.append(job)
            return {"text": "The name is " + job["inputs"]["name"], "quotes": {"name": job["inputs"]["name"]}}
        run(self.root, [target], apply=True, generator=generate)
        self.write("data.json", {"name": "Mina", "unrelated": 7})
        run(self.root, [target], apply=True, generator=generate)
        self.assertEqual(len(calls), 1)
        self.write("data.json", {"name": "Theo"})
        run(self.root, [target], apply=True, generator=generate)
        self.assertEqual(len(calls), 2)

    def test_no_model_means_pending_not_fake_output(self):
        target = self.agent()
        before = (self.root / target).read_bytes()
        with self.assertRaisesRegex(SproutError, "waiting for an agent"):
            run(self.root, [target], apply=True)
        self.assertEqual(before, (self.root / target).read_bytes())

    def test_fabricated_quote_prevents_publication(self):
        target = self.agent()
        before = (self.root / target).read_bytes()
        with self.assertRaisesRegex(SproutError, "quote does not match"):
            run(self.root, [target], apply=True, generator=lambda _: {"text": "Some text", "quotes": {"name": "not in the source"}})
        self.assertEqual(before, (self.root / target).read_bytes())

    def test_generator_cannot_change_job_inputs_to_validate_a_fake_quote(self):
        target = self.agent()
        def generate(job):
            job["inputs"]["name"] = "Invented"
            return {"text": "Invented", "quotes": {"name": "Invented"}}
        with self.assertRaisesRegex(SproutError, "quote does not match"):
            run(self.root, [target], apply=True, generator=generate)

    def test_stale_agent_submission_is_rejected_then_valid_one_applies(self):
        target = self.agent()
        runtime = Runtime(self.root)
        with self.assertRaises(SproutError):
            runtime.refresh(target)
        job = runtime.jobs[0]
        proposal = {k: job[k] for k in ("file", "block", "input_hash")}
        proposal.update(text="Mina is the named person.", quotes={"name": "Mina"})
        proposal_path = self.root / "proposal.json"
        self.write("proposal.json", proposal)
        self.write("data.json", {"name": "Theo"})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--root", str(self.root), "submit", str(proposal_path)]), 2)
        self.write("data.json", {"name": "Mina"})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--root", str(self.root), "submit", str(proposal_path)]), 0)
        self.assertEqual(load((self.root / target).read_bytes())["state"]["blocks"]["summary"]["value"], proposal["text"])

    def test_cooperating_refreshes_cannot_overlap(self):
        with FolderLock(self.root), self.assertRaisesRegex(SproutError, "Another refresh"):
            with FolderLock(self.root):
                self.fail("Acquired a held lock")
        self.assertFalse((self.root / ".sprout.lock").exists())

    def test_create_preserves_existing_file(self):
        target = self.make()
        before = (self.root / target).read_bytes()
        with self.assertRaisesRegex(SproutError, "exists"):
            self.make()
        self.assertEqual(before, (self.root / target).read_bytes())


if __name__ == "__main__":
    unittest.main()
