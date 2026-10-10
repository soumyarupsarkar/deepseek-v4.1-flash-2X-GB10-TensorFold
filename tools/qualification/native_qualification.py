"""Run synthetic legacy workloads using native counters, with no guessed values."""
import importlib,pathlib,sys
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from benchmark import normalize_health
original_get=cluster.get
def health_get(path,**kw):
    h=original_get(path,**kw)
    if path!='/health':return h
    out=normalize_health(h)
    out['streams']=dict(out['streams'],max=h['max_batch_size'])
    out['context_length']=h['max_model_len']
    out['capacity']=dict(per_request_tokens=h['max_model_len'],shared_pool_tokens=h['native']['pool_tokens'])
    out['memory']=dict(h['memory'],kv_compactions=h['native']['compactions'])
    out['progress']=dict(prefill_tokens=h['native']['prefill_tokens'],
                         generation_tokens=h['scheduler']['generation_tokens_total'])
    return out
cluster.get=health_get
assert common.PAIR.config['api']['bind']=='127.0.0.1'
stage=sys.argv.pop(1)
assert stage in ('pool','memory','pool_queue','recovery','soak','native_context')
assert '--record' in sys.argv
record=sys.argv[sys.argv.index('--record')+1]
assert record.replace('-','').isalnum()
assert not (common.ROOT/'records'/('validation-'+record+'.json')).exists(),'Preserve earlier receipts'
importlib.import_module('qualify_'+stage).main()
