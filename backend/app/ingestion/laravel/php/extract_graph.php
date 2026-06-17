<?php

/**
 * Deterministic whole-repo model/migration/controller extractor (QA Automation).
 *
 * Usage:  php extract_graph.php <repo_path>
 * Output (stdout, JSON):
 *   {
 *     "models":     [{"class","table","fillable":[..],"relationships":[{"name","kind","related"}]}],
 *     "migrations": [{"table","columns":[..]}],
 *     "actions":    [{"controller","action","model_refs":[..],"validation":{"source","fields":[..]}}]
 *   }
 *
 * Uses nikic/php-parser (AST) — never regex on PHP source. Requires php-parser
 * available via the target repo's vendor/autoload.php. Sibling of
 * extract_validation.php (T1.3); deterministic and AI-free.
 *
 * Honesty: only statically derivable facts are emitted. Convention-derived
 * tables, unresolved relationships, and non-model references are left out rather
 * than guessed; the Python ingester decides confidence and skips the rest.
 */

declare(strict_types=1);

use PhpParser\Node;
use PhpParser\NodeFinder;
use PhpParser\ParserFactory;

function fail(string $message): never
{
    fwrite(STDERR, $message . "\n");
    exit(1);
}

[$_script, $repo] = array_pad($argv, 2, null);
if ($repo === null) {
    fail('usage: extract_graph.php <repo_path>');
}
$repo = rtrim($repo, '/');

$autoload = $repo . '/vendor/autoload.php';
if (!is_file($autoload)) {
    fail('vendor/autoload.php not found in repo; run `composer install`');
}
require $autoload;

if (!class_exists(ParserFactory::class)) {
    fail('nikic/php-parser not installed; run `composer require nikic/php-parser`');
}

const RELATION_METHODS = [
    'belongsTo', 'hasMany', 'hasOne', 'belongsToMany',
    'hasManyThrough', 'hasOneThrough',
    'morphTo', 'morphMany', 'morphOne', 'morphToMany', 'morphedByMany',
];

const COLUMN_TYPES = [
    'string', 'char', 'text', 'mediumText', 'longText', 'tinyText',
    'integer', 'tinyInteger', 'smallInteger', 'mediumInteger', 'bigInteger',
    'unsignedInteger', 'unsignedTinyInteger', 'unsignedSmallInteger',
    'unsignedMediumInteger', 'unsignedBigInteger',
    'foreignId', 'foreignUlid', 'foreignUuid',
    'boolean', 'date', 'dateTime', 'dateTimeTz', 'time', 'timeTz',
    'timestamp', 'timestampTz', 'year',
    'decimal', 'float', 'double', 'unsignedDecimal',
    'json', 'jsonb', 'uuid', 'ulid', 'ipAddress', 'macAddress',
    'binary', 'enum', 'set',
];

/** @return Node\Stmt[] */
function parse_file(string $path): array
{
    $parser = (new ParserFactory())->createForNewestSupportedVersion();
    return $parser->parse((string) file_get_contents($path)) ?? [];
}

/** Recursively list *.php files under a directory (sorted, deterministic). */
function php_files(string $dir): array
{
    if (!is_dir($dir)) {
        return [];
    }
    $files = [];
    $it = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS)
    );
    foreach ($it as $entry) {
        if ($entry->isFile() && $entry->getExtension() === 'php') {
            $files[] = $entry->getPathname();
        }
    }
    sort($files);
    return $files;
}

/** Build a short-name => FQCN map from a file's `use` statements. */
function use_map(array $ast): array
{
    $map = [];
    foreach ((new NodeFinder())->findInstanceOf($ast, Node\Stmt\Use_::class) as $use) {
        foreach ($use->uses as $u) {
            $alias = $u->alias?->toString() ?? $u->name->getLast();
            $map[$alias] = $u->name->toString();
        }
    }
    return $map;
}

function namespace_of(array $ast): string
{
    $ns = (new NodeFinder())->findFirstInstanceOf($ast, Node\Stmt\Namespace_::class);
    return $ns !== null && $ns->name !== null ? $ns->name->toString() : '';
}

function first_class(array $ast): ?Node\Stmt\Class_
{
    return (new NodeFinder())->findFirstInstanceOf($ast, Node\Stmt\Class_::class);
}

function class_method(?Node\Stmt\Class_ $class, string $name): ?Node\Stmt\ClassMethod
{
    if ($class === null) {
        return null;
    }
    foreach ($class->getMethods() as $method) {
        if ($method->name->toString() === $name) {
            return $method;
        }
    }
    return null;
}

/** Resolve a (possibly short) class name to an FQCN via the file's use-map. */
function resolve_name(string $name, array $uses, string $namespace): string
{
    if (str_starts_with($name, '\\')) {
        return ltrim($name, '\\');
    }
    $head = explode('\\', $name)[0];
    if (isset($uses[$head])) {
        return $uses[$head] . substr($name, strlen($head));
    }
    return $namespace !== '' ? $namespace . '\\' . $name : $name;
}

function fqcn_to_path(string $repo, string $fqcn): ?string
{
    $fqcn = ltrim($fqcn, '\\');
    if (!str_starts_with($fqcn, 'App\\')) {
        return null;
    }
    $relative = str_replace('\\', '/', substr($fqcn, strlen('App\\')));
    $path = $repo . '/app/' . $relative . '.php';
    return is_file($path) ? $path : null;
}

function property_default(Node\Stmt\Class_ $class, string $name): ?Node\Expr
{
    foreach ($class->getProperties() as $property) {
        foreach ($property->props as $prop) {
            if ($prop->name->toString() === $name && $prop->default !== null) {
                return $prop->default;
            }
        }
    }
    return null;
}

function string_list(?Node\Expr $expr): array
{
    $out = [];
    if ($expr instanceof Node\Expr\Array_) {
        foreach ($expr->items as $item) {
            if ($item !== null && $item->value instanceof Node\Scalar\String_) {
                $out[] = $item->value->value;
            }
        }
    }
    return $out;
}

function string_value(?Node\Expr $expr): ?string
{
    return $expr instanceof Node\Scalar\String_ ? $expr->value : null;
}

function snake(string $name): string
{
    return strtolower((string) preg_replace('/(?<!^)[A-Z]/', '_$0', $name));
}

/** Convention pluralizer for table names (common cases; explicit $table wins). */
function pluralize(string $word): string
{
    if (preg_match('/[^aeiou]y$/i', $word)) {
        return substr($word, 0, -1) . 'ies';
    }
    if (preg_match('/(s|x|z|ch|sh)$/i', $word)) {
        return $word . 'es';
    }
    return $word . 's';
}

function table_for(string $class_name, ?string $explicit): string
{
    return $explicit ?? pluralize(snake($class_name));
}

/** Relationship methods: `return $this->belongsTo(Related::class, ...)`. */
function relationships(Node\Stmt\Class_ $class, array $uses, string $namespace): array
{
    $out = [];
    foreach ($class->getMethods() as $method) {
        if (!$method->isPublic() || $method->stmts === null) {
            continue;
        }
        foreach ((new NodeFinder())->findInstanceOf($method->stmts, Node\Expr\MethodCall::class) as $call) {
            if (
                !$call->var instanceof Node\Expr\Variable
                || $call->var->name !== 'this'
                || !$call->name instanceof Node\Identifier
                || !in_array($call->name->toString(), RELATION_METHODS, true)
            ) {
                continue;
            }
            $args = $call->getArgs();
            if ($args === []) {
                continue;
            }
            $first = $args[0]->value;
            if (
                $first instanceof Node\Expr\ClassConstFetch
                && $first->class instanceof Node\Name
            ) {
                $out[] = [
                    'name' => $method->name->toString(),
                    'kind' => $call->name->toString(),
                    'related' => resolve_name($first->class->toString(), $uses, $namespace),
                ];
                break; // one relationship per method
            }
        }
    }
    return $out;
}

/** Validation summary for a controller action: form_request | inline_validate | none. */
function action_validation(Node\Stmt\ClassMethod $method, array $uses, string $namespace, string $repo): array
{
    // 1. Type-hinted FormRequest parameter → resolve its rules().
    foreach ($method->params as $param) {
        if (!$param->type instanceof Node\Name) {
            continue;
        }
        $path = fqcn_to_path($repo, resolve_name($param->type->toString(), $uses, $namespace));
        if ($path === null) {
            continue;
        }
        $rules = class_method(first_class(parse_file($path)), 'rules');
        if ($rules === null || $rules->stmts === null) {
            continue;
        }
        $return = (new NodeFinder())->findFirstInstanceOf($rules->stmts, Node\Stmt\Return_::class);
        if ($return !== null && $return->expr instanceof Node\Expr\Array_) {
            return ['source' => 'form_request', 'fields' => array_keys_of($return->expr)];
        }
    }
    // 2. Inline $request->validate([...]).
    foreach ((new NodeFinder())->findInstanceOf($method->stmts ?? [], Node\Expr\MethodCall::class) as $call) {
        if (!$call->name instanceof Node\Identifier || $call->name->toString() !== 'validate') {
            continue;
        }
        foreach ($call->getArgs() as $arg) {
            if ($arg->value instanceof Node\Expr\Array_) {
                return ['source' => 'inline_validate', 'fields' => array_keys_of($arg->value)];
            }
        }
    }
    return ['source' => 'none', 'fields' => []];
}

function array_keys_of(Node\Expr\Array_ $arr): array
{
    $keys = [];
    foreach ($arr->items as $item) {
        if ($item !== null && $item->key instanceof Node\Scalar\String_) {
            $keys[] = $item->key->value;
        }
    }
    return $keys;
}

/** Static model references in a controller method, resolved against known models. */
function model_refs(Node\Stmt\ClassMethod $method, array $uses, string $namespace, array $model_set): array
{
    $names = [];
    $finder = new NodeFinder();
    foreach ($finder->findInstanceOf($method, Node\Expr\StaticCall::class) as $call) {
        if ($call->class instanceof Node\Name) {
            $names[] = $call->class->toString();
        }
    }
    foreach ($finder->findInstanceOf($method, Node\Expr\New_::class) as $new) {
        if ($new->class instanceof Node\Name) {
            $names[] = $new->class->toString();
        }
    }
    foreach ($finder->findInstanceOf($method, Node\Expr\ClassConstFetch::class) as $fetch) {
        if ($fetch->class instanceof Node\Name) {
            $names[] = $fetch->class->toString();
        }
    }
    foreach ($method->params as $param) {
        if ($param->type instanceof Node\Name) {
            $names[] = $param->type->toString();
        }
    }
    $refs = [];
    foreach (array_unique($names) as $name) {
        $fqcn = resolve_name($name, $uses, $namespace);
        if (in_array($fqcn, $model_set, true)) {
            $refs[$fqcn] = true;
        }
    }
    return array_keys($refs);
}

// ---- 1. models -------------------------------------------------------------
$models = [];
foreach (php_files($repo . '/app/Models') as $file) {
    $ast = parse_file($file);
    $class = first_class($ast);
    if ($class === null || $class->name === null) {
        continue;
    }
    $namespace = namespace_of($ast);
    $uses = use_map($ast);
    $class_name = $class->name->toString();
    $models[] = [
        'class' => ($namespace !== '' ? $namespace . '\\' : '') . $class_name,
        'table' => table_for($class_name, string_value(property_default($class, 'table'))),
        'fillable' => string_list(property_default($class, 'fillable')),
        'relationships' => relationships($class, $uses, $namespace),
    ];
}
$model_set = array_map(static fn(array $m): string => $m['class'], $models);

// ---- 2. migrations ---------------------------------------------------------
$migrations = [];
foreach (php_files($repo . '/database/migrations') as $file) {
    $ast = parse_file($file);
    foreach ((new NodeFinder())->findInstanceOf($ast, Node\Expr\StaticCall::class) as $call) {
        if (
            !$call->class instanceof Node\Name
            || $call->class->getLast() !== 'Schema'
            || !$call->name instanceof Node\Identifier
            || $call->name->toString() !== 'create'
        ) {
            continue;
        }
        $args = $call->getArgs();
        if (count($args) < 2) {
            continue;
        }
        $table = string_value($args[0]->value);
        if ($table === null) {
            continue;
        }
        $columns = [];
        $closure = $args[1]->value;
        $body = $closure instanceof Node\Expr\Closure ? $closure->stmts : [];
        foreach ((new NodeFinder())->findInstanceOf($body, Node\Expr\MethodCall::class) as $col) {
            if (!$col->name instanceof Node\Identifier) {
                continue;
            }
            $method_name = $col->name->toString();
            if ($method_name === 'id') {
                $columns[] = 'id';
            } elseif ($method_name === 'timestamps' || $method_name === 'timestampsTz') {
                $columns[] = 'created_at';
                $columns[] = 'updated_at';
            } elseif ($method_name === 'softDeletes') {
                $columns[] = 'deleted_at';
            } elseif ($method_name === 'rememberToken') {
                $columns[] = 'remember_token';
            } elseif (in_array($method_name, COLUMN_TYPES, true)) {
                $name = string_value(($col->getArgs()[0] ?? null)?->value);
                if ($name !== null) {
                    $columns[] = $name;
                }
            }
        }
        $migrations[] = ['table' => $table, 'columns' => array_values(array_unique($columns))];
    }
}

// ---- 3. controller actions -------------------------------------------------
$actions = [];
foreach (php_files($repo . '/app/Http/Controllers') as $file) {
    $ast = parse_file($file);
    $class = first_class($ast);
    if ($class === null || $class->name === null) {
        continue;
    }
    $namespace = namespace_of($ast);
    $uses = use_map($ast);
    $controller = ($namespace !== '' ? $namespace . '\\' : '') . $class->name->toString();
    foreach ($class->getMethods() as $method) {
        if (!$method->isPublic() || $method->name->toString() === '__construct') {
            continue;
        }
        $actions[] = [
            'controller' => $controller,
            'action' => $method->name->toString(),
            'model_refs' => model_refs($method, $uses, $namespace, $model_set),
            'validation' => action_validation($method, $uses, $namespace, $repo),
        ];
    }
}

echo json_encode([
    'models' => $models,
    'migrations' => $migrations,
    'actions' => $actions,
]);
exit(0);
