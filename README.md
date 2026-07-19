# Cisco RoomOS for Home Assistant

A Home Assistant custom integration for Cisco Webex Room / Board / Desk devices
running RoomOS (Collaboration Endpoint software). It connects over the
device's WebSocket xAPI for a persistent, push-based session — no polling —
so state changes (calls ringing, volume changes, standby, presentation
sharing) are reflected in Home Assistant immediately.

> **Status:** first pass / initial release. Core power, calling, and content
> sharing features are implemented; see [Roadmap](#roadmap) for what's next.

## How it works

RoomOS devices expose their xAPI (the same command/status tree used by
`xCommand`/`xStatus`/`xConfiguration` over SSH or HTTP) on a WebSocket
endpoint at `wss://<device>/ws`, using JSON-RPC 2.0 messages. This
integration:

- Opens a single authenticated WebSocket connection per device and keeps it
  open, automatically reconnecting with backoff if it drops.
- Authenticates with HTTP Basic Auth (username/password) on the WebSocket
  handshake — the same local user account you'd use to SSH into the device.
- Subscribes to the entire `Status` feedback tree once (`xFeedback/Subscribe`)
  and merges incoming `xFeedback/Event` notifications into a local cache, so
  every entity updates instantly instead of polling.

## Prerequisites

On the RoomOS device (via the web admin UI, Control Hub, or `xConfiguration`):

1. **HTTPS** must be enabled (`NetworkServices HTTPS Mode: On`, the default).
2. **The WebSocket service** must be enabled: `NetworkServices WebSocket:
   FollowHTTPService` (or `Enabled`) — this is the default on most RoomOS
   versions but is worth checking if the integration can't connect.
3. A **local user account** with the API/Integrator or Admin role, since the
   default `admin` account (or a dedicated integration user) needs permission
   to run xCommands.
4. Devices typically use a self-signed certificate out of the box, so
   **"Verify SSL certificate"** defaults to off in the config flow. Turn it on
   if you've installed a trusted certificate on the device.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories → add this repo URL, category
   "Integration".
2. Install "Cisco RoomOS", then restart Home Assistant.

### Manual

Copy `custom_components/cisco_roomos` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

Settings → Devices & Services → Add Integration → **Cisco RoomOS**, then
enter the device's host/IP, username, password, port (default `443`), and
whether to verify its TLS certificate.

## Entities

| Platform | Entity | Description |
|---|---|---|
| Button | Wake up | `xCommand Standby Deactivate` |
| Button | Standby | `xCommand Standby Activate` |
| Button | Answer call | Accept an incoming call |
| Button | Reject call | Reject an incoming call |
| Button | Hang up | Disconnect the active call(s) |
| Button | Share locally | Start presenting the selected source to the room screen only |
| Button | Share to call | Start presenting the selected source to the room screen *and* the far end |
| Button | Stop sharing | Stop any active presentation |
| Select | Share source | Picks which video input connector the two share buttons act on |
| Switch | Microphone mute | Mute/unmute the device's microphones |
| Number | Volume | Master volume, 0-100 |
| Sensor | Call status | `Idle`/`Ringing`/`Connecting`/`Connected`/... plus remote number, display name, direction, and duration as attributes |
| Sensor | Standby state | `Off`/`Standby`/`EnteringStandby`/`HalfWake` |
| Binary sensor | In call | On while any call is active |
| Binary sensor | Sharing content | On while a presentation is being shared |

## Services

For automations that need parameters the entities above don't expose:

| Service | Description |
|---|---|
| `cisco_roomos.dial` | Dial a number/SIP URI/Webex address, with an optional `protocol` |
| `cisco_roomos.hang_up` | Disconnect a call by `call_id`, or all calls if omitted |
| `cisco_roomos.answer` | Accept a specific incoming call by `call_id` |
| `cisco_roomos.reject` | Reject a specific incoming call by `call_id` |
| `cisco_roomos.send_dtmf` | Send DTMF `digits` on a call |
| `cisco_roomos.share_local` | Share a specific `connector_id` locally only |
| `cisco_roomos.share_remote` | Share a specific `connector_id` locally and to the call |
| `cisco_roomos.share_stop` | Stop sharing |

All services target the device's "Call status" sensor entity (or its device).

## Roadmap

Ideas for a future pass, not yet implemented:

- `media_player` entity for a more native "TV-like" dashboard card.
- Camera/self-view snapshot support.
- Configuration (not just status) feedback, e.g. surfacing device settings.
- Multi-call / conference roster detail beyond the primary call.
- Options flow for adjusting settings without deleting/re-adding the entry.

## Development

```bash
pip install websockets pytest
python3 -m pytest tests/
```

`custom_components/cisco_roomos/api.py` contains the WebSocket/JSON-RPC
client and has no Home Assistant dependency, so it can be unit tested in
isolation (see `tests/test_api.py`).
