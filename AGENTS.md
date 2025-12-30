# AGENTS.md

Guidelines for AI agents working on Python code in this repository.

## Python version

Use Python 3.13+. Leverage modern syntax:

- `type` statements for type aliases
- Built-in generics (`list[T]`, `dict[K, V]`—no `typing` imports)
- `Self` for fluent interfaces
- `match` statements where appropriate
- Union syntax with `|`

## Package manager

Use `uv` for all dependency management:

- `uv add <package>` to add dependencies
- `uv sync` to install from lockfile
- `uv run <command>` to execute in the environment

## Project structure

Use src layout:

```
project/
├── src/
│   └── packagename/
│       ├── __init__.py
│       └── ...
├── tests/
│   └── ...
└── pyproject.toml
```

## Type checking

Use `ty` in strict mode. Requirements:

- All functions must have complete type annotations (parameters and return types)
- No `Any` without explicit justification in an adjacent comment
- No `# type: ignore` without error code and reason: `# type: ignore[arg-type] -- reason`

## Formatting and linting

Use `ruff` for both formatting and linting. Run:

- `ruff format .`
- `ruff check . --fix`

## Imports

- Use relative imports within the package (`from .utils import helper`)
- Use absolute imports for external dependencies
- Ordering (enforced by ruff):
  1. Standard library
  2. Third-party
  3. First-party
  4. Local/relative

## Naming over documentation

**Prefer self-describing names over comments and docstrings.**

- Choose precise, unambiguous names for functions, parameters, classes, and variables
- If you need a comment to explain what code does, consider renaming or restructuring first
- Types are documentation—use them fully

## Docstrings

Use Google style when docstrings are warranted.

**Do not write docstrings for trivial or self-describing functions.** A function is self-describing when:

- Its name clearly states what it does
- Its parameter names and types make usage obvious
- Its return type makes the output obvious

Example—no docstring needed:

```python
def get_peer_by_id(peer_id: PeerId) -> Peer | None:
    return self._peers.get(peer_id)
```

Example—docstring warranted (non-obvious behavior, important constraints):

```python
def discover_peers(timeout: float, max_peers: int = 10) -> list[Peer]:
    """Discover peers via DHT traversal.

    Queries are parallelized across bootstrap nodes. Results are deduplicated
    and sorted by observed latency. The timeout applies to the entire operation,
    not individual queries.

    Args:
        timeout: Maximum seconds for the entire discovery process.
        max_peers: Stop early if this many unique peers are found.

    Raises:
        NetworkError: If all bootstrap nodes are unreachable.
    """
```

When you do write docstrings:

- Don't repeat type information already in the signature
- Focus on behavior, constraints, side effects, and non-obvious details
- One-liner docstrings are fine: `"""Raise if the connection is closed."""`

## Testing

Use `pytest`. Structure:

- Tests live in `tests/`, mirroring src structure
- Test files prefixed with `test_`
- Shared fixtures in `conftest.py`
- Run: `uv run pytest`

Before proposing changes, run the test suite and ensure it passes.

## Forbidden patterns

1. **Mutable default arguments**

   ```python
   # ✗
   def f(items: list[int] = []) -> None: ...
   # ✓
   def f(items: list[int] | None = None) -> None: ...
   ```

2. **Bare except clauses**

   ```python
   # ✗
   except:
   # ✓
   except Exception:
   ```

3. **Unqualified type: ignore**

   ```python
   # ✗
   x = thing  # type: ignore
   # ✓
   x = thing  # type: ignore[assignment] -- external lib returns wrong type
   ```

4. **Legacy string formatting**

   ```python
   # ✗
   "Hello %s" % name
   "Hello {}".format(name)
   # ✓
   f"Hello {name}"
   ```

5. **Assert for runtime validation**

   ```python
   # ✗
   assert user_id is not None
   # ✓
   if user_id is None:
       raise ValueError("user_id is required")
   ```

6. **Wildcard imports**

   ```python
   # ✗
   from module import *
   ```

7. **Shadowing builtins**

   ```python
   # ✗
   list = [1, 2, 3]
   id = get_id()
   ```

8. **Silent exception swallowing**

   ```python
   # ✗
   except SomeError:
       pass
   # ✓
   except SomeError:
       logger.debug("Ignored transient error", exc_info=True)
   ```

9. **Excessive nesting** — Functions nested more than 2 levels deep indicate a need for decomposition.

10. **Long functions** — Functions exceeding ~50 lines should be split.

## Git commits

Use [Conventional Commits](https://www.conventionalcommits.org/). Format:

```
<type>: <description>

[optional body]
```

Types:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `style:` — formatting, no code change
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `chore:` — maintenance, dependencies, CI

Rules:

- Use lowercase for type and description
- No period at the end of the description
- Keep the first line under 72 characters
- Use imperative mood ("add feature" not "added feature")

## Change scope

Adapt to the task:

- **Bug fixes**: Minimal, focused diffs. Don't refactor unrelated code.
- **Refactoring**: Broader changes acceptable. Maintain behavior, improve structure.
- **New features**: Follow existing patterns. Propose new patterns only with justification.
