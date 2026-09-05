## Per arm, wall clock launch -> terminal status (client side, ms)

| arm | n | mean | median | min | max | stdev |
| --- | --- | --- | --- | --- | --- | --- |
| on | 20 | 6124.1 | 6124.0 | 6092.2 | 6156.0 | 14.9 |
| off | 20 | 6125.7 | 6118.9 | 6070.6 | 6177.5 | 27.8 |
| bh (extra) | 5 | 6106.5 | 6116.5 | 6078.0 | 6123.5 | 19.5 |
| off, bh session control | 5 | 6117.0 | 6118.9 | 6062.4 | 6150.5 | 35.8 |

## The delta

| quantity | value |
| --- | --- |
| mean(on) - mean(off) | -1.66 ms (-0.027 % of the off mean) |
| median(on) - median(off) | +5.12 ms (+0.084 %) |
| standard error of that delta | 7.06 ms |
| Welch t / df | -0.24 / 29.1 |
| 95 % interval on the mean delta | -15.50 .. +12.17 ms |
| stdev of the on arm / the off arm | 14.9 ms / 27.8 ms |

Extra arm: mean(bh) - mean(off control) = -10.48 ms (SE 18.25 ms, Welch t = -0.57).

## The exporter's own counters, per run (from the summary line)

| arm | summary lines | frames_enqueued | frames_dropped | observations_sent | http_errors | enqueue p50 us, median (range) | enqueue p95 us, median (range) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| on | 20/20 | 96-97 | 0 | 41-41 | 0 | 1.5 (0-3) | 5 (2-12) |
| bh (extra) | 3/5 | 96-97 | 0 | 41-41 | 20 | 2 (1-2) | 7 (3-10) |

## What the app did, per arm - the E2 half of this measurement

| arm | runs | status | app frames | app frames dropped | calls | tokens |
| --- | --- | --- | --- | --- | --- | --- |
| on | 20 | completed | 96-97 | 0 | 6 | 4337 |
| off | 20 | completed | 96-97 | 0 | 6 | 4337 |
| bh (extra) | 5 | completed | 96-97 | 0 | 6 | 4337 |
| off control | 5 | completed | 96-97 | 0 | 6 | 4337 |

## Every run

| set | arm | block | # | run_id | status | wall ms | app frames | enqueued | dropped | sent | http_err | p50 us | p95 us |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | on | 1 | 1 | 347ffecc-96cc-4bca-b979-bb28977f4c68 | completed | 6138.4 | 96 | 96 | 0 | 41 | 0 | 2 | 7 |
| main | on | 1 | 2 | 798c4f4b-8a4e-4c9d-8fb9-f1d33ae60741 | completed | 6126.8 | 96 | 96 | 0 | 41 | 0 | 0 | 4 |
| main | on | 1 | 3 | b3a3036b-d9a7-4902-9d90-132ec55c2ebc | completed | 6121.1 | 97 | 97 | 0 | 41 | 0 | 0 | 5 |
| main | on | 1 | 4 | 2925dbec-f4cf-4906-8184-a52242c7206d | completed | 6092.2 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 1 | 5 | 6dd5692f-79f8-48e9-9ac5-72f5eec3e66f | completed | 6133.6 | 97 | 97 | 0 | 41 | 0 | 2 | 5 |
| main | off | 2 | 1 | ba5fa675-6e24-4573-8b57-04edf3bfad62 | completed | 6171.1 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 2 | 9c18f493-4180-4273-b339-600e9f922285 | completed | 6114.9 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 3 | fa4e28ac-3070-4a17-a5a5-d87015fc48b3 | completed | 6137.9 | 97 | - | - | - | - | not found | not found |
| main | off | 2 | 4 | 72aa470e-2c50-4ca7-9004-f4580429619f | completed | 6108.5 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 5 | 028dcd2e-071a-490c-8a90-01754eb0d592 | completed | 6088.9 | 97 | - | - | - | - | not found | not found |
| main | off | 3 | 1 | 61828dc4-d428-4f8c-b732-34f97f11f3ca | completed | 6177.5 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 2 | 0a1c339f-debe-4bc2-a864-422268ba1690 | completed | 6116.9 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 3 | 144c491a-937a-4de9-9d59-c17ca1a8d7e5 | completed | 6070.6 | 97 | - | - | - | - | not found | not found |
| main | off | 3 | 4 | 59eaf720-40c9-4c18-b565-b44158aaa2fa | completed | 6130.6 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 5 | f1bc6fa1-fc5a-4222-9947-4255f56ed4e0 | completed | 6140.7 | 97 | - | - | - | - | not found | not found |
| main | on | 4 | 1 | f0a295f0-0342-4c46-8221-f855886f23b0 | completed | 6156.0 | 96 | 96 | 0 | 41 | 0 | 1 | 6 |
| main | on | 4 | 2 | 0e81928d-5b6a-479b-b3b0-c12e55989702 | completed | 6118.0 | 96 | 96 | 0 | 41 | 0 | 2 | 5 |
| main | on | 4 | 3 | 064d0420-9cb3-41ce-a90a-9e19a7ea44ea | completed | 6137.0 | 97 | 97 | 0 | 41 | 0 | 2 | 5 |
| main | on | 4 | 4 | 6fb3413c-99c0-4473-b070-968751b62431 | completed | 6134.9 | 96 | 96 | 0 | 41 | 0 | 3 | 8 |
| main | on | 4 | 5 | 592afd43-6dd8-4496-8fc2-6ad2cc3ff9dd | completed | 6117.2 | 97 | 97 | 0 | 41 | 0 | 2 | 7 |
| main | on | 5 | 1 | 6ff0ddff-61fb-4ef6-af61-228c69c2bb8f | completed | 6097.9 | 96 | 96 | 0 | 41 | 0 | 1 | 2 |
| main | on | 5 | 2 | f51ba6c1-f82e-4bb8-b191-a1fe4bc28cc3 | completed | 6139.4 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 3 | cf045557-3113-41c1-a17d-f1f17750d7de | completed | 6116.3 | 97 | 97 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 4 | 83513496-e4c6-4765-8bd1-71184d8be747 | completed | 6115.3 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 5 | 3fb44755-f608-4210-8400-e518887edb84 | completed | 6121.8 | 97 | 97 | 0 | 41 | 0 | 0 | 2 |
| main | off | 6 | 1 | 06adb60c-3fa4-4726-a69c-7110fa4dbb2d | completed | 6163.3 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 2 | 7b55e756-02d7-44d4-8970-aa29431ff798 | completed | 6115.3 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 3 | cbc39284-14ac-4d30-8a12-8a20a83cc412 | completed | 6131.8 | 97 | - | - | - | - | not found | not found |
| main | off | 6 | 4 | 6e0ab1fd-7e62-4600-b7b7-1dc4218daf7a | completed | 6137.1 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 5 | a5a735e1-122f-41fd-bb59-b0f10fe5b607 | completed | 6108.4 | 97 | - | - | - | - | not found | not found |
| main | off | 7 | 1 | c034d8c4-ffb5-475b-943e-be2fc962b65f | completed | 6161.7 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 2 | 096434fe-5367-4893-bac4-9ee50018533b | completed | 6118.3 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 3 | af38e9ca-553d-40fd-9c04-d5495a94c47b | completed | 6095.9 | 97 | - | - | - | - | not found | not found |
| main | off | 7 | 4 | bb268de9-9dac-4b7a-83e1-16bf5cd36ed2 | completed | 6119.5 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 5 | e1aa348f-5e75-4ceb-bfbc-728df3f2a571 | completed | 6105.8 | 97 | - | - | - | - | not found | not found |
| main | on | 8 | 1 | 7ce96766-0f03-460f-bc79-7e51c91fb8a9 | completed | 6134.8 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 8 | 2 | 456a84bc-75c7-4d67-a73b-b25cd13fb3e3 | completed | 6126.2 | 96 | 96 | 0 | 41 | 0 | 2 | 5 |
| main | on | 8 | 3 | b2686d21-5674-405d-bef8-31737c60ce8e | completed | 6130.6 | 97 | 97 | 0 | 41 | 0 | 3 | 12 |
| main | on | 8 | 4 | 31c339b4-d887-4399-80db-13e8207f463b | completed | 6115.5 | 96 | 96 | 0 | 41 | 0 | 2 | 7 |
| main | on | 8 | 5 | 2b22e3e0-eb5c-4997-a6ab-092d32b8c30f | completed | 6108.8 | 97 | 97 | 0 | 41 | 0 | 2 | 7 |
| blackhole | bh | 1 | 1 | 8a28d64c-c216-40a5-9b91-0789a279183e | completed | 6123.5 | 96 | 96 | 0 | 41 | 6 | 2 | 7 |
| blackhole | bh | 1 | 2 | 1f84825e-6bcd-46b2-8271-75ff01198a14 | completed | 6094.7 | 96 | 96 | 0 | 41 | 8 | 1 | 10 |
| blackhole | bh | 1 | 3 | 10274c2f-0fbf-4dc2-bc09-0d9c0806ad4a | completed | 6116.5 | 97 | 97 | 0 | 41 | 6 | 2 | 3 |
| blackhole | bh | 1 | 4 | 196bcad5-2331-4ecb-8251-736038b65745 | completed | 6119.9 | 96 | - | - | - | - | not found | not found |
| blackhole | bh | 1 | 5 | 4476d6cb-b4bf-40e9-a77d-8ebbf15df9ac | completed | 6078.0 | 97 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 1 | 4781791e-3c8a-4440-a4a2-18e88c0d8bfe | completed | 6147.1 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 2 | 6d51aa74-cfe0-4ae7-8ecd-96a4584fee7f | completed | 6062.4 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 3 | fec7ae54-9a85-4bc9-99ab-167c346e4d13 | completed | 6106.1 | 97 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 4 | 7d7bcdf9-77a3-4edc-9a87-70553d900d21 | completed | 6150.5 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 5 | 08573c9a-b7df-4dec-8e5c-247647ca3dba | completed | 6118.9 | 97 | - | - | - | - | not found | not found |

## Confirmation pass, re-run against a later working tree

| arm | n | mean | median | min | max | stdev |
| --- | --- | --- | --- | --- | --- | --- |
| on | 10 | 6077.3 | 6069.1 | 6052.4 | 6133.3 | 25.1 |
| off | 10 | 6084.2 | 6077.8 | 6052.0 | 6153.3 | 30.0 |

mean(on) - mean(off) = -6.93 ms (-0.114 %), SE 12.36 ms, Welch t = -0.56, 95 % interval -31.16 .. +17.30 ms.

Enqueue latency, on arm: p50 median 0 us (range 0-1), p95 median 2.5 us (range 1-6), from 10/10 summary lines. Statuses: completed; app frames dropped 0.

## Process boot, per block (not per run - a one-off cost)

| block | arm | boot s | /readyz exporter | reason | environment | capture_content |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | on | 3.63 | enabled | - | synthetic | False |
| 2 | off | 3.08 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 3 | off | 3.08 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 4 | on | 3.61 | enabled | - | synthetic | False |
| 5 | on | 3.62 | enabled | - | synthetic | False |
| 6 | off | 3.10 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 7 | off | 3.12 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 8 | on | 3.63 | enabled | - | synthetic | False |
| 1 | bh | 3.66 | enabled | - | synthetic | False |
| 2 | off | 3.09 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 1 | on (confirm) | 3.67 | enabled | - | synthetic | False |
| 2 | off (confirm) | 3.11 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 3 | off (confirm) | 3.09 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 4 | on (confirm) | 3.59 | enabled | - | synthetic | False |

Boot, on arm mean 3.62 s; off arm mean 3.10 s; difference +526 ms, paid once per process.
