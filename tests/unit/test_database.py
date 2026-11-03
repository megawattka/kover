from unittest.mock import AsyncMock, MagicMock

from bson import Binary
import pytest

from kover import Kover, WriteConcern
from kover.network.pool import ConnectionPool


async def test_user_management_commands_preserve_options() -> None:
    database = Kover(pool=MagicMock(spec=ConnectionPool)).get_database("test")
    command = AsyncMock(return_value={"ok": 1})
    database.command = command
    with pytest.raises(ValueError, match="roles"):
        await database.create_user("user", "password")
    command.assert_not_awaited()
    await database.create_user("user", "password", root=True)
    assert command.await_args is not None
    sent = command.await_args.args[0]
    assert sent["mechanisms"] == ["SCRAM-SHA-1", "SCRAM-SHA-256"]
    assert {"role": "root", "db": "admin"} in sent["roles"]
    await database.create_user(
        "user",
        "password",
        roles=["read"],
        custom_data={"test": True},
        mechanisms=["SCRAM-SHA-256"],
        comment="test",
    )
    command.assert_awaited_with(
        {
            "createUser": "user",
            "pwd": "password",
            "roles": ["read"],
            "mechanisms": ["SCRAM-SHA-256"],
            "customData": {"test": True},
            "comment": "test",
        },
    )
    await database.grant_roles_to_user("user", ["readWrite"])
    command.assert_awaited_with(
        {"grantRolesToUser": "user", "roles": ["readWrite"]},
    )
    await database.drop_user("user", comment="test")
    command.assert_awaited_with({"dropUser": "user", "comment": "test"})
    command.return_value = {"n": 3}
    assert (
        await database.drop_all_users_from_database(WriteConcern(w=2), "test")
        == 3
    )
    command.assert_awaited_with(
        {
            "dropAllUsersFromDatabase": 1,
            "writeConcern": {"w": 2},
            "comment": "test",
        },
    )


async def test_users_info_maps_models_and_empty_result() -> None:
    database = Kover(pool=MagicMock(spec=ConnectionPool)).get_database("test")
    command = AsyncMock(
        return_value={
            "users": [
                {
                    "userId": Binary(b"id"),
                    "user": "user",
                    "db": "test",
                    "mechanisms": ["SCRAM-SHA-256"],
                    "roles": [],
                },
            ],
        },
    )
    database.command = command
    users = await database.users_info()
    assert users[0].username == "user"
    assert users[0].db_name == "test"
    assert command.await_args is not None
    assert command.await_args.args[0]["usersInfo"] == 1
    command.return_value = {"users": []}
    assert await database.users_info("missing") == []
    assert command.await_args is not None
    assert command.await_args.args[0]["usersInfo"] == "missing"
