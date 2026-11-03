from unittest.mock import patch

import pytest

from kover.network import compressors


def test_zlib_context_roundtrip_and_cache() -> None:
    context = compressors.get_context_by_id(2)
    assert compressors.get_context_by_id(2) is context
    data = b"compressible" * 100
    assert context.decompress(context.compress(data)) == data


@pytest.mark.parametrize(("identifier", "availability", "extra"), [
    (1, "_HAVE_SNAPPY", "snappy"), (3, "_HAVE_ZSTD", "zstd"),
])
def test_missing_optional_compressor_has_install_hint(
    identifier: int, availability: str, extra: str,
) -> None:
    compressors.get_context_by_id.cache_clear()
    try:
        with (
            patch.object(compressors, availability, new=False),
            pytest.raises(ModuleNotFoundError, match=rf"kover\[{extra}\]"),
        ):
            compressors.get_context_by_id(identifier)
    finally:
        compressors.get_context_by_id.cache_clear()
