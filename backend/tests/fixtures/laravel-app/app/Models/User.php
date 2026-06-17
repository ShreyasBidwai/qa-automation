<?php

namespace App\Models;

use Illuminate\Foundation\Auth\User as Authenticatable;

class User extends Authenticatable
{
    protected $fillable = [
        'name',
        'email',
        'age',
        'country_id',
        'newsletter',
    ];

    protected $casts = [
        'age' => 'integer',
        'newsletter' => 'boolean',
    ];
}
