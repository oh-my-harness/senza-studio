#!/usr/bin/env python3
"""Verify Studio's actual senza-sdk usage against the installed senza module.

Usage:
    python scripts/check_senza_compat.py

Studio's meta-agent and Play executor depend on a specific set of senza
symbols (functions, plugins, HarnessBuilder methods, WorkflowEngine). That
surface is described in studio_backend/agent.py, studio_backend/play.py, and
studio_backend/tools/*.py, hand-written against whatever senza-sdk version
happened to be installed at the time. Nothing previously checked that those
calls still match the ACTUAL installed SDK — which is exactly how a
stale/mismatched SDK build can silently "look broken" (or silently look fine
when it isn't) until someone stumbles on it manually.

This script:
1. AST-scans agent.py + play.py + tools/*.py for every `senza.*` symbol used (including
   chained HarnessBuilder methods like `.plugin(...)`, `.auto_compact(...)`)
   and the keyword arguments passed at each call site.
2. Introspects the installed `senza` module for each discovered symbol
   (mirrors ../Senza/scripts/check_stubs.py's __text_signature__-based
   technique, adapted to look up one dotted path at a time instead of
   diffing a full .pyi file).
3. Reports any symbol that doesn't exist, or any keyword argument passed
   that the real signature doesn't accept.

Exits 1 if drift is found, 0 otherwise.
"""
from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_FILES = [
    REPO_ROOT / "studio_backend" / "agent.py",
    REPO_ROOT / "studio_backend" / "play.py",
    *sorted((REPO_ROOT / "studio_backend" / "tools").glob("*.py")),
]

# HarnessBuilder methods return the builder itself (fluent chain), so calls
# chained off senza.HarnessBuilder(...) are checked against this class,
# not as top-level senza.* symbols.
BUILDER_ROOT = "HarnessBuilder"


@dataclass
class Usage:
    symbol: str  # dotted path, e.g. "providers.openai", "create_tool", "HarnessBuilder.plugin"
    kwargs: set[str] = field(default_factory=set)
    sites: list[str] = field(default_factory=list)  # "file:lineno" for error messages


def _dotted_path(node: ast.AST) -> list[str] | None:
    """Walk an Attribute/Name chain into a list of names, e.g.
    `senza.strategy.safety_defaults` -> ["senza", "strategy", "safety_defaults"].
    Returns None if the chain passes through anything else (e.g. a Call —
    that means it's a chained method call, handled separately)."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return None


def _kwargs_of(call: ast.Call) -> set[str]:
    return {kw.arg for kw in call.keywords if kw.arg is not None}


def _record(usages: dict[str, Usage], symbol: str, call: ast.Call, filename: str) -> None:
    u = usages.setdefault(symbol, Usage(symbol=symbol))
    u.kwargs |= _kwargs_of(call)
    u.sites.append(f"{filename}:{call.lineno}")


def _scan_inline_chains(
    tree: ast.AST, usages: dict[str, Usage], filename: str
) -> tuple[set[int], set[int]]:
    """Pass 1: find every `senza.<path>(...)` call anywhere in the tree, and
    every single *inline* method chain rooted at `senza.HarnessBuilder(...)`
    (e.g. `senza.HarnessBuilder(m).provider(...).plugin(...)`).

    Returns `(consumed, builder_typed)`:
    - `consumed`: every node id that's part of an inline chain, so pass 2
      (cross-statement chain continuation) doesn't re-walk/re-record them.
    - `builder_typed`: the outermost call id of each inline chain whose
      *result* is itself still a HarnessBuilder (i.e. the chain's last
      method isn't `.build()`) — needed so pass 2 can recognize
      `builder = <this already-consumed chain>` as builder-typed and seed
      variable tracking from it, instead of silently stopping there.
    """
    # ast.walk() visits every node independently, including every inner Call
    # in a long method chain (`a().b().c()` contains three Call nodes, each
    # of which ast.walk() reaches on its own). Once a chain has been walked
    # from its outermost call, every inner call belonging to that same chain
    # must be skipped, or it gets re-recorded once per remaining link
    # (O(n^2) duplicate "sites").
    consumed: set[int] = set()
    builder_typed: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if id(node) in consumed:
            continue

        # Case 1: plain dotted path, e.g. senza.create_tool(...),
        # senza.providers.openai(...), senza.HarnessBuilder(...).
        path = _dotted_path(node.func)
        if path is not None:
            if path[0] != "senza":
                continue
            symbol = ".".join(path[1:])
            if not symbol:
                continue
            _record(usages, symbol, node, filename)
            continue

        # Case 2: chained method call, e.g.
        #   senza.HarnessBuilder(model).provider(...).plugin(...)
        # func.value is itself a Call (the previous link in the chain).
        if not isinstance(node.func.value, ast.Call):
            continue

        method_calls: list[ast.Call] = [node]
        base = node.func.value
        while isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute) and isinstance(
            base.func.value, ast.Call
        ):
            method_calls.append(base)
            base = base.func.value

        if not isinstance(base, ast.Call):
            continue
        base_path = _dotted_path(base.func) if isinstance(base.func, (ast.Attribute, ast.Name)) else None
        if not base_path or base_path[0] != "senza" or base_path[-1] != BUILDER_ROOT:
            continue

        # Whole chain resolved — mark every inner call consumed so ast.walk()
        # reaching them later (it will) doesn't re-trigger this branch.
        consumed.add(id(base))
        consumed.update(id(c) for c in method_calls)

        _record(usages, BUILDER_ROOT, base, filename)
        for mcall in method_calls:
            assert isinstance(mcall.func, ast.Attribute)
            _record(usages, f"{BUILDER_ROOT}.{mcall.func.attr}", mcall, filename)

        # The outermost node (`node` itself) is what an assignment target
        # would bind to. It's still builder-typed unless the chain's last
        # method call is `.build()`.
        if node.func.attr != "build":
            builder_typed.add(id(node))

    return consumed, builder_typed


def _scan_cross_statement_chains(
    tree: ast.AST,
    usages: dict[str, Usage],
    filename: str,
    already_consumed: set[int],
    builder_typed: set[int],
) -> None:
    """Pass 2: HarnessBuilder's fluent chain is often continued across
    separate statements, e.g.:

        builder = (senza.HarnessBuilder(m).provider(...)....)
        ...
        builder = builder.session_repo(repo, session_id)   # separate stmt
        ...
        harness = builder.build()                          # separate stmt

    Pass 1 only sees inline chains; this pass tracks, per local variable
    name, whether it currently holds a HarnessBuilder instance (seeded by
    pass 1's results), and records `.method()` calls made on it later —
    including inside try/if blocks, which is exactly where the real
    `.session_repo(...)` call lives in agent.py.

    This is a simple forward pass over statements in *written* order
    (adequate for the straight-line code this targets — not a real
    control-flow/data-flow analysis).
    """
    builder_vars: set[str] = set()

    def handle_call(call: ast.Call) -> bool:
        """Record a usage if `call` is a method call on a tracked builder
        variable. Returns whether the call's result is itself a builder
        (i.e. should propagate to an assignment target) — false for
        `.build()`, which terminates the fluent chain."""
        if id(call) in already_consumed:
            # Already recorded by pass 1 (e.g. `builder = (senza.HarnessBuilder(...)....)`).
            # Still report builder-ness so the assignment target gets tracked.
            return id(call) in builder_typed
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            return False
        if call.func.value.id not in builder_vars:
            return False
        method = call.func.attr
        _record(usages, f"{BUILDER_ROOT}.{method}", call, filename)
        return method != "build"

    class Visitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            self.generic_visit(node)
            is_builder = isinstance(node.value, ast.Call) and handle_call(node.value)
            if is_builder:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        builder_vars.add(target.id)

        def visit_Expr(self, node: ast.Expr) -> None:
            self.generic_visit(node)
            if isinstance(node.value, ast.Call):
                handle_call(node.value)

    Visitor().visit(tree)


def scan_file(path: Path, usages: dict[str, Usage]) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    filename = path.relative_to(REPO_ROOT).as_posix()
    consumed, builder_typed = _scan_inline_chains(tree, usages, filename)
    _scan_cross_statement_chains(tree, usages, filename, consumed, builder_typed)


def discover_usages() -> dict[str, Usage]:
    usages: dict[str, Usage] = {}
    for path in SCANNED_FILES:
        scan_file(path, usages)
    return usages


# ── Runtime introspection (mirrors ../Senza/scripts/check_stubs.py) ────────


def _parse_text_signature(ts: str) -> tuple[list[str], set[str]]:
    """Parse a __text_signature__ string like '($self, pattern, provider)'."""
    inner = ts.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    if not inner.strip():
        return [], set()

    parts: list[str] = []
    depth = 0
    current = ""
    for ch in inner:
        if ch in "([{":
            depth += 1
            current += ch
        elif ch in ")]}":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())

    params: list[str] = []
    defaults: set[str] = set()
    for part in parts:
        if part in ("/", "*"):
            continue
        if "=" in part:
            pname = part.split("=")[0].strip().replace("$", "")
            params.append(pname)
            defaults.add(pname)
        else:
            pname = part.strip().replace("$", "")
            if pname:
                params.append(pname)
    return params, defaults


def _params_of(obj) -> tuple[list[str], set[str]] | None:
    """Best-effort parameter extraction: __text_signature__ (PyO3 builtins)
    first, falling back to inspect.signature (Python-defined callables)."""
    ts = getattr(obj, "__text_signature__", None)
    if ts and ts != ():
        return _parse_text_signature(ts)
    try:
        sig = inspect.signature(obj)
    except (ValueError, TypeError):
        return None
    params: list[str] = []
    defaults: set[str] = set()
    accepts_kwargs = False
    for name, p in sig.parameters.items():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            accepts_kwargs = True
            continue
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        params.append(name)
        if p.default is not inspect.Parameter.empty:
            defaults.add(name)
    if accepts_kwargs:
        params.append("**kwargs")
    return params, defaults


def resolve_symbol(symbol: str):
    """Resolve a dotted path against the installed senza module/HarnessBuilder
    class. Returns the object, or raises AttributeError/KeyError-style with
    a clear message if any segment is missing."""
    import senza  # local import: only needed when actually checking

    if symbol == BUILDER_ROOT or symbol.startswith(f"{BUILDER_ROOT}."):
        obj = senza.HarnessBuilder
        rest = symbol.split(".")[1:]
    else:
        obj = senza
        rest = symbol.split(".")

    for part in rest:
        obj = getattr(obj, part)
    return obj


def check(usages: dict[str, Usage]) -> list[str]:
    diffs: list[str] = []
    for symbol in sorted(usages):
        usage = usages[symbol]
        try:
            obj = resolve_symbol(symbol)
        except AttributeError:
            diffs.append(
                f"  {symbol}: used at {', '.join(usage.sites)} but does not exist on the "
                "installed senza module"
            )
            continue

        if not callable(obj):
            continue  # e.g. a namespace object itself, not a call target

        params_info = _params_of(obj)
        if params_info is None:
            continue  # signature not introspectable — can't check kwargs, but symbol exists
        params, _defaults = params_info
        accepts_kwargs = "**kwargs" in params
        if accepts_kwargs:
            continue

        unknown = usage.kwargs - set(params)
        if unknown:
            diffs.append(
                f"  {symbol}: used with unknown keyword argument(s) {sorted(unknown)} "
                f"at {', '.join(usage.sites)}\n"
                f"    accepted params: {params}"
            )
    return diffs


def main() -> int:
    usages = discover_usages()
    if not usages:
        print(
            "ERROR: discovered zero senza.* usages — the AST scanner likely broke. "
            f"Scanned: {[str(p) for p in SCANNED_FILES]}"
        )
        return 1

    diffs = check(usages)
    if diffs:
        print(f"Drift detected ({len(diffs)} difference(s)):\n")
        for d in diffs:
            print(d)
        return 1

    print(f"OK — {len(usages)} senza symbols verified, no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
