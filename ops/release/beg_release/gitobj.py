"""Exact-version artifacts built from Git objects, and Git tree verification.

Why not ``git archive``: it applies checkout conversions (``core.autocrlf``, ``eol``,
``export-subst``, ``export-ignore``). On the release PC ``core.autocrlf=true`` turned
702 LF files into CRLF in the W0-02 deploy artifact. Here the archive is written
from raw blob bytes (``git cat-file --batch``) and its identity is proven
independently by recomputing the Git tree hash from the archive itself.
"""
import hashlib
import io
import os
import stat
import subprocess
import tarfile
import tempfile

MODE_FILE = "100644"
MODE_EXEC = "100755"
SUPPORTED_MODES = (MODE_FILE, MODE_EXEC)


class ReleaseError(Exception):
    """A release integrity rule was violated. Always fail closed."""


def _git(repo, *args, input_bytes=None):
    proc = subprocess.run(["git", "-C", str(repo), *args], input=input_bytes,
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise ReleaseError("git %s failed: %s" % (" ".join(args[:2]),
                                                 proc.stderr.decode("utf-8", "replace").strip()))
    return proc.stdout


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_commit(repo, ref):
    sha = _git(repo, "rev-parse", "--verify", "%s^{commit}" % ref).decode().strip()
    tree = _git(repo, "rev-parse", "%s^{tree}" % sha).decode().strip()
    commit_time = int(_git(repo, "show", "-s", "--format=%ct", sha).decode().strip())
    return sha, tree, commit_time


def is_ancestor(repo, commit, ref):
    proc = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, ref],
                          capture_output=True)
    return proc.returncode == 0


def ls_tree(repo, commit):
    """path -> (mode, blob_sha) for every file of the commit tree. Fails closed on
    symlinks and submodules (not supported by the release format)."""
    entries = {}
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        mode, typ, sha = meta.decode().split()
        path = path.decode("utf-8")
        if typ != "blob" or mode not in SUPPORTED_MODES:
            raise ReleaseError("unsupported tree entry %s (%s %s)" % (path, mode, typ))
        entries[path] = (mode, sha)
    return entries


def read_blobs(repo, shas):
    """Raw blob bytes via ``git cat-file --batch`` — no filters, no conversions."""
    wanted = sorted(set(shas))
    out = _git(repo, "cat-file", "--batch", input_bytes=("\n".join(wanted) + "\n").encode())
    blobs, pos = {}, 0
    for sha in wanted:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode().split()
        if len(header) != 3 or header[1] != "blob":
            raise ReleaseError("cat-file returned %r for %s" % (header, sha))
        size = int(header[2])
        data = out[nl + 1:nl + 1 + size]
        if blob_sha(data) != sha:
            raise ReleaseError("blob %s content does not hash to its id" % sha)
        blobs[sha] = data
        pos = nl + 1 + size + 1
    return blobs


def tree_sha(entries):
    """Git tree hash of {path: (mode, blob_sha)} (nested trees, Git sort order)."""
    root = {}
    for path, (mode, sha) in entries.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ReleaseError("path conflict at %s" % path)
        if parts[-1] in node:
            raise ReleaseError("duplicate path %s" % path)
        node[parts[-1]] = (mode, sha)

    def build(node):
        items = []
        for name, value in node.items():
            if isinstance(value, dict):
                items.append((name.encode() + b"/", b"40000", name.encode(), bytes.fromhex(build(value))))
            else:
                items.append((name.encode(), value[0].encode(), name.encode(), bytes.fromhex(value[1])))
        items.sort(key=lambda it: it[0])
        body = b"".join(mode + b" " + name + b"\0" + raw for _, mode, name, raw in items)
        return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()

    return build(root)


def build_tar(entries, blobs, mtime):
    """Deterministic PAX tar: sorted paths, fixed mtime/owner, regular files only."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8") as tar:
        for path in sorted(entries):
            mode, sha = entries[path]
            data = blobs[sha]
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mtime = mtime
            info.mode = 0o755 if mode == MODE_EXEC else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _safe_member_name(name):
    if not name or name.startswith("/") or "\\" in name or ":" in name.split("/")[0]:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def tar_entries(tar_path):
    """{path: (mode, blob_sha, bytes)} from an artifact; rejects anything but safe regular files."""
    result = {}
    with tarfile.open(tar_path, mode="r:") as tar:
        for member in tar:
            if member.isdir():
                continue
            if not member.isreg():
                raise ReleaseError("non-regular archive member rejected: %s" % member.name)
            if not _safe_member_name(member.name):
                raise ReleaseError("unsafe archive member name rejected: %r" % member.name)
            if member.name in result:
                raise ReleaseError("duplicate archive member: %s" % member.name)
            data = tar.extractfile(member).read()
            mode = MODE_EXEC if member.mode & 0o111 else MODE_FILE
            result[member.name] = (mode, blob_sha(data), data)
    return result


def tree_sha_of_tar(tar_path):
    entries = tar_entries(tar_path)
    return tree_sha({p: (m, s) for p, (m, s, _) in entries.items()}), entries


def fs_preserves_modes(probe_dir):
    """True when chmod'ed exec bits are observable in ``probe_dir``.

    False on Windows (NTFS) and on filesystems that map permissions from ACLs, where
    every file reports the same mode. There the exec bit is not a property of the files
    on disk, so it cannot be verified there and is taken from the release artifact."""
    if os.name == "nt":
        return False
    try:
        fd, path = tempfile.mkstemp(prefix=".beg-mode-probe-", dir=probe_dir)
    except OSError:
        return False
    os.close(fd)
    try:
        os.chmod(path, 0o644)
        plain = os.stat(path).st_mode & 0o111
        os.chmod(path, 0o755)
        executable = os.stat(path).st_mode & 0o111
        return plain == 0 and executable == 0o111
    except OSError:
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def dir_entries(root, mode_hint=None, fs_modes=None):
    """{path: (mode, blob_sha)} for every file below ``root``. With ``fs_modes`` false
    (default on Windows) the exec bit is not observable and ``mode_hint`` supplies the
    expected mode for known paths; unknown paths count as non-executable."""
    if fs_modes is None:
        fs_modes = os.name != "nt"
    entries = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                raise ReleaseError("symlinked directory rejected: %s" % os.path.join(dirpath, d))
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            st = os.lstat(full)
            if not stat.S_ISREG(st.st_mode):
                raise ReleaseError("non-regular file rejected: %s" % rel)
            with open(full, "rb") as f:
                data = f.read()
            if fs_modes:
                mode = MODE_EXEC if st.st_mode & 0o111 else MODE_FILE
            else:
                mode = (mode_hint or {}).get(rel, MODE_FILE)
            entries[rel] = (mode, blob_sha(data))
    return entries


def verify_dir_tree(root, expected_tree, allow_extra=None, mode_hint=None, fs_modes=None):
    """Prove that ``root`` holds exactly the Git tree ``expected_tree``.

    ``allow_extra`` = {path: blob_sha} lists legacy files that may exist on top of the
    tree only with exactly that content (used once, to adopt the pre-W0-09A layout).
    ``fs_modes`` false: paths and bytes are verified, exec bits come from ``mode_hint``.
    Returns (ok, details)."""
    if fs_modes is None:
        fs_modes = os.name != "nt"
    modes_note = "" if fs_modes else "; exec bits from the release artifact (filesystem does not keep POSIX modes)" \
        if mode_hint else "; filesystem does not keep POSIX modes and no artifact mode hint was given"
    entries = dir_entries(root, mode_hint, fs_modes)
    extras = {}
    for path, blob in (allow_extra or {}).items():
        if path in entries:
            if entries[path][1] != blob:
                return False, "legacy extra %s has unexpected content" % path
            extras[path] = entries.pop(path)
    actual = tree_sha(entries)
    if actual != expected_tree:
        return False, "tree mismatch: expected %s, found %s (%d files%s)" % (expected_tree, actual, len(entries), modes_note)
    return True, "tree %s verified (%d files%s%s)" % (actual, len(entries),
                                                        ", legacy extras: " + ",".join(sorted(extras)) if extras else "",
                                                        modes_note)


def safe_extract(tar_path, dest):
    """Extract verified regular files into a NEW directory and return the tar entries."""
    if os.path.exists(dest):
        raise ReleaseError("staging directory already exists: %s" % dest)
    entries = tar_entries(tar_path)
    os.makedirs(dest)
    dest_abs = os.path.abspath(dest)
    for path, (mode, _sha, data) in sorted(entries.items()):
        target = os.path.abspath(os.path.join(dest_abs, *path.split("/")))
        if not target.startswith(dest_abs + os.sep):
            raise ReleaseError("extraction path escapes staging dir: %s" % path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        if os.name != "nt":
            os.chmod(target, 0o755 if mode == MODE_EXEC else 0o644)
    return entries
