import os
import tempfile

from hep_multiagent.features.citation_builder import _merge_quotes


def test_merge_quotes_no_existing_bib():
    with tempfile.TemporaryDirectory() as tmpdir:
        bib_path = os.path.join(tmpdir, "refs.bib")
        content, note = _merge_quotes(bib_path, "2301.00774", ["quote one"])
        assert content == ""
        assert note == '["quote one"]'


def test_merge_quotes_existing_bib_different_paper():
    with tempfile.TemporaryDirectory() as tmpdir:
        bib_path = os.path.join(tmpdir, "refs.bib")
        with open(bib_path, "w") as f:
            f.write("""@article{arxiv2301other,
  title = {Other Paper},
  eprint = {2301.99999},
  note = {["existing quote"]}
}
""")
        content, note = _merge_quotes(bib_path, "2301.00774", ["new quote"])
        assert "2301.99999" in content
        assert note == '["new quote"]'


def test_merge_quotes_same_paper_merges():
    with tempfile.TemporaryDirectory() as tmpdir:
        bib_path = os.path.join(tmpdir, "refs.bib")
        with open(bib_path, "w") as f:
            f.write("""@article{arxiv230100774,
  title = {Test Paper},
  eprint = {2301.00774},
  note = {["old quote"]}
}
""")
        content, note = _merge_quotes(bib_path, "2301.00774", ["new quote"])
        assert "2301.00774" not in content
        assert "old quote" in note
        assert "new quote" in note


def test_merge_quotes_deduplicates():
    with tempfile.TemporaryDirectory() as tmpdir:
        bib_path = os.path.join(tmpdir, "refs.bib")
        with open(bib_path, "w") as f:
            f.write("""@article{arxiv230100774,
  title = {Test Paper},
  eprint = {2301.00774},
  note = {["same quote"]}
}
""")
        content, note = _merge_quotes(bib_path, "2301.00774", ["same quote", "new quote"])
        import json
        quotes = json.loads(note)
        assert quotes.count("same quote") == 1
        assert "new quote" in quotes
