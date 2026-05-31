# Red adversary level instructions

Scope: all adversary-level plan files and generated-spec notes under `red/adversary_levels/`.

- Treat `red/build_merchant_agent.md` as the base merchant creation contract. Do not invent a separate merchant creation workflow.
- Create generated merchant data outside the repository, preferably under `/tmp/trust-agentic-commerce-merchants/<run-id>/<level>/<merchant-slug>/`.
- Use one unique `--out` directory per merchant. The generator intentionally refuses to write into an existing directory to avoid concurrent clobbering.
- Preserve each merchant's `temp_files_manifest.json`; future agents must inspect manifests before reading generated merchant data.
- Level-specific `AGENTS.md` files define adversarial mutations. Apply those mutations only to generated temp files unless explicitly asked to change repository fixtures.
- If a level needs multiple merchants, create one base merchant per unique output directory and record cross-merchant relationships in a sidecar file in the run root.
