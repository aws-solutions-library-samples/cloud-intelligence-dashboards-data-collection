"""
CID Record Schema Conformance

``RecordSchema`` shapes every output record to a fixed, module-declared
schema before it is written as JSONL. The module's CloudFormation template
owns the table; the module's Lambda code declares the same columns, and a
``RecordSchema`` conforms each record to them. Nothing here reads the table
or calls any AWS service.

Conforming a record:

* fields the schema does not declare are dropped,
* declared fields that are missing are written as ``null``,
* ``struct``, ``array``, and ``map`` values are conformed recursively, and
* scalars are coerced to the declared type. Timestamps are written in the
  ``yyyy-MM-dd HH:mm:ss.SSS`` form Athena's JSON SerDe reads.

Types use Hive DDL syntax, so the declaration reads the same as the table's
``Columns`` in CloudFormation and the two are easy to compare::

    SAMPLE_SCHEMA = RecordSchema({
        "Engine": "string",
        "SupportedEngineLifecycles": "array<struct<LifecycleSupportName:string,"
                                     "LifecycleSupportStartDate:timestamp>>",
    })
    record = SAMPLE_SCHEMA.conform(api_item)

Types are parsed when the schema is built, so a malformed declaration fails
at import (Lambda cold start), not on the first record. Field names match
case-insensitively, as Athena's JSON SerDe does, and are written using the
schema's spelling. Subsets, derived fields, and flattening are done by the
collector before conforming; the schema just declares the result. No
dependency on the collection framework.
"""

import json
from datetime import date, datetime, timezone

HIVE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

_STRING_TYPES = {"string", "varchar", "char"}
_INTEGER_TYPES = {"tinyint", "smallint", "int", "integer", "bigint"}
_FLOAT_TYPES = {"float", "double", "decimal"}
_PRIMITIVE_TYPES = _STRING_TYPES | _INTEGER_TYPES | _FLOAT_TYPES | {"boolean", "timestamp", "date"}


class RecordSchema:
    """A fixed output record shape, declared as column name to type.

    Args:
        columns: Ordered mapping of column name to Hive DDL type string, in
            table column order.

    Raises:
        ValueError: If any type is malformed or unsupported.
    """

    def __init__(self, columns: dict):
        self._columns = dict(columns)
        self._fields = tuple((name, self.parse_type(text)) for name, text in self._columns.items())

    def __repr__(self):
        return f"RecordSchema({list(self._columns)})"

    # -----------------------------------------------------------------------
    # Public surface
    # -----------------------------------------------------------------------
    @property
    def names(self) -> list:
        """Column names, in declared order."""
        return list(self._columns)

    def columns(self) -> list:
        """Return ``(name, type)`` pairs as declared, for comparison with the table."""
        return list(self._columns.items())

    def conform(self, record) -> dict:
        """Conform one record.

        Args:
            record: The record to conform, typically one API response item.

        Returns:
            dict: A new record with exactly the schema's columns, in order.
        """
        return self._conform_struct(record or {}, self._fields)

    def conform_all(self, records) -> list:
        """Conform every record in an iterable."""
        return [self.conform(record) for record in records]

    # -----------------------------------------------------------------------
    # Type parsing
    # -----------------------------------------------------------------------
    @classmethod
    def parse_type(cls, text):
        """Parse a Hive DDL type string into a nested tuple.

        Args:
            text: Type, e.g. ``"array<struct<Name:string,Start:timestamp>>"``.

        Returns:
            tuple: ``("struct", ((name, type), ...))``, ``("array", type)``,
            ``("map", key_type, value_type)``, or ``(primitive,)``.

        Raises:
            ValueError: If the type string is malformed or unsupported.
        """
        compact = "".join(str(text).split())
        node, pos = cls._parse_at(compact, 0)
        if pos != len(compact):
            raise ValueError(f"Unexpected '{compact[pos:]}' in type '{text}'")
        return node

    @classmethod
    def _parse_at(cls, text, pos):
        """Parse one type starting at ``pos``; return ``(node, next_pos)``."""
        word, pos = cls._read_word(text, pos)
        kind = word.lower()
        if kind == "array":
            pos = cls._expect(text, pos, "<")
            element, pos = cls._parse_at(text, pos)
            return ("array", element), cls._expect(text, pos, ">")
        if kind == "map":
            pos = cls._expect(text, pos, "<")
            key_type, pos = cls._parse_at(text, pos)
            pos = cls._expect(text, pos, ",")
            value_type, pos = cls._parse_at(text, pos)
            return ("map", key_type, value_type), cls._expect(text, pos, ">")
        if kind == "struct":
            pos = cls._expect(text, pos, "<")
            fields = []
            while True:
                name, pos = cls._read_word(text, pos)
                pos = cls._expect(text, pos, ":")
                field_type, pos = cls._parse_at(text, pos)
                fields.append((name, field_type))
                if pos < len(text) and text[pos] == ",":
                    pos += 1
                    continue
                return ("struct", tuple(fields)), cls._expect(text, pos, ">")
        base = kind.split("(", 1)[0]  # decimal(10,2), varchar(64), ...
        if base not in _PRIMITIVE_TYPES:
            raise ValueError(f"Unsupported type '{word}'")
        return (base,), pos

    @staticmethod
    def _read_word(text, pos):
        """Read a type or field name, including a ``(...)`` precision suffix."""
        start = pos
        while pos < len(text) and (text[pos].isalnum() or text[pos] == "_"):
            pos += 1
        if pos < len(text) and text[pos] == "(":
            end = text.find(")", pos)
            if end < 0:
                raise ValueError(f"Unclosed '(' in type '{text}'")
            pos = end + 1
        if pos == start:
            raise ValueError(f"Expected a name at position {pos} in type '{text}'")
        return text[start:pos], pos

    @staticmethod
    def _expect(text, pos, char):
        """Consume ``char`` at ``pos`` or raise."""
        if pos >= len(text) or text[pos] != char:
            raise ValueError(f"Expected '{char}' at position {pos} in type '{text}'")
        return pos + 1

    # -----------------------------------------------------------------------
    # Conformance
    # -----------------------------------------------------------------------
    @classmethod
    def _conform_value(cls, value, node):
        """Conform a value to a parsed type, or ``None`` if missing or not coercible."""
        if value is None:
            return None
        kind = node[0]
        if kind == "struct":
            return cls._conform_struct(value, node[1]) if isinstance(value, dict) else None
        if kind == "array":
            items = value if isinstance(value, (list, tuple, set)) else [value]
            return [cls._conform_value(item, node[1]) for item in items]
        if kind == "map":
            if not isinstance(value, dict):
                return None
            return {cls._conform_value(key, node[1]): cls._conform_value(item, node[2])
                    for key, item in value.items()}
        return cls._conform_scalar(value, kind)

    @classmethod
    def _conform_struct(cls, value, fields):
        """Keep only declared fields, matched case-insensitively, in declared order."""
        lookup = {str(key).lower(): item for key, item in value.items()}
        return {name: cls._conform_value(lookup.get(name.lower()), field_type) for name, field_type in fields}

    @classmethod
    def _conform_scalar(cls, value, kind):  # pylint: disable=too-many-return-statements
        """Coerce a scalar to a primitive type, or ``None`` if it cannot be."""
        try:
            if kind in _STRING_TYPES:
                if isinstance(value, (dict, list, tuple)):
                    return json.dumps(value, default=cls._json_default)
                if isinstance(value, datetime):
                    return cls.hive_timestamp(value)
                return str(value)
            if kind == "boolean":
                if isinstance(value, str):
                    return value.strip().lower() in ("true", "1", "yes")
                return bool(value)
            if kind in _INTEGER_TYPES:
                return int(value)
            if kind in _FLOAT_TYPES:
                return float(value)
            if kind == "timestamp":
                return cls.hive_timestamp(cls.to_datetime(value))
            return cls.to_datetime(value).date().isoformat()  # date
        except (TypeError, ValueError, OverflowError):
            return None

    # -----------------------------------------------------------------------
    # Value helpers
    # -----------------------------------------------------------------------
    @staticmethod
    def to_datetime(value):
        """Return ``value`` as a datetime.

        Accepts a datetime, a date, epoch seconds, or an ISO 8601 string.

        Raises:
            TypeError: If the value is of another type.
            ValueError: If a string is not ISO 8601.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        raise TypeError(f"Cannot convert {type(value).__name__} to datetime")

    @staticmethod
    def hive_timestamp(value):
        """Format a datetime as a Hive timestamp, converting aware values to UTC."""
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime(HIVE_TIMESTAMP_FORMAT)[:-3]

    @staticmethod
    def _json_default(obj):
        """JSON fallback for values nested inside a ``string`` column."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)
