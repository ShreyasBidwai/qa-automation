"""Static model/migration/controller parser → ``RepoGraph`` — NO app boot (ADR-0055).

Replaces the ``extract_graph.php`` AST helper (which required the target's
``vendor/autoload.php`` + nikic/php-parser, i.e. a ``composer install``). Reads the
source directly into the SAME ``RepoGraph`` (``ModelMeta`` / ``MigrationMeta`` /
``ActionMeta``) the ingester already consumes:

- models (``app/Models``, ``app``): ``$table`` (or pluralise(snake(class))),
  ``$fillable``, declared relationships (``$this->belongsTo(Related::class)`` …);
- migrations (``database/migrations``): ``Schema::create('t', fn($t){…})`` columns;
- controllers (``app/Http/Controllers``): public actions, statically-referenced
  models, and validation (a type-hinted FormRequest's ``rules()`` keys, or an inline
  ``$request->validate([...])``).

Every file is parsed defensively — a malformed file, an odd class, a duplicate/
``_original`` copy is skipped, never fatal (real apps are messy).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

from .graph import (
    ActionMeta,
    ActionValidation,
    MigrationMeta,
    ModelMeta,
    Relationship,
    RepoGraph,
)
from .static_routes import (
    _mask,
    _match,
    _resolve_class,
    _split_args,
    _string_lit,
    _use_map,
)

logger = logging.getLogger("app.ingestion.laravel")

_RELATIONS = (
    "belongsTo",
    "hasMany",
    "hasOne",
    "belongsToMany",
    "hasManyThrough",
    "hasOneThrough",
    "morphTo",
    "morphMany",
    "morphOne",
    "morphToMany",
    "morphedByMany",
)
_COLUMN_TYPES = (
    "string",
    "char",
    "text",
    "mediumText",
    "longText",
    "tinyText",
    "integer",
    "tinyInteger",
    "smallInteger",
    "mediumInteger",
    "bigInteger",
    "unsignedInteger",
    "unsignedTinyInteger",
    "unsignedSmallInteger",
    "unsignedMediumInteger",
    "unsignedBigInteger",
    "foreignId",
    "foreignUlid",
    "foreignUuid",
    "boolean",
    "date",
    "dateTime",
    "dateTimeTz",
    "time",
    "timeTz",
    "timestamp",
    "timestampTz",
    "year",
    "decimal",
    "float",
    "double",
    "unsignedDecimal",
    "json",
    "jsonb",
    "uuid",
    "ulid",
    "ipAddress",
    "macAddress",
    "binary",
    "enum",
    "set",
)

_NAMESPACE = re.compile(r"\bnamespace\s+([A-Za-z0-9_\\]+)\s*;")
_CLASS = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_METHOD = re.compile(
    r"((?:\b(?:public|protected|private|static|final|abstract)\b\s+)*)function\s+([A-Za-z_]\w*)\s*\("
)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _php_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.php")) if root.is_dir() else []


def _namespace(src: str) -> str:
    m = _NAMESPACE.search(src)
    return m.group(1).strip("\\") if m else ""


def _array_after(masked: str, src: str, prop_pat: str) -> list[str]:
    """The quoted strings of an array assigned to ``$prop`` (``$fillable = [...]``)."""
    m = re.search(prop_pat, masked)
    if not m:
        return []
    bracket = masked.find("[", m.end())
    if bracket == -1 or bracket - m.end() > 4:
        return []
    close = _match(masked, bracket)
    return re.findall(r"['\"]([^'\"]+)['\"]", src[bracket : close + 1])


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _pluralize(word: str) -> str:
    if re.search(r"[^aeiou]y$", word, re.I):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", word, re.I):
        return word + "es"
    return word + "s"


def _iter_methods(masked: str, src: str) -> Iterator[tuple[str, str, str, str, str]]:
    """Yield (name, modifiers, params_src, body_src, body_masked) for each method."""
    for m in _METHOD.finditer(masked):
        mods, name = m.group(1), m.group(2)
        paren = m.end() - 1
        pclose = _match(masked, paren)
        brace = masked.find("{", pclose)
        if brace == -1:
            yield name, mods, src[paren + 1 : pclose], "", ""
            continue
        bclose = _match(masked, brace)
        yield name, mods, src[paren + 1 : pclose], src[brace + 1 : bclose], masked[
            brace + 1 : bclose
        ]


def _is_public(mods: str) -> bool:
    return "private" not in mods and "protected" not in mods


# --- models ------------------------------------------------------------------


def _parse_models(repo: Path) -> list[ModelMeta]:
    out: list[ModelMeta] = []
    seen: set[str] = set()
    roots = [repo / "app" / "Models", repo / "app"]
    files: list[Path] = []
    for root in roots:
        files.extend(_php_files(root))
    for path in sorted(set(files)):
        # Only look at app/Models or files that look like an Eloquent model.
        src = _read(path)
        if src is None:
            continue
        try:
            if (
                "Models" not in str(path)
                and "extends Model" not in src
                and "extends Authenticatable" not in src
            ):
                continue
            masked = _mask(src)
            cls_m = _CLASS.search(masked)
            if not cls_m:
                continue
            ns = _namespace(src)
            name = cls_m.group(1)
            fqcn = f"{ns}\\{name}" if ns else name
            if fqcn in seen:
                continue
            seen.add(fqcn)
            uses = _use_map(src)
            table = _array_str(masked, src, r"\$table\s*=\s*") or _pluralize(
                _snake(name)
            )
            fillable = _array_after(masked, src, r"\$fillable\s*=\s*")
            out.append(
                ModelMeta(
                    cls=fqcn,
                    table=table,
                    fillable=fillable,
                    relationships=_relationships(masked, src, uses, ns),
                )
            )
        except Exception:  # noqa: BLE001 — a messy model never aborts ingestion
            logger.warning(
                "ingestion.laravel.model_unparsed", extra={"file": path.name}
            )
    return out


def _array_str(masked: str, src: str, prefix_pat: str) -> str | None:
    m = re.search(prefix_pat, masked)
    if not m:
        return None
    return _string_lit(src[m.end() : m.end() + 200].split(";", 1)[0].strip())


def _relationships(
    masked: str, src: str, uses: dict[str, str], ns: str
) -> list[Relationship]:
    rels: list[Relationship] = []
    for name, mods, _params, body, body_m in _iter_methods(masked, src):
        if not _is_public(mods) or not body_m:
            continue
        rm = re.search(
            rf"\$this\s*->\s*({'|'.join(_RELATIONS)})\s*\(\s*([A-Za-z0-9_\\]+)\s*::\s*class",
            body,
        )
        if rm:
            related = _resolve_class(rm.group(2), uses, ns)
            if related:
                rels.append(Relationship(name=name, kind=rm.group(1), related=related))
    return rels


# --- migrations --------------------------------------------------------------


def _parse_migrations(repo: Path) -> list[MigrationMeta]:
    out: list[MigrationMeta] = []
    for path in _php_files(repo / "database" / "migrations"):
        src = _read(path)
        if src is None:
            continue
        try:
            masked = _mask(src)
            for cm in re.finditer(r"Schema\s*::\s*create\s*\(", masked):
                popen = cm.end() - 1
                pclose = _match(masked, popen)
                args = _split_args(masked, src, popen, pclose)
                if len(args) < 2:
                    continue
                table = _string_lit(args[0])
                if not table:
                    continue
                brace = masked.find("{", popen, pclose)
                body = src[brace + 1 : _match(masked, brace)] if brace != -1 else ""
                out.append(MigrationMeta(table=table, columns=_columns(body)))
        except Exception:  # noqa: BLE001 — a broken migration never aborts ingestion
            logger.warning(
                "ingestion.laravel.migration_unparsed", extra={"file": path.name}
            )
    return out


def _columns(body: str) -> list[str]:
    cols: list[str] = []
    for m in re.finditer(r"->\s*([A-Za-z_]\w*)\s*\(([^)]*)", body):
        method, raw = m.group(1), m.group(2)
        if method == "id":
            cols.append("id")
        elif method in ("timestamps", "timestampsTz"):
            cols += ["created_at", "updated_at"]
        elif method == "softDeletes":
            cols.append("deleted_at")
        elif method == "rememberToken":
            cols.append("remember_token")
        elif method in _COLUMN_TYPES:
            name = _string_lit(raw.split(",", 1)[0].strip())
            if name:
                cols.append(name)
    return list(dict.fromkeys(cols))


# --- controllers -------------------------------------------------------------


def _parse_controllers(repo: Path, model_set: set[str]) -> list[ActionMeta]:
    out: list[ActionMeta] = []
    for path in _php_files(repo / "app" / "Http" / "Controllers"):
        src = _read(path)
        if src is None:
            continue
        try:
            masked = _mask(src)
            cls_m = _CLASS.search(masked)
            if not cls_m:
                continue
            ns = _namespace(src)
            controller = f"{ns}\\{cls_m.group(1)}" if ns else cls_m.group(1)
            uses = _use_map(src)
            for name, mods, params, body, body_m in _iter_methods(masked, src):
                if not _is_public(mods) or name == "__construct" or not body_m:
                    continue
                out.append(
                    ActionMeta(
                        controller=controller,
                        action=name,
                        model_refs=_model_refs(params, body, uses, ns, model_set),
                        validation=_validation(repo, params, body, uses, ns),
                    )
                )
        except Exception:  # noqa: BLE001 — a messy controller never aborts ingestion
            logger.warning(
                "ingestion.laravel.controller_unparsed", extra={"file": path.name}
            )
    return out


def _model_refs(
    params: str, body: str, uses: dict[str, str], ns: str, model_set: set[str]
) -> list[str]:
    names: list[str] = []
    names += re.findall(
        r"\b([A-Za-z_][A-Za-z0-9_\\]*)\s*::", body
    )  # Static:: / ::class
    names += re.findall(r"\bnew\s+([A-Za-z_][A-Za-z0-9_\\]*)", body)
    names += re.findall(r"([A-Za-z_][A-Za-z0-9_\\]*)\s+\$", params)  # typed params
    refs: list[str] = []
    for raw in dict.fromkeys(names):
        fqcn = _resolve_class(raw, uses, ns)
        if fqcn is not None and fqcn in model_set and fqcn not in refs:
            refs.append(fqcn)
    return refs


def _validation(
    repo: Path, params: str, body: str, uses: dict[str, str], ns: str
) -> ActionValidation:
    # 1) a type-hinted FormRequest parameter → resolve its rules() keys.
    for type_name in re.findall(r"([A-Za-z_][A-Za-z0-9_\\]*)\s+\$\w+", params):
        fqcn = _resolve_class(type_name, uses, ns)
        if not fqcn or not fqcn.startswith("App\\"):
            continue
        rel = fqcn[len("App\\") :].replace("\\", "/")
        path = repo / "app" / f"{rel}.php"
        fields = _rules_fields(path)
        if fields is not None:
            return ActionValidation(source="form_request", fields=fields)
    # 2) inline $request->validate([...]).
    vm = re.search(r"->\s*validate\s*\(", _mask(body))
    if vm:
        bracket = _mask(body).find("[", vm.end())
        if bracket != -1 and bracket - vm.end() < 4:
            arr = body[bracket : _match(_mask(body), bracket) + 1]
            return ActionValidation(source="inline_validate", fields=_array_keys(arr))
    return ActionValidation(source="none", fields=[])


def _rules_fields(path: Path) -> list[str] | None:
    src = _read(path)
    if src is None:
        return None
    masked = _mask(src)
    for name, _mods, _params, body, _body_m in _iter_methods(masked, src):
        if name != "rules":
            continue
        rm = re.search(r"\breturn\b", _mask(body))
        bracket = _mask(body).find("[", rm.end()) if rm else -1
        if bracket != -1:
            arr = body[bracket : _match(_mask(body), bracket) + 1]
            return _array_keys(arr)
        return []
    return None


def _array_keys(arr_src: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"['\"]([^'\"]+)['\"]\s*=>", arr_src)))


def parse_graph(repo_path: str) -> RepoGraph:
    """Parse models/migrations/controllers into the Brain RepoGraph (static)."""
    repo = Path(repo_path)
    models = _parse_models(repo)
    model_set = {m.cls for m in models}
    return RepoGraph(
        models=models,
        migrations=_parse_migrations(repo),
        actions=_parse_controllers(repo, model_set),
    )
