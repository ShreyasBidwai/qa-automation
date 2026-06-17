<?php

namespace Database\Seeders;

use App\Models\Country;
use App\Models\User;
use Illuminate\Database\Seeder;

/**
 * Baseline DB state the generated plan's db-dependencies need:
 *  - one Country (id = 1) → a valid `exists:countries,id` reference,
 *  - one User with a known email → the `unique:users,email` duplicate case.
 *
 * RefreshDatabase re-seeds this before every test (TestCase::$seed = true).
 */
class DatabaseSeeder extends Seeder
{
    public const EXISTING_EMAIL = 'existing@example.com';

    public function run(): void
    {
        Country::create(['name' => 'Seedland']);

        User::create([
            'name' => 'Seed User',
            'email' => self::EXISTING_EMAIL,
            'age' => 30,
            'country_id' => 1,
            'newsletter' => false,
        ]);
    }
}
