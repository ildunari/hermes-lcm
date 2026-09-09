"""Tool schemas for LCM — what the LLM sees."""

LCM_GREP = {
    "name": "lcm_grep",
    "description": "Search conversation material archived by LCM (raw messages, tool outputs, summary nodes). Use 1-3 distinctive terms or a quoted phrase. Results default to recency; set sort='relevance' or 'hybrid' for older exact facts. Snippets can be truncated \u2014 use lcm_expand(store_id=...) to read a full row. Default scope is the active session; 'all'/'session' scopes return raw-message hits only. For Hermes session history outside LCM, use session_search.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query (FTS5 syntax: keywords, phrases, OR/NOT). "
                    "FTS5 defaults to AND matching, so prefer 1-3 distinctive terms or one quoted multi-word phrase. "
                    "Wrap exact phrases in quotes. Short CJK fragments and emoji-heavy queries may use substring fallback instead of plain FTS token matching."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Max results to return (default 10, hard upper bound 200). "
                    "Values above the cap are clamped and reported via limit_clamped_from in the response."
                ),
                "default": 10,
            },
            "sort": {
                "type": "string",
                "enum": ["recency", "relevance", "hybrid"],
                "description": (
                    "How to order matches. 'recency' favors newer hits, 'relevance' favors strongest FTS matches, "
                    "and 'hybrid' keeps strong older matches competitive while still boosting newer context."
                ),
                "default": "recency",
            },
            "session_scope": {
                "type": "string",
                "enum": ["current", "all", "session"],
                "description": (
                    "Scope of the search across the plugin-local LCM database. "
                    "'current' (default) restricts to the active session and preserves historical behavior. "
                    "'all' searches every session in the local LCM database. "
                    "'session' restricts to the session_id supplied via the session_id parameter. "
                    "Cross-session search returns snippets and message store_ids; cross-session summary node expansion is deferred. "
                    "For Hermes-tracked session history outside the LCM database, use session_search."
                ),
                "default": "current",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "When session_scope='session', the explicit session id to restrict the search to. "
                    "Must not be supplied with session_scope='current' or session_scope='all'."
                ),
            },
            "source": {
                "type": "string",
                "description": (
                    "Optional source/platform filter (for example cli, discord, telegram). "
                    "Applies directly to raw messages and to summaries via descendant source lineage. "
                    "Use 'unknown' for explicit unknown-source content."
                ),
            },
            "conversation_id": {
                "type": "string",
                "description": (
                    "Optional gateway conversation/session key filter for lane-scoped retrieval. "
                    "Use this to restrict Discord searches to one channel/thread/forum topic lane when rows carry metadata."
                ),
            },
            "role": {
                "type": "string",
                "enum": ["system", "user", "assistant", "tool", "unknown"],
                "description": "Optional raw-message role filter. When supplied, lcm_grep returns raw message hits only.",
            },
            "time_from": {
                "anyOf": [{"type": "number"}, {"type": "string"}],
                "description": (
                    "Optional inclusive minimum raw-message timestamp. Accepts Unix seconds or timezone-aware ISO 8601; "
                    "naive ISO timestamps are rejected. When supplied, lcm_grep returns raw message hits only."
                ),
            },
            "time_to": {
                "anyOf": [{"type": "number"}, {"type": "string"}],
                "description": (
                    "Optional inclusive maximum raw-message timestamp. Accepts Unix seconds or timezone-aware ISO 8601; "
                    "naive ISO timestamps are rejected. When supplied, lcm_grep returns raw message hits only."
                ),
            },
        },
        "required": ["query"],
    },
}

LCM_LOAD_SESSION = {
    "name": "lcm_load_session",
    "description": "Load an ordered raw-message transcript page for one explicit session_id from the LCM database. Enumeration, not search: chronological rows, paginated via after_store_id/next_cursor. Use after session_search or lcm_grep identified the session_id.",
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Explicit LCM session id to load. Required; no implicit current/all fallback is applied.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum raw messages to return (default 100, hard upper bound 200). "
                    "Values above the cap are clamped and reported via limit_clamped_from."
                ),
                "default": 100,
            },
            "max_content_chars": {
                "type": "integer",
                "description": (
                    "Maximum content characters to include per message (default 4000, hard upper bound 20000). "
                    "Longer rows include content_truncated=true and can be recovered fully with lcm_expand(store_id=...)."
                ),
                "default": 4000,
            },
            "after_store_id": {
                "type": "integer",
                "description": (
                    "Exclusive cursor for pagination. Pass the previous response's next_cursor "
                    "to continue with rows whose store_id is greater than this value."
                ),
                "default": 0,
            },
            "roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional role filter, for example ['user', 'assistant', 'tool', 'system'].",
            },
            "time_from": {
                "type": "number",
                "description": "Optional inclusive minimum message timestamp (Unix seconds).",
            },
            "time_to": {
                "type": "number",
                "description": "Optional inclusive maximum message timestamp (Unix seconds).",
            },
        },
        "required": ["session_id"],
    },
}

LCM_DESCRIBE = {
    "name": "lcm_describe",
    "description": "Inspect a summary node's subtree metadata (token counts, child manifest, expand hints) or an externalized payload ref WITHOUT loading full content. No args = top-level DAG overview. Use to plan retrieval before spending tokens on lcm_expand.",
    "parameters": {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "integer",
                "description": "Summary node ID to inspect. Omit for session overview.",
            },
            "externalized_ref": {
                "type": "string",
                "description": "Optional externalized payload ref filename to inspect instead of a summary node.",
            },
        },
        "required": [],
    },
}

LCM_EXPAND = {
    "name": "lcm_expand",
    "description": "Recover original detail behind a summary node (node_id, current session), externalized payload (externalized_ref, current session), or single raw message (store_id, any session). Exactly one mode. Bounded by max_tokens; pageable via content_offset.",
    "parameters": {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Summary node ID to expand. Current-session only — cross-session DAG expansion "
                    "is not supported in this version."
                ),
            },
            "externalized_ref": {
                "type": "string",
                "description": "Externalized payload ref filename to expand instead of a summary node. Current-session only.",
            },
            "store_id": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Raw message store_id to fetch. Works across sessions, so a store_id surfaced by "
                    "a cross-session lcm_grep result can be expanded directly. Returns the message's "
                    "content paged by content_offset. If the row references an externalized payload, "
                    "the ref is surfaced via 'externalized_ref'; payload metadata and content are "
                    "session-scoped, so a cross-session row also includes 'externalized_note' "
                    "explaining that the ref is for traceability only and cannot be expanded in this version."
                ),
            },
            "max_tokens": {
                "type": "integer",
                "description": "Token budget for returned content (default 4000)",
                "default": 4000,
            },
            "source_offset": {
                "type": "integer",
                "description": "Zero-based pagination offset into the node's immediate source list (node_id mode only).",
                "default": 0,
            },
            "source_limit": {
                "type": "integer",
                "description": "Maximum number of immediate sources to return from source_offset (node_id mode only). Output still respects max_tokens.",
            },
            "content_offset": {
                "type": "integer",
                "description": "Character offset used to continue an oversized raw message, externalized payload, or store_id-mode message. Use next_content_offset from the previous response.",
                "default": 0,
            },
        },
        "required": [],
    },
}

LCM_STATUS = {
    "name": "lcm_status",
    "description": "LCM engine health overview: compression count, store size, DAG depth distribution, context usage, active config, session filter state, and rotate snapshot state.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

LCM_INSPECT = {
    "name": "lcm_inspect",
    "description": "Read-only LCM metadata for the current session: lineage, message frontier, fresh tail, compaction frontier and skip reason, externalized refs, matched ignore/stateless patterns. Inventory only \u2014 use lcm_grep/lcm_expand for content.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of rows/items to return for bounded sections. Defaults to 20 and is capped at 200.",
                "default": 20,
            },
        },
        "required": [],
    },
}

LCM_DOCTOR = {
    "name": "lcm_doctor",
    "description": "Run LCM diagnostics: database integrity, orphaned DAG nodes, config validation, potential issues.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

LCM_EXPAND_QUERY = {
    "name": "lcm_expand_query",
    "description": "Answer a question using expanded LCM context from the current session: give a prompt plus either a query to find candidate summaries or explicit node_ids. Descends the DAG under the context budget. For cross-session recall use session_search first.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The question or task to answer from expanded LCM context",
            },
            "query": {
                "type": "string",
                "description": "Optional search query used to find candidate summaries before expansion",
            },
            "node_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional explicit summary node IDs to expand instead of searching",
            },
            "max_results": {
                "type": "integer",
                "description": "Max candidate summaries to expand when using query (default 5)",
                "default": 5,
            },
            "max_tokens": {
                "type": "integer",
                "description": "Max answer tokens for bounded synthesis returned to the main agent (default 2000)",
                "default": 2000,
            },
            "context_max_tokens": {
                "type": "integer",
                "description": "Expanded serialized summary/raw/child-source/externalized fresh context budget for the auxiliary LLM before it returns the bounded answer (default max(answer max_tokens, 32000 or LCM_EXPANSION_CONTEXT_TOKENS))",
                "default": 32000,
            },
        },
        "required": ["prompt"],
    },
}
