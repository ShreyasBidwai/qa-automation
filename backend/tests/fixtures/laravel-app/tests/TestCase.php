<?php

namespace Tests;

use Illuminate\Foundation\Testing\TestCase as BaseTestCase;

abstract class TestCase extends BaseTestCase
{
    // RefreshDatabase re-seeds DatabaseSeeder before each test, establishing
    // the baseline the generated plan's db-dependencies rely on.
    protected $seed = true;
}
