# Report Hours Generator

This repo contains a small script that creates a `Report` folder and calculates how many hours you have worked based on task descriptions.

## How it works
- Each task line can include time markers like `2h`, `1.5 hours`, or `30m`.
- The script totals all the time markers found across the task file.
- A `Report/summary.md` file is generated with per-task hours and the total.

## Usage
```bash
python3 report_hours.py tasks.txt
```

You can also change the output directory:
```bash
python3 report_hours.py tasks.txt --report-dir Report
```

## Example task file
See `tasks.txt` for a starter format.
