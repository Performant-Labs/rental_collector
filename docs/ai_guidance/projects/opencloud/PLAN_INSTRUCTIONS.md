## ⚠️ Mandatory Go Implementation Constraints
Before generating code or executing this plan, you **MUST** adhere to the following strict Go conventions for this repository:

1. **Idiomatic Formatting & Style**: 
   - Write standard, boring, and idiomatic Go as defined in *Effective Go*. 
   - Before completing your work, always run `go fmt` on any modified files to handle proper indentation and spacing.
   - Do not use clever "AI-isms" or heavily abstracted architectures. 

2. **Standard Library Exclusivity (with Ecosystem Exceptions)**:
   - Use the Go 1.22+ standard library `servemux` for routing (`net/http`) and `html/template` for HTML views. 
   - **Do not** introduce external frameworks like Gin, Fiber, Vue, or React.
   - **Exception:** When operating within a parent ecosystem (e.g., OpenCloud/oCIS), libraries that are established conventions in that ecosystem **must** be adopted over standard library equivalents. For example, oCIS uses `github.com/rs/zerolog` for structured logging — use `zerolog`, not `log/slog`.

3. **Strict Error Handling**:
   - Never ignore errors with `_`. 
   - Every error must be explicitly handled and wrapped contextually (e.g., `fmt.Errorf("failed to fetch user: %w", err)`).

4. **Stateless Operations & Context Isolation**:
   - The Go application must remain completely stateless. All persistent state must be pushed to SQLite.
   - Every major function (especially OpenCloud API adapters and DB queries) must accept and pass a `context.Context` as its first parameter to handle timeouts properly.
