"""Read-only SaltGuard Phase 4.6 environment preflight.
Run in dashboard: python phase46_check.py [--url http://127.0.0.1:8000]
Does not send commands, change schedules, write SQLite or operate pumps.
"""
import argparse
import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def request(base, path):
    try:
        with urlopen(base.rstrip('/') + path, timeout=5) as response:
            return json.load(response), None
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return None, f'{type(exc).__name__}: {exc}'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    print('SaltGuard Phase 4.6 – Read-only preflight')
    snap,err=request(args.url,'/api/snapshot')
    if err:
        print('BLOCKED: Backend unavailable:',err)
        return 2
    latest=snap.get('latest') or {}
    print('Device:',latest.get('device','—'))
    print('Broker:', 'connected' if snap.get('broker_connected') else 'disconnected')
    print('ESP32:', 'online' if snap.get('device_online') else 'offline')
    print('Telemetry age (s):', round(snap['age_seconds'],1) if isinstance(snap.get('age_seconds'),(int,float)) else '—')
    print('State:',latest.get('state','—'), '| Fault:',latest.get('fault','—'), '| E-stop:',latest.get('emergency_stop','—'))
    for k in ('irrigation_zone1_estimated_total_l','irrigation_zone2_estimated_total_l','air_c','air_rh_pct','water_c','tank_l'):
        print(' ',k,'=',latest.get(k,'MISSING'))
    report,err=request(args.url,'/api/activity/report?days=1&zone=0')
    if err:
        print('BLOCKED: activity API unavailable:',err)
        return 2
    summary=report.get('summary') or {}
    print('24h verified water (L):',summary.get('water_liters'))
    print('Z1:',summary.get('zone1_estimated_water_l'),' Z2:',summary.get('zone2_estimated_water_l'))
    print('Verified segments:',summary.get('water_verified_segments'))
    print('Partial segments:',summary.get('water_partial_segments'))
    print('Unverified segments:',summary.get('unverified_segments'))
    print('Latest 3 segments:')
    for row in (report.get('segments') or [])[:3]:
        print('  ID',row.get('id'),'Z',row.get('zone'),'volume',row.get('water_estimated_l'),
              'quality',row.get('water_quality'),'reason',row.get('end_reason'))
    if not snap.get('device_online'):
        print('CHECK: ESP32 is offline; live integration test must wait for an online reading.')
        return 1
    print('PASS: API responds and ESP32 is online; proceed with manual Wokwi tests.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
