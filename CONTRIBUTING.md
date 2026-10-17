# Contributing

Use Python 3.11/3.12 in a virtual environment and install with `python -m pip install -c requirements-demo.txt -e ".[dev]"`. Run `ruff check .`, `python -m pytest`, the demo command from README and `python -m build` before proposing a change.

Keep reusable logic in src/transit_demand. Add meaningful tests for changed data semantics, availability cutoffs, missingness or aggregation. Explain changed behavior and validation in the pull request. Clearly distinguish implemented functionality from roadmap items.

Use reviewed synthetic fixtures only. Do not include real observations, credentials, internal documents or third-party code without rights. Review docs/data-governance.md and staged content before every push. No open-source license is assigned to this snapshot; contributors must clarify permissions before contributing substantive code.
