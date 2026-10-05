# Local workload measurements

Run these only on released hardware, against its currently resident model. The
runners refuse owner holds and check residency before each request. They do not
select models. Use the controller for an idle, reversible preset change first.

`run.py` measures streamed latency or generated invoice/frame vision fixtures;
`quality.py` exercises real two-step tool calls, OpenCode file edits, a disposable
BGE-M3/Chroma collection, or bounded long-context markers. `telemetry.py` records
memory, PSI, swap devices and NVIDIA VRAM when available. Output is JSON with
actual process arguments and token counts; responses and conversation text are
excluded. OpenCode's last synthetic fixture events go to a private /tmp file for
diagnosis. Coding evaluation runs bounded pure functions with restricted imports.

The legacy fixture label `latency-8k` is a name, not a measured token count. Its
current chat input measures 11,036 prompt tokens on the tested Qwen tokenizer;
compare the recorded usage, identical fixture version, decoding budget, repeat
count and load label. Five repetitions are initial measurements, not a broad
quality score. Shared-load results are not isolated hardware performance claims.

Examples (do not run Radeon while its user hold is present):

```bash
python3 benchmarks/run.py rtx5080 --base-url http://127.0.0.1:11435 --suite latency --repeat 5 --max-tokens 256 --output /tmp/result.json
python3 benchmarks/quality.py rtx5080 --base-url http://127.0.0.1:11435 --suite tools --output /tmp/tools.json
python3 benchmarks/telemetry.py --seconds 30 --output /tmp/memory.json
```

After authenticated admission activation, management benchmarking must target the
private owner backend with `LARIO_BENCHMARK_KEY`, while workload tests target the
public gate with their class credential. Never expose /running, /upstream or child
ports to consumers. Real boot and 30-minute mixed-load tests remain separate gates.
