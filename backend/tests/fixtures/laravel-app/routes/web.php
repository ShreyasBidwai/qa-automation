<?php

use App\Http\Controllers\UserController;
use Illuminate\Support\Facades\Route;

// Authenticated endpoint under test. Feature tests authenticate with
// actingAs(); an unauthenticated JSON request yields 401.
Route::middleware('auth')->group(function () {
    Route::post('/users', [UserController::class, 'store'])->name('users.store');
});
