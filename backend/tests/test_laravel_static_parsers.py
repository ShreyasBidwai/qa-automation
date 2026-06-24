"""Static Laravel parsers (ADR-0055) — routes + models/migrations/controllers.

Pure source parsing, no app boot. Covers simple routes, groups (prefix / name /
middleware / controller, nested, array form), resource / apiResource, any / match,
an UNRESOLVABLE controller (recorded, not crashed), migrations → schema, models →
relationships, controller actions → model refs + validation, and that broken/messy
source is tolerated.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.laravel.static_graph import parse_graph
from app.ingestion.laravel.static_routes import parse_routes


def _write(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _routes(repo: Path, body: str, name: str = "web.php"):
    _write(repo, f"routes/{name}", body)
    return parse_routes(str(repo))


# --- routes ------------------------------------------------------------------


def test_simple_route_resolves_controller_via_use_import(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\UserController;
        use Illuminate\\Support\\Facades\\Route;
        Route::get('/users', [UserController::class, 'index'])->name('users.index');
        Route::post('/users', [UserController::class, 'store']);
        """,
    )
    assert r.unresolved == []
    facts = {(f.method, f.uri): f for f in r.facts}
    idx = facts[("GET", "users")]
    assert idx.action == "App\\Http\\Controllers\\UserController@index"
    assert idx.name == "users.index"
    assert (
        facts[("POST", "users")].action
        == "App\\Http\\Controllers\\UserController@store"
    )


def test_group_prefix_name_middleware_and_nesting(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\AdminController;
        use Illuminate\\Support\\Facades\\Route;
        Route::prefix('admin')->name('admin.')->middleware(['auth'])->group(function () {
            Route::get('/dash', [AdminController::class, 'dash'])->name('dash');
            Route::prefix('reports')->group(function () {
                Route::get('/sales', [AdminController::class, 'sales'])->name('sales');
            });
        });
        """,
    )
    facts = {f.uri: f for f in r.facts}
    assert facts["admin/dash"].name == "admin.dash"
    assert facts["admin/dash"].middleware == ["auth"]
    assert facts["admin/dash"].auth_required is True
    assert "admin/reports/sales" in facts
    assert facts["admin/reports/sales"].name == "admin.sales"
    assert facts["admin/reports/sales"].middleware == ["auth"]  # inherited


def test_group_array_form_and_controller_group(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\Api\\ThingController;
        use Illuminate\\Support\\Facades\\Route;
        Route::group(['prefix' => 'v1', 'as' => 'v1.', 'middleware' => ['auth:sanctum']], function () {
            Route::controller(ThingController::class)->group(function () {
                Route::get('/things', 'index')->name('things');
                Route::post('/things', 'store');
            });
        });
        """,
    )
    facts = {(f.method, f.uri): f for f in r.facts}
    show = facts[("GET", "v1/things")]
    assert show.action == "App\\Http\\Controllers\\Api\\ThingController@index"
    assert show.name == "v1.things"
    assert show.auth_required is True  # auth:sanctum
    assert facts[("POST", "v1/things")].action.endswith("ThingController@store")


def test_resource_and_api_resource_expand(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\PostController;
        use App\\Http\\Controllers\\TagController;
        use Illuminate\\Support\\Facades\\Route;
        Route::resource('posts', PostController::class);
        Route::apiResource('tags', TagController::class);
        """,
    )
    posts = {(f.method, f.uri) for f in r.facts if f.uri.startswith("posts")}
    assert ("GET", "posts") in posts and ("POST", "posts") in posts
    assert ("GET", "posts/create") in posts and ("GET", "posts/{id}/edit") in posts
    assert ("PUT", "posts/{id}") in posts and ("DELETE", "posts/{id}") in posts
    tags = {(f.method, f.uri) for f in r.facts if f.uri.startswith("tags")}
    # apiResource omits create + edit (web-only).
    assert ("GET", "tags/create") not in tags and ("GET", "tags/{id}/edit") not in tags
    assert ("POST", "tags") in tags and ("DELETE", "tags/{id}") in tags
    names = {f.name for f in r.facts}
    assert "posts.index" in names and "tags.destroy" in names


def test_any_and_match_methods(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\C;
        use Illuminate\\Support\\Facades\\Route;
        Route::any('/hook', [C::class, 'hook']);
        Route::match(['GET', 'POST'], '/cb', [C::class, 'cb']);
        """,
    )
    by_uri = {f.uri: f for f in r.facts}
    assert "GET" in by_uri["hook"].methods and "POST" in by_uri["hook"].methods
    assert by_uri["cb"].methods == ["GET", "POST"]
    assert by_uri["cb"].method == "GET"


def test_unresolvable_action_is_recorded_not_crashed(tmp_path: Path) -> None:
    # The robustness guarantee that replaces the artisan crash: an action that cannot
    # be turned into a class — a bare method string with no controller-group, and a
    # ``$variable`` controller — is RECORDED, not fatal, and the well-formed route
    # alongside them is still emitted. (Static parsing can't load a class, so it can
    # never crash the way ``artisan route:list`` did on a missing controller.)
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\OkController;
        use Illuminate\\Support\\Facades\\Route;
        Route::get('/bare', 'orphanMethod');
        Route::get('/var', [$controller, 'show']);
        Route::get('/ok', [OkController::class, 'index']);
        """,
    )
    blob = " ".join(r.unresolved)
    assert "orphanMethod" in blob and "$controller" in blob  # both recorded
    uris = {f.uri for f in r.facts}
    assert {"bare", "var", "ok"} <= uris  # nothing crashed; all still emitted
    ok = next(f for f in r.facts if f.uri == "ok")
    assert ok.action == "App\\Http\\Controllers\\OkController@index"


def test_api_routes_get_the_api_prefix_convention(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        """<?php
        use App\\Http\\Controllers\\PingController;
        use Illuminate\\Support\\Facades\\Route;
        Route::get('/ping', [PingController::class, 'show']);
        """,
        name="api.php",
    )
    fact = r.facts[0]
    assert fact.uri == "api/ping"
    assert "api" in fact.middleware


def test_malformed_route_file_never_crashes(tmp_path: Path) -> None:
    r = _routes(
        tmp_path,
        "<?php this is not ((( valid php at all ]]] Route::get(",
    )
    assert isinstance(r.facts, list)  # parsed what it could, did not raise


# --- migrations → schema -----------------------------------------------------


def test_migration_columns_extracted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "database/migrations/2024_create_orders.php",
        """<?php
        use Illuminate\\Database\\Schema\\Blueprint;
        use Illuminate\\Support\\Facades\\Schema;
        return new class extends Migration {
            public function up(): void {
                Schema::create('orders', function (Blueprint $table) {
                    $table->id();
                    $table->string('reference');
                    $table->foreignId('user_id');
                    $table->decimal('total', 8, 2);
                    $table->softDeletes();
                    $table->timestamps();
                });
            }
        };
        """,
    )
    graph = parse_graph(str(tmp_path))
    orders = next(m for m in graph.migrations if m.table == "orders")
    assert orders.columns == [
        "id",
        "reference",
        "user_id",
        "total",
        "deleted_at",
        "created_at",
        "updated_at",
    ]


# --- models → relationships --------------------------------------------------


def test_model_table_fillable_and_relationships(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app/Models/Order.php",
        """<?php
        namespace App\\Models;
        use App\\Models\\User;
        use Illuminate\\Database\\Eloquent\\Model;
        class Order extends Model {
            protected $fillable = ['reference', 'total'];
            public function user() { return $this->belongsTo(User::class); }
            public function items() { return $this->hasMany(OrderItem::class); }
        }
        """,
    )
    _write(
        tmp_path,
        "app/Models/Category.php",
        """<?php
        namespace App\\Models;
        use Illuminate\\Database\\Eloquent\\Model;
        class Category extends Model {
            protected $table = 'cats';
        }
        """,
    )
    graph = parse_graph(str(tmp_path))
    order = next(m for m in graph.models if m.cls == "App\\Models\\Order")
    assert order.table == "orders"  # convention pluralise(snake(Order))
    assert order.fillable == ["reference", "total"]
    rels = {(r.name, r.kind, r.related) for r in order.relationships}
    assert ("user", "belongsTo", "App\\Models\\User") in rels
    assert ("items", "hasMany", "App\\Models\\OrderItem") in rels
    cat = next(m for m in graph.models if m.cls == "App\\Models\\Category")
    assert cat.table == "cats"  # explicit $table wins


# --- controllers → actions / model refs / validation ------------------------


def test_controller_actions_model_refs_and_validation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app/Models/Post.php",
        "<?php\nnamespace App\\Models;\nuse Illuminate\\Database\\Eloquent\\Model;\nclass Post extends Model {}\n",
    )
    _write(
        tmp_path,
        "app/Http/Requests/StorePostRequest.php",
        """<?php
        namespace App\\Http\\Requests;
        class StorePostRequest extends FormRequest {
            public function rules(): array {
                return ['title' => 'required', 'body' => 'required'];
            }
        }
        """,
    )
    _write(
        tmp_path,
        "app/Http/Controllers/PostController.php",
        """<?php
        namespace App\\Http\\Controllers;
        use App\\Http\\Requests\\StorePostRequest;
        use App\\Models\\Post;
        class PostController extends Controller {
            public function index() { return Post::all(); }
            public function store(StorePostRequest $request) { return Post::create([]); }
            public function inline($request) {
                $request->validate(['name' => 'required', 'email' => 'email']);
            }
            private function helper() {}
        }
        """,
    )
    graph = parse_graph(str(tmp_path))
    actions = {a.action: a for a in graph.actions}
    assert "helper" not in actions  # private excluded
    assert actions["index"].model_refs == ["App\\Models\\Post"]
    assert actions["store"].validation.source == "form_request"
    assert actions["store"].validation.fields == ["title", "body"]
    assert actions["inline"].validation.source == "inline_validate"
    assert actions["inline"].validation.fields == ["name", "email"]


def test_messy_controller_does_not_abort_the_rest(tmp_path: Path) -> None:
    # A broken/duplicate file must not stop the good ones being parsed.
    _write(
        tmp_path,
        "app/Http/Controllers/_original/OldController.php",
        "<?php this file is broken {{{ no class here",
    )
    _write(
        tmp_path,
        "app/Http/Controllers/GoodController.php",
        "<?php\nnamespace App\\Http\\Controllers;\nclass GoodController extends Controller { public function ok() { return 1; } }\n",
    )
    graph = parse_graph(str(tmp_path))
    assert any(
        a.controller.endswith("GoodController") and a.action == "ok"
        for a in graph.actions
    )
