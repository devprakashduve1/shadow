from events.redaction import redact


def test_redacts_openai_style_key():
    text = "my key is sk-abcdefghijklmnopqrstuvwx12345"
    assert "sk-abcdefghijklmnopqrstuvwx12345" not in redact(text)
    assert "[REDACTED_API_KEY]" in redact(text)


def test_redacts_aws_key():
    assert "[REDACTED_AWS_KEY]" in redact("AKIAABCDEFGHIJKLMNOP")


def test_redacts_github_token():
    assert "[REDACTED_GITHUB_TOKEN]" in redact("token: ghp_abcdefghijklmnopqrstuvwxyz0123")


def test_redacts_bearer_header():
    assert "Bearer [REDACTED_TOKEN]" in redact("Authorization: Bearer abcdef123456")


def test_redacts_generic_assignment():
    result = redact("password=SuperSecret123")
    assert "SuperSecret123" not in result
    assert "REDACTED" in result


def test_redacts_email():
    assert "[REDACTED_EMAIL]" in redact("contact me at jane.doe@example.com please")


def test_redacts_card_number():
    assert "[REDACTED_CARD_NUMBER]" in redact("card: 4111 1111 1111 1111")


def test_leaves_ordinary_text_untouched():
    text = "Fixed the payment timeout bug in checkout.py"
    assert redact(text) == text
