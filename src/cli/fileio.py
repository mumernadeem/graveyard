"""
Text file reading with a fallback for legacy encodings.

Graveyard reads and writes UTF-8. Earlier versions used the platform default
encoding, so files written on Windows (config, incidents, .env) may be CP1252.
"""
import locale


def read_text(filepath):
    """
    Read a text file as UTF-8, falling back to the platform encoding and then
    CP1252 for files written by earlier versions on Windows.

    Raises UnicodeDecodeError if no encoding can decode the file.
    """
    with open(filepath, "rb") as f:
        raw = f.read()

    encodings = ["utf-8-sig"]
    for fallback in (locale.getpreferredencoding(False), "cp1252"):
        if fallback and fallback.lower().replace("_", "-") not in ("utf-8", "utf8", "utf-8-sig"):
            if fallback not in encodings:
                encodings.append(fallback)

    first_error = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            if first_error is None and isinstance(e, UnicodeDecodeError):
                first_error = e
            continue
        # Normalise line endings the same way text-mode open() does.
        return text.replace("\r\n", "\n").replace("\r", "\n")

    raise first_error
