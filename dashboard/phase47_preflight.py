"""SaltGuard Phase 4.7 read-only pre-demo check. No MQTT publishes or SQLite writes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / 'dashboard'


def static_check():
    problems=[]
    sketch=ROOT/'firmware_wokwi'/'sketch.ino'
    diagram=ROOT/'firmware_wokwi'/'diagram.json'
    try:
        source=sketch.read_text(encoding='utf-8')
        obj=json.loads(diagram.read_text(encoding='utf-8'))
        edges=obj['connections']
        checks={
            'Firmware MANUAL -> GPIO15': 'MANUAL_PIN=15' in source or 'MANUAL_PIN = 15' in source,
            'Firmware DHT22 GPIO26': 'DHT_PIN=26' in source or 'DHT_PIN = 26' in source,
            'Firmware DS18B20 GPIO13': 'WATER_TEMP_PIN=13' in source or 'WATER_TEMP_PIN = 13' in source,
            'Wokwi no RX0 wiring': not any('esp:RX0' in str(p) for e in edges for p in e[:2]),
            'Wokwi MANUAL GPIO15': any('fault:' in str(e[0]) and 'esp:D15' in str(e[1]) or 'fault:' in str(e[0]) and 'esp:15' in str(e[1]) for e in edges),
        }
        for k,v in checks.items():
            print(('PASS' if v else 'FAIL') + ': ' + k)
            if not v: problems.append(k)
        print('INFO: Wokwi parts:',len(obj.get('parts',[])),'connections:',len(edges))
    except (OSError, ValueError, KeyError) as exc:
        problems.append(str(exc))
        print('FAIL: Cannot inspect firmware/diagram:',exc)
    return problems


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--offline',action='store_true',help='Only inspect project files; do not query Backend')
    args=p.parse_args()
    print('SaltGuard Phase 4.7 pre-demo check (READ ONLY)')
    problems=static_check()
    if not args.offline:
        from phase46_check import main as old_main
        previous=sys.argv[:]
        try:
            sys.argv=['phase46_check.py','--url',args.url]
            status=old_main()
        finally:
            sys.argv=previous
        if status:
            problems.append('API/live preflight returned '+str(status))
    else:
        print('SKIP: Live API check (--offline)')
    print('RESULT:', 'PASS' if not problems else 'BLOCKED ('+str(len(problems))+' checks)')
    return 0 if not problems else 1


if __name__=='__main__':
    raise SystemExit(main())
