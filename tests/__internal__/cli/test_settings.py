"""Setting values through the real CLI, where the command text reads as YAML once.

The models store values as passed, so the parse at the command line is the only one,
and a quoted string stays the string it parsed to.
"""


def _owner(made) -> str:
    (user,) = made.run(
        "users",
        "create",
        "--username",
        "ada",
        "--email",
        "ada@example.com",
        "--password",
        "secret123",
    ).rows()
    return user["id"]


def test_create_reads_the_value_as_yaml_once(project) -> None:
    made = project()
    owner = _owner(made)

    for name, text, expected in [
        ("number", "5", 5),
        ("boolean", "true", True),
        ("text", '"true"', "true"),
    ]:
        outcome = made.run(
            "settings", "create", "--user-id", owner, "--name", name, "--value", text
        )

        assert outcome.ok, outcome.stderr
        (setting,) = outcome.rows()
        assert setting["value"] == expected


def test_set_reads_the_value_as_yaml(project) -> None:
    made = project()
    owner = _owner(made)
    assert made.run("settings", "create", "--user-id", owner, "--name", "k", "--value", "1").ok

    outcome = made.run(
        "settings",
        "update",
        "--name",
        "k",
        "--set",
        "{ value: [1, 2] }",
        "--no-confirm",
        "--collect",
    )

    assert outcome.ok, outcome.stderr
    (setting,) = outcome.rows()
    assert setting["value"] == [1, 2]
