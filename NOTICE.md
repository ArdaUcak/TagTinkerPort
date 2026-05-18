# Attribution

This project is a Raspberry Pi port of **TagTinker** by [i12bp8](https://github.com/i12bp8).

- Upstream project: https://github.com/i12bp8/TagTinker
- Upstream license: GPL-3.0-only

The ESL wire protocol implementation (`tagtinker/proto.py`, `tagtinker/profiles.py`)
and the PP4 carrier/symbol timing in `tagtinker/ir.py` are direct ports of the C
source files in the upstream repository. The pigpio-specific GPIO handling and the
Pillow-based rendering layer are new.

Upstream also acknowledges furrtek's reverse-engineering of the ESL protocols and
the PrecIR implementation; this port stands on that work too.

Per GPL-3.0, this port is also licensed GPL-3.0-only — see [`LICENSE`](LICENSE).
