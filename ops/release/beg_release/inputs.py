"""Build-input inventory for the declared deployment layout.

Every file that influences an image must be versioned: the layout files (compose +
Dockerfiles) come from ``ops/synology/deploy`` in the release tree, and every
``COPY``/``ADD`` source must exist in the release tree. A missing or undeclared input
fails the build, and a compose file that no longer matches ``layout.json`` fails too.
"""
import hashlib
import json
import re

from .gitobj import ReleaseError

_INSTR = re.compile(r"^\s*([A-Za-z]+)\s+(.*)$")


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(obj):
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def _logical_lines(text):
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        yield (buf + line).strip()
        buf = ""
    if buf.strip():
        yield buf.strip()


def parse_dockerfile(text):
    """Return {'base_images': [...], 'sources': [...], 'args': [...]} for the subset of
    Dockerfile syntax the layout uses. Unsupported source forms fail closed."""
    base_images, sources, args, stages = [], [], [], set()
    for line in _logical_lines(text):
        m = _INSTR.match(line)
        if not m:
            continue
        instr, rest = m.group(1).upper(), m.group(2).strip()
        if instr == "FROM":
            parts = rest.split()
            image = parts[0]
            if len(parts) >= 3 and parts[1].upper() == "AS":
                stages.add(parts[2])
            if image not in stages:
                base_images.append(image)
        elif instr == "ARG":
            args.append(rest.split("=", 1)[0].strip())
        elif instr in ("COPY", "ADD"):
            if rest.startswith("["):
                raise ReleaseError("JSON-form %s is not supported by the input inventory: %s" % (instr, line))
            tokens = rest.split()
            from_stage = any(t.startswith("--from=") for t in tokens)
            tokens = [t for t in tokens if not t.startswith("--")]
            if len(tokens) < 2:
                raise ReleaseError("malformed %s: %s" % (instr, line))
            if from_stage:
                continue
            for src in tokens[:-1]:
                if any(ch in src for ch in "*?[") or "://" in src:
                    raise ReleaseError("wildcard/remote %s source not supported: %s" % (instr, src))
                sources.append(src)
    return {"base_images": base_images, "sources": sources, "args": args}


def parse_compose_services(text):
    """Minimal parser for the compose subset in the layout: services → container_name,
    build.context, build.dockerfile, build.args. Anything else is ignored; the result is
    compared with layout.json, so structural drift fails the release."""
    services, current, section = {}, None, None
    in_services = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            in_services = line == "services:"
            current = section = None
            continue
        if not in_services:
            continue
        if indent == 2 and line.endswith(":"):
            current = line[:-1]
            services[current] = {"container": None, "context": None, "dockerfile": None, "build_args": {}}
            section = None
            continue
        if current is None:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if indent == 4:
            section = key
            if key == "container_name":
                services[current]["container"] = value
        elif indent == 6 and section == "build":
            if key in ("context", "dockerfile"):
                services[current][key] = value
            elif key == "args":
                section = "build.args"
        elif indent == 8 and section == "build.args":
            services[current]["build_args"][key] = value
    return services


def _expand_source(src, tree_paths):
    norm = src[2:] if src.startswith("./") else src
    if norm in ("", "."):
        return sorted(tree_paths)
    if norm.endswith("/"):
        prefix = norm
        matched = sorted(p for p in tree_paths if p.startswith(prefix))
    elif norm in tree_paths:
        matched = [norm]
    else:
        prefix = norm + "/"
        matched = sorted(p for p in tree_paths if p.startswith(prefix))
    if not matched:
        raise ReleaseError("missing build input: '%s' is copied by a Dockerfile but is not in the release tree" % src)
    return matched


def inventory(layout, tree_entries, layout_blobs):
    """Build the service/input inventory.

    ``tree_entries``: {path: (mode, blob_sha)} of the effective source tree.
    ``layout_blobs``: {layout_file_name: bytes} taken from the versioned layout dir.
    Returns (services, layout_file_sha256, unpinned_base_images).
    """
    for name in layout["layout_files"]:
        if name not in layout_blobs:
            raise ReleaseError("missing build input: layout file %s/%s is not versioned in the release tree"
                               % (layout["versioned_layout_dir"], name))
    compose = parse_compose_services(layout_blobs["docker-compose.yml"].decode("utf-8"))
    declared = layout["services"]
    if sorted(compose) != sorted(declared):
        raise ReleaseError("compose services %s do not match layout.json %s" % (sorted(compose), sorted(declared)))
    services, unpinned = {}, []
    for name in sorted(declared):
        want, got = declared[name], compose[name]
        for key in ("container", "context", "dockerfile", "build_args"):
            if want[key] != got[key]:
                raise ReleaseError("compose drift for service %s: %s is %r, layout.json declares %r"
                                   % (name, key, got[key], want[key]))
        dockerfile_name = want["dockerfile"].split("/")[-1]
        if dockerfile_name not in layout_blobs:
            raise ReleaseError("missing build input: %s is not a versioned layout file" % dockerfile_name)
        parsed = parse_dockerfile(layout_blobs[dockerfile_name].decode("utf-8"))
        inputs = []
        for src in parsed["sources"]:
            for path in _expand_source(src, tree_entries):
                mode, blob = tree_entries[path]
                inputs.append([path, mode, blob])
        inputs = sorted({tuple(i) for i in inputs})
        for image in parsed["base_images"]:
            if "@sha256:" not in image and image not in unpinned:
                unpinned.append(image)
        fingerprint = sha256_json({
            "dockerfile_sha256": hashlib.sha256(layout_blobs[dockerfile_name]).hexdigest(),
            "compose_service": want,
            "base_images": parsed["base_images"],
            "inputs": [list(i) for i in inputs],
        })
        services[name] = {
            "container": want["container"],
            "dockerfile": dockerfile_name,
            "base_images": parsed["base_images"],
            "copy_sources": parsed["sources"],
            "input_file_count": len(inputs),
            "fingerprint": fingerprint,
        }
    layout_sha = {n: hashlib.sha256(layout_blobs[n]).hexdigest() for n in layout["layout_files"]}
    return services, layout_sha, unpinned


def services_to_rebuild(services, previous_manifest):
    """Only services whose input fingerprint changed; everything when unknown (safe default)."""
    if not previous_manifest:
        return sorted(services), "no previous manifest: rebuild all services"
    prev = previous_manifest.get("release", {}).get("build", {}).get("services", {})
    changed = [name for name in sorted(services)
               if name not in prev or prev[name].get("fingerprint") != services[name]["fingerprint"]]
    return changed, "fingerprint comparison with previous release %s" % previous_manifest["release"]["release_id"]
