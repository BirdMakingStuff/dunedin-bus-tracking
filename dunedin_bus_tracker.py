#!/usr/bin/env python3
"""
Dunedin (ORC) Bus Live-Tracking Client

Demonstrates how to retrieve real-time bus locations, forecasts, and stop
information from the ORC / Mattersoft timetable system used in Dunedin, NZ.

API Base: https://orc.mattersoft.fi/timetable
Provider: Mattersoft Oy (Finnish transit software company)

Dependencies: requests, websockets (only for the WebSocket demo)
    pip install requests websockets
"""

import json
import time
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Install requests: pip install requests")

BASE = "https://orc.mattersoft.fi/timetable"


# ──────────────────────────────────────────────
# 1. CONFIG & SERVER TIME
# ──────────────────────────────────────────────

def get_application_config():
    """Returns app config: map center, zoom, color mappings, feature flags."""
    return requests.get(f"{BASE}/rest/applicationconfig").json()


def get_server_time():
    """Returns the server's current time as a Unix timestamp in milliseconds."""
    data = requests.get(f"{BASE}/rest/servertime").json()
    return data["serverTime"]


# ──────────────────────────────────────────────
# 2. STOPS
# ──────────────────────────────────────────────

def get_all_stops():
    """Returns every stop in the system (hundreds of entries)."""
    return requests.get(f"{BASE}/rest/stops").json()


def get_stop(stop_code):
    """Returns a single stop by its numeric code (e.g. '59000232')."""
    return requests.get(f"{BASE}/rest/stops/{stop_code}").json()


def search_stops_by_bbox(left, top, right, bottom):
    """
    Returns stops inside a geographic bounding box.

    Coordinates are EPSG:4326 (WGS84):
        left   = min longitude
        top    = max latitude
        right  = max longitude
        bottom = min latitude

    Example (central Dunedin):
        left=170.48, top=-45.85, right=170.53, bottom=-45.90
    """
    url = f"{BASE}/rest/stops/searchbybbox"
    params = {"left": left, "top": top, "right": right, "bottom": bottom}
    return requests.get(url, params=params).json()


# ──────────────────────────────────────────────
# 3. REAL-TIME STOP DISPLAY (the main live data)
# ──────────────────────────────────────────────

def get_stop_display(stop_code):
    """
    Returns the live passenger display for a stop — the same data the
    website shows when you click a stop.

    Response includes:
      - stop metadata (name, code, location, zone)
      - nextStopVisits[]: grouped by line/direction, each with:
          - directionOfLine (lineNumber, destinationName, direction)
          - stopVisits[]: per-visit data including:
              - scheduledArrivalTime / estimatedArrivalTime (epoch ms)
              - scheduledDepartureTime / estimatedDepartureTime
              - arrivalCancelled / departureCancelled
              - atStop flag
              - tripId (can be used to fetch vehicle forecast)
    """
    return requests.get(f"{BASE}/rest/stopdisplays/{stop_code}").json()


def get_current_stop_schedule(stop_code):
    """
    Returns today's scheduled departures for a stop, grouped by hour.

    Response format:
      - stop: stop metadata
      - operatingDate: "YYYY-MM-DD"
      - departureTimes: { "YYYY-MM-DDTHH:MM": [ { directionOfLine, arrivalTime, departureTime } ] }
    """
    return requests.get(f"{BASE}/rest/currentstopschedule/{stop_code}").json()


# ──────────────────────────────────────────────
# 4. VEHICLES & TRIPS (active fleet)
# ──────────────────────────────────────────────

def get_active_trips():
    """
    Returns ALL currently active vehicles with their trip info.

    Each entry:
      - vehicleId: numeric string (e.g. "215002")
      - tripId: composite key (e.g. "903111358_2026-06-25_3_1_11:35:00")
      - directionOfLine: { lineNumber, destinationName, direction, lineIdentifier }
      - lastStopName: where the bus was last registered

    This is the primary way to discover which vehicle IDs are live.
    """
    return requests.get(f"{BASE}/rest/trips").json()


def get_vehicle_forecast(vehicle_id):
    """
    Returns a detailed forecast for a specific vehicle — its full remaining
    route with estimated arrival/departure times at each upcoming stop.

    Response:
      - vehicleId, tripId, lineNumber, lineType, destinationName
      - departureTime / arrivalTime (epoch ms, route-level)
      - lastStopIndex, lastStopState (e.g. "NOT_REGISTERED", "AT_STOP", "DEPARTED")
      - onwardCalls[]: each with:
          - stop: { id, name, code, location, zone }
          - scheduledArrivalTime / estimatedArrivalTime (epoch ms)
          - scheduledDepartureTime / estimatedDepartureTime
          - timingPoint: bool (control point for schedule adherence)
          - arrivalCancelled / departureCancelled
          - pickupAvailable / dropOffAvailable
          - stopIndex: position in the trip's stop sequence
    """
    return requests.get(f"{BASE}/rest/vehicles/{vehicle_id}/forecast").json()


# ──────────────────────────────────────────────
# 5. LINES & ROUTE SHAPES
# ──────────────────────────────────────────────

def get_lines():
    """Returns all bus lines (shortName + type)."""
    return requests.get(f"{BASE}/rest/lines").json()


def get_route_shapes(trip_id):
    """
    Returns the geographic shape (polyline) of a trip's route.

    Response:
      - links[]: each with:
          - startStop / endStop: stop metadata
          - routePoints[]: { latitude, longitude } points along the road

    Useful for drawing routes on a map.
    """
    return requests.get(f"{BASE}/rest/shapes", params={"tripId": trip_id}).json()


# ──────────────────────────────────────────────
# 6. SERVICE STATUS
# ──────────────────────────────────────────────

def get_bulletins():
    """Returns active service bulletins / alerts."""
    return requests.get(f"{BASE}/rest/bulletins").json()


def get_stop_closings():
    """Returns currently closed stops."""
    return requests.get(f"{BASE}/rest/stopclosings").json()


def get_stop_relocations():
    """Returns stops that have been temporarily relocated."""
    return requests.get(f"{BASE}/rest/stoprelocations").json()


# ──────────────────────────────────────────────
# 7. WEBSOCKET (real-time vehicle position stream)
# ──────────────────────────────────────────────

def demo_websocket(duration_seconds=10):
    """
    Connects to the live WebSocket and streams vehicle position updates.

    The WebSocket protocol:
      - URL: wss://orc.mattersoft.fi/timetable/websocket/all?map
      - The URL is derived from the page's REST base by replacing
        http:// -> ws:// or https:// -> wss:// and appending /websocket/all
      - A query parameter identifies the client type (e.g. ?map, ?monitor, ?carousel)

    Subscribing — messages are prefixed through the vehiclesService layer:
      - Send "V_ALL" to subscribe to all vehicle position updates
      - Send "V_{vehicleId}" for a specific vehicle
      - Send "V_{stopCode}" for vehicles approaching a specific stop
      - Send "L_{lineNumber}" for a specific line
      - Send "T_{tripId}" for a specific trip
      - Send "V_ignore" or "L_ignore" to unsubscribe

    IMPORTANT: The subscription messages MUST include the 2-char prefix
    (e.g. "V_ALL", not "ALL"). The browser's vehiclesService.send() prepends
    "V_" or "L_" before passing to the raw WebSocket.send().

    Receiving:
      - Messages are pipe-delimited: "<PREFIX><json>|<PREFIX><json>|..."
      - 2-char prefix identifies the data type:
          V_ = vehicle position/forecast update
          L_ = line update
          T_ = trip update
          S_ = stop closing update
          B_ = bulletin update
          C_ = closing update
          R_ = relocation update
          U_ = schedule update
      - After the prefix, the rest is a JSON object

    Vehicle update (V_) payload typically contains:
      - vehicleId, tripId, lineNumber
      - vehicleLocation: { location: { latitude, longitude }, heading }
      - type: "APPROACHING" | "SCHEDULED" | "REMOVED" (approaching = bus is near a stop)
    """
    try:
        import websockets
        import asyncio
    except ImportError:
        print("Install websockets: pip install websockets")
        return

    async def listen():
        uri = "wss://orc.mattersoft.fi/timetable/websocket/all?map"
        print(f"Connecting to {uri} ...")
        async with websockets.connect(uri) as ws:
            # Subscribe to all vehicle updates (must include V_ prefix)
            await ws.send("V_ALL")
            print(f"Subscribed to ALL vehicles. Listening for {duration_seconds}s ...\n")

            end_time = time.time() + duration_seconds
            msg_count = 0
            vehicle_updates = []

            while time.time() < end_time:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    continue

                # Messages are pipe-delimited
                parts = raw.split("|")
                for part in parts:
                    if len(part) < 2:
                        continue
                    prefix = part[:2]
                    payload = part[2:]

                    if not payload:
                        continue

                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    msg_count += 1

                    if prefix == "V_":
                        vid = data.get("vehicleId", "?")
                        vtype = data.get("type", "?")
                        loc = data.get("vehicleLocation", {})
                        coords = loc.get("location", {})
                        lat = coords.get("latitude", "n/a")
                        lon = coords.get("longitude", "n/a")
                        heading = loc.get("heading", "n/a")
                        line = data.get("lineNumber", "?")
                        vehicle_updates.append(data)

                        print(f"  [V_] Vehicle {vid} | Line {line} | "
                              f"({lat}, {lon}) heading={heading} | "
                              f"type={vtype}")
                    elif prefix == "T_":
                        print(f"  [T_] Trip update: {json.dumps(data)[:120]}")
                    elif prefix == "B_":
                        print(f"  [B_] Bulletin: {json.dumps(data)[:120]}")
                    else:
                        print(f"  [{prefix}] {json.dumps(data)[:120]}")

            print(f"\nReceived {msg_count} messages in {duration_seconds}s")
            print(f"Vehicle position updates: {len(vehicle_updates)}")
            return vehicle_updates

    return asyncio.run(listen())


# ──────────────────────────────────────────────
# 8. DEMO: put it all together
# ──────────────────────────────────────────────

def demo():
    """Runs a full demonstration of the API."""
    ts = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M:%S UTC")

    print("=" * 60)
    print("  ORC / Mattersoft Bus Tracking API Demo")
    print("=" * 60)

    # Server time
    server_ts = get_server_time()
    print(f"\nServer time: {ts(server_ts)} ({server_ts})")

    # App config (summary)
    cfg = get_application_config()
    print(f"Map center: ({cfg['mapCenterLatitude']}, {cfg['mapCenterLongitude']})")
    print(f"Default zoom: {cfg['mapDefaultZoom']}")
    print(f"Supported languages: {cfg['supportedLanguages']}")

    # Active vehicles
    trips = get_active_trips()
    print(f"\nActive vehicles: {len(trips)}")
    for t in trips[:5]:
        line = t["directionOfLine"]["lineNumber"]
        dest = t["directionOfLine"]["destinationName"]
        print(f"  Vehicle {t['vehicleId']}: Line {line} -> {dest}")
    if len(trips) > 5:
        print(f"  ... and {len(trips) - 5} more")

    # Lines
    lines = get_lines()
    print(f"\nBus lines: {len(lines)}")
    unique_names = sorted(set(l["shortName"] for l in lines), key=lambda x: (len(x), x))
    print(f"  {', '.join(unique_names[:15])} ...")

    # Stop lookup
    stop_code = "59000232"  # Dundas St, 141
    stop = get_stop(stop_code)
    print(f"\nStop lookup: {stop['name']} ({stop['code']})")
    print(f"  Location: ({stop['location']['latitude']}, {stop['location']['longitude']})")
    print(f"  Zone: {stop['zone']}")

    # Live stop display
    display = get_stop_display(stop_code)
    print(f"\nLive departures from {stop['name']}:")
    for visit_group in display.get("nextStopVisits", []):
        dol = visit_group["directionOfLine"]
        print(f"  Line {dol['lineNumber']} -> {dol['destinationName']}:")
        for sv in visit_group.get("stopVisits", []):
            sched = ts(sv["scheduledArrivalTime"]) if sv.get("scheduledArrivalTime") else "n/a"
            est = ts(sv["estimatedArrivalTime"]) if sv.get("estimatedArrivalTime") else "no estimate"
            cancelled = " CANCELLED" if sv.get("arrivalCancelled") else ""
            print(f"    Scheduled: {sched} | Estimated: {est}{cancelled}")

    # Vehicle forecast (first active vehicle)
    if trips:
        vid = trips[0]["vehicleId"]
        forecast = get_vehicle_forecast(vid)
        print(f"\nVehicle {vid} forecast:")
        print(f"  Line {forecast['lineNumber']} -> {forecast['destinationName']}")
        print(f"  State: {forecast.get('lastStopState', 'n/a')}")
        calls = forecast.get("onwardCalls", [])
        print(f"  Upcoming stops ({len(calls)}):")
        for c in calls[:5]:
            est = ts(c["estimatedArrivalTime"]) if c.get("estimatedArrivalTime") else "n/a"
            sched = ts(c["scheduledArrivalTime"]) if c.get("scheduledArrivalTime") else "n/a"
            tp = " [timing point]" if c.get("timingPoint") else ""
            cancelled = " CANCELLED" if c.get("arrivalCancelled") else ""
            print(f"    {c['stop']['name']}: sched={sched} est={est}{tp}{cancelled}")
        if len(calls) > 5:
            print(f"    ... and {len(calls) - 5} more stops")

    # Bounding box search
    print("\nStops near central Dunedin (bbox search):")
    nearby = search_stops_by_bbox(170.49, -45.86, 170.52, -45.88)
    for s in nearby[:5]:
        print(f"  {s['name']} ({s['code']})")
    if len(nearby) > 5:
        print(f"  ... and {len(nearby) - 5} more")

    # Service status
    bulletins = get_bulletins()
    closings = get_stop_closings()
    relocations = get_stop_relocations()
    print(f"\nService status:")
    print(f"  Active bulletins: {len(bulletins)}")
    print(f"  Stop closings: {len(closings)}")
    print(f"  Stop relocations: {len(relocations)}")

    print("\n" + "=" * 60)
    print("  Demo complete. Run demo_websocket() for live position stream.")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--websocket":
        dur = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        demo_websocket(dur)
    else:
        demo()
