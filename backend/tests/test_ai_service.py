from app.services.ai_service import build_system_prompt, build_user_message


def test_system_prompt_includes_scoring():
    context = {
        "league_settings": {
            "scoring": "half_ppr",
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
        }
    }
    prompt = build_system_prompt(context)
    assert "HALF-PPR" in prompt
    assert "FLEX" in prompt


def test_system_prompt_defaults():
    prompt = build_system_prompt({})
    assert "PPR" in prompt


def test_user_message_embeds_question_and_data():
    msg = build_user_message("Start Chase or Lamb?", {"players": [{"name": "Ja'Marr Chase"}]})
    assert 'Start Chase or Lamb?' in msg
    assert "Ja'Marr Chase" in msg
