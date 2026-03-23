# Demo 01 - Basic EW log correlation

This scenario is a short passive ELINT capture from two ground sensors
(`SENSOR-A`, `SENSOR-B`) listening over roughly two minutes. The raw log
(`elint_log.csv`) interleaves detections from three real-world emitters plus
one stray one-off hit:

| Real emitter | Frequency      | Bearing | Notes                          |
|--------------|----------------|---------|--------------------------------|
| Marine radar | ~9410 MHz      | ~045    | recurs every few seconds       |
| Comms link   | ~2401 MHz      | ~120    | bursts clustered in time       |
| Weather radar| ~5610 MHz      | ~300    | crosses the 360/0 bearing seam |
| Stray hit    | ~1090 MHz      | ~210    | single uncorrelated detection  |

EWCORR groups detections that agree in **time + frequency + bearing**, so the
interleaved log should deinterleave back into the emitters above. The stray
1090 MHz hit stays a singleton (low confidence).

## Run it

```bash
# Human-readable table
python -m ewcorr correlate demos/01-basic/elint_log.csv

# JSON for piping into jq / a SIEM
python -m ewcorr correlate --format json demos/01-basic/elint_log.csv

# Only keep emitters seen at least twice (drop the stray)
python -m ewcorr correlate --min-hits 2 demos/01-basic/elint_log.csv
```

## Expected

Four clusters in the default run (three multi-hit emitters + one singleton);
three clusters with `--min-hits 2`. Exit code `0` when emitters are found,
`1` if correlation yields nothing.
