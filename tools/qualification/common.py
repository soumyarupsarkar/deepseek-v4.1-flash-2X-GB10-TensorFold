"""Bind synthetic acceptance clients to this installation's portable controller.

These clients generate their own fixtures. Receipts may contain those generated
requests/responses and private host identifiers; keep them under ignored state.
"""
import os
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(1,str(SOURCE/'deployment/scripts'))
from configuration import load, read, STATE
from runtime import Pair, atomic, now

CONFIG_PATH=Path(os.environ.get('DEEPSEEK_CLUSTER_CONFIG',SOURCE/'deployment/local.json'))
PAIR=Pair(load(CONFIG_PATH))
ROOT=STATE/'qualification'
bind=PAIR.config['api']['bind']
API_BASE='http://'+('127.0.0.1' if bind=='0.0.0.0' else bind)+':'+str(PAIR.config['api']['port'])
containers=PAIR.containers


def snapshot_launch():
    """Capture current identity for the clients; never select or start a profile."""
    if not read(STATE/'active.json')['running']:
        raise RuntimeError('Start and qualify only the selected owned pair')
    launch=read(STATE/'launch.json')
    atomic(ROOT/'records/launch.json',dict(launch,settings=launch['profile']))
    atomic(ROOT/'records/active.json',read(STATE/'active.json'))


snapshot_launch()
