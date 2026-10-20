"""A stateful, offline fake GitLab + GitHub forge for the executed-CI harness.

The executed-CI tests (S1-CITPL) run the shipped CI templates as real jobs. The
product's provider transports (:class:`custodex.pr.GitLabTransport` /
:class:`custodex.pr.GitHubTransport`) talk to a forge through ONE injected HTTP
leaf (``request(method, url, *, body, token) -> dict``). The CI shim
(``tests/_cdx_ci_shim.py``) binds that leaf to :class:`FakeForge`, so the REAL
transport code runs against a forge that is:

* **stateful across processes** — state lives in one JSON file, read and written
  under an exclusive ``flock`` with an atomic ``tmp`` + ``os.replace``, so two
  jobs (or a job and the test) see the same branches / MRs;
* **all-or-nothing** — a request mutates a deep copy and the file is replaced only
  when the request succeeds, so a refused request leaves the bytes untouched;
* **as strict as the real thing** where a lax fake would hide a product bug:
  ``id != iid`` (and the wrong identifier is a 404), a duplicate branch is 400
  (GitLab) / 422 (GitHub), a duplicate open MR is 409 / 422, an MR needs both
  branches, an ``update`` of a path the branch does not hold is 400, a ref update
  that is not a fast-forward is 422 unless forced, list defaults and the
  ``per_page`` cap follow each provider, GitHub's ``head`` filter must be
  ``owner:branch``, and an empty token is a 401;
* **logged** — every request (success or failure) appends one sorted-key JSONL
  line ``{provider, method, path, body, status, authorized}``; the token itself is
  never written (``authorized`` is a bool).

Nothing here touches a network (K4). URLs use the reserved ``.example.test``
TLD; they are test constants, not configuration.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from custodex.errors import TransportError

__all__ = [
    "GITHUB_API_URL",
    "GITHUB_REPOSITORY",
    "GITHUB_SERVER_URL",
    "GITLAB_API_URL",
    "GITLAB_PROJECT_ID",
    "GITLAB_PROJECT_PATH",
    "GITLAB_PROJECT_URL",
    "GITLAB_SERVER_URL",
    "FakeForge",
    "FakeForgeHTTPError",
    "seed_forge",
]

GITLAB_SERVER_URL = "https://gitlab.example.test"
GITLAB_API_URL = f"{GITLAB_SERVER_URL}/api/v4"
GITLAB_PROJECT_PATH = "acme/widget"
GITLAB_PROJECT_ID = "4242"
GITLAB_PROJECT_URL = f"{GITLAB_SERVER_URL}/{GITLAB_PROJECT_PATH}"

GITHUB_SERVER_URL = "https://github.example.test"
GITHUB_API_URL = f"{GITHUB_SERVER_URL}/api/v3"
GITHUB_REPOSITORY = "acme/widget"

#: The offset between a merge request's global ``id`` and its per-project
#: ``iid`` / ``number``. Non-zero on purpose: a product that sends the id where
#: the iid belongs gets a 404, exactly as on a real forge.
_GITLAB_ID_OFFSET = 10000
_GITHUB_ID_OFFSET = 20000

#: (default per_page, max per_page) — the providers' documented list paging.
_PAGE_LIMITS = {"gitlab": (20, 100), "github": (30, 100)}

_PROVIDERS = ("gitlab", "github")


class FakeForgeHTTPError(TransportError):
    """A forge-side HTTP failure (subclasses the product's ``TransportError``)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def _sha1(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()  # noqa: S324 (content id, not security)


def _git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    out = subprocess.run(  # noqa: S603 (fixed git verbs)
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def _repo_path(repo: object) -> Path:
    path = getattr(repo, "path", repo)
    if not isinstance(path, Path):
        raise TypeError(f"expected a GitRepo or Path, got {type(repo).__name__}")
    return path


def _empty_provider() -> dict[str, Any]:
    return {
        "branches": {},
        "commits": {},
        "trees": {},
        "mrs": [],
        "next_number": 1,
        "notes": [],
    }


def seed_forge(
    state_path: Path,
    repo: object,
    heads: Mapping[str, str] | None = None,
) -> None:
    """Write a fresh forge state mirroring ``repo``'s ``heads`` (branch -> sha).

    ``heads`` defaults to ``{<repo default branch>: <repo HEAD>}``. Each head's
    tree (path -> blob id, from ``git ls-tree -r``) is recorded so a commit
    ``update`` of a path the branch does not hold is refused like the real API.
    Both providers are seeded with the same branches.
    """
    path = _repo_path(repo)
    if heads is None:
        branch = getattr(repo, "default_branch", "main")
        heads = {branch: _git(path, "rev-parse", "HEAD").strip()}
    state: dict[str, Any] = {p: _empty_provider() for p in _PROVIDERS}
    for branch, sha in sorted(heads.items()):
        full = _git(path, "rev-parse", f"{sha}^{{commit}}").strip()
        tree_sha = _git(path, "rev-parse", f"{full}^{{tree}}").strip()
        files: dict[str, str] = {}
        for line in _git(path, "ls-tree", "-r", full).splitlines():
            meta, name = line.split("\t", 1)
            files[name] = meta.split()[2]
        for prov in _PROVIDERS:
            st = state[prov]
            st["trees"][tree_sha] = files
            st["commits"][full] = {"tree": tree_sha, "parents": [], "message": "seed"}
            st["branches"][branch] = full
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(state_path, state)


def _atomic_write(path: Path, state: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class FakeForge:
    """The fake forge: one ``request`` entry point plus test-side hooks."""

    def __init__(self, state_path: Path, *, log_path: Path | None = None) -> None:
        self.state_path = Path(state_path)
        self.log_path = None if log_path is None else Path(log_path)
        if not self.state_path.is_file():
            raise FileNotFoundError(f"fake forge state not seeded: {self.state_path}")

    # ------------------------------------------------------------------ state

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock = self.state_path.with_name(self.state_path.name + ".lock")
        with lock.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def _transact(self, fn: Any) -> Any:
        """Run ``fn(state)`` on a deep copy; persist only if it returns normally."""
        with self._locked():
            original = self._read()
            work = copy.deepcopy(original)
            result = fn(work)
            if work != original:
                _atomic_write(self.state_path, work)
            return result

    def _log(self, entry: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    # ---------------------------------------------------------------- request

    def request(self, method: str, url: str, *, body: dict | None, token: str) -> Any:
        """Serve one provider API call (the transports' injected HTTP leaf)."""
        provider, path, query = self._route(url)
        entry: dict[str, Any] = {
            "provider": provider,
            "method": method,
            "path": path + (f"?{query}" if query else ""),
            "body": body,
            "authorized": bool(token),
        }
        try:
            if provider is None:
                raise FakeForgeHTTPError(404, f"unknown forge host or project: {url}")
            if not token:
                raise FakeForgeHTTPError(401, "401 Unauthorized (empty token)")
            handler = self._gitlab if provider == "gitlab" else self._github
            params = {k: v[-1] for k, v in parse_qs(query).items()}

            def run(state: dict[str, Any]) -> Any:
                return handler(state[provider], method, path, params, body or {})

            result = self._transact(run)
        except FakeForgeHTTPError as exc:
            entry["status"] = exc.status
            self._log(entry)
            raise
        entry["status"] = 201 if method == "POST" else 200
        self._log(entry)
        return result

    def _route(self, url: str) -> tuple[str | None, str, str]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        gl_projects = (
            f"/api/v4/projects/{GITLAB_PROJECT_ID}/",
            f"/api/v4/projects/{quote(GITLAB_PROJECT_PATH, safe='')}/",
        )
        if origin == GITLAB_SERVER_URL:
            for prefix in gl_projects:
                if parsed.path.startswith(prefix):
                    rest = parsed.path[len(prefix) :]
                    return (
                        "gitlab",
                        f"/projects/{GITLAB_PROJECT_ID}/{rest}",
                        parsed.query,
                    )
        if origin == GITHUB_SERVER_URL:
            prefix = f"/api/v3/repos/{GITHUB_REPOSITORY}/"
            if parsed.path.startswith(prefix):
                rest = parsed.path[len(prefix) :]
                return "github", f"/repos/{GITHUB_REPOSITORY}/{rest}", parsed.query
        return None, parsed.path, parsed.query

    # ----------------------------------------------------------------- shared

    @staticmethod
    def _page(items: list[dict], params: Mapping[str, str], provider: str) -> list:
        default, cap = _PAGE_LIMITS[provider]
        try:
            per_page = min(int(params.get("per_page", default)), cap)
            page = int(params.get("page", 1))
        except ValueError as exc:
            raise FakeForgeHTTPError(400, f"bad paging parameter: {exc}") from exc
        if per_page < 1 or page < 1:
            raise FakeForgeHTTPError(400, "per_page and page must be >= 1")
        start = (page - 1) * per_page
        return items[start : start + per_page]

    @staticmethod
    def _new_commit(
        st: dict[str, Any], files: dict[str, str], parent: str, message: str
    ) -> str:
        tree_sha = _sha1({"files": files})
        st["trees"][tree_sha] = files
        sha = _sha1({"tree": tree_sha, "parents": [parent], "message": message})
        st["commits"][sha] = {"tree": tree_sha, "parents": [parent], "message": message}
        return sha

    @staticmethod
    def _find(st: dict[str, Any], number: int) -> dict[str, Any]:
        for mr in st["mrs"]:
            if mr["number"] == number:
                return mr
        raise FakeForgeHTTPError(404, f"404 Not Found (no MR/PR number {number})")

    @staticmethod
    def _int(text: str) -> int:
        try:
            return int(text)
        except ValueError as exc:
            raise FakeForgeHTTPError(404, f"404 Not Found ({text!r})") from exc

    # ----------------------------------------------------------------- GitLab

    def _gitlab(
        self,
        st: dict[str, Any],
        method: str,
        path: str,
        params: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> Any:
        rest = path.split("/", 3)[3]  # strip "/projects/<id>/"
        parts = rest.split("/")
        if rest == "repository/branches" and method == "POST":
            return self._gl_create_branch(st, body)
        is_branch = parts[:2] == ["repository", "branches"] and len(parts) == 3
        if is_branch and method == "GET":
            name = parts[2]
            if name not in st["branches"]:
                raise FakeForgeHTTPError(404, f"404 Branch Not Found: {name}")
            return {"name": name, "commit": {"id": st["branches"][name]}}
        if rest == "repository/commits" and method == "POST":
            return self._gl_commit(st, body)
        if rest == "merge_requests":
            if method == "POST":
                return self._gl_create_mr(st, body)
            if method == "GET":
                return self._gl_list(st, params)
        if parts[0] == "merge_requests" and len(parts) >= 2:
            mr = self._find(st, self._int(parts[1]))
            if len(parts) == 2 and method == "GET":
                return copy.deepcopy(mr["gitlab"])
            if len(parts) == 2 and method == "PUT":
                if body.get("state_event") == "close":
                    mr["state"] = "closed"
                    mr["gitlab"]["state"] = "closed"
                return copy.deepcopy(mr["gitlab"])
            if parts[2:] == ["notes"] and method == "POST":
                note = {"id": len(st["notes"]) + 1, "body": body.get("body", "")}
                st["notes"].append({"number": mr["number"], **note})
                return note
        raise FakeForgeHTTPError(404, f"404 Not Found: {method} {path}")

    def _gl_create_branch(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        name = body.get("branch")
        ref = body.get("ref")
        if not name or not ref:
            raise FakeForgeHTTPError(400, "branch and ref are required")
        if name in st["branches"]:
            raise FakeForgeHTTPError(400, "Branch already exists")
        sha = st["branches"].get(ref) or (ref if ref in st["commits"] else None)
        if sha is None:
            raise FakeForgeHTTPError(400, "Invalid reference name")
        st["branches"][name] = sha
        return {"name": name, "commit": {"id": sha}}

    def _gl_commit(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        branch = body.get("branch")
        if branch not in st["branches"]:
            raise FakeForgeHTTPError(404, f"404 Branch Not Found: {branch}")
        head = st["branches"][branch]
        files = dict(st["trees"][st["commits"][head]["tree"]])
        for action in body.get("actions") or []:
            kind = action.get("action")
            fpath = action.get("file_path")
            if kind == "update":
                if fpath not in files:
                    raise FakeForgeHTTPError(
                        400, f"A file with this name doesn't exist: {fpath}"
                    )
            elif kind == "create":
                if fpath in files:
                    raise FakeForgeHTTPError(
                        400, f"A file with this name already exists: {fpath}"
                    )
            elif kind == "delete":
                if fpath not in files:
                    raise FakeForgeHTTPError(
                        400, f"A file with this name doesn't exist: {fpath}"
                    )
                del files[fpath]
                continue
            else:
                raise FakeForgeHTTPError(400, f"unknown commit action {kind!r}")
            files[fpath] = _sha1({"content": action.get("content", "")})
        message = str(body.get("commit_message", ""))
        sha = self._new_commit(st, files, head, message)
        st["branches"][branch] = sha
        for mr in st["mrs"]:  # an open MR follows its source branch (as on GitLab)
            if mr["state"] == "opened" and mr["source"] == branch:
                mr["gitlab"]["sha"] = sha
        return {
            "id": sha,
            "short_id": sha[:8],
            "title": message.splitlines()[0] if message else "",
        }

    def _gl_create_mr(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        source = body.get("source_branch")
        target = body.get("target_branch")
        for name in (source, target):
            if name not in st["branches"]:
                raise FakeForgeHTTPError(400, f"branch does not exist: {name}")
        for mr in st["mrs"]:
            if (
                mr["state"] == "opened"
                and mr["source"] == source
                and mr["target"] == target
            ):
                raise FakeForgeHTTPError(
                    409,
                    "Another open merge request already exists for this source "
                    f"branch: !{mr['number']}",
                )
        iid = st["next_number"]
        st["next_number"] = iid + 1
        labels = [x for x in str(body.get("labels", "")).split(",") if x]
        view = {
            "id": iid + _GITLAB_ID_OFFSET,
            "iid": iid,
            "project_id": int(GITLAB_PROJECT_ID),
            "title": body.get("title", ""),
            "description": body.get("description", ""),
            "source_branch": source,
            "target_branch": target,
            "state": "opened",
            "sha": st["branches"][source],
            "labels": labels,
            "web_url": f"{GITLAB_PROJECT_URL}/-/merge_requests/{iid}",
        }
        st["mrs"].append(
            {
                "number": iid,
                "state": "opened",
                "source": source,
                "target": target,
                "gitlab": view,
            }
        )
        return copy.deepcopy(view)

    def _gl_list(self, st: dict[str, Any], params: Mapping[str, str]) -> list:
        state = params.get("state", "all")
        rows = []
        for mr in sorted(st["mrs"], key=lambda m: -m["number"]):
            if state != "all" and mr["state"] != state:
                continue
            if "source_branch" in params and mr["source"] != params["source_branch"]:
                continue
            if "target_branch" in params and mr["target"] != params["target_branch"]:
                continue
            rows.append(copy.deepcopy(mr["gitlab"]))
        return self._page(rows, params, "gitlab")

    # ----------------------------------------------------------------- GitHub

    def _github(
        self,
        st: dict[str, Any],
        method: str,
        path: str,
        params: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> Any:
        rest = path.split("/", 4)[4]  # strip "/repos/<owner>/<repo>/"
        parts = rest.split("/")
        if parts[:3] == ["git", "ref", "heads"] and method == "GET":
            name = "/".join(parts[3:])
            if name not in st["branches"]:
                raise FakeForgeHTTPError(404, f"404 Not Found: ref heads/{name}")
            return {
                "ref": f"refs/heads/{name}",
                "object": {"sha": st["branches"][name], "type": "commit"},
            }
        if parts[:2] == ["git", "commits"] and len(parts) == 3 and method == "GET":
            commit = st["commits"].get(parts[2])
            if commit is None:
                raise FakeForgeHTTPError(404, f"404 Not Found: commit {parts[2]}")
            return {
                "sha": parts[2],
                "tree": {"sha": commit["tree"]},
                "parents": [{"sha": p} for p in commit["parents"]],
                "message": commit["message"],
            }
        if rest == "git/trees" and method == "POST":
            return self._gh_tree(st, body)
        if rest == "git/commits" and method == "POST":
            return self._gh_commit(st, body)
        if rest == "git/refs" and method == "POST":
            return self._gh_create_ref(st, body)
        if parts[:3] == ["git", "refs", "heads"] and method == "PATCH":
            return self._gh_update_ref(st, "/".join(parts[3:]), body)
        if rest == "pulls":
            if method == "POST":
                return self._gh_create_pr(st, body)
            if method == "GET":
                return self._gh_list(st, params)
        if parts[0] == "pulls" and len(parts) == 2:
            pr = self._find(st, self._int(parts[1]))
            if method == "GET":
                return copy.deepcopy(pr["github"])
            if method == "PATCH":
                if body.get("state") == "closed":
                    pr["state"] = "closed"
                    pr["github"]["state"] = "closed"
                return copy.deepcopy(pr["github"])
        if parts[0] == "issues" and len(parts) == 3 and method == "POST":
            pr = self._find(st, self._int(parts[1]))
            if parts[2] == "comments":
                note = {"id": len(st["notes"]) + 1, "body": body.get("body", "")}
                st["notes"].append({"number": pr["number"], **note})
                return note
            if parts[2] == "labels":
                labels = sorted(
                    set(pr["github"]["labels"]) | set(body.get("labels") or [])
                )
                pr["github"]["labels"] = labels
                return [{"name": x} for x in labels]
        raise FakeForgeHTTPError(404, f"404 Not Found: {method} {path}")

    def _gh_tree(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        base = body.get("base_tree")
        if base not in st["trees"]:
            raise FakeForgeHTTPError(422, f"base_tree is not a known tree: {base}")
        files = dict(st["trees"][base])
        for entry in body.get("tree") or []:
            files[entry["path"]] = _sha1({"content": entry.get("content", "")})
        sha = _sha1({"files": files})
        st["trees"][sha] = files
        return {"sha": sha}

    def _gh_commit(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        tree = body.get("tree")
        parents = list(body.get("parents") or [])
        if tree not in st["trees"]:
            raise FakeForgeHTTPError(422, f"tree is not a known tree: {tree}")
        for parent in parents:
            if parent not in st["commits"]:
                raise FakeForgeHTTPError(422, f"parent is not a known commit: {parent}")
        message = str(body.get("message", ""))
        sha = _sha1({"tree": tree, "parents": parents, "message": message})
        st["commits"][sha] = {"tree": tree, "parents": parents, "message": message}
        return {"sha": sha, "tree": {"sha": tree}}

    def _gh_create_ref(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        ref = str(body.get("ref", ""))
        sha = body.get("sha")
        if not ref.startswith("refs/heads/"):
            raise FakeForgeHTTPError(422, f"only refs/heads/* is modelled: {ref}")
        name = ref[len("refs/heads/") :]
        if name in st["branches"]:
            raise FakeForgeHTTPError(422, "Reference already exists")
        if sha not in st["commits"]:
            raise FakeForgeHTTPError(422, f"Object does not exist: {sha}")
        st["branches"][name] = sha
        return {"ref": ref, "object": {"sha": sha, "type": "commit"}}

    def _gh_update_ref(
        self, st: dict[str, Any], name: str, body: Mapping[str, Any]
    ) -> dict:
        if name not in st["branches"]:
            raise FakeForgeHTTPError(422, f"Reference does not exist: {name}")
        sha = body.get("sha")
        if not isinstance(sha, str) or sha not in st["commits"]:
            raise FakeForgeHTTPError(422, f"Object does not exist: {sha}")
        old = st["branches"][name]
        if not body.get("force") and not self._descends(st, sha, old):
            raise FakeForgeHTTPError(422, "Update is not a fast forward")
        st["branches"][name] = sha
        for pr in st["mrs"]:
            if pr["source"] == name:
                pr["github"]["head"]["sha"] = sha
        return {"ref": f"refs/heads/{name}", "object": {"sha": sha, "type": "commit"}}

    @staticmethod
    def _descends(st: dict[str, Any], sha: str, ancestor: str) -> bool:
        seen: set[str] = set()
        stack = [sha]
        while stack:
            cur = stack.pop()
            if cur == ancestor:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(st["commits"].get(cur, {}).get("parents", []))
        return False

    def _gh_create_pr(self, st: dict[str, Any], body: Mapping[str, Any]) -> dict:
        head = body.get("head")
        base = body.get("base")
        for name in (head, base):
            if name not in st["branches"]:
                raise FakeForgeHTTPError(422, f"Validation Failed: no branch {name}")
        for pr in st["mrs"]:
            if pr["state"] == "open" and pr["source"] == head and pr["target"] == base:
                raise FakeForgeHTTPError(
                    422,
                    "A pull request already exists for "
                    f"{GITHUB_REPOSITORY.split('/')[0]}:{head}.",
                )
        number = st["next_number"]
        st["next_number"] = number + 1
        view = {
            "id": number + _GITHUB_ID_OFFSET,
            "number": number,
            "state": "open",
            "title": body.get("title", ""),
            "body": body.get("body", ""),
            "head": {"ref": head, "sha": st["branches"][head]},
            "base": {"ref": base},
            "labels": [],
            "html_url": f"{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/pull/{number}",
        }
        st["mrs"].append(
            {
                "number": number,
                "state": "open",
                "source": head,
                "target": base,
                "github": view,
            }
        )
        return copy.deepcopy(view)

    def _gh_list(self, st: dict[str, Any], params: Mapping[str, str]) -> list:
        state = params.get("state", "open")
        head_filter = params.get("head")
        if head_filter is not None:
            owner = GITHUB_REPOSITORY.split("/")[0]
            if ":" not in head_filter:
                raise FakeForgeHTTPError(422, "head must be in the form owner:branch")
            got_owner, branch = head_filter.split(":", 1)
            if got_owner != owner:
                return []
            head_filter = branch
        rows = []
        for pr in sorted(st["mrs"], key=lambda m: -m["number"]):
            if state != "all" and pr["state"] != state:
                continue
            if head_filter is not None and pr["source"] != head_filter:
                continue
            if "base" in params and pr["target"] != params["base"]:
                continue
            rows.append(copy.deepcopy(pr["github"]))
        return self._page(rows, params, "github")

    # ------------------------------------------------------- test-side hooks

    def page_limits(self, provider: str) -> tuple[int, int]:
        """The provider's (default per_page, max per_page)."""
        return _PAGE_LIMITS[provider]

    def branch_head(self, provider: str, branch: str) -> str:
        sha: str = self._read()[provider]["branches"][branch]
        return sha

    def merge_requests(self, provider: str) -> list[dict]:
        """Every MR/PR (provider view), ascending by iid/number."""
        rows = sorted(self._read()[provider]["mrs"], key=lambda m: m["number"])
        return [r[provider] for r in rows]

    def mr(self, provider: str, number: int) -> dict:
        view: dict = self._find(self._read()[provider], number)[provider]
        return view

    def close(self, provider: str, number: int) -> None:
        """Close MR/PR ``number`` (as a human would in the forge UI)."""

        def run(state: dict[str, Any]) -> None:
            mr = self._find(state[provider], number)
            closed = "closed"
            mr["state"] = closed
            mr[provider]["state"] = closed

        self._transact(run)

    def human_commit(self, provider: str, number: int) -> str:
        """Push a human commit onto MR/PR ``number``'s source branch; return its sha."""

        def run(state: dict[str, Any]) -> str:
            st = state[provider]
            mr = self._find(st, number)
            branch = mr["source"]
            head = st["branches"][branch]
            files = dict(st["trees"][st["commits"][head]["tree"]])
            files["HUMAN_EDIT.md"] = _sha1({"content": f"human edit on {head}"})
            sha = self._new_commit(st, files, head, "human edit")
            st["branches"][branch] = sha
            if provider == "gitlab":
                mr["gitlab"]["sha"] = sha
            else:
                mr["github"]["head"]["sha"] = sha
            return sha

        result: str = self._transact(run)
        return result
