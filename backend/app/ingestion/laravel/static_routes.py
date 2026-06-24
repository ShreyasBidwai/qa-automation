"""Static route parser for ``routes/*.php`` — NO app boot (ADR-0055).

Ingestion reads source only; it never runs ``php artisan route:list`` (which boots
the target app — full .env, a reachable DB, every provider credential, and every
route's controller resolving). This parses the route DSL directly into the SAME
``RouteFacts`` the rest of ingestion consumes:

- ``Route::get|post|put|patch|delete|options|any`` and ``Route::match([...], …)``;
- ``Route::resource`` / ``apiResource`` (expanded to the REST sub-routes);
- groups — ``prefix`` / ``name`` (``as``) / ``middleware`` / ``controller``, the
  array form ``Route::group([...], fn)``, and nested groups;
- controller references resolved to an FQCN via the file's ``use`` imports.

Robustness is the point (real apps are messy): a route whose controller can't be
resolved, a file that won't parse, odd casing, ``_original``/``copy`` duplicates —
parse what's parseable, RECORD the rest, NEVER crash. Conventions only (api*.php →
``api`` prefix); exact dynamic/runtime routes are the optional artisan enrichment's
job, never required.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .route_list import RouteFacts, derive_auth_required

logger = logging.getLogger("app.ingestion.laravel")

_VERBS = ("get", "post", "put", "patch", "delete", "options", "any")
_PAIRS = {"(": ")", "{": "}", "[": "]"}
_OPENERS = "([{"
_CLOSERS = ")]}"

# REST verb/suffix/name for resource() (7) and the apiResource subset (5).
_RESOURCE = [
    ("GET", "", "index", False),
    ("GET", "/create", "create", True),  # web-only
    ("POST", "", "store", False),
    ("GET", "/{id}", "show", False),
    ("GET", "/{id}/edit", "edit", True),  # web-only
    ("PUT", "/{id}", "update", False),
    ("DELETE", "/{id}", "destroy", False),
]


@dataclass
class _Ctx:
    """The accumulated group context applied to a route."""

    prefix: str = ""
    name: str = ""
    middleware: tuple[str, ...] = ()
    controller: str | None = None


@dataclass
class StaticRoutes:
    facts: list[RouteFacts] = field(default_factory=list)
    # Controller references that could not be resolved to an FQCN (missing import /
    # missing class — recorded, not fatal). ``"<file>: <reference>"``.
    unresolved: list[str] = field(default_factory=list)


# --- string/comment-aware scanning ------------------------------------------


def _mask(src: str) -> str:
    """A same-length copy with string-literal + comment bodies blanked to spaces, so
    brace/paren matching never trips on a ``{`` inside a string or comment."""
    out: list[str] = []
    i, n = 0, len(src)
    state: str | None = None  # "'" | '"' | "//" | "/*" | None
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c in "'\"":
                state = c
                out.append(c)
            elif c == "/" and nxt == "/":
                state = "//"
                out.append("  ")
                i += 2
                continue
            elif c == "/" and nxt == "*":
                state = "/*"
                out.append("  ")
                i += 2
                continue
            else:
                out.append(c)
        elif state in ("'", '"'):
            if c == "\\":
                out.append("  ")
                i += 2
                continue
            if c == state:
                state = None
                out.append(c)
            else:
                out.append("\n" if c == "\n" else " ")
        elif state == "//":
            if c == "\n":
                state = None
                out.append("\n")
            else:
                out.append(" ")
        else:  # /* */
            if c == "*" and nxt == "/":
                state = None
                out.append("  ")
                i += 2
                continue
            out.append("\n" if c == "\n" else " ")
        i += 1
    return "".join(out)


def _match(masked: str, idx: int) -> int:
    """Index of the bracket that closes the one at ``idx`` (all bracket types nest)."""
    depth = 0
    for j in range(idx, len(masked)):
        ch = masked[j]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
            if depth == 0:
                return j
    return len(masked) - 1


def _stmt_end(masked: str, start: int) -> int:
    """Index just past the ``;`` ending the statement at ``start`` (skips brackets)."""
    j = start
    n = len(masked)
    while j < n:
        ch = masked[j]
        if ch in _OPENERS:
            j = _match(masked, j) + 1
        elif ch == ";":
            return j + 1
        else:
            j += 1
    return n


def _split_args(masked: str, src: str, open_idx: int, close_idx: int) -> list[str]:
    """Split the comma-separated args inside ``(...)``/``[...]`` (top level only)."""
    args: list[str] = []
    depth = 0
    last = open_idx + 1
    for j in range(open_idx + 1, close_idx):
        ch = masked[j]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(src[last:j].strip())
            last = j + 1
    tail = src[last:close_idx].strip()
    if tail:
        args.append(tail)
    return args


# --- value extraction --------------------------------------------------------

_STRING = re.compile(r"""^(['"])(.*)\1$""", re.DOTALL)
_USE = re.compile(r"\buse\s+([A-Za-z0-9_\\]+)(?:\s+as\s+([A-Za-z0-9_]+))?\s*;")


def _string_lit(expr: str) -> str | None:
    m = _STRING.match(expr.strip())
    return m.group(2) if m else None


def _use_map(src: str) -> dict[str, str]:
    """alias/short-name -> FQCN from the file's ``use`` imports."""
    out: dict[str, str] = {}
    for fqcn, alias in _USE.findall(src):
        fqcn = fqcn.lstrip("\\")
        key = alias or fqcn.rsplit("\\", 1)[-1]
        out[key] = fqcn
    return out


def _resolve_class(name: str, uses: dict[str, str], default_ns: str) -> str | None:
    """A class name (``Foo``, ``A\\B``, ``\\A\\B``, ``Foo::class``) -> FQCN, or None."""
    name = name.strip()
    if name.endswith("::class"):
        name = name[: -len("::class")].strip()
    if not name or not re.match(r"^\\?[A-Za-z_][A-Za-z0-9_\\]*$", name):
        return None
    if name.startswith("\\"):
        return name.lstrip("\\")
    head = name.split("\\", 1)[0]
    if head in uses:
        return uses[head] + name[len(head) :]
    if "\\" in name:  # already namespaced, no matching import
        return name
    return f"{default_ns}\\{name}" if default_ns else name


def _norm_uri(uri: str) -> str:
    return uri.strip().strip("/")


def _join_prefix(parent: str, child: str) -> str:
    return "/".join(p for p in (parent.strip("/"), child.strip("/")) if p)


# --- the parser --------------------------------------------------------------


def parse_routes(
    repo_path: str, *, default_ns: str = "App\\Http\\Controllers"
) -> StaticRoutes:
    """Parse every ``routes/*.php`` into RouteFacts (static; never boots the app)."""
    result = StaticRoutes()
    routes_dir = Path(repo_path) / "routes"
    if not routes_dir.is_dir():
        return result
    for php in sorted(routes_dir.glob("*.php")):
        try:
            src = php.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Laravel applies the `api` prefix + group to routes/api*.php by convention.
        api = php.name.startswith("api")
        base = _Ctx(
            prefix="api" if api else "",
            middleware=("api",) if api else (),
        )
        try:
            uses = _use_map(src)
            _scan(
                _mask(src), src, 0, len(src), base, uses, default_ns, result, php.name
            )
        except Exception:  # noqa: BLE001 — a broken route file must never abort ingest
            logger.warning(
                "ingestion.laravel.route_file_unparsed", extra={"file": php.name}
            )
            result.unresolved.append(f"{php.name}: file could not be parsed")
    return result


def _scan(
    masked: str,
    src: str,
    lo: int,
    hi: int,
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    out: StaticRoutes,
    fname: str,
) -> None:
    """Walk a block, dispatching each ``Route::`` statement to group or terminal.

    A cursor skips past each handled statement so a group's body (recursed into) is
    never re-processed at this level — otherwise a nested route is emitted twice.
    """
    cursor = lo
    for m in re.finditer(r"\bRoute\s*::", masked):
        start = m.start()
        if start < cursor or start >= hi:
            continue
        end = _stmt_end(masked, start)
        cursor = min(end, hi)  # consumed this whole statement (incl. any group body)
        if end <= start:
            continue
        stmt_m, stmt_s = masked[start:end], src[start:end]
        try:
            if "->group(" in stmt_m or re.match(r"Route\s*::\s*group\s*\(", stmt_m):
                _handle_group(
                    masked, src, start, end, ctx, uses, default_ns, out, fname
                )
            else:
                _handle_route(stmt_m, stmt_s, ctx, uses, default_ns, out, fname)
        except Exception:  # noqa: BLE001 — one bad statement never stops the rest
            out.unresolved.append(f"{fname}: unparsed route statement")


def _find_call(masked: str, start: int, end: int, name: str) -> int:
    """The index of ``(`` for the first ``<name>(`` token in [start,end), or -1."""
    for m in re.finditer(rf"\b{name}\s*\(", masked[start:end]):
        return start + m.end() - 1
    return -1


def _handle_group(
    masked: str,
    src: str,
    start: int,
    end: int,
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    out: StaticRoutes,
    fname: str,
) -> None:
    # The group's closure body is the LAST {...} block inside group(...).
    gopen = _find_call(masked, start, end, "group")
    if gopen < 0:
        return
    gclose = _match(masked, gopen)
    # group() args: optionally an attribute array, then the closure.
    args = _split_args(masked, src, gopen, gclose)
    child = _merge_chain(
        src[start:gopen], ctx, uses, default_ns
    )  # prefix()->name()… form
    for arg in args:  # array attribute form: Route::group(['prefix'=>…], fn)
        if arg.lstrip().startswith("["):
            child = _merge_array(arg, child, uses, default_ns)
    # Recurse into the closure body (the {...} within the group parens).
    body_open = masked.find("{", gopen, gclose)
    if body_open != -1:
        body_close = _match(masked, body_open)
        _scan(
            masked, src, body_open + 1, body_close, child, uses, default_ns, out, fname
        )


def _merge_chain(
    chain_src: str, ctx: _Ctx, uses: dict[str, str], default_ns: str
) -> _Ctx:
    """Apply fluent ``->prefix()/->name()/->middleware()/->controller()`` modifiers."""
    prefix, name = ctx.prefix, ctx.name
    middleware = list(ctx.middleware)
    controller = ctx.controller
    for mm in re.finditer(
        r"(?:Route\s*::|->)\s*(prefix|name|middleware|controller)\s*\(([^)]*)\)",
        chain_src,
    ):
        kind, raw = mm.group(1), mm.group(2)
        if kind == "prefix":
            v = _string_lit(raw)
            if v:
                prefix = _join_prefix(prefix, v)
        elif kind == "name":
            v = _string_lit(raw)
            if v:
                name = name + v
        elif kind == "middleware":
            middleware.extend(_string_values(raw))
        elif kind == "controller":
            c = _resolve_class(raw, uses, default_ns)
            if c:
                controller = c
    return _Ctx(
        prefix=prefix, name=name, middleware=tuple(middleware), controller=controller
    )


def _merge_array(
    arr_src: str, ctx: _Ctx, uses: dict[str, str], default_ns: str
) -> _Ctx:
    """Apply a ``Route::group(['prefix'=>…,'as'=>…,'middleware'=>…], …)`` attr array."""
    prefix, name = ctx.prefix, ctx.name
    middleware = list(ctx.middleware)
    controller = ctx.controller
    pm = re.search(r"['\"]prefix['\"]\s*=>\s*(['\"][^'\"]*['\"])", arr_src)
    if pm and (v := _string_lit(pm.group(1))):
        prefix = _join_prefix(prefix, v)
    nm = re.search(r"['\"](?:as|name)['\"]\s*=>\s*(['\"][^'\"]*['\"])", arr_src)
    if nm and (v := _string_lit(nm.group(1))) is not None:
        name = name + v
    mm = re.search(
        r"['\"]middleware['\"]\s*=>\s*(\[[^\]]*\]|['\"][^'\"]*['\"])", arr_src
    )
    if mm:
        middleware.extend(_string_values(mm.group(1)))
    cm = re.search(r"['\"]controller['\"]\s*=>\s*([A-Za-z0-9_\\]+::class)", arr_src)
    if cm:
        c = _resolve_class(cm.group(1), uses, default_ns)
        if c:
            controller = c
    return _Ctx(
        prefix=prefix, name=name, middleware=tuple(middleware), controller=controller
    )


def _string_values(raw: str) -> list[str]:
    """Every quoted string in an arg (handles ``'a'``, ``['a','b']``)."""
    return re.findall(r"['\"]([^'\"]+)['\"]", raw)


def _handle_route(
    stmt_m: str,
    stmt_s: str,
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    out: StaticRoutes,
    fname: str,
) -> None:
    verb_m = re.match(r"Route\s*::\s*([A-Za-z]+)\s*\(", stmt_m)
    if not verb_m:
        return
    verb = verb_m.group(1)
    open_idx = verb_m.end() - 1
    close_idx = _match(stmt_m, open_idx)
    args = _split_args(stmt_m, stmt_s, open_idx, close_idx)
    # Chained ->name()/->middleware() AFTER the call (between close paren and ;).
    tail = stmt_s[close_idx + 1 :]
    chain_name = _chain_string(tail, "name")
    chain_mw = _chain_mw(tail)

    if verb in ("resource", "apiResource"):
        _expand_resource(verb, args, ctx, uses, default_ns, chain_mw, out, fname)
        return
    if verb == "match":
        if len(args) < 3:
            return
        methods = [m.upper() for m in _string_values(args[0])]
        _emit(
            methods,
            args[1],
            args[2],
            ctx,
            uses,
            default_ns,
            chain_name,
            chain_mw,
            out,
            fname,
        )
        return
    if verb in _VERBS:
        if not args:
            return
        action = args[1] if len(args) > 1 else None
        methods = (
            ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
            if verb == "any"
            else [verb.upper()]
        )
        _emit(
            methods,
            args[0],
            action,
            ctx,
            uses,
            default_ns,
            chain_name,
            chain_mw,
            out,
            fname,
        )
        return
    # redirect / view / fallback / permanentRedirect → a GET with no controller.
    if verb in ("redirect", "permanentRedirect", "view", "fallback"):
        uri = args[0] if (args and verb != "fallback") else "'{fallback}'"
        _emit(
            ["GET"], uri, None, ctx, uses, default_ns, chain_name, chain_mw, out, fname
        )


def _chain_string(tail: str, kind: str) -> str | None:
    m = re.search(rf"->\s*{kind}\s*\(\s*(['\"][^'\"]*['\"])", tail)
    return _string_lit(m.group(1)) if m else None


def _chain_mw(tail: str) -> list[str]:
    vals: list[str] = []
    for m in re.finditer(r"->\s*(?:middleware|withoutMiddleware)\s*\(([^)]*)\)", tail):
        vals.extend(_string_values(m.group(1)))
    return vals


def _emit(
    methods: list[str],
    uri_arg: str | None,
    action_arg: str | None,
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    chain_name: str | None,
    chain_mw: list[str],
    out: StaticRoutes,
    fname: str,
) -> None:
    uri_lit = _string_lit(uri_arg) if uri_arg else None
    if uri_lit is None:
        return
    uri = _norm_uri(_join_prefix(ctx.prefix, uri_lit))
    name = (ctx.name + chain_name) if chain_name else (ctx.name or None)
    middleware = list(ctx.middleware) + chain_mw
    methods = [m for m in methods if m] or ["GET"]
    primary = next((m for m in methods if m not in ("HEAD", "OPTIONS")), methods[0])
    action = _resolve_action(action_arg, ctx, uses, default_ns, out, fname)
    out.facts.append(
        RouteFacts(
            method=primary,
            methods=methods,
            uri=uri,
            name=name or None,
            action=action,
            middleware=middleware,
            auth_required=derive_auth_required(middleware),
        )
    )


def _resolve_action(
    action_arg: str | None,
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    out: StaticRoutes,
    fname: str,
) -> str:
    """Resolve a route action to ``FQCN@method`` / ``Closure``; record if unknown."""
    if action_arg is None:
        return "Closure"
    a = action_arg.strip()
    if (
        a.startswith("function")
        or a.startswith("static function")
        or a.startswith("fn")
    ):
        return "Closure"
    if a.startswith("["):
        close = a.rfind("]")
        parts = _split_args(_mask(a), a, 0, close if close > 0 else len(a))
        if not parts:
            return "Closure"
        cls = _resolve_class(parts[0], uses, default_ns)
        if cls is None:
            out.unresolved.append(f"{fname}: {parts[0].strip()}")
            return parts[0].strip()
        method = _string_lit(parts[1]) if len(parts) > 1 else "__invoke"
        return f"{cls}@{method or '__invoke'}"
    lit = _string_lit(a)
    if lit is not None:
        if "@" in lit:
            cname, _, method = lit.partition("@")
            cls = _resolve_class(cname, uses, default_ns)
            if cls is None:
                out.unresolved.append(f"{fname}: {cname}")
                return lit
            return f"{cls}@{method}"
        if ctx.controller:  # bare 'method' under ->controller(Ctrl::class)
            return f"{ctx.controller}@{lit}"
        out.unresolved.append(f"{fname}: bare action {lit!r} (no group controller)")
        return lit
    cls = _resolve_class(a, uses, default_ns)  # invokable: Route::get('/', Ctrl::class)
    if cls is not None:
        return f"{cls}@__invoke"
    out.unresolved.append(f"{fname}: {a}")
    return a


def _expand_resource(
    verb: str,
    args: list[str],
    ctx: _Ctx,
    uses: dict[str, str],
    default_ns: str,
    chain_mw: list[str],
    out: StaticRoutes,
    fname: str,
) -> None:
    if len(args) < 2:
        return
    name = _string_lit(args[0])
    cls = _resolve_class(args[1], uses, default_ns)
    if name is None:
        return
    if cls is None:
        out.unresolved.append(f"{fname}: {args[1].strip()} (resource)")
    api = verb == "apiResource"
    middleware = list(ctx.middleware) + chain_mw
    for method, suffix, action_name, web_only in _RESOURCE:
        if api and web_only:
            continue
        uri = _norm_uri(_join_prefix(ctx.prefix, name) + suffix)
        route_name = f"{ctx.name}{name}.{action_name}"
        out.facts.append(
            RouteFacts(
                method=method,
                methods=[method],
                uri=uri,
                name=route_name,
                action=f"{cls}@{action_name}" if cls else f"{name}@{action_name}",
                middleware=middleware,
                auth_required=derive_auth_required(middleware),
            )
        )
