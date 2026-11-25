# -*- coding: utf-8 -*-
"""A small, output-only JSON encoder for PlayLab reports (Python 3.5+).

The inspected firmware omits the standard-library json package. This module
encodes only built-in reporting types; it is not installed into system Python
and does not parse input or implement json.loads. No third-party imports.
"""

def dumps(value, ensure_ascii=True, indent=None, sort_keys=False):
    if indent is not None and (not isinstance(indent, int) or not 0 <= indent <= 8):
        raise ValueError('indent must be None or an integer between 0 and 8')
    active = set()
    escapes = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f',
               '\n': '\\n', '\r': '\\r', '\t': '\\t'}

    def quoted(text):
        parts = ['"']
        for c in text:
            n = ord(c)
            if c in escapes:
                parts.append(escapes[c])
            elif n < 32 or 0xD800 <= n <= 0xDFFF or (ensure_ascii and n > 126):
                if n <= 0xFFFF:
                    parts.append('\\u%04x' % n)
                else:
                    n -= 0x10000
                    parts.append('\\u%04x\\u%04x' % (0xD800 + (n >> 10), 0xDC00 + (n & 1023)))
            else:
                parts.append(c)
        parts.append('"')
        return ''.join(parts)

    def encode(item, depth):
        if depth > 40:
            raise ValueError('report nesting limit exceeded')
        if item is None:
            return 'null'
        if item is True:
            return 'true'
        if item is False:
            return 'false'
        if isinstance(item, str):
            return quoted(item)
        if isinstance(item, int):
            return str(item)
        if isinstance(item, float):
            if item != item or item in (float('inf'), -float('inf')):
                raise ValueError('non-finite report value')
            return repr(item)
        if not isinstance(item, (dict, list, tuple)):
            raise TypeError('unsupported report type: ' + type(item).__name__)
        marker = id(item)
        if marker in active:
            raise ValueError('circular report value')
        active.add(marker)
        try:
            if isinstance(item, dict):
                keys = list(item.keys())
                if not all(isinstance(k, str) for k in keys):
                    raise TypeError('report dictionary keys must be strings')
                if sort_keys:
                    keys.sort()
                content = [quoted(k) + ': ' + encode(item[k], depth + 1) for k in keys]
                left, right = '{', '}'
            else:
                content = [encode(x, depth + 1) for x in item]
                left, right = '[', ']'
            if not content:
                return left + right
            if indent is None:
                return left + ', '.join(content) + right
            pad = ' ' * (indent * (depth + 1))
            return left + '\n' + pad + (',\n' + pad).join(content) + '\n' + ' ' * (indent * depth) + right
        finally:
            active.remove(marker)

    return encode(value, 0)
