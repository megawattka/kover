# powershell run_tests.sh

echo "running ruff tests..."
ruff check --exclude ./kover/bson

echo "running unittests..."
python -m unittest discover ./tests --quiet
read