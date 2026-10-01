import json
from datetime import date
from types import SimpleNamespace

from services.api import main


FLEET_SNAPSHOT = {
    "from_date": "2026-09-02",
    "to_date": "2026-10-01",
    "vehicle_count": 50,
    "total_fuel_cost_inr": 395084.89,
    "total_idle_cost_inr": 10576.57,
    "total_operating_cost_inr": 405661.46,
    "total_idle_min": 14890,
    "avg_utilisation_pct": 30.9,
}


def test_fleet_question_detection():
    assert main.is_fleet_data_question("How much money are we wasting?")
    assert main.is_fleet_data_question("How can we optimise it?")
    assert not main.is_fleet_data_question("Tell me a joke")


def test_fleet_context_is_sent_before_prompt_and_model_reply_is_returned(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(main, "get_fleet_cost_snapshot", lambda *_: FLEET_SNAPSHOT)
    captured = {}
    model_answer = "Idle waste is ₹10,576.57 for the period. Review recurring idle patterns."

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=model_answer))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    answer, tool_calls = main.answer_assistant_query(
        "How can we optimize idle waste?",
        date(2026, 9, 2),
        date(2026, 10, 1),
        {"fleet_id": "*"},
    )

    assert answer == model_answer
    assert tool_calls == []
    messages = captured["messages"]
    assert messages[-1] == {"role": "user", "content": "How can we optimize idle waste?"}
    context = json.loads(messages[-2]["content"].split("\n", 1)[1])
    assert context["reporting_period"] == {
        "from_inclusive": "2026-09-02",
        "to_inclusive": "2026-10-01",
        "inclusive_days": 30,
    }
    assert context["fleet_metrics"]["idle_cost_inr"] == 10576.57
    assert context["fleet_metrics"]["total_operating_cost_inr"] == 405661.46


def test_offender_context_uses_database_rows(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(main, "get_fleet_cost_snapshot", lambda *_: FLEET_SNAPSHOT)
    monkeypatch.setattr(main, "get_fleet_filter", lambda _: None)
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_):
            pass

        def fetchall(self):
            return [{"vin": "TESTVIN0000000001", "idle_cost": 123.45}]

    class FakeDB:
        def __enter__(self):
            return FakeCursor()

        def __exit__(self, *_):
            return False

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="The highest idle cost is ₹123.45."))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(main, "get_db", FakeDB)
    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    main.answer_assistant_query(
        "Which vehicle has the highest idle cost?",
        date(2026, 9, 2),
        date(2026, 10, 1),
        {"fleet_id": "*"},
    )

    context = json.loads(captured["messages"][-2]["content"].split("\n", 1)[1])
    assert context["highest_idle_cost_vehicles"] == [
        {"vin": "TESTVIN0000000001", "idle_cost_inr": 123.45}
    ]


def test_unsupported_numbers_are_detected_against_database_context():
    context = {
        "reporting_period": {
            "from_inclusive": "2026-09-02",
            "to_inclusive": "2026-10-01",
        },
        "fleet_metrics": {
            "vehicles_with_data": 50,
            "fuel_cost_inr": 395084.89,
            "idle_cost_inr": 10576.57,
            "total_operating_cost_inr": 405661.46,
            "idle_minutes": 14890,
            "average_utilisation_pct": 30.9,
            "idle_cost_share_pct": 2.6,
        },
    }
    assert not main.has_unsupported_numeric_claim(
        "Idle cost is ₹10,576.57, or 2.6% of ₹405,661.46.", context
    )
    assert main.has_unsupported_numeric_claim(
        "Idle cost is ₹12,780,000 for 87 vehicles.", context
    )


def test_fabricated_numbers_trigger_a_corrective_model_request(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(main, "get_fleet_cost_snapshot", lambda *_: FLEET_SNAPSHOT)
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            answer = (
                "Idle cost is ₹12,780,000 for 87 vehicles."
                if len(calls) == 1
                else "Idle cost is ₹10,576.57. Review repeated idle patterns with dispatch."
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(main, "OpenAI", FakeOpenAI)
    answer, _ = main.answer_assistant_query(
        "How can we optimise idling?",
        date(2026, 9, 2),
        date(2026, 10, 1),
        {"fleet_id": "*"},
    )

    assert len(calls) == 2
    assert "₹10,576.57" in answer
    assert "₹12,780,000" not in answer
    assert "corrected response" in calls[1]["messages"][-1]["content"]
