"""Language dispatch for the mutation engine.

Keeps `mutate.py` (Python/`ast`) and `mutate_cfamily.py` (C-family/token) as
independent front ends behind one interface, so adding a language is a new front
end plus one registry line rather than an edit to the search itself.
"""
from __future__ import annotations

import ast
import pathlib

import mutate
import mutate_cfamily
from mutate import Site


def _ext(path) -> str:
    return pathlib.Path(str(path)).suffix.lower().lstrip(".")


def sites_for(path, src: str) -> list[Site]:
    return mutate.find_sites(src) if _ext(path) == "py" \
        else mutate_cfamily.find_sites_cfamily(src)


def apply_for(path, src: str, site: Site) -> str | None:
    """Splice, then validate as cheaply as the language allows.

    Python gets a real parse. C-family gets a bracket-balance check and relies on
    the compiler for the rest — a mutant that will not compile simply fails to
    run and is discarded, so a cheap pre-filter is enough.
    """
    out = src[:site.start] + site.repl + src[site.end:]
    if _ext(path) == "py":
        try:
            ast.parse(out)
        except SyntaxError:
            return None
        return out
    return out if mutate_cfamily.balanced(out) else None
