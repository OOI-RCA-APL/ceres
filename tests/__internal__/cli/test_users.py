"""The user lifecycle through the real CLI, create through delete.

These run the native binary against a disposable project, so they cover the argument
surface, the wire conversion, and the database rules exactly as a deployment sees them.
"""

CREATE = ("users", "create", "--username", "ada", "--email", "ada@example.com")
PASSWORD = ("--password", "secret123")


def test_a_bare_admin_flag_creates_an_admin(project) -> None:
    outcome = project().run(*CREATE, *PASSWORD, "--admin")

    assert outcome.ok, outcome.stderr
    (user,) = outcome.rows()
    assert user["admin"] is True


def test_admin_takes_an_explicit_value(project) -> None:
    made = project()
    for value, expected in [("true", True), ("false", False)]:
        outcome = made.run(
            "users",
            "create",
            "--username",
            f"ada-{value}",
            "--email",
            f"ada-{value}@example.com",
            *PASSWORD,
            "--admin",
            value,
        )

        assert outcome.ok, outcome.stderr
        (user,) = outcome.rows()
        assert user["admin"] is expected


def test_admin_defaults_to_false(project) -> None:
    outcome = project().run(*CREATE, *PASSWORD)

    assert outcome.ok, outcome.stderr
    (user,) = outcome.rows()
    assert user["admin"] is False
    assert user["disabled"] is False


def test_a_created_password_is_stored_hashed(project) -> None:
    outcome = project().run(*CREATE, *PASSWORD)

    assert outcome.ok, outcome.stderr
    (user,) = outcome.rows()
    assert user["password"].startswith("$argon2id$")
    assert "secret123" not in user["password"]


def test_select_finds_the_created_user(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run("users", "select", "--username", "ada")

    assert outcome.ok, outcome.stderr
    (user,) = outcome.rows()
    assert user["email"] == "ada@example.com"


def test_update_rehashes_a_password(project) -> None:
    made = project()
    (created,) = made.run(*CREATE, *PASSWORD).rows()

    outcome = made.run(
        "users",
        "update",
        "--username",
        "ada",
        "--set",
        "{password: newsecret456}",
        "--no-confirm",
        "--collect",
    )

    assert outcome.ok, outcome.stderr
    (updated,) = outcome.rows()
    assert updated["password"].startswith("$argon2id$")
    assert updated["password"] != created["password"]
    assert "newsecret456" not in updated["password"]


def test_update_takes_a_flow_yaml_object(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run(
        "users",
        "update",
        "--username",
        "ada",
        "--set",
        "{ username: grace }",
        "--no-confirm",
        "--collect",
    )

    assert outcome.ok, outcome.stderr
    (user,) = outcome.rows()
    assert user["username"] == "grace"


def test_update_refuses_an_unknown_column(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run(
        "users",
        "update",
        "--username",
        "ada",
        "--set",
        "{nope: 1}",
        "--no-confirm",
    )

    assert not outcome.ok
    assert "nope" in outcome.stderr


def test_update_refuses_an_identity_column(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run(
        "users",
        "update",
        "--username",
        "ada",
        "--set",
        "{id: 01a01715-0f1e-7890-bcbc-1b9f7dcd50aa}",
        "--no-confirm",
    )

    assert not outcome.ok
    assert "identifies" in outcome.stderr


def test_update_refuses_a_non_object(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run(
        "users",
        "update",
        "--username",
        "ada",
        "--set",
        "just text",
        "--no-confirm",
    )

    assert not outcome.ok
    assert "--set" in outcome.stderr


def test_delete_removes_the_user(project) -> None:
    made = project()
    assert made.run(*CREATE, *PASSWORD).ok

    outcome = made.run("users", "delete", "--username", "ada", "--no-confirm")
    assert outcome.ok, outcome.stderr

    remaining = made.run("users", "select")
    assert remaining.ok
    assert remaining.rows() == []


def test_migrate_declines_cleanly_without_a_terminal(project) -> None:
    made = project(migrate=False)

    outcome = made.run("database", "migrate")

    assert outcome.ok
    assert "not been modified" in outcome.stderr
