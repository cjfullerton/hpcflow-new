# Make sure we ran `poetry install --extras=pyinstaller` (or `poetry install --no-dev --extras "pyinstaller"`)
rm -r build
rm -r dist
rm hpcflow.spec
poetry run pyinstaller --name=hpcflow --onefile ../hpcflow/cli/__init__.py 
