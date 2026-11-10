# Candidate build, installation and rollback

This is the 0.1.8 build prepared for user testing. Live-host interaction acceptance
remains separate from the automated checks. Use the matching deployment record
to determine whether a particular installation has been updated.

## Build and verify

Run `python native/fx/build.py` with the configured Krita 5.3 Qt5 reference graph,
LLVM-MinGW, CMake, Ninja and glslang available. The build regenerates the canonical
filter metadata and all eight Vulkan shaders before compiling. The actual
vendored inference libraries are rebuilt in a private CMake tree. The selection
kernel is compiled in the same candidate batch as the DLL and worker.

`build/native-5.3/batches/<hash>/` is an immutable complete batch. `current.json`
is the last publication commit record. The familiar `bin/` files and top-level
`manifest.json` are compatibility mirrors. A build/worker failure retains the
previous complete batch; interrupted or modified mirrors cannot be packaged.
Manifest version 2 records source, generated files, shaders, linked library and
binary hashes plus compiler/tool versions. It contains relative paths.

Record the complete batch-bound report with:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-test.txt python scripts/validate_candidate.py --krita-root <installed-krita> --model <BiRefNet-lite-F16.gguf>
```

After the candidate validation report has been recorded, run
`python package_release.py --output <candidate.zip>`. Packaging rejects changed
inputs, missing/tampered binaries, invalid batch identity and incomplete
publication. The archive includes BUILD-MANIFEST.json, PACKAGE-MANIFEST.json,
validation results and dependency notices. Source files and generated outputs
must still match the build when packaging finishes.

Run `python scripts/validate_delivery.py <candidate.zip>` for full isolated staging,
injected rollback at the final native write, ZIP inventory/hash verification and
developer-path checks. It does not launch Krita or write to the daily installation.

## Isolated candidate installation

```powershell
python install_candidate.py <empty-resource-directory> --native-directory <empty-private-kritaplugins-directory>
```

Both directories must already exist. Existing program targets are never
overwritten. Every copy is hashed; a failure removes only the files/directories
created by this staging operation. Omitting `--native-directory` stages only
resource files for offline Python checks and is **not** full native acceptance.
All installation paths use the same program inventory as deployment/packaging.

The private native directory must belong to a separate test installation. On
Windows, separately verify that Krita's actual Known Folder configuration and
resource roots are isolated before launching. Environment variables alone were
insufficient on the tested installation; the live launcher now refuses this
unsafe setup.

## Rollback

For a disposable candidate installation, close its process and discard that
candidate directory after retaining the validation report. User assets, presets,
scripts, models and normal configuration must remain outside the disposable tree.

For a later authorized daily installation, close Krita, back up the **complete**
previous TFM program inventory and both native binaries before copying anything.
Restore that full program set together to roll back; do not mix an old DLL with a
new worker. Keep the existing `TFM/config.json`, `settings.json`, assets, models
and scripts. No user-data migration is introduced by this quality candidate.

If build publication is interrupted, the former `current.json` identifies the
previous intact batch. Rebuilding republishes complete mirrors. Do not manually
mark a mixed bin directory valid or bypass manifest checks.

## Diagnostics

Python failures use a bounded `tfm` log and recent-error buffer. Set `TFM_LOG_DIR`
to choose the diagnostic directory; otherwise logs reside under the local
application-data TFM/logs directory. Logs rotate at 1 MiB with two backups.
Optional host capabilities may degrade gracefully; save/export/execution and
configuration-recovery failures are recorded. Native processing reports explicit
backend fallback reasons and logs unsupported HDR profile conversions.

Worker deadlines default to 10 seconds for startup and 120 seconds for a request.
`TFM_VULKAN_STARTUP_TIMEOUT_MS` and `TFM_VULKAN_DISPATCH_TIMEOUT_MS` accept positive
millisecond overrides up to one hour. Cancellation does not restart CPU work.
The two-second worker idle retirement remains unchanged.
