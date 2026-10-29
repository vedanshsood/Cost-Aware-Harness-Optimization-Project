"""Standard-library output checks.

Checks inspect file structure and observable changes.
Passing checks does not establish semantic task correctness.
"""

import hashlib
import json
import re
import struct
import tokenize
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath


def _json_file(path):
    path = Path(path)

    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError(
            "JSON exceeds the 16 MiB inspection limit."
        )

    return json.loads(
        path.read_text(encoding="utf-8-sig")
    )


def _digest(path):
    """Hash a bounded regular file without changing it."""
    path = Path(path)

    if path.is_symlink() or not path.is_file():
        raise ValueError(
            f"Not a regular non-symlink file: {path}"
        )

    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError(
            f"File exceeds the 64 MiB hashing limit: {path}"
        )

    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def expand_declared_outputs(paths, manifest_paths):
    """Resolve supported required_* JSON output declarations."""
    resolved = list(
        dict.fromkeys(map(str, paths))
    )

    roots = [
        PurePosixPath(path)
        for path in resolved
    ]

    result = {
        "paths": resolved,
        "sources": [],
        "declarations": [],
        "errors": [],
    }

    def fail(source, reason):
        result["errors"].append({
            "manifest": str(source),
            "reason": reason,
        })

    def visit(value, source, location="$", depth=0):
        if depth > 32:
            fail(
                source,
                "JSON nesting exceeds the resolver limit.",
            )
            return

        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(
                    item,
                    source,
                    f"{location}[{index}]",
                    depth + 1,
                )

        elif isinstance(value, dict):
            for key, names in value.items():
                match = re.fullmatch(
                    r"required_(?:(.+)_)?"
                    r"(?:artifacts|files|outputs)",
                    key,
                )

                if match:
                    valid_names = (
                        isinstance(names, list)
                        and bool(names)
                        and all(
                            isinstance(name, str)
                            and name.strip()
                            for name in names
                        )
                    )

                    if not valid_names:
                        fail(
                            source,
                            f"{location}.{key}: expected a "
                            "nonempty filename list.",
                        )

                    elif len(names) > 100:
                        fail(
                            source,
                            f"{location}.{key}: more than "
                            "100 filenames.",
                        )

                    else:
                        prefix = match.group(1)

                        if prefix:
                            directory_keys = [
                                f"{prefix}_output_dir",
                                f"{prefix}_dir",
                            ]
                        else:
                            directory_keys = [
                                "output_dir",
                                "artifact_dir",
                            ]

                        directories = list(
                            dict.fromkeys(
                                value[key_name]
                                for key_name in directory_keys
                                if isinstance(
                                    value.get(key_name),
                                    str,
                                )
                                and value[key_name]
                            )
                        )

                        relative_names = any(
                            not PurePosixPath(name).is_absolute()
                            for name in names
                        )

                        if (
                            relative_names
                            and len(directories) != 1
                        ):
                            fail(
                                source,
                                f"{location}.{key}: no unambiguous "
                                "sibling output directory.",
                            )

                        else:
                            children = []

                            for name in names:
                                child = PurePosixPath(name)

                                if not child.is_absolute():
                                    child = (
                                        PurePosixPath(directories[0])
                                        / child
                                    )

                                allowed = (
                                    child.is_absolute()
                                    and ".." not in child.parts
                                    and any(
                                        child == root
                                        or root in child.parents
                                        for root in roots
                                    )
                                )

                                if not allowed:
                                    fail(
                                        source,
                                        "Disallowed declared output "
                                        f"path: {child}",
                                    )
                                    continue

                                text = str(child)
                                children.append(text)

                                if text not in resolved:
                                    resolved.append(text)

                            result["declarations"].append({
                                "manifest": str(source),
                                "field": f"{location}.{key}",
                                "paths": children,
                            })

                if isinstance(names, (dict, list)):
                    visit(
                        names,
                        source,
                        f"{location}.{key}",
                        depth + 1,
                    )

    manifests = list(
        dict.fromkeys(map(str, manifest_paths))
    )

    if len(manifests) > 16:
        fail(
            "",
            "More than 16 referenced JSON files; "
            "resolution skipped.",
        )
        return result

    for source in manifests:
        result["sources"].append(source)

        try:
            visit(
                _json_file(source),
                source,
            )

        except (
            OSError,
            ValueError,
            UnicodeError,
            RecursionError,
        ) as error:
            fail(
                source,
                f"{type(error).__name__}: {error}",
            )

    return result


def check_png(path):
    """Inspect PNG chunks and CRCs without decoding pixels."""
    size = path.stat().st_size

    if size > 64 * 1024 * 1024:
        return "PNG exceeds the 64 MiB inspection limit."

    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            return "Invalid PNG signature."

        first = True
        image_data = False

        while True:
            header = stream.read(8)

            if len(header) != 8:
                return "PNG is truncated or missing IEND."

            length, kind = struct.unpack(
                ">I4s",
                header,
            )

            if length > size:
                return "Invalid PNG chunk length."

            data = stream.read(length)
            checksum = stream.read(4)

            if len(data) != length or len(checksum) != 4:
                return "Truncated PNG chunk."

            expected_crc = struct.unpack(
                ">I",
                checksum,
            )[0]

            actual_crc = (
                zlib.crc32(kind + data)
                & 0xFFFFFFFF
            )

            if expected_crc != actual_crc:
                return "PNG chunk checksum mismatch."

            if first:
                if kind != b"IHDR" or length != 13:
                    return "Missing or invalid PNG header."

                if 0 in struct.unpack(">II", data[:8]):
                    return "Invalid PNG dimensions."

                first = False

            if kind == b"IDAT":
                image_data = True

            if kind == b"IEND":
                if length or not image_data:
                    return (
                        "Invalid PNG end or missing image data."
                    )

                if stream.read(1):
                    return "Unexpected bytes after PNG end."

                return None


def check_artifact(path_text):
    """Check basic validity for one file or directory."""
    path = Path(path_text)

    result = {
        "path": str(path),
        "valid": False,
        "kind": "basic_file",
    }

    try:
        if not path.exists():
            raise ValueError(
                "Required path does not exist."
            )

        if path.is_dir():
            result.update(
                valid=True,
                reason=(
                    "Directory exists; required contents "
                    "need separate checks."
                ),
            )
            return result

        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(
                "Output is not a nonempty regular file."
            )

        extension = path.suffix.lower()

        if extension == ".png":
            error = check_png(path)

            if error:
                raise ValueError(error)

        elif extension in {
            ".docx",
            ".xlsx",
            ".pptx",
            ".epub",
        }:
            required = {
                ".docx": "word/document.xml",
                ".xlsx": "xl/workbook.xml",
                ".pptx": "ppt/presentation.xml",
                ".epub": "META-INF/container.xml",
            }[extension]

            with zipfile.ZipFile(path) as archive:
                if required not in archive.namelist():
                    raise ValueError(
                        f"Missing package entry: {required}"
                    )

        elif extension == ".json":
            _json_file(path)

        elif extension == ".py":
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError(
                    "Python source exceeds 16 MiB."
                )

            # Compile only: do not execute or import task code.
            # This also avoids writing __pycache__ files.
            with tokenize.open(str(path)) as stream:
                compile(
                    stream.read(),
                    str(path),
                    "exec",
                    dont_inherit=True,
                )

        elif extension == ".pdf":
            # Basic envelope inspection, not a full PDF parser.
            with path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError(
                        "Invalid PDF header."
                    )

                stream.seek(
                    max(
                        0,
                        path.stat().st_size - 4096,
                    )
                )

                if b"%%EOF" not in stream.read():
                    raise ValueError(
                        "PDF end marker not found."
                    )

        result.update(
            valid=True,
            reason=(
                "Basic checks passed; semantic correctness "
                "is unverified."
            ),
        )

    except (
        OSError,
        ValueError,
        UnicodeError,
        SyntaxError,
        zipfile.BadZipFile,
        struct.error,
        RecursionError,
    ) as error:
        result["reason"] = (
            f"{type(error).__name__}: {error}"
        )

    return result


def check_artifacts(paths):
    return [
        check_artifact(path)
        for path in paths
    ]


def _images(directory):
    """Snapshot image names and hashes in one directory."""
    extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
    }

    paths = sorted(
        path
        for path in Path(directory).iterdir()
        if path.suffix.lower() in extensions
    )

    if len(paths) > 100:
        raise ValueError(
            "More than 100 images; rename snapshot unavailable."
        )

    return {
        path.name: _digest(path)
        for path in paths
    }


def _pdfs(directory):
    """Snapshot PDF names and hashes in one directory."""
    root = Path(directory)

    if not root.exists():
        return {}

    paths = sorted(
        path
        for path in root.iterdir()
        if path.suffix.lower() == ".pdf"
    )

    if len(paths) > 100:
        raise ValueError(
            "More than 100 PDFs; snapshot unavailable."
        )

    return {
        path.name: _digest(path)
        for path in paths
    }


def _public_setup():
    """Read only the public setup fields used for discovery."""
    path = Path(
        "/usr/local/share/tua/task_spec.json"
    )

    if not path.is_file():
        return {}

    document = _json_file(path)

    if not isinstance(document, dict):
        raise ValueError(
            "Public setup metadata must be an object."
        )

    return {
        key: document.get(key)
        for key in ("downloads", "startup")
    }


def prepare_checks(instruction, paths, manifest_paths):
    """Capture requirements and initial state before model execution."""
    expansion = expand_declared_outputs(
        paths,
        manifest_paths,
    )

    snapshot = {
        "status": "prepared",
        "required_paths": expansion["paths"],
        "declaration_sources": expansion["sources"],
        "declared_output_groups": expansion["declarations"],
        "declaration_errors": expansion["errors"],
        "alternatives": [],
        "code_files": [],
        "rename_groups": [],
        "pdf_groups": [],
        "errors": [],
        "limitations": [],
    }

    def error(stage, exception):
        snapshot["errors"].append({
            "stage": stage,
            "reason": str(exception),
        })

    quoted = re.findall(
        r"`([^`\r\n]+)`",
        instruction,
    )

    absolute = [
        path
        for path in quoted
        if path.startswith("/")
        and ".." not in PurePosixPath(path).parts
        and not any(
            character in path
            for character in "*?{}"
        )
    ]

    setup = {}

    try:
        setup = _public_setup()

    except (
        OSError,
        ValueError,
        UnicodeError,
        RecursionError,
    ) as exception:
        error("public_setup", exception)

    downloads = setup.get("downloads") or []

    if not isinstance(downloads, list):
        downloads = []

    supplied = []

    for entry in downloads:
        text = (
            entry.get("path")
            if isinstance(entry, dict)
            else None
        )

        if (
            isinstance(text, str)
            and text.startswith("/")
            and ".." not in PurePosixPath(text).parts
        ):
            supplied.append(text)

    # Accepted output filenames are alternatives, not an all-required list.
    alternative_pattern = (
        r"(?im)^\s*(?:accepted|allowed|permitted)\s+"
        r"(?:output\s+)?filenames?\s+"
        r"(?:are|include)\s+(.+)$"
    )

    for match in re.finditer(
        alternative_pattern,
        instruction,
    ):
        try:
            names = re.findall(
                r"`([^`]+)`",
                match.group(1),
            )

            valid_names = (
                bool(names)
                and all(
                    PurePosixPath(name).name == name
                    and name not in {".", ".."}
                    and not any(
                        character in name
                        for character in "*?{}"
                    )
                    for name in names
                )
            )

            if not valid_names:
                raise ValueError(
                    "Could not resolve accepted filename alternatives."
                )

            directories = list(
                dict.fromkeys(
                    str(Path(path))
                    for path in absolute
                    if Path(path).is_dir()
                )
            )

            if (
                len(directories) != 1
                or not re.search(
                    r"\bsame directory\b",
                    instruction,
                    re.IGNORECASE,
                )
            ):
                raise ValueError(
                    "No unambiguous directory for filename alternatives."
                )

            snapshot["alternatives"].append({
                "directory": directories[0],
                "paths": [
                    str(Path(directories[0]) / name)
                    for name in names
                ],
            })

        except (OSError, ValueError) as exception:
            error(
                "filename_alternatives",
                exception,
            )

    # Discover Python source from public downloads and explicit paths.
    repair = (
        re.search(
            r"\b(?:fix|repair|debug)\b",
            instruction,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:code|python|program|bugs?)\b",
            instruction,
            re.IGNORECASE,
        )
    )

    if repair:
        try:
            files = list(
                dict.fromkeys(
                    path
                    for path in supplied + absolute
                    if Path(path).suffix.lower() == ".py"
                )
            )

            if not files or len(files) > 100:
                raise ValueError(
                    "No bounded Python source set could be discovered."
                )

            snapshot["code_files"] = [
                {
                    "path": path,
                    "before_sha256": _digest(path),
                }
                for path in files
            ]

            snapshot["limitations"].append(
                "Python checks establish syntax, "
                "not functional bug repair."
            )

        except (OSError, ValueError) as exception:
            error(
                "python_source_discovery",
                exception,
            )

    # Capture image contents before the agent can rename or modify them.
    rename = re.search(
        r"\brenam(?:e|es|ed|ing)\b"
        r"|\bchange\s+(?:their\s+)?filenames?\b",
        instruction,
        re.IGNORECASE,
    )

    if rename:
        try:
            image_extensions = {
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".tif",
                ".tiff",
                ".webp",
            }

            directories = sorted({
                str(Path(path).parent)
                for path in supplied
                if Path(path).suffix.lower() in image_extensions
            })

            if not directories:
                raise ValueError(
                    "No supplied image directory could be discovered."
                )

            for directory in directories:
                before = _images(directory)

                if not before:
                    raise ValueError(
                        "No images found before execution: "
                        f"{directory}"
                    )

                snapshot["rename_groups"].append({
                    "directory": directory,
                    "before": before,
                })

            snapshot["limitations"].append(
                "Rename checks preserve image bytes and require "
                "changed filenames; names are not identified."
            )

        except (OSError, ValueError) as exception:
            error(
                "image_rename_snapshot",
                exception,
            )

    # Use initial URLs declared by public setup metadata.
    browser_pdf = (
        re.search(
            r"\bpdfs?\b",
            instruction,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:blogs?|articles?|tabs?|webpages?|web pages?)\b",
            instruction,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:download|save|store|export|print|convert)\b",
            instruction,
            re.IGNORECASE,
        )
    )

    if browser_pdf:
        try:
            startup = setup.get("startup") or {}

            urls = (
                startup.get("chrome_urls", [])
                if isinstance(startup, dict)
                else []
            )

            urls = list(
                dict.fromkeys(
                    url
                    for url in urls
                    if isinstance(url, str)
                    and url.startswith(
                        ("https://", "http://")
                    )
                )
            )

            directories = list(
                dict.fromkeys(
                    path
                    for path in paths
                    if not Path(path).suffix
                )
            )

            if not urls or len(directories) != 1:
                raise ValueError(
                    "Could not resolve initial browser URLs "
                    "and one PDF output directory."
                )

            directory = directories[0]

            snapshot["pdf_groups"].append({
                "directory": directory,
                "source_urls": urls,
                "before": _pdfs(directory),
                "expected_count": len(urls),
            })

            snapshot["limitations"].append(
                "PDF checks use setup-declared URLs and inspect "
                "header/end markers and output count. Actual browser "
                "state, article identity, titles, and full PDF "
                "integrity are unverified."
            )

        except (OSError, ValueError) as exception:
            error(
                "browser_pdf_snapshot",
                exception,
            )

    snapshot["has_checks"] = bool(
        snapshot["required_paths"]
        or snapshot["alternatives"]
        or snapshot["code_files"]
        or snapshot["rename_groups"]
        or snapshot["pdf_groups"]
    )

    return snapshot


def validate_outputs(
    paths,
    manifest_paths,
    snapshot,
    limit=100,
):
    """Check final outputs using the pre-execution snapshot.

    manifest_paths is retained in the interface for provenance.
    Requirements are taken from the saved snapshot rather than
    re-reading potentially modified inputs after execution.
    """
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("status") != "prepared"
    ):
        snapshot = {
            "required_paths": paths,
            "errors": [
                {
                    "stage": "preparation",
                    "reason": (
                        "Initial snapshot unavailable; "
                        "dynamic checks were not established."
                    ),
                }
            ],
        }

    errors = list(
        snapshot.get("errors", [])
    )

    declaration_errors = list(
        snapshot.get("declaration_errors", [])
    )

    checks = []
    seen = set()
    truncated = False

    def add(record):
        nonlocal truncated

        if len(checks) >= limit:
            truncated = True
            return

        checks.append(record)

    required = list(
        dict.fromkeys(
            snapshot.get("required_paths", paths)
        )
    )

    for text in required:
        if text not in seen:
            add(check_artifact(text))
            seen.add(text)

    for text in required:
        directory = Path(text)

        if truncated:
            break

        try:
            if (
                not directory.is_dir()
                or directory.is_symlink()
            ):
                continue

            for child in directory.rglob("*"):
                if (
                    child.is_file()
                    and str(child) not in seen
                ):
                    add(
                        check_artifact(str(child))
                    )
                    seen.add(str(child))

                    if truncated:
                        break

        except OSError as exception:
            errors.append({
                "stage": "directory_scan",
                "reason": str(exception),
            })

    for group in snapshot.get("alternatives", []):
        candidates = check_artifacts(
            group["paths"]
        )

        add({
            "path": group["directory"],
            "kind": "output_alternatives",
            "valid": any(
                candidate["valid"]
                for candidate in candidates
            ),
            "reason": (
                "At least one permitted output must pass "
                "basic file checks: "
                + ", ".join(group["paths"])
            ),
            "candidates": candidates,
        })

    for source in snapshot.get("code_files", []):
        check = check_artifact(
            source["path"]
        )
        check["kind"] = "python_syntax"

        try:
            check["changed"] = (
                _digest(source["path"])
                != source["before_sha256"]
            )

        except (OSError, ValueError):
            check["changed"] = None

        add(check)

    for group in snapshot.get("rename_groups", []):
        try:
            after = _images(
                group["directory"]
            )
            before = group["before"]

            same_content = (
                Counter(before.values())
                == Counter(after.values())
            )

            old_names_removed = not (
                set(before) & set(after)
            )

            add({
                "path": group["directory"],
                "kind": "image_rename_integrity",
                "valid": bool(
                    same_content
                    and old_names_removed
                ),
                "reason": (
                    "Image contents must be preserved and original "
                    "filenames replaced; semantic names are unverified."
                ),
                "before_names": sorted(before),
                "after_names": sorted(after),
                "same_image_contents": same_content,
                "original_names_removed": old_names_removed,
            })

        except (OSError, ValueError) as exception:
            errors.append({
                "stage": "image_rename_check",
                "reason": str(exception),
            })

    for group in snapshot.get("pdf_groups", []):
        try:
            after = _pdfs(
                group["directory"]
            )

            changed = [
                name
                for name, digest in after.items()
                if group["before"].get(name) != digest
            ]

            candidates = [
                check_artifact(
                    str(Path(group["directory"]) / name)
                )
                for name in changed
            ]

            valid_count = sum(
                candidate["valid"]
                for candidate in candidates
            )

            add({
                "path": group["directory"],
                "kind": "browser_pdf_outputs",
                "valid": (
                    valid_count >= group["expected_count"]
                ),
                "reason": (
                    "Require enough new or modified PDFs with "
                    "basic header/end checks. "
                    "Article correspondence is unverified."
                ),
                "expected_count": group["expected_count"],
                "valid_output_count": valid_count,
                "source_urls": group["source_urls"],
                "candidates": candidates,
            })

        except (OSError, ValueError) as exception:
            errors.append({
                "stage": "browser_pdf_check",
                "reason": str(exception),
            })

    all_valid = (
        all(check["valid"] for check in checks)
        if checks
        else None
    )

    if all_valid and (
        truncated
        or errors
        or declaration_errors
    ):
        all_valid = None

    return {
        "status": "checked",
        "all_valid": all_valid,
        "checks": checks,
        "truncated": truncated,
        "declaration_sources": snapshot.get(
            "declaration_sources",
            [],
        ),
        "declared_output_groups": snapshot.get(
            "declared_output_groups",
            [],
        ),
        "declaration_errors": declaration_errors,
        "validation_errors": errors,
        "limitations": snapshot.get(
            "limitations",
            [],
        ),
        "reason": (
            "Checks cover observable structure and changes, "
            "not task correctness."
        ),
    }