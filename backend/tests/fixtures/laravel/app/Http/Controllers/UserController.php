<?php

namespace App\Http\Controllers;

use App\Http\Requests\StoreUserRequest;
use Illuminate\Http\Request;

class UserController extends Controller
{
    // Validation comes from the type-hinted FormRequest.
    public function store(StoreUserRequest $request)
    {
        return response()->json([], 201);
    }

    // Validation is inline.
    public function update(Request $request, int $user)
    {
        $validated = $request->validate([
            'name' => 'sometimes|string|max:255',
            'age' => 'nullable|integer|min:18|max:120',
            'email' => 'sometimes|email|unique:users,email',
        ]);

        return response()->json($validated);
    }

    public function health()
    {
        return response()->json(['status' => 'ok']);
    }
}
