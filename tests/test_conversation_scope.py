import json

from hermes_lcm import tools as lcm_tools
from hermes_lcm.command import _doctor_clean_apply_text
from hermes_lcm.config import LCMConfig
from hermes_lcm.dag import SummaryNode
from hermes_lcm.engine import LCMEngine


def _engine(db_path, conversation_id="", session_id=""):
    engine = LCMEngine(
        config=LCMConfig(database_path=str(db_path), restrict_to_conversation=True),
    )
    if session_id:
        engine.on_session_start(session_id, platform="test", conversation_id=conversation_id)
    return engine


def test_restricted_same_db_clamps_all_and_preserves_owned_cross_session_history(tmp_path):
    db_path = tmp_path / "shared.db"
    contact_a = _engine(db_path, "conversation-a", "session-a")
    contact_b = _engine(db_path, "conversation-b", "session-b")
    try:
        contact_a.ingest([{"role": "user", "content": "secret contact A"}])
        contact_b.ingest([{"role": "user", "content": "secret contact B"}])

        all_results = json.loads(contact_b.handle_tool_call(
            "lcm_grep", {"query": "secret", "session_scope": "all"}
        ))
        assert all_results["conversation_id"] == "conversation-b"
        assert len(all_results["results"]) == 1
        assert "contact B" in all_results["results"][0]["snippet"]

        loaded = json.loads(lcm_tools.lcm_load_session(
            {"session_id": "session-b"}, engine=contact_b
        ))
        assert [item["content"] for item in loaded["messages"]] == ["secret contact B"]
        assert json.loads(contact_b.handle_tool_call(
            "lcm_load_session", {"session_id": "session-a"}
        ))["error"].startswith("session_id does not belong")
    finally:
        contact_a.shutdown()
        contact_b.shutdown()


def test_restricted_explicit_store_and_node_ids_are_owned_and_survive_restart(tmp_path):
    db_path = tmp_path / "restart.db"
    owner = _engine(db_path, "same-contact", "session-one")
    foreign = _engine(db_path, "other-contact", "session-two")
    try:
        owner.ingest([{"role": "user", "content": "owned history"}])
        foreign.ingest([{"role": "user", "content": "foreign history"}])
        owned_id = owner._store.search("owned", session_id="session-one")[0]["store_id"]
        foreign_id = foreign._store.search("foreign", session_id="session-two")[0]["store_id"]
        foreign_node_id = foreign._dag.add_node(SummaryNode(
            session_id="session-two",
            summary="foreign summary",
            source_ids=[foreign_id],
        ))

        assert "owned history" in json.loads(owner.handle_tool_call(
            "lcm_expand", {"store_id": owned_id}
        ))["content"]
        assert "does not belong" in json.loads(lcm_tools.lcm_expand(
            {"store_id": foreign_id}, engine=owner
        ))["error"]
        assert "does not belong" in json.loads(owner.handle_tool_call(
            "lcm_expand", {"node_id": foreign_node_id}
        ))["error"]
        assert "does not belong" in json.loads(lcm_tools.lcm_describe(
            {"node_id": foreign_node_id}, engine=owner
        ))["error"]
    finally:
        owner.shutdown()
        foreign.shutdown()

    restarted = _engine(db_path, "same-contact", "session-one")
    try:
        result = json.loads(restarted.handle_tool_call(
            "lcm_grep", {"query": "history", "session_scope": "all"}
        ))
        assert len(result["results"]) == 1
        assert "history" in result["results"][0]["snippet"]
    finally:
        restarted.shutdown()


def test_restricted_mode_fails_closed_unbound_and_denies_cleanup(tmp_path):
    engine = _engine(tmp_path / "unbound.db")
    try:
        for name in ("lcm_grep", "lcm_load_session", "lcm_describe", "lcm_expand",
                     "lcm_expand_query", "lcm_status", "lcm_inspect", "lcm_doctor"):
            result = json.loads(engine.handle_tool_call(name, {}, messages=[
                {"role": "user", "content": "must not ingest"},
            ]))
            assert "unbound" in result["error"]
        assert "denied" in _doctor_clean_apply_text(engine)
    finally:
        engine.shutdown()


def test_restricted_doctor_does_not_expose_global_metadata(tmp_path):
    import json
    from hermes_lcm.config import LCMConfig
    from hermes_lcm.engine import LCMEngine
    from hermes_lcm.tools import lcm_doctor
    engine=LCMEngine(config=LCMConfig(database_path=str(tmp_path/'doctor.db'),restrict_to_conversation=True))
    try:
        engine.on_session_start('mine',conversation_id='contact:mine',platform='bluebubbles')
        for response in (lcm_doctor({},engine=engine),engine.handle_tool_call('lcm_doctor',{})):
            assert json.loads(response)=={'error':'LCM database diagnostics require operator access'}
    finally:engine.shutdown()


def test_all_restricted_maintenance_commands_are_denied():
    from types import SimpleNamespace
    from hermes_lcm.command import handle_lcm_command
    engine=SimpleNamespace(_config=SimpleNamespace(restrict_to_conversation=True))
    for command in ('doctor','doctor clean','doctor clean apply','doctor clean lifecycle apply','doctor repair','doctor repair apply','doctor source','doctor source apply','doctor retention','backup','rotate','rotate apply','preset show','preset suggest','preset apply default'):
        assert 'require operator access' in handle_lcm_command(command,engine),command
