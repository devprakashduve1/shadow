from screen.window_watcher import WindowInfo, is_window_excluded

# Default excluded_apps per config/default_settings.yaml — tests exercise both
# "with defaults" and "with an empty/overridden list" to prove the Shadow
# exclusion doesn't depend on user config.
_DEFAULT_EXCLUDED_APPS = ["Claude", "Shadow"]


def test_shadow_app_name_excluded_even_without_config_entry():
    # Simulates a user's local settings.yaml replacing excluded_apps entirely,
    # dropping the "Shadow" entry — the app must still exclude its own window.
    window = WindowInfo(app_name="Shadow", window_title="Live Monitor")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_shadow_window_title_excluded_even_without_config_entry():
    window = WindowInfo(app_name="python3", window_title="Shadow")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_folder_named_shadow_excluded():
    # e.g. a Finder window browsing this project's own "shadow" folder
    window = WindowInfo(app_name="Finder", window_title="shadow")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_file_starting_with_shadow_excluded():
    # e.g. an editor with one of DataLogger's own Shadow_*.txt files open
    window = WindowInfo(app_name="TextEdit", window_title="Shadow_screen.txt")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_case_insensitive():
    window = WindowInfo(app_name="Finder", window_title="SHADOW-notes")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_shadow_substring_not_at_start_of_title_still_relies_on_excluded_apps():
    # "shadow" appears but not at the start — the hardcoded rule is startswith-only,
    # so this only gets excluded because "Shadow" is in excluded_apps (the default).
    window = WindowInfo(app_name="iTerm2", window_title="~/Projects/shadow — zsh")
    assert is_window_excluded(window, excluded_apps=_DEFAULT_EXCLUDED_APPS, excluded_domains=[])
    assert not is_window_excluded(window, excluded_apps=[], excluded_domains=[])


def test_unrelated_window_not_excluded():
    window = WindowInfo(app_name="Google Chrome", window_title="Example Domain")
    assert not is_window_excluded(window, excluded_apps=_DEFAULT_EXCLUDED_APPS, excluded_domains=[])


def test_none_window_not_excluded():
    assert not is_window_excluded(None, excluded_apps=_DEFAULT_EXCLUDED_APPS, excluded_domains=[])


def test_configured_excluded_app_still_works():
    window = WindowInfo(app_name="Claude", window_title="Claude")
    assert is_window_excluded(window, excluded_apps=_DEFAULT_EXCLUDED_APPS, excluded_domains=[])


def test_configured_excluded_domain_still_works():
    window = WindowInfo(app_name="Google Chrome", window_title="Gmail", url="https://mail.google.com/mail/u/0")
    assert is_window_excluded(window, excluded_apps=[], excluded_domains=["mail.google.com"])
