"""Bounded, read-only inspection of a PDF's logical structure.

This is an inspection aid, not a PDF/UA validator or a screen reader simulation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class _Name:
    value: str


@dataclass(frozen=True)
class _Ref:
    xref: int


@dataclass
class TagNode:
    xref: int
    role: str
    mapped_role: str = ""
    title: str = ""
    alt_text: str = ""
    actual_text: str = ""
    language: str = ""
    page: int | None = None
    mcids: list[int] = field(default_factory=list)
    children: list[TagNode] = field(default_factory=list)


@dataclass
class ArtifactInfo:
    page: int
    count: int


@dataclass
class TaggedPdfReport:
    tagged: bool = False
    language: str = ""
    nodes: list[TagNode] = field(default_factory=list)
    artifacts: list[ArtifactInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reading_order: list[TagNode] = field(default_factory=list)
    limitations: str = (
        "Read-only inspection of declared structure order and page content streams. "
        "This is not a PDF/UA compliance check. Form XObjects, visual reading order, "
        "screen reader behavior and complete ParentTree consistency are not validated."
    )


class _Parser:
    """Small PDF object lexer: strings and comments never become operators."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.tokens = 0

    def _space(self):
        d = self.data
        while self.pos < len(d):
            if d[self.pos] in b"\x00\t\n\f\r ":
                self.pos += 1
            elif d[self.pos] == 37:
                while self.pos < len(d) and d[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                break

    def value(self, depth=0):
        self.tokens += 1
        if self.tokens > 200000 or depth > 100:
            raise ValueError("PDF object inspection limit exceeded")
        self._space()
        d = self.data
        if self.pos >= len(d):
            raise EOFError
        p = self.pos
        if d[p:p+2] == b"<<":
            self.pos += 2
            result = {}
            while True:
                self._space()
                if d[self.pos:self.pos+2] == b">>":
                    self.pos += 2
                    return result
                key = self.value(depth+1)
                if not isinstance(key, _Name):
                    raise ValueError("Invalid PDF dictionary key")
                result[key.value] = self.value(depth+1)
        if d[p:p+1] == b"[":
            self.pos += 1
            result = []
            while True:
                self._space()
                if d[self.pos:self.pos+1] == b"]":
                    self.pos += 1
                    return result
                result.append(self.value(depth+1))
        if d[p:p+1] == b"(":
            self.pos += 1
            level, result = 1, bytearray()
            while self.pos < len(d):
                c = d[self.pos]
                self.pos += 1
                if c == 92:
                    if self.pos == len(d):
                        break
                    c = d[self.pos]
                    self.pos += 1
                    if c in b"\r\n":
                        if c == 13 and d[self.pos:self.pos+1] == b"\n":
                            self.pos += 1
                        continue
                    if 48 <= c <= 55:
                        octal = bytes([c])
                        for _ in range(2):
                            if self.pos < len(d) and 48 <= d[self.pos] <= 55:
                                octal += bytes([d[self.pos]])
                                self.pos += 1
                            else:
                                break
                        result.append(int(octal, 8) & 255)
                    else:
                        result.append({110:10,114:13,116:9,98:8,102:12}.get(c,c))
                    continue
                if c == 40:
                    level += 1
                elif c == 41:
                    level -= 1
                    if level == 0:
                        return bytes(result)
                result.append(c)
            raise ValueError("Unterminated PDF string")
        if d[p:p+1] == b"<":
            end = d.find(b">", p+1)
            if end < 0:
                raise ValueError("Unterminated PDF hex string")
            raw = re.sub(rb"\s", b"", d[p+1:end])
            self.pos = end+1
            return bytes.fromhex((raw + (b"0" if len(raw)%2 else b"")).decode("ascii"))
        if d[p:p+1] == b"/":
            self.pos += 1
            start = self.pos
            while self.pos < len(d) and d[self.pos] not in b"\x00\t\n\f\r ()<>[]{}/%":
                self.pos += 1
            raw = re.sub(rb"#([0-9a-fA-F]{2})", lambda m: bytes([int(m[1],16)]), d[start:self.pos])
            return _Name(raw.decode("latin1"))
        start = self.pos
        while self.pos < len(d) and d[self.pos] not in b"\x00\t\n\f\r ()<>[]{}/%":
            self.pos += 1
        if self.pos == start:
            raise ValueError("Unexpected PDF delimiter")
        token = d[start:self.pos].decode("latin1")
        if re.fullmatch(r"[+-]?\d+", token):
            value = int(token)
            saved = self.pos
            self._space()
            match = re.match(rb"\d+\s+R\b", d[self.pos:])
            if match:
                self.pos += match.end()
                return _Ref(value)
            self.pos = saved
            return value
        return token


def _text(value):
    if isinstance(value, bytes):
        if value.startswith((b"\xfe\xff", b"\xff\xfe")):
            return value.decode("utf-16", errors="replace")
        if value.startswith(b"\xef\xbb\xbf"):
            return value[3:].decode("utf-8", errors="replace")
        # ISO 32000 PDFDocEncoding differs from Latin-1 at these byte values.
        special = {
            **dict(zip(range(0x18, 0x20), "\u02d8\u02c7\u02c6\u02d9\u02dd\u02db\u02da\u02dc")),
            **dict(zip(range(0x80, 0x9f),
                       "\u2022\u2020\u2021\u2026\u2014\u2013\u0192\u2044\u2039\u203a\u2212\u2030"
                       "\u201e\u201c\u201d\u2018\u2019\u201a\u2122\ufb01\ufb02\u0141\u0152\u0160"
                       "\u0178\u017d\u0131\u0142\u0153\u0161\u017e")),
            0x7f: "\ufffd", 0x9f: "\ufffd", 0xa0: "\u20ac", 0xad: "\ufffd",
        }
        return "".join(special.get(byte, chr(byte)) for byte in value)
    return ""


def inspect_tagged_pdf(document, *, max_nodes=10000, max_pages=2000) -> TaggedPdfReport:
    """Inspect existing tags; pages use zero-based indices. Never modify the PDF."""
    report = TaggedPdfReport()
    objects = {}

    def warn(message):
        if message not in report.warnings:
            report.warnings.append(message)

    def resolve(value):
        if isinstance(value, _Ref):
            if value.xref not in objects:
                raw = document.xref_object(value.xref, compressed=False).encode("latin1")
                if len(raw) > 4_000_000:
                    raise ValueError("PDF object inspection size limit exceeded")
                objects[value.xref] = _Parser(raw).value()
            return objects[value.xref]
        return value

    try:
        catalog = resolve(_Ref(document.pdf_catalog()))
        report.language = _text(resolve(catalog.get("Lang")))
        mark = resolve(catalog.get("MarkInfo", {}))
        report.tagged = isinstance(mark, dict) and mark.get("Marked") == "true"
        root = resolve(catalog.get("StructTreeRoot"))
        if not isinstance(root, dict):
            warn("No structure tree is present.")
        else:
            if not report.tagged:
                warn("Structure tree exists but MarkInfo/Marked is not true.")
            roles = resolve(root.get("RoleMap", {}))
            if not isinstance(roles, dict):
                roles = {}
            page_map = {document.page_xref(i): i for i in range(min(len(document), max_pages))}
            seen = set()
            count = 0

            def walk(value, inherited_page=None, depth=0, inherited_language=""):
                nonlocal count
                if depth > 80 or count >= max_nodes:
                    warn("Structure traversal limit reached; results are incomplete.")
                    return []
                if isinstance(value, list):
                    result = []
                    for child in value:
                        result.extend(walk(child, inherited_page, depth+1, inherited_language))
                    return result
                if isinstance(value, int):
                    return []
                xref = value.xref if isinstance(value, _Ref) else 0
                if xref:
                    if xref in seen:
                        warn("Repeated or cyclic structure reference skipped.")
                        return []
                    seen.add(xref)
                item = resolve(value)
                if isinstance(item, list):
                    return walk(item, inherited_page, depth+1, inherited_language)
                if not isinstance(item, dict):
                    warn("Malformed structure child skipped.")
                    return []
                page_ref = item.get("Pg")
                page = page_map.get(page_ref.xref) if isinstance(page_ref, _Ref) else inherited_page
                name = item.get("S")
                if not isinstance(name, _Name):
                    warn("Structure child without a role skipped.")
                    return []
                mapped = name.value
                visited = set()
                while isinstance(roles.get(mapped), _Name) and mapped not in visited:
                    visited.add(mapped)
                    mapped = roles[mapped].value
                if mapped in visited:
                    warn("Cyclic role mapping detected.")
                node = TagNode(xref=xref, role=name.value, mapped_role=mapped,
                               title=_text(resolve(item.get("T"))), alt_text=_text(resolve(item.get("Alt"))),
                               actual_text=_text(resolve(item.get("ActualText"))),
                               language=_text(resolve(item.get("Lang"))) or inherited_language, page=page)
                count += 1
                report.reading_order.append(node)
                children = item.get("K", [])
                resolved_children = resolve(children)
                if isinstance(resolved_children, list):
                    children = resolved_children
                else:
                    children = [children]
                for child in children:
                    if isinstance(child, int):
                        node.mcids.append(child)
                        continue
                    resolved = resolve(child)
                    if isinstance(resolved, int):
                        node.mcids.append(resolved)
                    elif isinstance(resolved, dict) and "MCID" in resolved:
                        if isinstance(resolved["MCID"], int):
                            node.mcids.append(resolved["MCID"])
                        if isinstance(resolved.get("Pg"), _Ref):
                            content_page = page_map.get(resolved["Pg"].xref)
                            if node.page is None:
                                node.page = content_page
                            elif content_page != node.page:
                                warn("A tag's content page differs from its structure page; review MCID page associations manually.")
                    elif isinstance(resolved, dict) and resolved.get("Type") == _Name("OBJR"):
                        warn("Object reference content requires manual review.")
                    else:
                        node.children.extend(walk(child, page, depth+1, node.language))
                return [node]

            report.nodes = walk(root.get("K", []), inherited_language=report.language)
    except (ValueError, RuntimeError, EOFError, TypeError, AttributeError, IndexError) as error:
        warn(f"Structure could not be completely inspected: {error}")
    if not report.language:
        warn("Document language is missing.")
    for node in report.reading_order:
        if node.mapped_role == "Figure" and not node.alt_text and not node.actual_text:
            warn("A Figure tag has no alternate text or actual text; review it manually.")
    if len(document) > max_pages:
        warn("Page inspection limit reached; results are incomplete.")
    scanned_bytes = 0
    for index in range(min(len(document), max_pages)):
        try:
            data = document[index].read_contents()
            scanned_bytes += len(data)
            if scanned_bytes > 16_000_000:
                warn("Total content inspection size limit reached; results are incomplete.")
                break
            if len(data) > 8_000_000:
                warn(f"Page {index+1} content exceeds the inspection size limit.")
                continue
            parser = _Parser(data)
            operands = []
            count = 0
            while True:
                try:
                    value = parser.value()
                except EOFError:
                    break
                if isinstance(value, str):
                    if value == "BI":
                        warn(f"Page {index+1} contains an inline image; artifact count is partial.")
                        break
                    if value in ("BMC", "BDC") and operands and operands[0] == _Name("Artifact"):
                        count += 1
                    operands = []
                else:
                    operands.append(value)
            report.artifacts.append(ArtifactInfo(index, count))
        except (ValueError, RuntimeError, TypeError, IndexError) as error:
            warn(f"Page {index+1} could not be completely inspected: {error}")
    return report
