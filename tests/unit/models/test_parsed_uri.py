from typing import Any

from pydantic import ValidationError
import pytest

from kover.models.parsed_uri import ParsedUri


@pytest.mark.parametrize(
    "mechanism",
    ["MONGODB-X509", "MONGODB-AWS", "GSSAPI", "MONGODB-OIDC"],
)
@pytest.mark.parametrize("username", [None, "user"])
@pytest.mark.parametrize("database", [None, "shop"])
def test_external_mechanisms_reject_non_external_auth_source(
    mechanism: str,
    username: str | None,
    database: str | None,
) -> None:
    with pytest.raises(ValidationError, match=r"authSource=\$external") as exc:
        ParsedUri(
            nodelist=[("localhost", 27017)],
            username=username,
            password=None,
            database=database,
            collection=None,
            options={"authMechanism": mechanism, "authSource": "admin"},
            fqdn=None,
        )
    assert exc.value.errors()[0]["loc"] == ("options",)


@pytest.mark.parametrize(
    ("options", "database", "auth_database"),
    [
        ({}, None, "admin"),
        ({}, "shop", "shop"),
        ({"authSource": "users"}, "shop", "users"),
        ({"authMechanism": "PLAIN"}, None, "$external"),
        ({"authMechanism": "PLAIN"}, "shop", "shop"),
        ({"authMechanism": "PLAIN", "authSource": "users"}, None, "users"),
        *[
            (options, "shop", "$external")
            for mechanism in (
                "MONGODB-X509",
                "MONGODB-AWS",
                "GSSAPI",
                "MONGODB-OIDC",
            )
            for options in (
                {"authMechanism": mechanism},
                {"authMechanism": mechanism, "authSource": "$external"},
            )
        ],
    ],
)
def test_auth_database_validation_preserves_fields(
    options: dict[str, Any],
    database: str | None,
    auth_database: str,
) -> None:
    parsed = ParsedUri(
        nodelist=[("localhost", 27017)],
        username="user",
        password=None,
        database=database,
        collection=None,
        options=options,
        fqdn=None,
    )
    assert parsed.database == database
    assert parsed.options == options
    assert parsed.credentials is not None
    assert parsed.credentials.auth_database == auth_database
