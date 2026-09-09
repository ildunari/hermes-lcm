"""Active instructions must not depend on tool retrieval to be read."""
import json

import pytest

from hermes_lcm.config import LCMConfig
from hermes_lcm.engine import LCMEngine


@pytest.mark.parametrize("role", ["system", "developer"])
def test_long_active_instructions_remain_inline_with_externalized_storage(tmp_path, role):
    content = "Preserve completed work. Check before repeating actions. " * 220
    engine = LCMEngine(config=LCMConfig(
        database_path=str(tmp_path / "lcm.db"),
        large_output_externalization_enabled=True,
        large_output_externalization_threshold_chars=8000,
    ), hermes_home=str(tmp_path))
    engine._session_id = "instructions"
    try:
        messages = [{"role": role, "content": content}]
        active = engine._ingest_messages(messages)
        assert active[0]["content"] == content
        assert engine.compress(messages)[0]["content"] == content
        assert messages[0]["content"] == content
        stored = engine._store.get_session_messages("instructions")
        assert stored[0]["content"].startswith("[Externalized payload:")
        payloads = list((tmp_path / "lcm-large-outputs").glob("*.json"))
        assert len(payloads) == 1
        assert json.loads(payloads[0].read_text())["content"] == content
    finally:
        engine.shutdown()


def test_only_latest_user_instruction_remains_inline_across_compress_calls(tmp_path):
    engine = LCMEngine(config=LCMConfig(
        database_path=str(tmp_path / "lcm.db"),
        large_output_externalization_enabled=True,
        large_output_externalization_threshold_chars=8000,
    ), hermes_home=str(tmp_path))
    engine._session_id = "instructions"
    earlier = "Earlier raw user payload: " + "x" * 9000
    recovery = "Resume without repeating completed work. " + "r" * 10860
    try:
        first_messages = [
            {"role": "user", "content": earlier},
            {"role": "assistant", "content": "Acknowledged."},
            {"role": "user", "content": recovery},
        ]
        first = engine.compress(first_messages)
        assert first[0]["content"].startswith("[Externalized payload:")
        assert first[-1]["content"] == recovery
        assert first_messages[0]["content"] == earlier
        assert first_messages[-1]["content"] == recovery

        latest = "Current task boundary: inspect the new failure. " + "n" * 9000
        second_messages = [*first_messages, {"role": "assistant", "content": "Working."}, {"role": "user", "content": latest}]
        second = engine.compress(second_messages)
        assert second[0]["content"].startswith("[Externalized payload:")
        assert second[2]["content"].startswith("[Externalized payload:")
        assert second[-1]["content"] == latest

        repeated = engine.compress(second_messages)
        assert repeated == second
        stored = engine._store.get_session_messages("instructions")
        assert stored[0]["content"].startswith("[Externalized payload:")
        assert stored[2]["content"].startswith("[Externalized payload:")
        assert stored[-1]["content"].startswith("[Externalized payload:")
    finally:
        engine.shutdown()
