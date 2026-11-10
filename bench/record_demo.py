"""Record actual demo stdout and render a time-compressed terminal GIF."""

import json
import os
import subprocess
import sys
import textwrap
import time

from PIL import Image, ImageDraw, ImageFont

from bench.common import ROOT


def main():
    target = ROOT / "bench/results"
    target.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    events = []
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "bench.demo"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdout is not None
    for line in process.stdout:
        events.append({"seconds": time.monotonic() - started, "text": line.rstrip()})
        print(line, end="", flush=True)
    code = process.wait()
    elapsed = time.monotonic() - started
    (target / "demo-recording.json").write_text(
        json.dumps({"elapsed_s": elapsed, "exit_code": code, "events": events}, indent=2),
        encoding="utf-8",
    )
    if code:
        raise SystemExit(code)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 19)
    except OSError:
        font = ImageFont.load_default(size=19)
    frames, lines = [], ["$ python -m bench.demo"]
    for event in events:
        lines.extend(textwrap.wrap(f"[{event['seconds']:6.2f}s] {event['text']}", width=100))
        frame = Image.new("RGB", (1240, 600), "#0b1220")
        draw = ImageDraw.Draw(frame)
        draw.text((28, 20), "RelayQueue | actual local execution", font=font, fill="#67e8c4")
        draw.text(
            (28, 52),
            f"{elapsed:.1f}s recording compressed to 20s | timestamps show real elapsed time",
            font=font,
            fill="#9baec7",
        )
        draw.multiline_text((28, 104), "\n".join(lines[-18:]), font=font, fill="#e2e8f0", spacing=6)
        frames.append(frame)
    # Preserve time ordering; keep the verified final result visible for three seconds.
    spans = [
        events[index + 1]["seconds"] - event["seconds"] for index, event in enumerate(events[:-1])
    ]
    total = sum(spans) or 1
    durations = [max(100, round(span / total * 17000 / 10) * 10) for span in spans]
    durations.append(max(1000, 20000 - sum(durations)))
    frames[0].save(
        target / "demo.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0
    )


if __name__ == "__main__":
    main()
