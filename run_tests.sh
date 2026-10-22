echo "running ruff tests..."
ruff check

echo "running unittests..."
python3 -m unittest discover ./tests/unit
python3 -m unittest discover ./tests/integration