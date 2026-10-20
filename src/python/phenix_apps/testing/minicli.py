"""A port of minimega's command lexer, to check the words a command delivers.

minimega lexes each command with minicli (pkg/minicli/input.go). A namespaced
command is lexed twice: minimega rebuilds the subcommand from its words,
Go-quoting only those that hold whitespace, and lexes it again. A mesh peer of
the namespace gets the command rebuilt and lexed a third time.
"""

from phenix_apps.common.go_unicode import go_is_print

ESCAPES = {
    "r": "\r",
    "n": "\n",
    "t": "\t",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "#": "#",
}

# Go's unicode.IsSpace: the Unicode White_Space property.
GO_SPACE = frozenset(
    [
        *"\t\n\v\f\r ",
        *map(chr, (0x85, 0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000)),
        *map(chr, range(0x2000, 0x200B)),
    ]
)

# The short escapes Go's strconv.Quote writes.
_GO_SHORT_ESCAPES = {
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\v": "\\v",
}


def go_quote(value: str) -> str:
    """Go's strconv.Quote: escape quotes, backslashes and the runes that are
    not printable."""
    out = []
    for c in value:
        if c in '"\\':
            out.append("\\" + c)
        elif go_is_print(c):
            out.append(c)
        elif c in _GO_SHORT_ESCAPES:
            out.append(_GO_SHORT_ESCAPES[c])
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\x{ord(c):02x}")
        elif ord(c) < 0x10000:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(f"\\U{ord(c):08x}")
    return '"' + "".join(out) + '"'


def lex(line: str) -> list[str]:
    """minicli's lexInput (minimega pkg/minicli/input.go): quotes group words,
    a backslash escapes one of ``ESCAPES`` inside or outside quotes,
    and an unquoted ``#`` ends the line."""
    items, content, emit, quote = [], "", False, None
    chars = iter(line)
    for c in chars:
        if c == "\\":
            escaped = next(chars, None)
            if escaped not in ESCAPES:
                raise ValueError(f"unexpected escaped character: {escaped}")
            content += ESCAPES[escaped]
        elif quote:
            if c == quote:
                quote, emit = None, True
            else:
                content += c
        elif c in "\"'":
            quote = c
        elif c == "#":
            break
        elif c in GO_SPACE:
            if content or emit:
                items.append(content)
            content, emit = "", False
        else:
            content += c
    if quote:
        raise ValueError(f"missing terminal {quote}")
    if content or emit:
        items.append(content)
    return items


def rebuild(words: list[str]) -> str:
    """minicli's inputItems.String: Go-quote the words that hold whitespace."""
    return " ".join(go_quote(w) if any(c in GO_SPACE for c in w) else w for w in words)


def namespaced_rebuild(command: str, remote: bool = False) -> list[str]:
    """Lex ``command`` again after minimega rebuilds it as a namespaced
    subcommand. ``remote`` gives the words a mesh peer of the namespace gets,
    after one more rebuild and lex. A lex error here is, in minimega, the
    daemon exiting (local) or the command hanging (remote)."""
    words = lex(command)
    for _ in range(2 if remote else 1):
        words = lex(rebuild(words))
    return words
