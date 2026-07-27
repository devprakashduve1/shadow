from events.project_keys import extract_project_keys


def test_extracts_single_ticket_key():
    assert extract_project_keys("Bug PROJ-1139 in Jira Cloud") == ["PROJ"]


def test_extracts_multiple_distinct_keys_sorted():
    """De-duplicated and returned in alphabetical order, not order of appearance."""
    text = "Blocked by PROJ-1192, tracked under PLAT-204, also see PROJ-1139"
    assert extract_project_keys(text) == ["PLAT", "PROJ"]


def test_no_keys_in_plain_text():
    assert extract_project_keys("just a normal sentence with no tickets") == []


def test_does_not_match_lowercase_prefix():
    assert extract_project_keys("see voGS-1139 for details") == []
