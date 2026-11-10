# Testing the quality candidate

Primary verification uses Python 3.13 and Qt5. Install test tools through the
declared requirements, without changing Krita's bundled Python environment:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-test.txt python scripts/test.py --suite unit --locale both
uv run --no-project --python 3.13 --with-requirements requirements-test.txt python scripts/test.py --suite host --locale both --krita-root <installed-krita>
uv run --no-project --python 3.13 --with-requirements requirements-test.txt python scripts/test.py --suite native --krita-root <installed-krita> --model <BiRefNet-lite-F16.gguf>
```

`unit` runs ordinary Python/Qt tests. `host` is explicitly an **offline** check
against the installed Qt bindings with isolated/mock host APIs. It is not a
running Krita session. `native` compiles actual algorithms and links current
production objects against the installed Krita libraries. It also executes
the Vulkan worker on an available GPU. AI inference requires an explicit model;
without it that case is skipped, not passed. `experimental` contains unregistered
Relight research and is not production filter coverage.

XML, text logs and machine-readable summaries are written below
`build/test-results/`. Missing entire environments return an unavailable status
and a nonzero exit; skipped cases remain visible in XML and summaries.

Additional checks include corrupt/changed build batches, partial publication,
worker protocol faults, cancellation during pipe backpressure, network deadlines,
parent/child process cleanup, and asset rename/move/scroll/selection preservation.
Shader and metadata checks can be run independently:

```powershell
python scripts/generate_filter_metadata.py --check
python native/fx/compile_shaders.py --all --check
```

## Live host boundary

The live probe is `scripts/host_acceptance.py`, with its temporary plugin in
`tests/quality_host_probe.py`. It must run in an independently isolated Krita
profile. A private executable path is not sufficient: on the tested Windows Qt5
build, Windows Known Folders ignore the APPDATA/LOCALAPPDATA environment overrides.
The first attempt did not load the probe and was stopped. The normal kritarc,
display configuration and shortcut file retained their pre-attempt modification
times. The launcher now rejects that environment before starting a GUI process.

Live preview/apply parity, undo/redo, reopened native parameters, canvas insertion,
and live search panel integration therefore remain **unverified**, not failed
product behavior. Version 0.1.8 is prepared for user testing; automated results
do not certify the live installation. Run the live probe in a separate OS user/test environment, then record
the result against the candidate batch. External search providers and attached
browser sessions require a separate manual smoke check; local network fault
tests do not prove provider availability.

## Test discipline

The original source/binary snapshot is preserved under `build/quality-baseline/`.
U8 compatibility uses byte comparisons; expected Vibrance skin and Temperature
Tint corrections are recorded separately. Float tests use absolute/relative
tolerances, gradient-level counts, transparent pixels and signed/HDR ranges.
An emitted PNG is only a display preview: raw numeric fixtures remain authoritative
for float/HDR assertions. Performance reports state fixture, hardware, sample
count, and cold-cache meaning. Do not rerun broad suites after a pass unless a
new change or unresolved result justifies it.
