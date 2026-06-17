<?php

/**
 * Deterministic validation-rule extractor for the QA Automation Platform.
 *
 * Usage:  php extract_validation.php <repo_path> <controller_fqcn> <action>
 * Output (stdout, JSON):
 *   {"source": "form_request"|"inline_validate"|"none", "class"?: "...",
 *    "rules": {"<field>": "<pipe|rules>" | ["<rule>", ...]}}
 *
 * Uses nikic/php-parser (AST) — never regex. Requires php-parser available via
 * the target repo's vendor/autoload.php (`composer require nikic/php-parser`).
 *
 * NOTE: exercised only in a real/dev run against an actual Laravel repo. In CI
 * the Python side injects a fake CommandRunner, so this script is never invoked
 * by the test suite — its JSON contract is what the tests pin.
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

[$_script, $repo, $controllerFqcn, $action] = array_pad($argv, 4, null);
if ($repo === null || $controllerFqcn === null || $action === null) {
    fail('usage: extract_validation.php <repo_path> <controller_fqcn> <action>');
}

$autoload = rtrim($repo, '/') . '/vendor/autoload.php';
if (!is_file($autoload)) {
    fail('vendor/autoload.php not found in repo; run `composer install`');
}
require $autoload;

if (!class_exists(ParserFactory::class)) {
    fail('nikic/php-parser not installed; run `composer require nikic/php-parser`');
}

/** Map an `App\...` FQCN to a PSR-4 file path under <repo>/app. */
function fqcn_to_path(string $repo, string $fqcn): ?string
{
    $fqcn = ltrim($fqcn, '\\');
    if (!str_starts_with($fqcn, 'App\\')) {
        return null;
    }
    $relative = str_replace('\\', '/', substr($fqcn, strlen('App\\')));
    $path = rtrim($repo, '/') . '/app/' . $relative . '.php';
    return is_file($path) ? $path : null;
}

/** @return Node\Stmt[] */
function parse_file(string $path): array
{
    $parser = (new ParserFactory())->createForNewestSupportedVersion();
    return $parser->parse((string) file_get_contents($path)) ?? [];
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

function find_method(array $ast, string $name): ?Node\Stmt\ClassMethod
{
    foreach ((new NodeFinder())->findInstanceOf($ast, Node\Stmt\ClassMethod::class) as $m) {
        if ($m->name->toString() === $name) {
            return $m;
        }
    }
    return null;
}

/** Convert a validation-rules array literal into {field: string|list}. */
function rules_from_array(?Node\Expr\Array_ $arr): array
{
    $rules = [];
    if ($arr === null) {
        return $rules;
    }
    foreach ($arr->items as $item) {
        if ($item === null || !$item->key instanceof Node\Scalar\String_) {
            continue;
        }
        $field = $item->key->value;
        $value = $item->value;
        if ($value instanceof Node\Scalar\String_) {
            $rules[$field] = $value->value;
        } elseif ($value instanceof Node\Expr\Array_) {
            $tokens = [];
            foreach ($value->items as $tok) {
                if ($tok !== null && $tok->value instanceof Node\Scalar\String_) {
                    $tokens[] = $tok->value->value;
                }
            }
            $rules[$field] = $tokens;
        }
        // Fluent Rule:: objects / variables are skipped — Sprint 2.
    }
    return $rules;
}

function emit(array $payload): never
{
    echo json_encode($payload);
    exit(0);
}

$controllerPath = fqcn_to_path($repo, $controllerFqcn);
if ($controllerPath === null) {
    fail("controller file not found for {$controllerFqcn}");
}
$controllerAst = parse_file($controllerPath);
$method = find_method($controllerAst, $action);
if ($method === null) {
    fail("action {$action} not found in {$controllerFqcn}");
}
$uses = use_map($controllerAst);

// 1. Type-hinted FormRequest parameter → resolve its rules().
foreach ($method->params as $param) {
    if (!$param->type instanceof Node\Name) {
        continue;
    }
    $fqcn = $uses[$param->type->getLast()] ?? $param->type->toString();
    $requestPath = fqcn_to_path($repo, $fqcn);
    if ($requestPath === null) {
        continue;
    }
    $rulesMethod = find_method(parse_file($requestPath), 'rules');
    if ($rulesMethod === null) {
        continue;
    }
    $return = (new NodeFinder())->findFirstInstanceOf(
        $rulesMethod->stmts ?? [],
        Node\Stmt\Return_::class
    );
    if ($return !== null && $return->expr instanceof Node\Expr\Array_) {
        emit([
            'source' => 'form_request',
            'class' => $fqcn,
            'rules' => rules_from_array($return->expr),
        ]);
    }
}

// 2. Inline $request->validate([...]).
foreach ((new NodeFinder())->findInstanceOf($method->stmts ?? [], Node\Expr\MethodCall::class) as $call) {
    if (!$call->name instanceof Node\Identifier || $call->name->toString() !== 'validate') {
        continue;
    }
    foreach ($call->args as $arg) {
        if ($arg instanceof Node\Arg && $arg->value instanceof Node\Expr\Array_) {
            emit(['source' => 'inline_validate', 'rules' => rules_from_array($arg->value)]);
        }
    }
}

emit(['source' => 'none', 'rules' => (object) []]);
