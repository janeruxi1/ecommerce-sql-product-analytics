"""The figures are drawn from results/ and linked from the documents."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_figure_is_drawn(tmp_path):
    spec = importlib.util.spec_from_file_location("make_figures", ROOT / "scripts" / "make_figures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUT = tmp_path
    made = {make().name for make in mod.FIGURES}
    assert made == {p.name for p in (ROOT / "docs" / "figures").glob("*.png")}
    assert all((tmp_path / name).stat().st_size > 10_000 for name in made)


def test_figures_are_linked_and_links_resolve():
    docs = [ROOT / "README.md", *sorted((ROOT / "cases").glob("*/README.md"))]
    linked = set()
    for doc in docs:
        for ref in re.findall(r"(?:src=\"|\]\()([^\")]*docs/figures/[^\")]+\.png)", doc.read_text(encoding="utf-8")):
            path = (doc.parent / ref).resolve()
            assert path.exists(), f"{doc.relative_to(ROOT)} links to missing {ref}"
            linked.add(path.name)
    assert linked == {p.name for p in (ROOT / "docs" / "figures").glob("*.png")}
