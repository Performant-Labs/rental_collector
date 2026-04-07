# Hanging Processes — Root Causes & Solutions

This document catalogs every type of process hang encountered in DDEV/Drupal/Playwright workflows, explains why each hang occurs, and provides the fix.

---

## Quick Reference

### A. DDEV / Environment

| # | Hang Type | Symptom | Fix |
|---|-----------|---------|-----|
| 4 | DDEV command hangs | `ddev drush` never returns | Verify with `ddev describe` first |
| 11 | Duplicate DDEV port conflicts | Random failures, wrong site content | Stop unused project: `ddev stop` |
| 13 | Nested DDEV project error | `ddev start` fails or behaves oddly | Remove parent `~/Sites/.ddev/` |
| 19 | DDEV `stop` flag confusion | `ddev stop -y` fails | Use `ddev stop projectname` (no `-y`) |
| 20 | DDEV port variability | Tests fail with connection refused | Check `ddev describe`, update config |
| 26 | `php:eval` entity save hang | `ddev drush php:eval` with `->save()` hangs silently for 10+ min | Check logs at 10s; use `config:import --partial` instead |

### B. Playwright / Testing

| # | Hang Type | Symptom | Fix |
|---|-----------|---------|-----|
| 1 | Playwright `networkidle` | **All tests freeze** during login | Use `waitForLoadState('load')` |
| 2 | Playwright long timeouts | Tests wait 2+ min for missing elements | Set `timeout: 30000`, `expect.timeout: 5000` |
| 8 | Locator matches admin toolbar | Assertion fails on hidden element | Scope locators to `main` element |
| 22 | Silent Playwright Failures (Zombie Code) | Code changes do not reflect in tests | Rebuild and deploy bundle to proxy via `cp` |

### C. Drupal Configuration

| # | Hang Type | Symptom | Fix |
|---|-----------|---------|-----|
| 5 | Config import hangs | `drush config:import` stalls | Check `ddev logs -s web` |
| 6 | `event_type` vs `event_types` | Event Type dropdown empty | Use `event_types` (**plural**) |
| 7 | `taxonomy_access_fix` blocking | Select has zero options | Grant `select terms in {vocab}` perm |
| 9 | Missing form display configs | Form field not rendered | Import `core.entity_form_display` YAML |
| 15 | WSOD from missing field storage | White screen after config import | `drush entity-updates` |
| 16 | Markdown filter escaping HTML | `<strong>` displays as text | Disable markdown filter in `full_html` |
| 17 | Missing enrollment sub-modules | Enroll button missing or 403 | Enable `social_event_an_enroll` + perms |

### D. Module / Library Issues

| # | Hang Type | Symptom | Fix |
|---|-----------|---------|-----|
| 10 | PHP opcode cache stale class | Web can't find class CLI sees | `ddev restart` (not just `drush cr`) |
| 14 | Custom module stale registry | Module exists but not found by Drupal | Uninstall, fix path, reinstall |
| 18 | Missing frontend libraries | JS errors, broken UI animations | Copy `node-waves`, `autosize` to `web/libraries/` |

### E. Process Cleanup

| # | Hang Type | Symptom | Fix |
|---|-----------|---------|-----|
| 3 | Orphan Playwright processes | `node` processes persist after cancel | Run `kill-zombies.sh` |
| 12 | `pkill` self-kill bug | Cleanup script kills itself | Use `pkill -f "node.*playwright"` |
| 21 | Agent approval gate | Command sits forever, no output | Agent must use `SafeToAutoRun: true` for safe commands |

---

## 1. Playwright `networkidle` Hang

### Symptom
Every test freezes immediately after the `beforeEach` login step. The test runner shows a test name but never progresses. Appears stuck indefinitely.

### Root Cause
The `beforeEach` hook calls:
```typescript
await page.waitForLoadState('networkidle');
```
`networkidle` waits until there are **zero network connections for 500ms**. Many Drupal distributions have perpetual background AJAX requests (heartbeat polling, notification checks, etc.) that **never stop**. The condition never resolves.

### Detection
- Tests hang consistently on the first test
- No timeout error appears (the wait is inside `beforeEach`, not subject to assertion timeouts)
- Killing the process and checking the test file reveals `networkidle`

### Solution
Change `networkidle` to `load` in the test's `beforeEach` hook:
```typescript
// ❌ WRONG — hangs forever with Open Social
await page.waitForLoadState('networkidle');

// ✅ CORRECT — completes after page loads
await page.waitForLoadState('load');
```

### Prevention
- **Never use `networkidle`** with any Drupal site that has background AJAX
- Add a comment in the test file explaining why `load` is used

---

## 2. Playwright Long Timeout Hang

### Symptom
A test waits 2+ minutes before failing. It looks stuck but is actually waiting for a missing element with an excessively long timeout.

### Root Cause
Default Playwright timeouts are generous:
- Test timeout: `120000ms` (2 minutes)
- Assertion timeout: `30000ms` (30 seconds)

When a UI element is missing (e.g., due to a Drupal config gap), Playwright retries for the full timeout duration before reporting a failure.

### Detection
- Test eventually fails with "Test timeout of 120000ms exceeded"
- The error shows "waiting for locator..." with many retry attempts
- The test itself is not stuck — it's just waiting too long

### Solution
Set fail-fast timeouts in `playwright.config.ts`:
```typescript
export default defineConfig({
    timeout: 30000,       // 30s per test (was 120s)
    expect: {
        timeout: 5000     // 5s per assertion (was 30s)
    },
    // ...
});
```

### Prevention
- Always set these timeouts when configuring a new test environment

---

## 3. Orphan Playwright / Node Processes

### Symptom
After cancelling a test run, `node` and `chromium` processes remain running. Subsequent test runs may fail with port conflicts or resource exhaustion. The `kill-zombies.sh` script reports these.

### Root Cause
When Playwright is interrupted (SIGTERM/SIGINT), the parent `node` process may die but its child Chromium browser processes survive. Similarly, `npx` may leave behind orphan `node` processes.

### Detection
```bash
# Check for orphan Playwright processes
pgrep -f "playwright" | head
pgrep -f "chromium" | head
```

### Solution
Run the zombie cleanup script if your project has one:
```bash
bash /path/to/your/project/scripts/kill-zombies.sh
```

Or manually:
```bash
pkill -f "node.*playwright"
pkill -f "chromium"
```

### Prevention
- Run process cleanup **before** every test phase
- Always let tests complete rather than cancelling mid-run when possible

---

## 4. DDEV Command Hangs

### Symptom
A `ddev drush` or `ddev exec` command never returns. The terminal sits with no output.

### Root Cause
Multiple possible causes:
1. **Targeting a stopped project**: If the DDEV project isn't running but you issue `ddev drush` from its directory, the command hangs waiting for the container
2. **Container unhealthy**: The web or database container is in a degraded state
3. **PHP fatal error in Drush**: A bootstrap error can cause Drush to hang silently

### Detection
```bash
# Check if DDEV is running and healthy
ddev describe

# Check container health
docker ps --filter "name=ddev" --format "{{.Names}} {{.Status}}"
```

### Solution
1. **If project isn't running**: Start it with `ddev start`
2. **If container is unhealthy**: `ddev restart`
3. **If stuck**: `Ctrl+C`, then check logs with `ddev logs`

### Prevention
- Always verify DDEV status before running commands: `ddev describe`
- Never issue DDEV commands against a project you haven't confirmed is running
- Set a mental 10-second rule: if `ddev drush` shows nothing for 10s, check container health

---

## 5. Drupal Config Import Hangs

### Symptom
`ddev drush config:import` or `ddev drush php:eval` runs but never completes.

### Root Cause
1. **Module dependency loops**: Importing config that references modules not yet enabled
2. **Database locks**: A previous import or update left a lock
3. **Memory exhaustion**: PHP runs out of memory during large imports

### Detection
```bash
# Check DDEV logs for PHP errors
ddev logs -s web | tail -50

# Check if PHP is still running inside the container
ddev exec ps aux | grep php
```

### Solution
1. `Ctrl+C` the stuck command
2. `ddev drush cr` to clear caches
3. Retry the import
4. If persistent, check `ddev logs -s web` for fatal errors

### Prevention
- Import configs in dependency order (fields before form displays)
- Clear cache after major config changes: `ddev drush cr`

---

## 6. Taxonomy `event_type` vs `event_types` Silent Failure

### Symptom
Event Type dropdown appears on the form but has **zero options** — only "- Select a value -". No error is displayed. Tests waiting to select an option hang until timeout.

### Root Cause
The vocabulary machine name may differ from what was used when creating terms (e.g., `event_types` plural vs `event_type` singular). Drupal silently accepts terms with a non-existent `vid` — the terms are saved to the database but orphaned. The `taxonomy_access_fix` module's `TermSelection` handler calls `loadTree()` with the wrong name, which returns nothing because the vocabulary doesn't exist under that name.

### Detection
```bash
# Check actual vocabulary names
ddev drush php:eval '
$vocabs = \Drupal::entityTypeManager()->getStorage("taxonomy_vocabulary")->loadMultiple();
foreach ($vocabs as $v) echo $v->id() . " => " . $v->label() . "\n";
'

# Check if terms are in the right vocabulary
ddev drush php:eval '
echo "event_type: " . count(\Drupal::entityTypeManager()->getStorage("taxonomy_term")->loadByProperties(["vid" => "event_type"])) . "\n";
echo "event_types: " . count(\Drupal::entityTypeManager()->getStorage("taxonomy_term")->loadByProperties(["vid" => "event_types"])) . "\n";
'
```

### Solution
Delete orphaned terms and recreate with the correct `vid`:
```bash
ddev drush php:eval '
// Delete orphans
$terms = \Drupal::entityTypeManager()->getStorage("taxonomy_term")->loadByProperties(["vid" => "event_type"]);
foreach ($terms as $t) { $t->delete(); }

// Recreate with correct vid
foreach (["User group meeting", "DrupalCon", "Sprint"] as $name) {
  \Drupal\taxonomy\Entity\Term::create(["vid" => "event_types", "name" => $name])->save();
}
'
```

### Prevention
- Always verify vocabulary machine names before creating terms:
  ```bash
  ddev drush ev 'echo \Drupal::entityTypeManager()->getStorage("taxonomy_vocabulary")->load("your_vocab_name")->label();'
  ```

---

## 7. `taxonomy_access_fix` Blocking Select Options

### Symptom
Same as #6 — Event Type dropdown is empty. But terms DO exist in the correct vocabulary.

### Root Cause
The `taxonomy_access_fix` module overrides Drupal's default entity reference selection handler with `Drupal\taxonomy_access_fix\TermSelection`. This handler checks `$term->access('select')` per-term, which requires the `select terms in {vocabulary_name}` permission. Without it, the handler returns zero results.

### Detection
```bash
ddev drush php:eval '
$handler = \Drupal::service("plugin.manager.entity_reference_selection")->getSelectionHandler(
  \Drupal\node\Entity\Node::create(["type" => "your_content_type"])->getFieldDefinition("field_your_vocab_ref")
);
echo get_class($handler) . "\n";
echo "Options: " . array_sum(array_map("count", $handler->getReferenceableEntities())) . "\n";
'
```

If handler is `TermSelection` and count is 0, this is the issue.

### Solution
Grant the permission (replace `your_vocab_name` with the actual vocabulary machine name):
```bash
ddev drush role:perm:add authenticated "select terms in your_vocab_name"
ddev drush role:perm:add administrator "select terms in your_vocab_name"
```

### Prevention
- After creating taxonomy terms, always verify they appear in form selects

---

## 10. PHP Opcode Cache Stale Class

### Symptom
The web process throws "class not found" errors even though CLI (`ddev drush`) can see the class just fine. The module is installed, the file exists, but the web server can't find it.

### Root Cause
PHP's opcode cache (`opcache`) caches compiled bytecode in memory. When a module's PHP files are added or modified while the web server is running, the opcache may still serve the old (or absent) bytecode. CLI uses a separate opcache instance, so it works fine.

### Detection
- `ddev drush php:eval 'echo class_exists("Drupal\\mymodule\\MyClass") ? "YES" : "NO";'` returns YES
- But the web interface throws "class not found" or filter plugin errors

### Solution
```bash
ddev restart
```
This flushes the PHP opcode cache by restarting the web container.

### Prevention
- Always run `ddev restart` (not just `ddev drush cr`) after copying new PHP files into `web/modules/`
- `ddev drush cr` clears Drupal caches but does NOT flush PHP's opcache

---

## 11. Duplicate DDEV Project Port Conflicts

### Symptom
Tests get random failures, unexpected responses, or the wrong site content. A test pointed at one DDEV project may unexpectedly see content from a different project.

### Root Cause
Two DDEV projects running simultaneously can conflict on ports or cause the DDEV router to misdirect traffic, especially if they were configured with similar domain patterns.

### Detection
```bash
# List all running DDEV projects
ddev list

# Check for port conflicts
docker ps --format "{{.Names}} {{.Ports}}" | grep ddev
```

### Solution
Stop the project you're not using:
```bash
cd /path/to/other-project && ddev stop
```

### Prevention
- Before running tests, always stop any DDEV project you're not actively using
- Never issue `ddev drush` commands from a directory whose DDEV project isn't running — this can hang indefinitely (see #4)

---

## 12. `pkill -f "playwright"` Self-Kill Bug

### Symptom
Running `pkill -f "playwright"` to clean up zombie processes kills its own parent shell. The cleanup command appears to hang or the terminal closes unexpectedly.

### Root Cause
`pkill -f "playwright"` pattern-matches against all processes whose command line contains "playwright" — including the shell running the `pkill` command itself (since the command line contains the string "playwright").

### Detection
- Terminal closes or becomes unresponsive after running `pkill -f "playwright"`
- The zombie processes may or may not actually get killed

### Solution
Use a more specific pattern that excludes `pkill` itself:
```bash
# ❌ WRONG — kills itself
pkill -f "playwright"

# ✅ CORRECT — only matches node playwright processes  
pkill -f "node.*playwright"
```

### Prevention
- The `kill-zombies.sh` script already uses the corrected pattern
- Never use bare `pkill -f` with a simple string that could match the command itself

---

## 13. Nested DDEV Project Error

### Symptom
`ddev start` fails with a "nested project" error, or DDEV behaves unpredictably. Configs from a parent directory's `.ddev/` folder interfere with the project's own DDEV configuration.

### Root Cause
An accidental `.ddev/` folder exists in a parent directory (e.g., in `~/Sites/` or another ancestor). DDEV walks up the directory tree looking for project configuration and finds this stray folder, causing a "nested project" conflict or configuration confusion.

### Detection
```bash
# Check for stray .ddev folders above the project
ls -la "$(dirname $(pwd))"/.ddev 2>/dev/null && echo "FOUND — remove this"
```

### Solution
Remove the stray `.ddev` folder from the parent directory:
```bash
rm -rf /path/to/parent/.ddev
```

### Prevention
- Never run `ddev config` from a shared parent directory like `~/Sites/`
- If you see a "nested project" error, check parent directories for `.ddev/`

---

## 14. Custom Module Stale Registry (Flat Copy)

### Symptom
A custom module is installed and the files exist in `web/modules/custom/`, but Drupal can't find it or reports "module not found" errors. The module was previously working.

### Root Cause
The module files were copied flat into `web/modules/custom/` (e.g., the `.info.yml` directly in `custom/`) instead of inside a proper subdirectory (`custom/my_module/my_module.info.yml`). Alternatively, the module was moved or renamed after being enabled, and Drupal's extension discovery cache still points to the old location.

### Detection
```bash
# Verify directory structure
ls web/modules/custom/my_module/
# Should contain: my_module.info.yml, src/, etc.

# If info.yml is directly in custom/ — that's the problem
ls web/modules/custom/*.info.yml
```

### Solution
1. Uninstall the module: `ddev drush pmu my_module -y`
2. Remove the incorrectly placed files
3. Re-copy with correct structure:
   ```bash
   cp -r /path/to/source/web/modules/custom/my_module \
         /path/to/dest/web/modules/custom/my_module
   ```
4. Clear cache: `ddev drush cr`
5. Re-enable: `ddev drush en my_module -y`
6. Restart to flush opcache: `ddev restart`

### Prevention
- Always copy module directories, not individual files
- Always use `cp -r source/module_name/ destination/module_name/` preserving the directory structure
- After copying modules, `ddev restart` (not just `ddev drush cr`) to ensure opcache picks up the new files

---

## 21. Agent Approval Gate (False Hang)

### Symptom
A command appears to hang indefinitely — no output, no error, no progress. It looks exactly like a stuck process, but the command never actually started. The terminal just sits there.

### Root Cause
The AI agent submitted the command with `SafeToAutoRun: false`, which means VS Code queues the command for **manual user approval** before executing it. However, the VS Code UI often **does not show an expand button or approval button** — the command is queued invisibly with no way the user can approve it. The command silently never runs, and the agent appears permanently stuck.

This is especially deceptive for obviously safe commands like `ddev export-db` (which just writes a file) or `ddev drush cr` (which clears caches).

### Detection
- The command has been queued but there is **zero output** — not even a partial line
- There is **no visible approval button or expand button** in the VS Code UI
- The process is not visible in `ps aux` because it was never launched
- The only way to break out is to cancel the agent

### Solution
1. Cancel the agent's current operation
2. Tell the agent to re-run the command — it will complete in seconds
3. If exit code 130 appears on retry, that's SIGINT residue from the cancel — just try once more

### Commands That Should ALWAYS Be Auto-Run
These commands are safe and should never wait for approval:
- `ddev export-db` — writes a backup file
- `ddev drush cr` — clears caches
- `ddev drush status` — read-only status
- `ddev describe` / `ddev list` — read-only info
- `mkdir -p` — creates directories
- `ls`, `cat`, `grep`, `head`, `tail` — read-only
- `cp -r` (for module/config copying) — safe in context
- `npx playwright test` — runs tests

### Prevention
- The agent should mark all non-destructive commands as `SafeToAutoRun: true`
- Only destructive commands (e.g., `rm -rf`, `ddev delete`, `git push --force`) should require approval

---

## 15. WSOD from Missing Field Storage

### Symptom
White Screen of Death (WSOD) or a PHP fatal error immediately after importing a field configuration. The site becomes completely inaccessible via web browser. Drush commands may also fail.

### Root Cause
A field configuration YAML (e.g., `field.field.node.event.field_event_url`) was imported, but the underlying database storage table for that field doesn't exist. Drupal tries to query a non-existent table and crashes.

### Detection
```bash
# Check DDEV web logs for the PHP fatal
ddev logs -s web | tail -20
# Look for: "SQLSTATE[42S02]: Base table or view not found"
```

### Solution
Synchronize the field storage definitions:
```bash
ddev drush entity-updates
# or for specific fields:
ddev drush php:eval '
$update_manager = \Drupal::entityDefinitionUpdateManager();
$update_manager->applyUpdates();
echo "Storage updates applied.\n";
'
```

### Prevention
- Always import field **storage** configs before field **instance** configs
- If a field already existed but was removed, ensure the storage table is recreated before re-importing
- Check `ddev logs -s web` immediately after config imports for early warning signs

---

## 16. Markdown Filter Escaping HTML

### Symptom
Content with `<strong>`, `<a>`, or other HTML tags displays the raw HTML as text instead of rendering it. For example, `<strong>bold</strong>` shows as literal text on the page. Tests checking for rendered HTML fail.

### Root Cause
The `markdown` filter is enabled in the `full_html` text format. When active, it processes the content through a Markdown parser that escapes HTML entities, converting `<` to `&lt;`. This means raw HTML typed into CKEditor gets double-escaped.

### Detection
- View a node's rendered output and see literal `<strong>` text instead of bold
- Check text format config:
```bash
ddev drush php:eval '
$format = \Drupal\filter\Entity\FilterFormat::load("full_html");
foreach ($format->filters() as $id => $filter) {
  if ($filter->status) echo "$id (weight: " . $filter->weight . ")\n";
}
'
```
If `filter_markdown` or `markdown` appears, that's the issue.

### Solution
Disable the markdown filter in `full_html`:
```bash
ddev drush php:eval '
$format = \Drupal\filter\Entity\FilterFormat::load("full_html");
$config = $format->filters("filter_markdown");
// Disable it
$format->setFilterConfig("filter_markdown", ["status" => FALSE]);
$format->save();
echo "Markdown filter disabled in full_html.\n";
'
```

### Prevention
- Markdown and CKEditor are fundamentally incompatible — don't enable both on the same text format

---

## 17. Missing Feature Sub-Modules

### Symptom
A feature button or action is missing from pages, or clicking it returns a 403 Forbidden error. Tests checking for that functionality fail.

### Root Cause
Some Drupal distribution features are split across sub-modules that are not enabled by default. The required sub-module must be explicitly enabled, and the relevant roles need explicit permissions granted.

### Detection
```bash
# Check if the required module is enabled
ddev drush pm:list --status=enabled | grep my_feature_module

# Check relevant permissions
ddev drush role:perm:list authenticated | grep "feature keyword"
```

### Solution
```bash
# Enable required sub-modules
ddev drush en my_feature_module my_feature_submodule -y

# Grant required permissions
ddev drush role:perm:add authenticated "required permission string"
ddev drush role:perm:add anonymous "required permission string"
```

### Prevention
- Always verify the feature UI after enabling modules
- Check module README or install hooks for required companion modules and permissions

---

## 18. Missing Frontend Libraries

### Symptom
JavaScript errors in the browser console. UI animations don't work. Buttons may appear unstyled. PHP warnings about missing `file_get_contents` for library files.

### Root Cause
Some libraries required by the Drupal project are not installed by Composer by default or are expected in `web/libraries/` but are missing.

### Detection
```bash
# Check for a missing library (replace with actual library name)
ls web/libraries/my-library 2>/dev/null || echo "MISSING: my-library"

# Check PHP warnings in DDEV logs
ddev logs -s web | grep "file_get_contents.*libraries"
```

### Solution
Install via Composer (preferred):
```bash
composer require oomphinc/composer-installers-extender
```
Or copy from a working environment:
```bash
cp -r /path/to/source/web/libraries/my-library /path/to/dest/web/libraries/
```

### Prevention
- After `composer install`, verify `web/libraries/` contains all expected packages
- Add missing libraries to `composer.json` so they install automatically

---

## 19. DDEV `stop` Flag Confusion

### Symptom
Running `ddev stop -y` or `ddev stop -p projectname` fails with unexpected errors. The DDEV project doesn't stop.

### Root Cause
`ddev stop` does not support the `-y` confirmation flag (it doesn't ask for confirmation). The `-p` flag is also not a valid flag for `ddev stop`. These are common assumptions carried over from other CLI tools.

### Correct Usage
```bash
# Stop the current project (from within project directory)
ddev stop

# Stop a specific project by name
ddev stop projectname

# Stop AND remove project data
ddev delete --omit-snapshot -y
```

### Prevention
- Run `ddev stop --help` if unsure about flags
- For cleanup, use `ddev delete --omit-snapshot -y` which does accept `-y`

---

## 20. DDEV Port Variability

### Symptom
Tests fail with "connection refused" or connect to the wrong site. The `playwright.config.ts` has a `baseURL` with a port that doesn't match the actual DDEV project.

### Root Cause
DDEV assigns HTTPS ports that can vary by environment. Common ports include `8443` and `8493`. The port depends on the DDEV router configuration, whether other projects are running, and the host system's port availability.

### Detection
```bash
# Get the actual URL including port
ddev describe | grep -i url
```

### Solution
Update `playwright.config.ts` to match the actual DDEV port:
```typescript
// Check `ddev describe` output and use the correct port
baseURL: 'https://your-project.ddev.site:ACTUAL_PORT'
```

### Prevention
- Always run `ddev describe` before configuring test URLs
- Store the URL in an environment variable to avoid hardcoding:
  ```bash
  export PLAYWRIGHT_BASE_URL=$(ddev describe -j | jq -r '.raw.primary_url')
  ```

---

## 8. Test Locator Matching Admin Toolbar

### Symptom
A test assertion like `a:has-text("Enroll")` resolves to a hidden admin toolbar element instead of the visible page content. Test fails with "Expected: visible / Received: hidden".

### Root Cause
Drupal's admin toolbar contains links to configuration pages that can match broad locators. The toolbar elements are technically in the DOM but are hidden or positioned off-screen.

### Detection
The Playwright error log shows "locator resolved to" followed by an admin toolbar element:
```
locator resolved to <a href="/admin/config/..." ...>Admin Link Text</a>
```

### Solution
Scope all locators to the `main` element:
```typescript
// ❌ WRONG — matches admin toolbar
page.locator('a:has-text("Enroll")').first()

// ✅ CORRECT — scoped to page content
page.locator('main a:has-text("Enroll")').first()
```

### Prevention
- All test locators should be scoped to `main` to avoid admin toolbar collisions

---

## 9. Missing Form Display Configs

### Symptom
A form field (e.g., Event Type dropdown, revision log textarea) does not appear on the node add/edit form. Tests waiting for it hang until timeout.

### Root Cause
Drupal's form display configs (`core.entity_form_display.node.*.default.yml`) control which fields appear on forms and in what order. If these configs aren't imported, the field exists in the database but isn't rendered on the form.

### Detection
```bash
# Check what fields are in the form display
ddev drush php:eval '
$fd = \Drupal::entityTypeManager()->getStorage("entity_form_display")->load("node.event.default");
print_r(array_keys($fd->getComponents()));
'
```

### Solution
Import the form display config:
```bash
ddev drush config:import --partial --source=/path/to/config/sync
# or import specific file
ddev drush php:eval '...'
```

### Prevention
- Always verify form fields appear after config imports

---

## 22. Silent Playwright Failures (Zombie Code)

### Symptom
Playwright E2E tests interact with UI elements and successfully run, but recent changes applied to the source code (e.g., `.ts`, `.vue`) seem perfectly invisible. Diagnostic `console.log` statements added to the code do not appear in the test output.

### Root Cause
The Playwright tests run against a production-like reverse proxy or static server, which serves pre-built, static bundles of the application. If the application is not actively rebuilt (e.g., via `make build` / `pnpm build`) and the resulting `dist/` directory is not copied to where the proxy serves it, the proxy permanently serves the old JavaScript bundle. The tests run against zombie code.

### Detection
- Code modifications (e.g., adding an obvious UI element or `data-testid`) do not show up during the test.
- The `make dev` watcher is active, but Playwright is targeting a non-localhost `baseURL` that is completely disconnected from Vite's Hot Module Replacement (HMR).

### Solution
1. Completely rebuild the frontend application: `pnpm build` (or `npm run build`)
2. Copy the resulting static assets to wherever the proxy serves them:
   ```bash
   cp -r dist/* /path/to/proxy/served/directory/
   ```
3. Clear the browser cache or start a new in-memory context (Playwright does this natively).

### Prevention
- Never assume Vite dev server (HMR) dictates what the E2E framework sees when `baseURL` points to a non-localhost domain.
- Create a `make build-and-deploy` command or incorporate the copy step into the test pipeline's global setup.

---

## 23. Subtree Synchronization Failures (Missing Files)



### Symptom
When a Git Subtree is pulled into a host repository (e.g., via `ai:sync` or `git subtree pull`), the operation completes successfully without error, but recently created or modified files are conspicuously missing from the subtree directory.

### Root Cause
Git subtrees inherently fetch their payloads from the remote upstream repository (e.g., GitHub), not your local file system. If a file was added or modified locally inside the primary source repository (e.g., `~/LocalDevelopment/ai_guidance`) but was never explicitly committed and pushed to the remote origin (`git push origin main`), the downstream host repository has no access to it. The subtree pull natively downloads exactly what was available on the server at the exact moment of the last upstream push.

### Detection
- `git status` inside the host repository shows an incomplete list of staged files after a fetch.
- Running `git status` inside the upstream source repository reveals uncommitted tracking files or unpushed commits.

### Solution
1. Navigate directly to the original source repository (e.g., `~/LocalDevelopment/ai_guidance`).
2. Commit and push the newest files up to the server:
   ```bash
   git add .
   git commit -m "Publish new synchronization rules"
   git push origin main
   ```
3. Return to your host repository and rerun the subtree fetch command (e.g., `ai:sync`).

### Prevention
- Adopt a strict sequence: when subtrees are present, you must actively verify and push the upstream subtree master repository before you attempt to systematically sync downstream host projects.

---

## 24. AI Agent Hung on `git` Commands (Git Pager)

### Symptom
An AI agent attempts to run a terminal command like `git log`, `git show`, or `git diff` and appears to hang indefinitely. It never processes the output and requires you to manually intervene and cancel the running process. 

### Root Cause
By default, Git pipes any output stream exceeding one screen height through a terminal pager (typically `less`). The pager inherently waits for a human user to physically press the `q` key to gracefully exit. Because the AI is executing non-interactively, it cannot send the `q` keystroke, causing the agent to hang permanently.

### Detection
- The agent executes a Git inspection command.
- The terminal execution timer ticks indefinitely (e.g. 1m+) without resolving.
- `ps aux | grep less` may show an abandoned pager instance process.

### Solution
1. Cancel the agent's hung process. 
2. Explicitly instruct the agent to run the command with the `--no-pager` flag.

### Prevention
- AIs must **always explicitly disable the pager** when running stream commands in this environment:
  ```bash
  # ❌ WRONG — hangs the AI indefinitely inside 'less'
  git log -1

  # ✅ CORRECT — safely bypasses the pager and returns immediately
  git --no-pager log -1
  ```

## 25. Multi-Repo Scripts Appearing Stuck (Execution Duration)

### Symptom
An AI agent executes a bash `for` loop that iterates over multiple repositories (e.g., synchronizing the AI subtree across 7 local projects). The command execution timer ticks for 30-45 seconds, making the system look completely frozen, identical to a `git log` pager hang.

### Root Cause
Operations that hit network borders sequentially—like initiating 7 distinct SSH handshakes to `git@github.com` via `git fetch`—take approximately 4-6 seconds per repository. A 7-repository loop legitimately takes ~35 seconds to physically complete. The terminal is perfectly healthy; it is simply blocking while completing the heavy IO operations.

### Detection
- Inspect the exact command string. If it contains a `for repo in "${REPOS[@]}"; do ... git fetch ... done` loop, it is systematically iterating.
- Wait at least 60 seconds before assuming the loop is structurally broken. 

### Solution
Allow the agent's command to peacefully finish its network queue. If you accidentally execute `Cancel` on a long-running sync loop, simply re-run the loop.

### Prevention / The Sync Script
If the automated sync loop is ever disrupted, here is the official recovery snippet to cleanly rebuild the staged AI constraints across all host projects identically:

```bash
REPOS=( ~/Sites/project-a ~/Sites/project-b ~/Projects/project-c )
for repo in "${REPOS[@]}"; do
  cd "$repo"
  # Safely wipe uncommitted staged ghosts
  git rm -rf --cached docs/ai_guidance/ || true
  rm -rf docs/ai_guidance/
  # Refresh from upstream
  git fetch git@github.com:Performant-Labs/ai_guidance.git main
  git read-tree --prefix=docs/ai_guidance/ -u FETCH_HEAD
done
```

---

## 26. `ddev drush php:eval` Silent Hang on Entity `save()`

### Symptom
A `ddev drush php:eval` command that calls `->save()` on a Drupal entity (e.g., `EntityFormDisplay`, `EntityViewDisplay`, `NodeType`) hangs indefinitely with no output. The terminal timer ticks past 10 minutes with no result or error.

### Root Cause
Drupal's entity `save()` method fires a cascade of hooks — cache invalidation, config sync listeners, event subscribers, and schema updates. Inside a DDEV container under certain conditions (recent container start, pending schema updates, or heavy hook load), one of these hooks can deadlock or exceed PHP's internal memory/time thresholds silently. Drush does not surface the error; it simply never returns.

This is distinct from a PHP fatal being logged to `ddev logs -s web` — the process may be alive but permanently blocked inside a hook.

### Detection
```bash
# At the 10-second mark with no output, check web logs:
ddev logs -s web | tail -20

# Check if PHP is still processing:
ddev exec ps aux | grep php
```

If PHP shows CPU usage but no log output, it is blocked in a hook. If there is no PHP process, it crashed silently.

### Solution
1. `Ctrl+C` the stuck command immediately (apply the 10-second rule from Issue #4)
2. Use **config YAML import** instead of `php:eval` to create entity displays:

```bash
# Write the display config as a YAML file, then:
ddev drush config:import --partial --source=/var/www/html/path/to/yaml/dir --yes
```

This is reliable because it uses Drupal's own config management pipeline rather than triggering hooks via PHP eval.

### Prevention
- **Never use `ddev drush php:eval` to call `->save()` on entity displays** (`EntityFormDisplay`, `EntityViewDisplay`). Use `config:import --partial --yes` with YAML files instead.
- Apply the **10-second rule** (Issue #4): if `ddev drush` shows nothing for 10 seconds, check `ddev logs -s web` immediately — do not wait.
- For other entity types where `php:eval` is needed (e.g., creating nodes, terms, roles), short operations are fine. The hook cascade is heaviest for config entities like displays.

### Commands That Should Use Config Import Instead of `php:eval`
| Entity | Use config:import | Why |
|--------|-------------------|-----|
| `EntityFormDisplay` | ✅ Yes | Triggers heavy cache + layout hooks |
| `EntityViewDisplay` | ✅ Yes | Triggers heavy cache + layout hooks |
| `NodeType` (content type) | ⚠️ Caution | Can use `php:eval` but test on 10-second rule |
| `FieldStorageConfig` | ✅ Prefer import | Schema updates can deadlock |
| Taxonomy terms | ✅ Fine with `php:eval` | Lightweight, hooks are fast |
| Roles / permissions | ✅ Fine with drush commands | `drush role:create`, `role:perm:add` |

---

## Master Cleanup Script

If your project includes a process cleanup script (e.g., `scripts/kill-zombies.sh`), run it before every test phase:

```bash
bash /path/to/your/project/scripts/kill-zombies.sh
```

A cleanup script typically kills:
- Orphan Playwright (`node`) processes
- Orphan Chromium browsers
- Orphan Drush processes (host-side)
- Orphan PHP processes (host-side)
- Orphan Composer processes
- Node dev servers
- Orphan curl/wget processes

It may also report DDEV container health status.

**Run this script before every test phase.**

---

## Diagnostic Checklist

When something appears stuck, check in this order:

### Environment
1. **Is DDEV running?** → `ddev describe`
2. **Are there zombie processes?** → Run your project's cleanup script (e.g., `bash scripts/kill-zombies.sh`)
3. **Is another DDEV project interfering?** → `ddev list` and stop unused projects
4. **Is there a nested `.ddev` in a parent directory?** → `ls "$(dirname $(pwd))"/.ddev`
5. **Is the DDEV port correct?** → `ddev describe` and compare with `playwright.config.ts`

### Playwright / Testing
6. **Is the test using `networkidle`?** → Check `beforeEach` in the test file
7. **Are timeouts set to fail-fast?** → Check `playwright.config.ts` for 30s/5s
8. **Are locators scoped to `main`?** → Check for admin toolbar collisions
9. **Did `pkill` kill itself?** → Use `pkill -f "node.*playwright"` not `pkill -f "playwright"`

### Drupal Configuration
10. **Is PHP opcache stale?** → `ddev restart` (not just `ddev drush cr`)
11. **Are taxonomy terms in the right vocabulary?** → Check `vid` matches the actual vocabulary machine name
12. **Are form display configs imported?** → Check `entity_form_display` components
13. **Are `taxonomy_access_fix` permissions granted?** → Check `select terms in {vocab}`
14. **Is the markdown filter escaping HTML?** → Disable markdown in `full_html`
15. **Are required sub-modules enabled?** → Check for companion modules and their permissions
16. **Did a config import cause WSOD?** → Check `ddev logs -s web` for SQL errors

### Module / Library Issues
17. **Is the custom module in a proper subdirectory?** → Check `web/modules/custom/module_name/`
18. **Are frontend libraries present?** → Check `web/libraries/` for expected library directories

### DDEV CLI
19. **Using wrong DDEV flags?** → `ddev stop` has no `-y`, use `ddev delete --omit-snapshot -y`
20. **`ddev drush php:eval` with `->save()` hanging?** → Cancel at 10s, check `ddev logs -s web`, use `ddev drush config:import --partial --yes` instead (Issue #26)

### Git Environments
20. **Subtree fetch missing recent files?** → Verify the source repository has been explicitly committed and pushed to the remote origin.
21. **Agent hung on `git log`?** → The agent forgot to bypass the terminal pager. Cancel it and tell it to use `git --no-pager log`.
22. **Multi-repo loop appears hung?** → Sequential SSH handshakes naturally take ~35 seconds. Wait 60s before intervening.
