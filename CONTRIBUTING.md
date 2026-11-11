# Development

Use these commands at the root of the repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src tests examples
.venv/bin/python -m ruff format --check src tests examples
.venv/bin/python -m pytest -q --cov=runlog --cov-report=term-missing --cov-fail-under=85
```

Ruff controls the code format and import order. It uses a line length of 100 characters and Python 3.11 syntax.
To change the format, use this command:

```bash
.venv/bin/python -m ruff format src tests examples
```

Keep the Ruff version the same in the development dependencies and CI.

For the MySQL integration test, set `RUNLOG_TEST_MYSQL_URL` to a disposable database.
The test replaces the catalog tables in that database.

For each bug fix, add a regression test.
If you change a check or tag rule, update its description. Then make the validation report again:

```bash
.venv/bin/python examples/validate_checks.py
```

Save generated data in the ignored `examples/output/` directory.
Keep private data and local planning or review notes outside the repository.

## English text

Use [ASD-STE100 Issue 9](https://www.asd-ste100.org/) as the reference for English text.

- Use short, complete sentences and the active voice.
- Use a maximum of 20 words in each instruction. Use a maximum of 25 words in each descriptive sentence.
- Give one instruction in each sentence. Give one topic in each paragraph.
- Use one technical term for each concept. Keep command names and code identifiers unchanged.

Use these project terms consistently:

| Term | Meaning |
|---|---|
| record | One time-series log with its metadata |
| sidecar | A JSON file that accompanies a record |
| catalog | The SQLite index of records and analysis results |
| check | A quality rule or its result |
| tag | An interval label such as `quiet` or `steady` |

Use `check` as a noun. Write “do a check” for the action.
Software operations and mathematical methods can use their established technical terms.

## Distributions

Use these commands:

```bash
.venv/bin/python -m pip install build twine
.venv/bin/python -m build
.venv/bin/python -m twine check --strict dist/*
```

The source distribution contains tests, examples, and documentation.
The wheel contains the runtime package, CLI, and license.
Examine both archives. Test the installed wheel outside the source directory.
CI also does this installation test.
