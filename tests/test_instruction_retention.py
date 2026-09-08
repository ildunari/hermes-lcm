"""Active instructions must not depend on tool retrieval to be read."""
import json

import pytest

from hermes_lcm.config import LCMConfig
from hermes_lcm.engine import LCMEngine


@pytest.mark.parametrize("role", ["user", "system", "developer"])
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
