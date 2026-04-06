# Go Testing Conventions

## Test File Placement

In Go, test files **must** live in the same directory as the code they test. This is a language-level convention enforced by the `go test` toolchain — not a preference.

```
package/
├── handler.go         ← source code
├── handler_test.go    ← tests for handler.go
├── middleware.go
└── middleware_test.go
```

**Do NOT create a separate `tests/` directory.** The `go test` command discovers test files by the `_test.go` suffix within each package directory. Moving tests to an external folder breaks the toolchain and prevents access to unexported (lowercase) identifiers.

This is the opposite of PHP (`tests/`), Python (`tests/`), and JavaScript (`__tests__/`).

## Test File Naming

- Test files must end with `_test.go` (e.g., `auth_test.go`, `main_test.go`).
- Test function names must start with `Test` followed by a capital letter (e.g., `TestCreateFeature`, `TestRateLimiter_RejectsOverBurst`).
- Use underscores to separate the unit under test from the scenario: `TestUnitName_Scenario`.

## Test Framework

- Use **only** the standard library `testing` package and `net/http/httptest` for HTTP handlers.
- **Do NOT** introduce third-party test runners like Ginkgo, Gomega, or testify.
- Assertions use `t.Errorf()` (non-fatal) and `t.Fatalf()` (fatal). There is no built-in `assert` function.

## Test Helpers

- Mark shared setup functions with `t.Helper()` so error stack traces point to the calling test, not the helper.
- Use `t.TempDir()` for temporary files — Go automatically cleans up the directory after the test completes.

## Separating Unit Tests from Integration Tests

Use Go **build tags** to separate fast unit tests from slower integration tests that require real databases, network access, or full middleware chains.

Add this as the **first line** of integration test files (before `package`):

```go
//go:build integration

package mypackage
```

### What qualifies as an integration test?
- Tests that wire up multiple components together (handler → store → real database)
- Tests that require real file I/O (SQLite databases, temp files)
- Tests that make network calls (HTTP, OIDC discovery)

### What stays as a unit test?
- Tests for a single function or struct in isolation
- Tests using mocked dependencies or `httptest`
- Tests that complete in milliseconds with no I/O

## Running Tests

```bash
# Run unit tests only (fast, no build tags)
go test ./...

# Run integration tests only
go test -tags=integration ./...

# Run ALL tests (unit + integration)
go test -tags=integration ./...

# Verbose output with test names
go test -v ./...

# Force fresh run (bypass cache)
go test -v -count=1 ./...

# Run with coverage report (include integration)
go test -tags=integration -cover ./...
```

## Key Differences from Other Ecosystems

| Convention | Go | PHP / Python / JS |
| :--- | :--- | :--- |
| Test location | Same directory as source | Separate `tests/` folder |
| Test discovery | `_test.go` suffix | Config file or folder convention |
| Assertion style | `t.Errorf` / `t.Fatalf` | `assert()` / `expect()` |
| Test runner | `go test` (built-in) | PHPUnit / pytest / Jest |
| Mocking | Interfaces + manual stubs | Framework-provided mocks |
