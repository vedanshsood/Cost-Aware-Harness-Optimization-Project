"""Test artifact validation locally, without model calls."""

import json
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path

from harness.artifact_checks import check_artifact, check_artifacts


def png_chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", checksum)
    )


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        # Missing and empty files must fail.
        missing = root / "missing.txt"
        assert check_artifact(missing)["valid"] is False
        print("[OK] Missing file rejected.")

        empty = root / "empty.txt"
        empty.write_text("")
        assert check_artifact(empty)["valid"] is False
        print("[OK] Empty file rejected.")

        # Reproduce the placeholder-image failure we observed.
        fake_png = root / "placeholder.png"
        fake_png.write_text("This is a placeholder for the building render")
        assert check_artifact(fake_png)["valid"] is False
        print("[OK] Text disguised as PNG rejected.")

        # Construct a valid one-pixel RGB PNG.
        header = struct.pack(
            ">IIBBBBB",
            1, 1,       # Width and height.
            8, 2,       # Eight-bit RGB.
            0, 0, 0,    # Compression, filtering, interlacing.
        )

        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", header)
            + png_chunk(
                b"IDAT",
                zlib.compress(b"\x00\x00\x00\x00"),
            )
            + png_chunk(b"IEND", b"")
        )

        valid_png = root / "valid.png"
        valid_png.write_bytes(png_bytes)
        assert check_artifact(valid_png)["valid"] is True
        print("[OK] Basic valid PNG accepted.")

        corrupt_png = root / "corrupt.png"
        damaged = bytearray(png_bytes)
        damaged[-1] ^= 1
        corrupt_png.write_bytes(damaged)
        assert check_artifact(corrupt_png)["valid"] is False
        print("[OK] PNG checksum corruption rejected.")

        valid_json = root / "valid.json"
        valid_json.write_text(json.dumps({"value": 1}))
        assert check_artifact(valid_json)["valid"] is True

        invalid_json = root / "invalid.json"
        invalid_json.write_text("{broken")
        assert check_artifact(invalid_json)["valid"] is False
        print("[OK] Valid and invalid JSON distinguished.")

        # These are minimal package fixtures, not complete documents.
        for extension, required_entry in {
            ".docx": "word/document.xml",
            ".xlsx": "xl/workbook.xml",
            ".pptx": "ppt/presentation.xml",
            ".epub": "META-INF/container.xml",
        }.items():
            good = root / f"basic{extension}"
            with zipfile.ZipFile(good, "w") as archive:
                archive.writestr(required_entry, "<example/>")

            assert check_artifact(good)["valid"] is True

            bad = root / f"wrong{extension}"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("unrelated.txt", "example")

            assert check_artifact(bad)["valid"] is False

        print("[OK] Required document package entries checked.")

        # An existing directory is insufficient when a child is required.
        directory = root / "outputs"
        directory.mkdir()

        checks = check_artifacts([
            str(directory),
            str(directory / "required.txt"),
        ])

        assert checks[0]["valid"] is True
        assert checks[1]["valid"] is False
        print("[OK] Required child file checked separately from directory.")

    print("\nAll basic artifact-checker tests passed.")
    print("No model calls or benchmark attempts were made.")


if __name__ == "__main__":
    main()