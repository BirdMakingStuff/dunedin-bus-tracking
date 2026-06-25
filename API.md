# Dunedin Bus Live-Tracking API — Reverse-Engineering Notes

## Overview

The Dunedin regional bus network (ORC / Orbus) uses a web timetable application
hosted at `https://orc.mattersoft.fi/timetable/`. The software is built by
**Mattersoft Oy**, a Finnish company that provides transit information systems
to transport authorities worldwide.

The front-end is an AngularJS single-page application with an OpenLayers map.
Real-time vehicle positions are streamed over a **WebSocket** connection, while
stop schedules, vehicle forecasts, and configuration are served via a **REST API**.


## Architecture

```
┌──────────────┐     REST/JSON      ┌──────────────────────────┐
│  Browser SPA │ ◄──────────────────►│  Mattersoft Backend      │
│  (AngularJS) │                    │  (Spring Boot / Java)     │
│              │     WebSocket      │                          │
│              │ ◄═════════════════►│  /websocket/all           │
└──────────────┘     (wss://)       └──────────────────────────┘
                                              │
                                              ▼
                                     ┌──────────────────┐
                                     │  GTFS / SIRI     │
                                     │  Vehicle tracking │
                                     │  feed from ORC    │
                                     └──────────────────┘
```

The URL path `/ps/rest/...` appears in error responses, suggesting a backend
context path of `/ps` behind a reverse proxy that rewrites `/timetable/...`.


## REST API Reference

Base URL: `https://orc.mattersoft.fi/timetable`

All endpoints return JSON. No authentication required.

### Configuration

| Endpoint | Description |
|----------|-------------|
| `GET /rest/applicationconfig` | App config: map center, zoom, colors, feature flags, WebSocket timeout |
| `GET /rest/servertime` | Server clock as `{ "serverTime": <epoch_ms> }` |

### Stops

| Endpoint | Description |
|----------|-------------|
| `GET /rest/stops` | All stops in the system (array of stop objects) |
| `GET /rest/stops/{code}` | Single stop by code (e.g. `59000232`) |
| `GET /rest/stops/searchbybbox?left=&top=&right=&bottom=` | Stops in a geographic bounding box (EPSG:4326) |
| `GET /rest/stops/searchbylocation` | Stops near a point (params unclear — not used by the map UI) |

**Bounding box parameters** (EPSG:4326 / WGS84):
- `left` = minimum longitude (west)
- `top` = maximum latitude (north)
- `right` = maximum longitude (east)
- `bottom` = minimum latitude (south)

**Stop object:**
```json
{
    "id": "59000232",
    "name": "Dundas St, 141",
    "code": "59000232",
    "location": { "latitude": -45.8629786, "longitude": 170.5200736 },
    "zone": "00_1",
    "platformCode": "",
    "parentStation": "",
    "station": false
}
```

Zones follow the pattern `XX_N` (e.g. `00_1`, `00_2D`) — the `00` prefix
appears to be the operator/network identifier.

### Schedules

| Endpoint | Description |
|----------|-------------|
| `GET /rest/currentstopschedule/{code}` | Today's scheduled departures grouped by hour |
| `GET /rest/stopschedule/{code}/?operatingDate=YYYY-MM-DD` | Schedule for a specific date |

The `departureTimes` object uses ISO-style hour keys like `"2026-06-25T06:00"`,
each containing an array of departures with `directionOfLine` and epoch-ms
`arrivalTime`/`departureTime`.

### Real-Time Stop Display

**`GET /rest/stopdisplays/{code}`**

This is the primary live-data endpoint — the same data the web UI shows when
you click a stop. Returns:

```json
{
    "stop": { ... },
    "nextStopVisits": [
        {
            "directionOfLine": {
                "lineNumber": "15",
                "destinationName": "South Dunedin",
                "direction": 1,
                "lineIdentifier": { "shortName": "15", "type": "3" }
            },
            "stopVisits": [
                {
                    "arrivalCancelled": false,
                    "departureCancelled": false,
                    "index": 2,
                    "stopName": "Dundas St, 141",
                    "estimatedMinutesUntilDeparture": null,
                    "stopVisitCancelled": false,
                    "scheduledMinutesUntilDeparture": 21,
                    "scheduledArrivalTime": 1782388860000,
                    "scheduledDepartureTime": 1782388860000,
                    "timingPoint": false,
                    "atStop": false,
                    "tripId": "915112008_2026-06-25_15_1_12:00:00",
                    "estimatedArrivalTime": null,
                    "estimatedDepartureTime": null,
                    "platformCode": ""
                }
            ]
        }
    ]
}
```

Key fields:
- `estimatedArrivalTime` / `estimatedDepartureTime`: real-time predictions
  (epoch ms). `null` when no real-time data is available (scheduled time only).
- `arrivalCancelled` / `departureCancelled`: trip segment has been cancelled.
- `timingPoint`: a control point where schedule adherence is measured.
- `tripId`: composite key used to look up vehicle forecasts.

### Vehicles & Trips

| Endpoint | Description |
|----------|-------------|
| `GET /rest/trips` | All currently active vehicles with trip info |
| `GET /rest/vehicles/{vehicleId}/forecast` | Detailed forecast for a specific vehicle |
| `GET /rest/trips?tripId={tripId}` | Find vehicles on a specific trip |

**Active trips response** (each entry):
```json
{
    "vehicleId": "215002",
    "tripId": "903111358_2026-06-25_3_1_11:35:00",
    "directionOfLine": {
        "lineNumber": "3",
        "destinationName": "Ocean Grove",
        "direction": 1,
        "lineIdentifier": { "shortName": "3", "type": "3" }
    },
    "lastStopName": "Malvern St, opposite 63"
}
```

**Vehicle forecast response:**
```json
{
    "vehicleId": "221604",
    "tripId": "963111358_2026-06-25_63_1_11:36:00",
    "lineNumber": "63",
    "lineType": "3",
    "destinationName": "Balaclava",
    "departureTime": 1782387360000,
    "arrivalTime": 1782389520000,
    "lastStopIndex": 2,
    "lastStopState": "DEPARTED_STOP_AREA",
    "onwardCalls": [
        {
            "stop": { "id": "59005005", "name": "Bus Hub Stop F", ... },
            "timingPoint": true,
            "pickupAvailable": true,
            "dropOffAvailable": true,
            "arrivalCancelled": false,
            "departureCancelled": false,
            "scheduledArrivalTime": 1782388140000,
            "scheduledDepartureTime": 1782388140000,
            "stopIndex": 4,
            "stopCode": "59005005",
            "estimatedArrivalTime": 1782388166107,
            "estimatedDepartureTime": 1782388166107
        },
        ...
    ]
}
```

**`lastStopState` values** (observed in the JS source):
- `NOT_REGISTERED` — vehicle hasn't reported its position yet
- `APPROACHING` — vehicle is approaching a stop
- `AT_STOP` — vehicle is currently at a stop
- `DEPARTED_STOP_AREA` — vehicle has left the stop area

### Lines & Route Shapes

| Endpoint | Description |
|----------|-------------|
| `GET /rest/lines` | All bus lines (`shortName` + `type`) |
| `GET /rest/shapes?tripId={tripId}` | Route polyline for a trip |

**Shapes response:**
```json
{
    "links": [
        {
            "startStop": { "id": "...", "name": "...", "code": "...", "location": {...} },
            "endStop": { ... },
            "routePoints": [
                { "latitude": -45.86832, "longitude": 170.52388 },
                { "latitude": -45.8682665, "longitude": 170.5239129 },
                ...
            ]
        }
    ]
}
```

### Service Status

| Endpoint | Description |
|----------|-------------|
| `GET /rest/bulletins` | Active service alerts / bulletins |
| `GET /rest/stopclosings` | Currently closed stops |
| `GET /rest/stoprelocations` | Temporarily relocated stops |

### Not Fully Explored

| Endpoint | Notes |
|----------|-------|
| `GET /rest/linesearchlines` | Line search feature (not used in map mode) |
| `GET /rest/stopdisplays/{code}` | Could have pagination via `viewNumber` param |


## WebSocket Protocol

**URL:** `wss://orc.mattersoft.fi/timetable/websocket/all?map`

The URL is derived from the REST base by:
1. Replacing `http://` → `ws://` or `https://` → `wss://`
2. Appending `/websocket/all`
3. Adding a query parameter for the client type: `?map`, `?monitor`, or `?carousel`
   (the `LIVE2_PAGE_NAME` value — the server uses this to identify which view
   is connecting)

This is a **raw WebSocket** connection (not STOMP, not SockJS). The server
does not use a sub-protocol.

> **Critical:** The `?map` parameter is required. Without it, the server accepts
> the connection but never sends data.

### Subscribing

After the connection opens, send a plain-text message to subscribe. **All
subscription messages must include the 2-character prefix** — the browser's
`vehiclesService.send()` prepends `"V_"` or `"L_"` before passing to the raw
WebSocket. Sending bare `"ALL"` without the prefix will be silently ignored.

| Message | Effect |
|---------|--------|
| `V_ALL` | Subscribe to all vehicle position updates |
| `V_{vehicleId}` | Subscribe to a specific vehicle |
| `V_{stopCode}` | Subscribe to vehicles approaching a specific stop |
| `L_{lineNumber}` | Subscribe to vehicles on a specific line |
| `T_{tripId}` | Subscribe to trip-level updates |
| `V_ignore` / `L_ignore` | Unsubscribe from current subscription |

The client in the web UI sends `V_ALL` when the user clicks "Show all vehicles".

### Receiving Updates

Messages from the server are **pipe-delimited** (`|`), containing one or more
data frames per message:

```
V_{"vehicleId":"215002","tripId":"...","lineNumber":"3",...}|V_{"vehicleId":"221604",...}
```

Each frame has:
- **2-character prefix** identifying the data type
- **JSON payload** immediately following the prefix

### Data Type Prefixes

| Prefix | Type | Description |
|--------|------|-------------|
| `V_` | Vehicle | Position/forecast update for a vehicle |
| `L_` | Line | Line-level update |
| `T_` | Trip | Trip-level update (trip state change, vehicle reassignment) |
| `S_` | Stop | Stop closing/reopening |
| `B_` | Bulletin | Service alert update |
| `C_` | Closing | Stop closing update |
| `R_` | Relocation | Stop relocation update |
| `U_` | Update | Schedule update |

### Vehicle Update Payload (`V_`)

Actual payload observed from the live WebSocket stream:

```json
{
    "type": "APPROACHING",
    "vehicleId": "215002",
    "tripId": "903113058_2026-06-25_3_1_13:05:00",
    "vehicleLocation": {
        "location": { "latitude": -45.873155, "longitude": 170.505817 },
        "heading": 203.67
    },
    "lineNumber": "3"
}
```

The `type` field values:
- `APPROACHING` — vehicle is near a stop (the most common value in the stream)
- `SCHEDULED` — normal service
- `REMOVED` — vehicle has been removed from service

Note: The REST forecast endpoint (`/rest/vehicles/{id}/forecast`) returns
richer data including `lastStopState`, `lastStopIndex`, `lineType`, and the
full `onwardCalls` array. The WebSocket pushes compact position-only updates.

### Connection Lifecycle

The front-end implements:
1. Connect to WebSocket
2. On open: resubscribe to previous subscription
3. On message: dispatch to registered listeners by prefix
4. On close: set a reconnect timer (default 10 seconds from `webSocketConnectionTimeout`)
5. Periodic ping: every 5 seconds, checks `readyState`; reconnects if connection dropped

The `LIVE2_PAGE_NAME` values seen in the code: `"map"`, `"carousel"`, `"monitor"`.


## Trip ID Format

Trip IDs follow the pattern:
```
{numeric_id}_{date}_{lineNumber}_{direction}_{time}
```

Example: `963111358_2026-06-25_63_1_11:36:00`

- `963111358` — internal trip identifier
- `2026-06-25` — operating date
- `63` — line number
- `1` — direction (0 or 1)
- `11:36:00` — departure time


## Line Type

All observed lines have `"type": "3"`. This likely corresponds to a GTFS
route type. Type 3 = Bus in the GTFS specification.


## Coordinate Systems

- **REST API**: EPSG:4326 (WGS84 latitude/longitude)
- **Map display**: EPSG:3857 (Web Mercator)
- The front-end uses OpenLayers (`ol.js`) to transform between the two.


## Rate Limiting & Etiquette

No authentication is required. No rate limiting was observed during testing,
but the application is designed for a small regional transit network (~55
active vehicles). Polling the REST API every 10-30 seconds is reasonable.
The WebSocket is the preferred method for continuous tracking since it pushes
updates without polling.

The front-end polls:
- `applicationconfig` + `bulletins` every ~60 seconds
- `stopdisplays` on demand when a stop is selected
- Vehicle forecasts every ~20 seconds (via the display refresh cycle)


## Dunedin-Specific Context

- **Network**: Orbus Dunedin (ORC — Otago Regional Council)
- **Map center**: (-45.881, 170.503) — central Dunedin
- **Default zoom**: 14
- **Stop code format**: 8-digit numeric starting with `59` (e.g. `59000232`)
- **Zones**: `00_1` (central), `00_2A` through `00_2F` (suburban)
- The system also appears to cover **Queenstown** routes (Lines 1, 2, 3, 4, 5
  to Arrowtown, Lake Hayes, Remarkables, etc.) — vehicle IDs starting with
  `231xxx` and `220xxx`.
- **Mosgiel On-Demand**: a demand-responsive service appears in the line list.

## Files in This Repository

- `dunedin_bus_tracker.py` — Python client library + demo script
- `API.md` — this document

## Running the Demo

```bash
# REST API demo (stops, schedules, forecasts)
python3 dunedin_bus_tracker.py

# Live WebSocket vehicle stream (default 15 seconds)
python3 dunedin_bus_tracker.py --websocket 15
```
