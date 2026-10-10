"""Run the unchanged synthetic retrieval workload through the native health adapter."""
import pathlib,sys
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from benchmark import normalize_health
old_get=cluster.get
cluster.get=lambda path,**kw: normalize_health(old_get(path,**kw)) if path=='/health' else old_get(path,**kw)
assert common.PAIR.config['api']['bind']=='127.0.0.1'
import qualify_native_context
qualify_native_context.main()
