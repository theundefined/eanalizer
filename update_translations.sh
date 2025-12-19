#!/bin/bash
# This script updates the translation files.

# Ensure the script is run from the project root
cd "$(dirname "$0")"/.. || exit

# Activate virtual environment if needed
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    else
        echo "Error: Virtual environment not found." >&2
        exit 1
    fi
fi

echo "Extracting strings from source code..."
pybabel extract -F babel.cfg -o locales/eanalizer.pot .
if [ $? -ne 0 ]; then
    echo "Error: Failed to extract strings." >&2
    exit 1
fi

echo "Updating Polish translation file..."
pybabel update -i locales/eanalizer.pot -d locales -l pl --domain eanalizer
if [ $? -ne 0 ]; then
    echo "Error: Failed to update translation file." >&2
    exit 1
fi

echo -e "\nTranslation files updated successfully."
echo "You can now run 'python scripts/translate.py' to apply automatic translations from the dictionary."
echo "After that, manually check the .po file for any remaining untranslated strings."
