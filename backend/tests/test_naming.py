from app import naming


def test_sanitize_removes_forbidden_chars():
    assert naming.sanitize('A: B/C?*"') == "A B C"
    assert naming.sanitize("  ...  ") == "Unbenannt"


def test_episode_guessing():
    assert naming.guess_episode_number("Some Show Episode 03") == 3
    assert naming.guess_episode_number("Some Show - 12") == 12
    assert naming.guess_episode_number("Folge 7: Titel") == 7
    assert naming.guess_episode_number("kein Hinweis") is None


def test_episode_from_url_slug():
    assert naming.episode_from_url("https://example.org/videos/some-show-4") == 4
    assert naming.episode_from_url("https://example.org/videos/some-show") is None


def test_series_name_strips_episode_suffix():
    assert naming.guess_series_name("Some Show Episode 3") == "Some Show"
    assert naming.guess_series_name("Some Show 2 - 03") == "Some Show 2"


def test_build_relative_path_jellyfin_layout():
    folder, name = naming.build_relative_path("Show: Name", 1, 3, "Der Titel")
    assert folder == "Show Name/Season 01"
    assert name == "Show Name - S01E03 - Der Titel.%(ext)s"


def test_percent_is_escaped():
    _, name = naming.build_relative_path("100% Show", 1, 1, "")
    assert name == "100%% Show - S01E01.%(ext)s"
