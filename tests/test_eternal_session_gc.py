"""Eternal-session GC and LCM-note re-injection.

An eternal session — a hidden always-on bot chat, a long-lived assistant
thread — never reaches session end or rollover, so the cleanup paths that
bound database growth never run and two things go wrong: raw rows that a
leaf summary already covers stay at full size forever, and the LCM note is
never restored after the host rebuilds its system prompt.
"""

import time

from hermes_lcm.config import LCMConfig
from hermes_lcm.dag import SummaryNode
from hermes_lcm.engine import LCMEngine


ETERNAL_SESSION = "eternal-bot-chat"
OLD = time.time() - (72 * 3600)


def _build_engine(tmp_path, **overrides) -> LCMEngine:
    config = LCMConfig()
    config.database_path = str(tmp_path / "lcm_eternal_gc.db")
    config.eternal_session_gc_enabled = True
    config.eternal_session_gc_retain_messages = 2
    config.eternal_session_gc_min_age_hours = 24.0
    config.eternal_session_gc_min_content_bytes = 100
    config.eternal_session_gc_max_rows_per_run = 50
    for key, value in overrides.items():
        setattr(config, key, value)
    engine = LCMEngine(config=config, hermes_home=str(tmp_path / "hermes_home"))
    engine._session_id = ETERNAL_SESSION
    engine._conversation_id = ETERNAL_SESSION
    return engine


def _append(engine, role, content, *, age_seconds=None, pinned=False):
    store_id = engine._store.append(engine._session_id, {"role": role, "content": content})
    timestamp = time.time() - (age_seconds if age_seconds is not None else 72 * 3600)
    engine._store._conn.execute(
        "UPDATE messages SET timestamp = ? WHERE store_id = ?", (timestamp, store_id)
    )
    if pinned:
        engine._store.pin(store_id)
    engine._store._conn.commit()
    return store_id


def _summarize(engine, store_ids):
    return engine._dag.add_node(
        SummaryNode(
            session_id=engine._session_id,
            depth=0,
            summary="leaf summary",
            token_count=10,
            source_token_count=100,
            source_ids=list(store_ids),
            source_type="messages",
            created_at=time.time(),
        )
    )


def _content(engine, store_id):
    return engine._store.get(store_id)["content"]


def _seed_covered_row(engine, *, extra_tail=3, **row_kwargs):
    """One big old summarized row, plus enough newer rows to clear the tail."""
    store_id = _append(engine, "assistant", "x" * 4000, **row_kwargs)
    _summarize(engine, [store_id])
    for index in range(extra_tail):
        _append(engine, "user", f"later-{index}")
    engine._last_compacted_store_id = store_id + extra_tail
    return store_id


class TestEternalSessionGC:
    def test_disabled_by_default(self, tmp_path):
        engine = _build_engine(tmp_path, eternal_session_gc_enabled=False)
        store_id = _seed_covered_row(engine)

        assert engine._maybe_eternal_session_gc() == {"rows": 0, "bytes": 0}
        assert _content(engine, store_id) == "x" * 4000

    def test_prunes_summarized_row_and_preserves_row_identity(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _seed_covered_row(engine)

        result = engine._maybe_eternal_session_gc()

        assert result["rows"] == 1
        assert result["bytes"] > 3000
        row = engine._store.get(store_id)
        assert row["store_id"] == store_id
        assert row["role"] == "assistant"
        assert "eternal-session GC" in row["content"]
        assert f"summary_node=" in row["content"]
        assert len(row["content"]) < 400

    def test_second_run_is_a_no_op(self, tmp_path):
        engine = _build_engine(tmp_path)
        _seed_covered_row(engine)

        assert engine._maybe_eternal_session_gc()["rows"] == 1
        assert engine._maybe_eternal_session_gc() == {"rows": 0, "bytes": 0}

    def test_pinned_row_is_never_pruned(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _seed_covered_row(engine, pinned=True)

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_uncovered_row_is_never_pruned(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _append(engine, "assistant", "x" * 4000)
        for index in range(3):
            _append(engine, "user", f"later-{index}")
        engine._last_compacted_store_id = store_id + 3

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_row_above_the_compaction_frontier_is_never_pruned(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _seed_covered_row(engine)
        engine._last_compacted_store_id = store_id - 1

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_newest_retained_rows_are_exempt(self, tmp_path):
        engine = _build_engine(tmp_path, eternal_session_gc_retain_messages=10)
        store_id = _seed_covered_row(engine)

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_recent_row_is_exempt(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _seed_covered_row(engine, age_seconds=60)

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_small_row_is_not_worth_a_write(self, tmp_path):
        engine = _build_engine(tmp_path, eternal_session_gc_min_content_bytes=100000)
        store_id = _seed_covered_row(engine)

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "x" * 4000

    def test_system_row_is_never_pruned(self, tmp_path):
        engine = _build_engine(tmp_path)
        store_id = _append(engine, "system", "s" * 4000)
        _summarize(engine, [store_id])
        for index in range(3):
            _append(engine, "user", f"later-{index}")
        engine._last_compacted_store_id = store_id + 3

        assert engine._maybe_eternal_session_gc()["rows"] == 0
        assert _content(engine, store_id) == "s" * 4000

    def test_run_is_capped(self, tmp_path):
        engine = _build_engine(tmp_path, eternal_session_gc_max_rows_per_run=2)
        store_ids = [_append(engine, "assistant", f"{index}" + "x" * 4000) for index in range(5)]
        _summarize(engine, store_ids)
        for index in range(3):
            _append(engine, "user", f"later-{index}")
        engine._last_compacted_store_id = store_ids[-1]

        assert engine._maybe_eternal_session_gc()["rows"] == 2
        survivors = [sid for sid in store_ids if len(_content(engine, sid)) > 1000]
        assert len(survivors) == 3

    def test_other_sessions_are_untouched(self, tmp_path):
        engine = _build_engine(tmp_path)
        other = engine._store.append("some-other-session", {"role": "assistant", "content": "y" * 4000})
        engine._store._conn.execute(
            "UPDATE messages SET timestamp = ? WHERE store_id = ?", (OLD, other)
        )
        engine._store._conn.commit()
        engine._dag.add_node(
            SummaryNode(
                session_id="some-other-session",
                depth=0,
                summary="leaf summary",
                token_count=10,
                source_token_count=100,
                source_ids=[other],
                source_type="messages",
                created_at=time.time(),
            )
        )
        engine._store._conn.commit()
        _seed_covered_row(engine)

        assert engine._maybe_eternal_session_gc()["rows"] == 1
        assert _content(engine, other) == "y" * 4000


class TestLCMNoteReinjection:
    """A rebuilt system prompt must get the LCM note back.

    The note is what tells the model that history was compacted and that
    lcm_grep/lcm_describe/lcm_expand exist. It used to be applied only on the
    first compaction, so a host that rebuilds its system prompt mid-session (a
    capability-epoch change, a profile edit) silently dropped it, and an
    eternal session never gets another first compaction to restore it.
    """

    def test_note_applied_on_first_compaction(self, tmp_path):
        engine = _build_engine(tmp_path)

        result = engine._assemble_context({"role": "system", "content": "You are helpful."}, [])

        assert "Lossless Context Management" in result[0]["content"]
        assert engine._lcm_note_applied is True

    def test_note_is_not_duplicated_when_the_prompt_still_carries_it(self, tmp_path):
        engine = _build_engine(tmp_path)
        annotated = engine._assemble_context(
            {"role": "system", "content": "You are helpful."}, []
        )[0]["content"]
        engine.compression_count = 1

        again = engine._assemble_context({"role": "system", "content": annotated}, [])

        assert again[0]["content"] == annotated
        assert again[0]["content"].count("Lossless Context Management") == 1

    def test_note_is_reapplied_when_the_host_rebuilds_the_prompt(self, tmp_path):
        engine = _build_engine(tmp_path)
        engine._assemble_context({"role": "system", "content": "You are helpful."}, [])
        engine.compression_count = 7

        rebuilt = engine._assemble_context(
            {"role": "system", "content": "You are helpful. New capability epoch."}, []
        )

        assert "New capability epoch." in rebuilt[0]["content"]
        assert "Lossless Context Management" in rebuilt[0]["content"]

    def test_note_is_not_forced_onto_a_prompt_lcm_never_annotated(self, tmp_path):
        engine = _build_engine(tmp_path)
        engine.compression_count = 1

        result = engine._assemble_context({"role": "system", "content": "You are helpful."}, [])

        assert result[0]["content"] == "You are helpful."

    def test_session_reset_clears_the_annotation_marker(self, tmp_path):
        engine = _build_engine(tmp_path)
        engine._assemble_context({"role": "system", "content": "You are helpful."}, [])

        engine._reset_session_counters()

        assert engine._lcm_note_applied is False
