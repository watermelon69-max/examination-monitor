#!/usr/bin/env python3
"""Run from any directory: python /path/to/examination-monitor/run.py."""
import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'backend'))

if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description='Examination hall monitoring dashboard')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    print(f'Examination monitoring: http://localhost:{args.port}', flush=True)
    uvicorn.run('main:app', host=args.host, port=args.port, reload=False)
