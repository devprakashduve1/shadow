from assistant.manual_projects import ManualProjectRegistry, name_matches_content


def test_name_matches_content_requires_all_words_regardless_of_separator():
    # Regression test: a kebab-case folder name rarely appears verbatim in
    # captured text — this is what previously caused retrieve_for_project to
    # find zero activity for a real project the user had plenty of.
    assert name_matches_content("user-profile-mfe", "Deployed the User Profile MFE today")
    assert name_matches_content("user-profile-mfe", "user_profile_mfe build failed")
    assert name_matches_content("user-profile-mfe", "USER PROFILE MFE rollout plan")


def test_name_matches_content_requires_every_word():
    assert not name_matches_content("user-profile-mfe", "the offer service is down")  # missing "selection", "mfe"


def test_name_matches_content_uses_word_boundaries():
    # "mfe" must be a whole word, not a substring buried in an unrelated word.
    assert not name_matches_content("mfe", "restarted the npmfeed process")


def test_name_matches_content_single_word_folder():
    assert name_matches_content("shadow", "working in the shadow repo")
    assert not name_matches_content("shadow", "no relation here")


def test_add_and_list(tmp_path):
    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    project = registry.add(tmp_path / "myrepo")

    assert project.name == "myrepo"
    assert project.path == str(tmp_path / "myrepo")

    listed = registry.list()
    assert len(listed) == 1
    assert listed[0].name == "myrepo"


def test_add_is_idempotent_for_same_path(tmp_path):
    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")
    registry.add(tmp_path / "myrepo")

    assert len(registry.list()) == 1


def test_add_different_folders_creates_separate_entries(tmp_path):
    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "repo-one")
    registry.add(tmp_path / "repo-two")

    names = {p.name for p in registry.list()}
    assert names == {"repo-one", "repo-two"}


def test_remove(tmp_path):
    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")
    registry.remove("myrepo")

    assert registry.list() == []


def test_persists_across_instances(tmp_path):
    path = tmp_path / "manual_projects.json"
    ManualProjectRegistry(path).add(tmp_path / "myrepo")

    reloaded = ManualProjectRegistry(path)
    assert [p.name for p in reloaded.list()] == ["myrepo"]
