# ptouch-mcp

[![CI](https://github.com/jacobhaynes/ptouch-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jacobhaynes/ptouch-mcp/actions/workflows/ci.yml)

Print labels on a Brother P-touch tape printer by asking for them.

```
"print a label that says Bolts & Fasteners"
"print 2 of these for my boxes"
```

A small container that exposes one P-touch printer over **HTTP** and over **MCP**
(Streamable HTTP), so an LLM assistant, a Home Assistant automation, or `curl` can all
drive it.

Text is rendered with Pillow and sent to the printer by the
[`ptouch`](https://github.com/nbuchwitz/ptouch) library over USB or raw TCP. No CUPS, no
Brother driver, no print queue.

> **Status: everything but the last inch is verified.** CI builds the image, starts it,
> and checks that it serves — status, a two-copy print, and a preview of the right
> height. What has *not* been confirmed is the final USB write to a real PT-P710BT and
> tape coming out of the machine. Treat the hardware path as unproven until someone
> reports otherwise.

## What it does

- Sizes the type automatically to fill the tape — one line prints tall, three lines
  print small, the way the handheld units behave.
- Renders a **preview** so you can look at a label before spending tape.
- Prints *n* separate labels, each cut individually, rather than one chained strip.
- Sizes to the printer's real **print pin count**, not the nominal tape width. On a
  PT-P710BT, 12 mm tape prints 70 dots tall, not 76 — the edge pins do not fire.

## Quick start

```bash
docker compose up -d
curl -X POST localhost:8080/print -H 'Content-Type: application/json' \
     -d '{"text": "Garage", "copies": 2}'
```

With no printer attached, set `PTOUCH_BACKEND=dry` and every label is written to a PNG
instead of being printed. The whole stack runs that way — useful on a Mac, where Docker
cannot pass through USB at all.

## HTTP API

| Method | Path | Body / notes |
| --- | --- | --- |
| `POST` | `/print` | `{"text": "...", "copies": 1, "tape_mm": null, "align": "center"}` |
| `POST` | `/preview` | Same body. Returns `image/png`; prints nothing. |
| `GET` | `/status` | Printer reachable, model, tape widths it accepts. |
| `GET` | `/healthz` | Liveness. |

`text` may contain newlines for multi-line labels.

## MCP

Streamable HTTP at **`/mcp`**, three tools: `print_label`, `preview_label`,
`printer_status`.

```bash
claude mcp add --transport http ptouch http://your-server:8080/mcp
```

The tool schemas total **under 200 tokens**. That matters more than it looks: an MCP
client resends every tool's schema on every request, so a chatty server is a per-message
tax. Wired into a voice assistant, this will not be the expensive part.

## Home Assistant

Expose it to Assist — and so to a voice satellite — with a `rest_command` and a script:

```yaml
rest_command:
  print_label:
    url: "http://your-server:8080/print"
    method: POST
    content_type: "application/json"
    payload: '{"text": "{{ text }}", "copies": {{ copies | default(1) | int }}}'

script:
  print_label:
    alias: Print a label
    fields:
      text:   { description: "The text to print on the label", example: "Garage" }
      copies: { description: "How many copies", example: 2, selector: { number: { min: 1, max: 20 } } }
    sequence:
      - action: rest_command.print_label
        data:
          text: "{{ text }}"
          copies: "{{ copies | default(1) }}"
```

Expose the script under **Settings → Voice assistants → Expose**. Nothing is exposed by
default, which is the usual reason a working setup says it cannot find something.

## Configuration

All via environment; see [`.env.example`](.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `PTOUCH_BACKEND` | `hardware` | `hardware` prints; `dry` writes a PNG and prints nothing. |
| `PTOUCH_TRANSPORT` | `usb` | `usb`, or `network` for raw port 9100. |
| `PTOUCH_MODEL` | `PT-P710BT` | See supported printers below. |
| `PTOUCH_HOST_ADDR` | — | Printer address, for `network` transport. |
| `PTOUCH_TAPE_MM` | `24` | Tape width assumed when a request omits one. |
| `PTOUCH_MARGIN_MM` | `3` | Blank tape before and after each label. |
| `PTOUCH_FONT` | — | Path to a `.ttf`. Defaults to DejaVu Sans Bold, then Arial Bold. |
| `PTOUCH_MAX_COPIES` | `20` | Ceiling on a single request. |
| `PTOUCH_MAX_TEXT` | `200` | Ceiling on label text length. |
| `PTOUCH_PORT` | `8080` | Listen port. |

## Supported printers

`PT-P710BT`, `PT-E550W`, `PT-P750W`, `PT-P900`, `PT-P900W`, `PT-P910BT`, `PT-P950NW` —
whatever the underlying library supports. Tape widths come from each printer's own pin
configuration, so asking for a width a given model cannot take is rejected with the list
it can.

## USB access

The compose file hands in the USB bus rather than a fixed device node:

```yaml
volumes:
  - /dev/bus/usb:/dev/bus/usb
device_cgroup_rules:
  - 'c 189:* rmw'
```

This survives unplugging and replugging the printer, which a `devices:` entry does not —
the node is recreated with a new number and the old mapping goes stale. It also avoids
needing a udev rule on the host, which matters if you cannot get root
non-interactively.

**Docker Desktop on macOS and Windows cannot pass through USB.** On macOS the kernel
also claims printer-class devices, so libusb cannot take them even outside a container.
Run this on Linux, or run it in dry mode.

## A note on the dependency pin

`ptouch` is pinned to a git commit rather than a PyPI version. PT-P710BT support is on
the library's `main` branch but is not in the 1.1.0 release from February 2026. Move to
a released version once one ships with `PTP710BT`.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
PTOUCH_BACKEND=dry .venv/bin/python -m pytest
PTOUCH_BACKEND=dry .venv/bin/python -m ptouch_mcp
```

## Prior art

- [nbuchwitz/ptouch](https://github.com/nbuchwitz/ptouch) — the Python library doing the
  actual printing here.
- [`ptouch-print`](https://dominic.familie-radermacher.ch/projekte/ptouch-print/) —
  Dominic Radermacher's C utility, the long-standing Linux option.
- [JesperKock/ptouch-print-service](https://github.com/JesperKock/ptouch-print-service) —
  a Go HTTP wrapper around that binary.
- [robby-cornelissen/pt-p710bt-label-maker](https://github.com/robby-cornelissen/pt-p710bt-label-maker) —
  a PT-P710BT driver in Python, including the Bluetooth path.
- [danielrosehill/Label-Printing-Resources](https://github.com/danielrosehill/Label-Printing-Resources) —
  a broad index of label-printer tooling on Linux.

## License

MIT
