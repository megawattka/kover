import typing
import unittest

from pydantic import create_model

from kover.schema import Document, SchemaGenerator


class AnnotationTests(unittest.TestCase):
    @staticmethod
    def test_schema_supports_both_python_union_representations() -> None:
        typing_union = create_model(
            "TypingUnion", __base__=Document,
            value=(typing.Union[str, int, None], ...),  # ruff: ignore[non-pep604-annotation-union]
        )
        modern = create_model(
            "Modern", __base__=Document, value=(str | int | None, ...),
        )
        generator = SchemaGenerator()
        assert generator.generate(typing_union) == generator.generate(modern)


if __name__ == "__main__":
    unittest.main()
