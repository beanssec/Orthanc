"""OQL (Orthanc Query Language) Parser.

Tokenizes, parses, and compiles OQL query strings into SQLAlchemy Core select()
statements compatible with async SQLAlchemy sessions.

Syntax examples:
    source_type=telegram author="AMK*" content="drone strike"
    (source_type=telegram OR source_type=rss) content="Iran"
    source_type=telegram | stats count by author | sort -count
    | timechart span=1h count by source_type
    entities: type=PERSON | top 10 name
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from sqlalchemy import and_, func, not_, or_, select, text
from sqlalchemy.orm import DeclarativeBase

from app.models.entity import Entity
from app.models.event import Event
from app.models.post import Post


# ── Field registry ─────────────────────────────────────────────────────────────

FIELD_MAP: dict[str, dict[str, Any]] = {
    "posts": {
        "id": Post.id,
        "source_type": Post.source_type,
        "source_id": Post.source_id,
        "author": Post.author,
        "content": Post.content,
        "timestamp": Post.timestamp,
        "ingested_at": Post.ingested_at,
        "media_type": Post.media_type,
        "authenticity_score": Post.authenticity_score,
        "external_id": Post.external_id,
    },
    "entities": {
        "id": Entity.id,
        "name": Entity.name,
        "type": Entity.type,
        "canonical_name": Entity.canonical_name,
        "mention_count": Entity.mention_count,
        "first_seen": Entity.first_seen,
        "last_seen": Entity.last_seen,
    },
    "events": {
        "id": Event.id,
        "post_id": Event.post_id,
        "lat": Event.lat,
        "lng": Event.lng,
        "place_name": Event.place_name,
        "confidence": Event.confidence,
        "precision": Event.precision,
    },
}

TABLE_MODEL: dict[str, Any] = {
    "posts": Post,
    "entities": Entity,
    "events": Event,
}

# Timestamp column per table (for timechart)
TABLE_TIMESTAMP = {
    "posts": Post.timestamp,
    "entities": Entity.first_seen,
}

# Human-readable field types (for /oql/schema)
FIELD_TYPES: dict[str, dict[str, dict]] = {
    "posts": {
        "id": {"type": "uuid", "description": "Unique post identifier"},
        "source_type": {"type": "string", "description": "Source platform (telegram, rss, reddit, …)"},
        "source_id": {"type": "string", "description": "Source channel/feed identifier"},
        "author": {"type": "string", "description": "Post author / username"},
        "content": {"type": "text", "description": "Post text content"},
        "timestamp": {"type": "datetime", "description": "Original post timestamp"},
        "ingested_at": {"type": "datetime", "description": "When Orthanc ingested the post"},
        "media_type": {"type": "string", "description": "Media type if present (image, video, document)"},
        "authenticity_score": {"type": "float", "description": "Authenticity score 0.0–1.0"},
        "external_id": {"type": "string", "description": "External dedup identifier"},
    },
    "entities": {
        "id": {"type": "uuid", "description": "Unique entity identifier"},
        "name": {"type": "string", "description": "Entity name as extracted"},
        "type": {"type": "string", "description": "Entity type: PERSON, ORG, GPE, NORP, EVENT"},
        "canonical_name": {"type": "string", "description": "Normalised canonical name"},
        "mention_count": {"type": "integer", "description": "Total mention count"},
        "first_seen": {"type": "datetime", "description": "First observed timestamp"},
        "last_seen": {"type": "datetime", "description": "Most recent observed timestamp"},
    },
    "events": {
        "id": {"type": "uuid", "description": "Unique event identifier"},
        "post_id": {"type": "uuid", "description": "Source post UUID"},
        "lat": {"type": "float", "description": "Latitude"},
        "lng": {"type": "float", "description": "Longitude"},
        "place_name": {"type": "string", "description": "Place name extracted"},
        "confidence": {"type": "float", "description": "Extraction confidence 0.0–1.0"},
        "precision": {"type": "string", "description": "Geo precision: exact/city/region/country/continent"},
    },
}

# Valid timechart spans and their postgres date_trunc levels
SPAN_TRUNC = {
    "1m": "minute", "5m": None, "15m": None, "30m": None,
    "1h": "hour", "6h": None, "12h": None,
    "1d": "day", "7d": "week",
}
# For spans that need custom bucketing: minutes value
SPAN_CUSTOM_MINUTES: dict[str, int] = {
    "5m": 5, "15m": 15, "30m": 30, "6h": 360, "12h": 720,
}


# ── Levenshtein distance (for typo suggestions) ────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _suggest_field(name: str, table: str) -> str | None:
    candidates = list(FIELD_MAP.get(table, {}).keys())
    if not candidates:
        return None
    best = min(candidates, key=lambda c: _levenshtein(name, c))
    if _levenshtein(name, best) <= 3:
        return best
    return None


# ── Token types ────────────────────────────────────────────────────────────────

class TType(Enum):
    FIELD_OP = auto()   # field=value, field!=value, field>value, etc.
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    PIPE = auto()
    WORD = auto()       # bare word (identifier or number in pipe args)
    EOF = auto()


@dataclass
class Token:
    ttype: TType
    value: str
    pos: int
    field: str = ""
    op: str = ""
    raw_value: str = ""


# ── Tokenizer ──────────────────────────────────────────────────────────────────

_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_UNQUOTED_RE = re.compile(r'[^\s\(\)\|"=!<>]+')
_OP_RE = re.compile(r'!=|>=|<=|>|<|=')


class OQLError(Exception):
    def __init__(self, message: str, position: int = -1):
        super().__init__(message)
        self.message = message
        self.position = position

    def to_dict(self) -> dict:
        return {"error": self.message, "position": self.position}


def tokenize(query: str) -> list[Token]:
    """Tokenize an OQL string into a list of Tokens."""
    tokens: list[Token] = []
    i = 0
    n = len(query)

    while i < n:
        # Skip whitespace
        if query[i].isspace():
            i += 1
            continue

        pos = i

        if query[i] == "|":
            tokens.append(Token(TType.PIPE, "|", pos))
            i += 1
            continue

        if query[i] == "(":
            tokens.append(Token(TType.LPAREN, "(", pos))
            i += 1
            continue

        if query[i] == ")":
            tokens.append(Token(TType.RPAREN, ")", pos))
            i += 1
            continue

        m = _UNQUOTED_RE.match(query, i)
        if not m:
            raise OQLError(f"Unexpected character '{query[i]}'", i)

        word = m.group(0)
        word_end = m.end()

        # Try to match field=value (only if next non-whitespace is an operator)
        op_m = _OP_RE.match(query, word_end)
        if op_m:
            op = op_m.group(0)
            val_start = op_m.end()
            if val_start < n and query[val_start] == '"':
                qm = _QUOTED_RE.match(query, val_start)
                if not qm:
                    raise OQLError("Unclosed string literal", val_start)
                raw_val = qm.group(1)
                i = qm.end()
            else:
                vm = _UNQUOTED_RE.match(query, val_start)
                if not vm:
                    raise OQLError(f"Expected value after '{op}'", val_start)
                raw_val = vm.group(0)
                i = vm.end()
            tokens.append(Token(TType.FIELD_OP, f"{word}{op}{raw_val}", pos,
                                field=word, op=op, raw_value=raw_val))
            continue

        upper = word.upper()
        if upper == "AND":
            tokens.append(Token(TType.AND, word, pos))
        elif upper == "OR":
            tokens.append(Token(TType.OR, word, pos))
        elif upper == "NOT":
            tokens.append(Token(TType.NOT, word, pos))
        else:
            tokens.append(Token(TType.WORD, word, pos))
        i = word_end

    tokens.append(Token(TType.EOF, "", n))
    return tokens


# ── AST nodes ──────────────────────────────────────────────────────────────────

@dataclass
class ConditionNode:
    field: str
    op: str
    value: str
    pos: int


@dataclass
class BoolNode:
    op: str  # "AND" | "OR"
    left: Any
    right: Any


@dataclass
class NotNode:
    child: Any


@dataclass
class PipeCmd:
    name: str
    args: list[str]
    pos: int


@dataclass
class OQLQuery:
    table: str
    filter_ast: Any  # None or AST node
    pipes: list[PipeCmd] = field(default_factory=list)


# ── Parser ─────────────────────────────────────────────────────────────────────

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def consume(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def parse(self) -> OQLQuery:
        table = "posts"

        # Check for optional table prefix ("entities:", "events:", "posts:")
        if self.peek().ttype == TType.WORD and self.peek().value.rstrip(":") in TABLE_MODEL:
            word = self.peek().value
            if word.endswith(":"):
                table = word[:-1]
                self.consume()

        filter_ast = self._parse_or()

        pipes: list[PipeCmd] = []
        while self.peek().ttype == TType.PIPE:
            self.consume()
            pipes.append(self._parse_pipe_cmd())

        return OQLQuery(table=table, filter_ast=filter_ast, pipes=pipes)

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self.peek().ttype == TType.OR:
            self.consume()
            right = self._parse_and()
            left = BoolNode("OR", left, right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        while self.peek().ttype in (TType.FIELD_OP, TType.NOT, TType.LPAREN, TType.AND):
            if self.peek().ttype == TType.AND:
                self.consume()
            right = self._parse_not()
            if right is None:
                break
            left = BoolNode("AND", left, right)
        return left

    def _parse_not(self) -> Any:
        if self.peek().ttype == TType.NOT:
            self.consume()
            return NotNode(self._parse_primary())
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        t = self.peek()
        if t.ttype == TType.LPAREN:
            self.consume()
            node = self._parse_or()
            if self.peek().ttype != TType.RPAREN:
                raise OQLError("Expected closing ')'", self.peek().pos)
            self.consume()
            return node
        if t.ttype == TType.FIELD_OP:
            self.consume()
            return ConditionNode(field=t.field, op=t.op, value=t.raw_value, pos=t.pos)
        # Not a filter expression
        return None

    def _parse_pipe_cmd(self) -> PipeCmd:
        t = self.peek()
        if t.ttype != TType.WORD:
            raise OQLError(f"Expected pipe command name at position {t.pos}", t.pos)
        name_tok = self.consume()
        cmd_name = name_tok.value.lower()
        args: list[str] = []
        while self.peek().ttype not in (TType.PIPE, TType.EOF):
            args.append(self.consume().value)
        return PipeCmd(name=cmd_name, args=args, pos=name_tok.pos)


# ── Compiler ───────────────────────────────────────────────────────────────────

@dataclass
class CompiledOQL:
    """Result of compilation — ready to pass to async session.execute()."""
    stmt: Any                    # SQLAlchemy select() statement
    count_stmt: Any              # Statement to count total rows (may be None for aggregates)
    is_aggregate: bool
    select_fields: list[str] | None   # If | table was used
    viz_hint: str
    table: str
    limit: int


class OQLCompiler:
    def __init__(self, table: str):
        self.table = table
        self.model = TABLE_MODEL[table]
        self.fields = FIELD_MAP[table]

    def _resolve_field(self, name: str, pos: int) -> Any:
        if name not in self.fields:
            suggestion = _suggest_field(name, self.table)
            msg = f"Unknown field '{name}' at position {pos}"
            if suggestion:
                msg += f". Did you mean '{suggestion}'?"
            raise OQLError(msg, pos)
        return self.fields[name]

    def _compile_condition(self, node: ConditionNode) -> Any:
        col = self._resolve_field(node.field, node.pos)
        val = node.value
        op = node.op
        has_wildcard = "*" in val or "?" in val

        if op == "=":
            if has_wildcard:
                return col.ilike(val.replace("*", "%").replace("?", "_"))
            try:
                return col == float(val)
            except (ValueError, TypeError):
                return col.ilike(val)
        elif op == "!=":
            if has_wildcard:
                return not_(col.ilike(val.replace("*", "%").replace("?", "_")))
            try:
                return col != float(val)
            except (ValueError, TypeError):
                return not_(col.ilike(val))
        elif op == ">":
            return col > self._cast(val)
        elif op == "<":
            return col < self._cast(val)
        elif op == ">=":
            return col >= self._cast(val)
        elif op == "<=":
            return col <= self._cast(val)
        else:
            raise OQLError(f"Unknown operator '{op}'", node.pos)

    def _cast(self, val: str):
        try:
            return float(val)
        except ValueError:
            return val

    def _compile_ast(self, node: Any) -> Any:
        if node is None:
            return None
        if isinstance(node, ConditionNode):
            return self._compile_condition(node)
        if isinstance(node, BoolNode):
            left = self._compile_ast(node.left)
            right = self._compile_ast(node.right)
            if left is None:
                return right
            if right is None:
                return left
            return and_(left, right) if node.op == "AND" else or_(left, right)
        if isinstance(node, NotNode):
            child = self._compile_ast(node.child)
            return not_(child) if child is not None else None
        return None

    def compile(self, parsed: OQLQuery, limit: int = 1000) -> CompiledOQL:
        base_filter = self._compile_ast(parsed.filter_ast)
        viz_hint = "table"
        select_fields: list[str] | None = None
        extra_filters = []
        sort_clauses = []
        is_aggregate = False
        agg_stmt: Any = None
        effective_limit = limit

        for cmd in parsed.pipes:
            name = cmd.name
            args = cmd.args

            if name == "where":
                sub_tokens = tokenize(" ".join(args))
                sub_ast = Parser(sub_tokens)._parse_or()
                sub_filter = self._compile_ast(sub_ast)
                if sub_filter is not None:
                    extra_filters.append(sub_filter)

            elif name == "sort":
                if not args:
                    raise OQLError("| sort requires a field name", cmd.pos)
                sf = args[0]
                desc = sf.startswith("-")
                field_name = sf.lstrip("-")
                # Allow sorting by aggregate aliases (count, avg_field, sum_field, etc.)
                from sqlalchemy import literal_column
                agg_prefixes = ("count", "avg_", "sum_", "min_", "max_", "dc_")
                if field_name == "count" or any(field_name.startswith(p) for p in agg_prefixes):
                    col = literal_column(field_name)
                else:
                    col = self._resolve_field(field_name, cmd.pos)
                sort_clauses.append(col.desc() if desc else col.asc())

            elif name == "head":
                if not args:
                    raise OQLError("| head requires N", cmd.pos)
                try:
                    effective_limit = min(int(args[0]), effective_limit)
                except ValueError:
                    raise OQLError(f"| head expects integer, got '{args[0]}'", cmd.pos)

            elif name == "table":
                field_names = [a.strip(",") for a in args if a.strip(",")]
                for fn in field_names:
                    self._resolve_field(fn, cmd.pos)
                select_fields = field_names

            elif name == "stats":
                viz_hint, agg_stmt = self._build_stats(args, cmd.pos, base_filter, extra_filters)
                is_aggregate = True

            elif name == "top":
                viz_hint, agg_stmt, effective_limit = self._build_top(
                    args, cmd.pos, base_filter, extra_filters, effective_limit
                )
                is_aggregate = True

            elif name == "timechart":
                viz_hint, agg_stmt = self._build_timechart(args, cmd.pos, base_filter, extra_filters)
                is_aggregate = True

            else:
                raise OQLError(f"Unknown pipe command '{name}'", cmd.pos)

        if is_aggregate:
            # Apply sort to aggregate if sort was given after the agg
            if sort_clauses and agg_stmt is not None:
                agg_stmt = agg_stmt.order_by(*sort_clauses)
            final_stmt = agg_stmt.limit(effective_limit) if agg_stmt is not None else agg_stmt
            return CompiledOQL(
                stmt=final_stmt,
                count_stmt=None,
                is_aggregate=True,
                select_fields=None,
                viz_hint=viz_hint,
                table=parsed.table,
                limit=effective_limit,
            )

        # Build non-aggregate select
        if select_fields:
            cols = [self._resolve_field(fn, 0) for fn in select_fields]
            stmt = select(*cols).select_from(self.model)
        else:
            stmt = select(self.model)

        all_filters = ([base_filter] if base_filter is not None else []) + extra_filters
        if all_filters:
            stmt = stmt.where(and_(*all_filters))

        count_stmt = select(func.count()).select_from(self.model)
        if all_filters:
            count_stmt = count_stmt.where(and_(*all_filters))

        if sort_clauses:
            stmt = stmt.order_by(*sort_clauses)
        else:
            # Default sort by timestamp desc if available
            if "timestamp" in self.fields:
                stmt = stmt.order_by(self.fields["timestamp"].desc())
            elif "first_seen" in self.fields:
                stmt = stmt.order_by(self.fields["first_seen"].desc())

        stmt = stmt.limit(effective_limit)

        # Check viz_hint for lat/lng
        if select_fields and "lat" in select_fields and "lng" in select_fields:
            viz_hint = "map"
        elif select_fields is None and "lat" in self.fields and "lng" in self.fields:
            viz_hint = "map"

        return CompiledOQL(
            stmt=stmt,
            count_stmt=count_stmt,
            is_aggregate=False,
            select_fields=select_fields,
            viz_hint=viz_hint,
            table=parsed.table,
            limit=effective_limit,
        )

    # ── Aggregate builders ────────────────────────────────────────────────────

    def _build_stats(self, args: list[str], pos: int, base_filter, extra_filters: list):
        if not args:
            raise OQLError("| stats requires a function name", pos)

        func_name = args[0].lower()
        by_idx = next((i for i, a in enumerate(args) if a.lower() == "by"), None)

        # Find the field for the aggregate function (between func_name and 'by')
        func_field_args = args[1:by_idx] if by_idx is not None else args[1:]
        func_field = func_field_args[0] if func_field_args else None

        group_field_args = args[by_idx + 1:] if by_idx is not None else []
        group_fields = [a.strip(",") for a in group_field_args if a.strip(",")]

        agg_expr = self._build_agg_expr(func_name, func_field, pos)
        group_cols = [self._resolve_field(gf, pos) for gf in group_fields]
        select_exprs = group_cols + [agg_expr]

        stmt = select(*select_exprs).select_from(self.model)
        all_filters = ([base_filter] if base_filter is not None else []) + extra_filters
        if all_filters:
            stmt = stmt.where(and_(*all_filters))
        if group_cols:
            stmt = stmt.group_by(*group_cols)
        stmt = stmt.order_by(agg_expr.desc())

        viz = "bar" if func_name == "count" and len(group_fields) == 1 else "table"
        return viz, stmt

    def _build_agg_expr(self, func_name: str, func_field: str | None, pos: int):
        if func_name == "count":
            return func.count().label("count")
        if func_name == "dc":
            col = self._resolve_field(func_field, pos) if func_field else None
            if col is None:
                raise OQLError("| stats dc requires a field (e.g. dc field_name)", pos)
            return func.count(col.distinct()).label(f"dc_{func_field}")
        if func_name in ("avg", "sum", "min", "max"):
            if not func_field:
                raise OQLError(f"| stats {func_name} requires a field", pos)
            col = self._resolve_field(func_field, pos)
            fn = getattr(func, func_name)
            return fn(col).label(f"{func_name}_{func_field}")
        raise OQLError(
            f"Unknown stats function '{func_name}'. Valid: count, avg, sum, min, max, dc", pos
        )

    def _build_top(self, args: list[str], pos: int, base_filter, extra_filters, limit: int):
        if len(args) < 2:
            raise OQLError("| top requires N FIELD", pos)
        try:
            n = int(args[0])
        except ValueError:
            raise OQLError(f"| top expects integer N, got '{args[0]}'", pos)
        gf = args[1]
        col = self._resolve_field(gf, pos)
        agg_expr = func.count().label("count")

        stmt = select(col, agg_expr).select_from(self.model)
        all_filters = ([base_filter] if base_filter is not None else []) + extra_filters
        if all_filters:
            stmt = stmt.where(and_(*all_filters))
        stmt = stmt.group_by(col).order_by(agg_expr.desc()).limit(n)

        return "bar", stmt, min(n, limit)

    def _build_timechart(self, args: list[str], pos: int, base_filter, extra_filters):
        span = None
        group_field = None
        i = 0
        while i < len(args):
            a = args[i]
            if a.lower().startswith("span="):
                span = a[5:]
            elif a.lower() == "by" and i + 1 < len(args):
                group_field = args[i + 1]
                i += 1
            i += 1

        if not span:
            raise OQLError("| timechart requires span=INTERVAL (e.g. span=1h)", pos)
        if span not in SPAN_TRUNC:
            raise OQLError(
                f"Invalid span '{span}'. Valid: {', '.join(sorted(SPAN_TRUNC.keys()))}", pos
            )

        if self.table not in TABLE_TIMESTAMP:
            raise OQLError(f"timechart not supported for table '{self.table}'", pos)

        time_col = TABLE_TIMESTAMP[self.table]
        trunc_level = SPAN_TRUNC[span]

        if span in SPAN_CUSTOM_MINUTES:
            minutes = SPAN_CUSTOM_MINUTES[span]
            # Use integer arithmetic: floor(epoch / (minutes*60)) * (minutes*60)
            # Expressed as: date_trunc('minute', ts) - (extract(minute from ts)::int % N) * interval '1 minute'
            bucket_expr = (
                func.date_trunc("minute", time_col)
                - text(f"(EXTRACT(MINUTE FROM timestamp)::int % {minutes}) * interval '1 minute'")
            )
        else:
            bucket_expr = func.date_trunc(trunc_level, time_col)

        bucket_label = bucket_expr.label("bucket")
        agg_expr = func.count().label("count")

        all_filters = ([base_filter] if base_filter is not None else []) + extra_filters

        if group_field:
            gcol = self._resolve_field(group_field, pos)
            stmt = select(bucket_label, gcol, agg_expr).select_from(self.model)
            if all_filters:
                stmt = stmt.where(and_(*all_filters))
            stmt = stmt.group_by(bucket_label, gcol).order_by(bucket_label)
        else:
            stmt = select(bucket_label, agg_expr).select_from(self.model)
            if all_filters:
                stmt = stmt.where(and_(*all_filters))
            stmt = stmt.group_by(bucket_label).order_by(bucket_label)

        return "timeseries", stmt


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_oql(query_str: str) -> OQLQuery:
    """Parse an OQL string into an AST. Raises OQLError on syntax errors."""
    query_str = query_str.strip()

    # Handle optional table prefix at the very start before tokenizing
    table = "posts"
    for tbl in TABLE_MODEL:
        prefix = f"{tbl}:"
        if query_str.startswith(prefix):
            table = tbl
            query_str = query_str[len(prefix):].lstrip()
            break

    tokens = tokenize(query_str)
    parsed = Parser(tokens).parse()
    # Override table if it was detected via prefix stripping
    if table != "posts":
        parsed.table = table
    return parsed


def compile_oql(query_str: str, limit: int = 1000) -> CompiledOQL:
    """Parse + compile OQL to a SQLAlchemy statement. Does NOT execute."""
    parsed = parse_oql(query_str)
    compiler = OQLCompiler(parsed.table)
    return compiler.compile(parsed, limit=limit)


def get_schema() -> dict:
    """Return the full field schema for autocomplete."""
    tables = {}
    for table, field_meta in FIELD_TYPES.items():
        fields = [
            {"name": fname, "type": finfo["type"], "description": finfo.get("description", "")}
            for fname, finfo in field_meta.items()
        ]
        tables[table] = {"fields": fields}
    return {"tables": tables}


def serialize_rows(rows: list[dict]) -> list[dict]:
    """Convert SQLAlchemy row values to JSON-serializable types."""
    import datetime
    import uuid as _uuid

    out = []
    for row in rows:
        srow = {}
        for k, v in row.items():
            if isinstance(v, datetime.datetime):
                srow[k] = v.isoformat()
            elif isinstance(v, datetime.date):
                srow[k] = v.isoformat()
            elif isinstance(v, _uuid.UUID):
                srow[k] = str(v)
            elif isinstance(v, (dict, list)):
                import json
                srow[k] = json.dumps(v)
            else:
                srow[k] = v
        out.append(srow)
    return out


def infer_col_type(col_name: str, table: str) -> str:
    meta = FIELD_TYPES.get(table, {}).get(col_name, {})
    return meta.get("type", "string")
