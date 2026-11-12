# Quality performance evidence

These are offline production-code measurements on one workstation, not live Krita UI acceptance. The saved starting snapshot is the comparison baseline. All generated evidence remains under `build/test-results/`.

## Asset library

Fixture: 1000 mixed PNG/JPEG assets, two corrupt images, large 4K images and 120 nested directories; 800 x 600 offscreen Qt5 panel. Separate processes used the same fixture. Cold means empty application cache; the OS file cache was not forcibly cleared. Ten alternating directory switches were recorded.

| Metric | Before | After |
|---|---:|---:|
| Panel construction | 1381.8 ms | 68.6 ms |
| First visible folder | 296.4 ms | 122.9 ms |
| Directory switch median | 411.7 ms | 80.2 ms |
| Directory switch P95 | 654.0 ms | 141.0 ms |
| GUI heartbeat gap P95 | 551.3 ms | 12.2 ms |
| Peak process working set | 134.1 MiB | 55.1 MiB |

Ready means visible thumbnails, not all hidden assets. The new implementation intentionally defers offscreen decoding. P95 uses nearest-rank; nine switch samples mean P95 is the maximum. Timing/memory include fixture-specific Qt behaviour and should not be generalized to every storage device.

## Worker cache

GPU: NVIDIA GeForce RTX 5090. CPU: AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD. Same current production shaders were sent to preserved/current worker binaries; shader/binary hashes and per-request outputs are in `gpu-cache-benchmark.json`. All 32 alternating shader/size outputs were byte-identical. Seven warmed samples follow the first request for each size.

| Request | Before median / P95 | After median / P95 |
|---|---:|---:|
| pointwise-512 | 6.265 / 6.864 ms | 5.124 / 5.601 ms |
| motion-64 | 1.783 / 2.503 ms | 0.893 / 1.092 ms |
| pointwise-128 | 1.377 / 1.600 ms | 0.482 / 0.624 ms |
| pointwise-1024 | 24.064 / 25.275 ms | 21.691 / 21.887 ms |

Peak worker working set: 92.1 -> 91.9 MiB. Startup varied between runs; this single paired startup sample is not evidence of a startup speedup. The client now retires an idle worker after thirty seconds by default (`TFM_VULKAN_IDLE_MS`); the lifecycle fixture pins two seconds.

## Auto backend calibration

Actual U8 paint devices, standard sRGB, real filters/conversions/IPC, one CPU thread. Each row has three fresh-worker samples and twelve warmed samples. Values below are medians; all samples are retained in `backend-benchmark*/backend-benchmark.json`. CPU/GPU output maximum error was at most one U8 code value.

| Filter / side | CPU warm | GPU cold | GPU warm |
|---|---:|---:|---:|
| tfm_vibrance / 64 | 0.1 ms | 223.5 ms | 0.3 ms |
| tfm_vibrance / 2048 | 176.2 ms | 343.6 ms | 113.9 ms |
| tfm_color_temperature / 64 | 0.1 ms | 222.4 ms | 0.4 ms |
| tfm_color_temperature / 2048 | 82.1 ms | 341.8 ms | 113.1 ms |
| tfm_filmgrain / 64 | 0.0 ms | 234.9 ms | 0.4 ms |
| tfm_filmgrain / 2048 | 51.0 ms | 350.7 ms | 112.8 ms |
| tfm_vignette / 64 | 0.1 ms | 233.2 ms | 0.3 ms |
| tfm_vignette / 2048 | 81.4 ms | 342.0 ms | 114.2 ms |
| tfm_vibrance / 4096 | 653.7 ms | 666.3 ms | 437.7 ms |
| tfm_color_temperature / 4096 | 311.5 ms | 677.2 ms | 441.8 ms |
| tfm_filmgrain / 4096 | 197.9 ms | 662.2 ms | 442.5 ms |
| tfm_vignette / 4096 | 284.8 ms | 691.8 ms | 440.5 ms |
| tfm_vibrance / 5120 | 1069.2 ms | 923.7 ms | 716.5 ms |
| tfm_color_temperature / 5120 | 507.2 ms | 922.6 ms | 731.2 ms |
| tfm_filmgrain / 5120 | 333.1 ms | 943.6 ms | 724.3 ms |
| tfm_vignette / 5120 | 536.4 ms | 949.6 ms | 725.1 ms |

Production Auto/GPU policy prefers Vulkan for every supported filter; filters fall back to CPU when the worker rejects the job (unsupported depth, memory budget, missing device, etc.). The table above remains historical evidence of cold/warm crossover sizes and is not used as a runtime size gate. Explicit CPU still forces the CPU path.

Run `scripts/benchmark_assets.py`, `scripts/benchmark_gpu_worker.py`, and the compiled `native/fx/tests/benchmark_backend_native.cpp` to refresh evidence after relevant hardware or processing changes. The latter uses `TFM_BENCH_LARGE=1` for 4096 and `=2` for 5120.

## Final structure/scroll regression measurement

The asset column above uses `assets-final.json`, rerun after responsibility splits and scroll restoration. The earlier implementation checkpoint is retained in `assets-after.json`; the baseline is unchanged.

Colour-range mask was additionally calibrated with the same end-to-end method: CPU/GPU bytes were identical at all five sizes. CPU warm / GPU cold / GPU warm medians were 0.04 / 228.60 / 0.29 ms at 64, 56.35 / 335.65 / 114.17 ms at 2048, and 310.81 / 897.11 / 678.52 ms at 5120. Auto therefore retains CPU across the supported single-buffer U8 range; manual GPU remains available. See `backend-benchmark-mask*/backend-benchmark.json` for all samples.
