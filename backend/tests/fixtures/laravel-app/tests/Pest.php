<?php

use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

// Every Feature test boots the app, migrates a fresh sqlite DB, and seeds the
// baseline. The PestRunner writes generated tests into tests/Feature/_generated.
uses(TestCase::class, RefreshDatabase::class)->in('Feature');
