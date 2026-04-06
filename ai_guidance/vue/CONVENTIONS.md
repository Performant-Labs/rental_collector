# Vue 3 Development Conventions

> Sources: [Vue.js Testing Guide](https://vuejs.org/guide/scaling-up/testing.html), [Vue.js Style Guide](https://vuejs.org/style-guide/), [Vue.js Composables Guide](https://vuejs.org/guide/reusability/composables.html), [AGENTS.md standard](https://agents.md)

## Component Conventions

### Composition API Only
- Use `<script setup lang="ts">` for all Vue components. **Do NOT use Options API.**
- Use TypeScript for all `.vue`, `.ts` files.
- Use `defineProps()`, `defineEmits()`, and `defineExpose()` with TypeScript generics.

### Component Naming (Vue Style Guide Priority A & B)
- **File names**: PascalCase for components (e.g., `FeatureList.vue`), camelCase for composables (e.g., `useVotingApi.ts`).
- **Multi-word names**: Component names must always be multi-word to avoid conflict with existing and future HTML elements. Use `FeatureVoting.vue`, not `Voting.vue`.
- **Prop names**: camelCase in declarations, kebab-case in templates.
  ```vue
  <!-- ✅ Correct -->
  <MyComponent greeting-message="hello" />

  <!-- ❌ Incorrect -->
  <MyComponent greetingMessage="hello" />
  ```

### Component Structure Order
Within `<script setup>`, follow this order:
1. Imports
2. Props / emits definitions
3. Reactive state (`ref`, `reactive`, `computed`)
4. Composable calls
5. Methods / functions
6. Lifecycle hooks (`onMounted`, `onUnmounted`)
7. Watchers (`watch`, `watchEffect`)

## Composables

### Naming
- Always prefix with `use` (e.g., `useMouse`, `useVotingApi`).
- Place in `src/composables/` directory.
- File name must match function name: `useVotingApi.ts` exports `useVotingApi()`.

### Design Rules
- **Single responsibility**: One composable, one logical concern.
- **Return plain objects of refs**: Enable destructuring at the call site.
  ```typescript
  // ✅ Correct
  return { features, loading, error, loadFeatures }

  // ❌ Incorrect — don't return reactive()
  return reactive({ features, loading })
  ```
- **Synchronous invocation only**: Must be called inside `<script setup>` or `setup()`. Never call a composable inside an async callback, `setTimeout`, or event handler.
- **Accept refs or raw values**: Use `toValue()` to normalize input.
- **Clean up side effects**: Use `onUnmounted()` for event listeners, intervals, or subscriptions.

### Testing Composables
- If a composable uses **only** Reactivity APIs (no lifecycle hooks, no provide/inject): test it by directly invoking it.
  ```typescript
  import { useCounter } from './useCounter'
  test('increments', () => {
    const { count, increment } = useCounter()
    expect(count.value).toBe(0)
    increment()
    expect(count.value).toBe(1)
  })
  ```
- If a composable uses **lifecycle hooks** or **provide/inject**: wrap it in a host component using a `withSetup()` test helper.

## Testing

### Test Strategy (per vuejs.org)
Vue recommends three levels. Each has a specific role:

| Level | Tool | Use For |
| :--- | :--- | :--- |
| **Unit** | Vitest | Pure logic, utility functions, composables without lifecycle hooks |
| **Component** | Vitest + `@vue/test-utils` | Component mounting, user interactions, DOM assertions |
| **E2E** | Playwright | Full-stack user journeys, cross-browser testing |

### Test File Placement
Unlike Go, Vue/JS tests can be placed either:
- **Next to source** (preferred for component tests): `src/components/FeatureList.spec.ts`
- **In a `tests/` directory** (preferred for E2E): `tests/e2e/voting.spec.ts`

Use the `.spec.ts` or `.test.ts` suffix. Configure Vitest to discover them automatically.

### Unit & Component Tests (Vitest)
- Use **Vitest** as the test runner — never Jest for new Vite-based projects.
- Use **`@vue/test-utils`** for component mounting. Prefer `mount()` over `shallowMount()`.
- Use **`happy-dom`** as the simulated DOM environment.
- Test **public interfaces** (props, emits, slots, DOM output), not internal state.
- **Do NOT** rely exclusively on snapshot tests. Write assertions with intentionality.
- **Do NOT** assert private component state or test private methods.

```typescript
// ✅ Correct — test what the user sees
const wrapper = mount(Stepper, { props: { max: 5 } })
await wrapper.find('[data-testid=increment]').trigger('click')
expect(wrapper.find('[data-testid=stepper-value]').text()).toContain('1')

// ❌ Incorrect — testing internals
expect(wrapper.vm.internalCount).toBe(1)
```

### E2E Tests (Playwright)
- Use **Playwright** (Vue's primary recommendation alongside Cypress).
- E2E tests do not import application source code — they navigate real pages in a real browser.
- Place in `tests/e2e/` with a `playwright.config.ts` at the project root.
- Always `pnpm build` before running E2E tests — never test against the dev server.

### Running Tests
```bash
# Unit + component tests
pnpm test:unit

# E2E tests (requires built app)
pnpm build && pnpm test:e2e

# Watch mode during development
pnpm vitest --watch
```

## Project Structure
```
web/
├── src/
│   ├── components/        # Vue components (PascalCase)
│   ├── composables/       # Composable functions (useXxx.ts)
│   ├── types.ts           # Shared TypeScript interfaces
│   ├── App.vue            # Root component
│   └── index.ts           # Extension registration
├── tests/
│   └── e2e/               # Playwright E2E tests
├── vite.config.ts
├── playwright.config.ts
└── package.json
```

## Key Differences from Other Ecosystems

| Convention | Vue / JS | Go |
| :--- | :--- | :--- |
| Test location | `tests/` dir or co-located `.spec.ts` | Must be co-located `_test.go` |
| Test runner | Vitest (unit), Playwright (E2E) | `go test` (built-in) |
| Assertion style | `expect().toBe()` | `t.Errorf()` / `t.Fatalf()` |
| Mocking | `vi.mock()`, `vi.fn()` | Interfaces + manual stubs |
| Component API | Composition API (`<script setup>`) | N/A |
| State management | `ref()`, `reactive()`, Pinia | Standard library only |
