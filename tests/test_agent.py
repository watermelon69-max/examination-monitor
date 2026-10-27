import pytest
from app.services.agent import ModelBasedAgent, StudentState


def phone(timestamp=0):
    return {'type': 'mobile_phone', 'track_id': 1, 'confidence': .9, 'duration': 1, 'timestamp': timestamp, 'bbox': [0, 0, 100, 100]}


def test_risk_decays_with_frequent_idle_ticks():
    agent = ModelBasedAgent()
    agent.process_events([phone()], 0)
    initial = agent.student_risk_scores[1]
    for second in range(1, 61):
        agent.process_events([], second)
    assert agent.student_risk_scores[1] == pytest.approx(max(0, initial - 55 * agent.decay_rate))


def test_single_event_transitions_after_hysteresis_without_another_event():
    agent = ModelBasedAgent()
    agent.process_events([phone()], 0)
    assert agent.student_states[1] == StudentState.NORMAL
    agent.process_events([], 3)
    assert agent.student_states[1] == StudentState.OBSERVE


def test_state_deescalates_through_lower_levels():
    agent = ModelBasedAgent()
    agent.register(1, 0)
    agent.student_risk_scores[1] = 90
    agent.update_state(1, 3)
    assert agent.student_states[1] == StudentState.ALERT
    agent.student_risk_scores[1] = 50
    agent.update_state(1, 6)
    assert agent.student_states[1] == StudentState.SUSPICIOUS
    agent.student_risk_scores[1] = 25
    agent.update_state(1, 9)
    assert agent.student_states[1] == StudentState.OBSERVE


def test_memory_expires_on_video_time_and_risk_caps():
    agent = ModelBasedAgent()
    for second in range(20):
        agent.process_events([phone(second)], second)
    assert agent.student_risk_scores[1] <= 100
    agent.process_events([], 100)
    assert agent.get_student_info(1)['recent_events'] == 0
