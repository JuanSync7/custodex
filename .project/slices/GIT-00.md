# GIT-00 — clone-on-demand (`gitfetch.py`)  [STEP 0]

## Goal (validable)

Over a **real `file://` git repo** (no network), a context manager clones it into
a throwaway temp tree and `configsync.run_sync(tree, mode="local")` over that tree
surfaces the cloned repo's documents + coverage — proving the server can sync a
repo it does **not** hold locally. A fake `cloner` proves teardown happens on
success AND error, and `_build_clone_argv` proves the secret never enters argv.

## In scope

New module `custodex/gitfetch.py` (engine, stdlib-only — K0):

```python
class RemoteSpec(BaseModel):                       # frozen, extra=forbid
    remote_url: str
    provider: Literal["github", "gitlab"]
    default_branch: str = "main"

class _Cloner(Protocol):                           # the ONE network leaf (K4)
    def clone(self, spec: RemoteSpec, secret: str | None, dest: Path) -> None: ...

def _build_clone_argv(spec: RemoteSpec, dest: Path) -> list[str]: ...
    # ["clone","--depth=1","--single-branch","--branch",<b>,<url>,<dest>] — pure, secret-free (unit-asserted)

class _GitCloner:                                  # real leaf
    def clone(self, spec, secret, dest) -> None: ...
    # subprocess.run(["git", *_build_clone_argv(...)], env=<GIT_ASKPASS + token-in-env>, capture, text)
    # nonzero exit → SyncError with the secret SCRUBBED from stderr (K8).
    # https+token path is `# pragma: no cover` (real network); the file:// path is exercised.

@contextmanager
def cloned_repo(spec: RemoteSpec, secret: str | None, *, cloner: _Cloner | None = None) -> Iterator[Path]:
    # tempfile.mkdtemp("cdmon-fetch-") → cloner.clone(spec, secret, <tmp>/"repo") → yield <tmp>/"repo"
    # finally: shutil.rmtree(tmp, ignore_errors=True)  (K1 — temp only, user tree untouched)
```

`__all__ = ["RemoteSpec", "cloned_repo"]` (the leaf/helpers are private). Reuse the
`SyncError` from `errors.py` (no new error type this slice).

## Test plan — `tests/integration/test_gitfetch.py` (real-git, mirrors `test_configsync.py`)

- **unit** `_build_clone_argv`: emits `--depth=1 --single-branch --branch <b>`; the
  URL is the bare `remote_url` (no embedded creds); a secret passed anywhere does
  NOT appear in the argv list (token-not-in-argv guard).
- **unit (fake cloner)** `cloned_repo` yields `<tmp>/repo`, calls `cloner.clone`
  once with that dest, and the temp dir is **gone after the block** (teardown on
  success); a `cloner.clone` that RAISES → the temp dir is still removed (teardown
  on error) and the error propagates.
- **integration (REAL `file://`, no network)** build a real dir-layout git repo
  (reuse the `_build_git_repo` shape from `test_configsync.py`), then
  `cloned_repo(RemoteSpec("file://"+repo, "github"), None)` with the REAL
  `_GitCloner`; inside the block `run_sync(tree, "demo", mode="local",
  default_branch="main", now=_NOW)` → `fully_synced`, the expected doc/code_ref
  counts, and a non-empty coverage snapshot. Exercises `_GitCloner.clone`'s
  `file://` branch with zero network (EDR-safe).
- **loud (K8)** a bogus `file://` path → `_GitCloner` raises `SyncError`; assert the
  temp dir is cleaned up.

## Constraints to cite

- **K0** stdlib only (`subprocess`, `tempfile`, `shutil`, `urllib.parse`); no new dep.
- **K1** the clone lands ONLY in a temp dir; the user/server tree is never mutated;
  teardown in `finally`.
- **K4** the real subprocess is behind the injected `_Cloner` leaf; tests use a fake
  OR a real `file://` clone (no network); the https+token path is the one pragma.
- **K8** a clone failure is a loud `SyncError` with the secret scrubbed.
- **K9** `configsync.py` is NOT touched; tests-first.

## Out of scope (later slices)

- Sealing/secret storage (GIT-01/02); the `secret` arg is accepted + kept out of
  argv but real https auth wiring is exercised only in GIT-04's route tests.
- `RemoteSpec` host allowlist / SSRF (GIT-04, at the route boundary).
- Any server route change (GIT-04).
