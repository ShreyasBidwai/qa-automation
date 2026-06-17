<?php

// Minimal Laravel routes snippet used as an ingestion fixture (offline tests).
// The canned `route:list --json` output in the tests mirrors these routes.

use App\Http\Controllers\UserController;
use Illuminate\Support\Facades\Route;

Route::middleware('auth:sanctum')->group(function () {
    // Validated via a type-hinted FormRequest (StoreUserRequest).
    Route::post('users', [UserController::class, 'store'])->name('users.store');

    // Validated inline via $request->validate([...]).
    Route::put('users/{user}', [UserController::class, 'update'])->name('users.update');
});

// Public endpoint (no auth middleware).
Route::get('health', [UserController::class, 'health'])->name('health');
