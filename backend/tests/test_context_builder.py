from app.services.context_builder import classify_intent


def test_start_sit_intent():
    assert classify_intent("Should I start Ja'Marr Chase or CeeDee Lamb?") == "start_sit"
    assert classify_intent("who should i play at flex") == "start_sit"
    assert classify_intent("Bench Saquon this week?") == "start_sit"


def test_trade_intent():
    assert classify_intent("Is this trade fair: my Hill for his Jefferson?") == "trade"
    assert classify_intent("Should I acquire a top RB in a package deal?") == "trade"


def test_waiver_intent():
    assert classify_intent("Who should I pick up off waivers this week?") == "waiver"
    assert classify_intent("Is there a good streaming defense to add?") == "waiver"


def test_matchup_intent():
    assert classify_intent("Break down my matchup against my opponent") == "matchup"


def test_general_fallback():
    assert classify_intent("What do you think about the Bengals offense?") == "general"
