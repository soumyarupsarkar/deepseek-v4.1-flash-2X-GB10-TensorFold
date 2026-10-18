"""CPU contracts for health interpretation and paired native launch configuration."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from configuration import CONFIG, launch_args, profile, read
from engine_health import healthy, ready, busy, progress
from memory_watch import health_sample
from benchmark import normalize_health, normalize_stats, summarize


def live():
    return dict(status='ok',runtime_poisoned=False,warming=False,max_model_len=1048576,max_batch_size=32,
                structured_outputs=True,scheduler=dict(running=1,waiting=0,generation_tokens_running=0),
                completed=dict(prompt_tokens=0,generation_tokens=0,decode_rounds=0),
                native=dict(rdma_failed=False,pool_tokens=8650752,context_tokens=1048576,stream_slots=32,
                            prefilling_streams=1,prefill_tokens=2048,verify_rounds=0,draft_passes=0))


class NativeControllerTests(unittest.TestCase):
    def test_native_benchmark_uses_live_committed_tokens_not_finished_tokens(self):
        h=live()
        h['scheduler']['generation_tokens_total']=50
        h['completed']['requests']=2
        h['completed']['generation_tokens']=10
        h['native']['active_streams']=1
        h['native']['prefilling_streams']=0
        first=normalize_health(h)
        later=copy.deepcopy(h);later['scheduler']['generation_tokens_total']=90
        last=normalize_health(later)
        result=dict(start=0,end=4,usage={'completion_tokens':100,'prompt_tokens':12},
                    tensorfold={'cached':0,'prefill_s':0.5},decode_tps=20,ttft_s=0.5,wall_s=4)
        summary=summarize([result],[dict(at=1,health=first),dict(at=3,health=last)],1)
        self.assertEqual(summary['sampled_steady_decode_tps'],20)
        self.assertEqual(first['requests_total'],2)
        del h['scheduler']['generation_tokens_total']
        with self.assertRaises(KeyError):normalize_health(h)

    def test_native_benchmark_requires_real_cache_and_draft_counts(self):
        stats=dict(prefill_seconds=0.5,decode_seconds=1.5)
        got=normalize_stats(stats,dict(prompt_tokens_details={'cached_tokens':7}),
                            dict(drafted=9,accepted=8))
        self.assertEqual((got['cached'],got['drafted'],got['accepted']),(7,9,8))
        with self.assertRaises(KeyError):normalize_stats(stats,{},dict(drafted=0,accepted=0))

    def test_long_prefill_counts_as_progress_before_any_output(self):
        first = live()
        later = copy.deepcopy(first)
        later['native']['prefill_tokens'] += 2048
        self.assertTrue(busy(later))
        self.assertNotEqual(progress(first),progress(later))
        self.assertEqual(first['completed'],later['completed'])
        self.assertTrue(ready(later,profile()))

    def test_poison_and_partial_capacity_fail_readiness(self):
        for target,key,value in [('native','rdma_failed',True),('native','stream_slots',4),
                                  ('native','pool_tokens',1048576),('native','context_tokens',8650752)]:
            h=live();h[target][key]=value
            self.assertFalse(ready(h,profile()))
        for patch in [dict(runtime_poisoned=True),dict(status='failed'),dict(warming=True),dict(structured_outputs=False)]:
            h=live();h.update(patch);self.assertFalse(ready(h,profile()))
        self.assertFalse(healthy({'ok':True}))

    def test_monitor_keeps_numbers_and_omits_arbitrary_strings(self):
        h=live();h['failure']='private text';h['native']['unexpected']='private text'
        h['completed']['payload']=['private text'];h['other']={'secret':'private text'}
        sample=health_sample(h)
        self.assertEqual(sample['native']['prefill_tokens'],2048)
        self.assertNotIn('private text',json.dumps(sample))

    def test_both_ranks_use_same_pool_context_slots_kit_and_gid(self):
        c=read(CONFIG/'cluster.example.json')
        uid='00000000-0000-4000-8000-000000000000'
        for host in ('head','worker'):
            rails=[dict(r,gid_index=3) for r in c[host]['rails']]
            args=launch_args(c,host,uid,'sha256:synthetic',rails,prepared_readonly=True)
            env=dict(args[i+1].split('=',1) for i,x in enumerate(args) if x=='-e')
            self.assertEqual(env['TF_RDMA_GID_INDEX'],'3')
            self.assertEqual(env['TF_DS_POOL_TOKENS'],'8650752')
            self.assertEqual(env['TF_DS_STREAMS'],'32')
            self.assertEqual(env['TENSORFOLD_SEED_MODE'],'random')
            self.assertEqual(env['TF_DS_FP8_WOA'],'1')
            self.assertEqual(env['TF_DS_VISION_BIAS'],'/vision-extra/vision-routing-bias.safetensors')
            self.assertIn(c[host]['data_root']+'/native-kit:/kit:ro',args)
            self.assertIn(c[host]['data_root']+'/prepared:/prepared:ro',args)
            if host=='head':
                self.assertIn('/opt/tensorfold/bin/tensorfold-native',args)
                limits=json.loads(env['TENSORFOLD_MODEL_CONTEXTS'])
                expected = {'deepseek-v4.1-flash': 1048576}
                for stem in ('DeepSeek-V4.1-Flash-1017', 'deepseek-v4.1-flash'):
                    for suffix, size in (('262k',262144),('524k',524288),('614k',614400),('1m',1048576)):
                        expected[stem+'-'+suffix] = size
                self.assertEqual(limits,expected)
                self.assertEqual(args[args.index('--name', args.index('sha256:synthetic'))+1], 'DeepSeek-V4.1-Flash-1017')
                for name in limits:self.assertIn(name,args)
            else:
                self.assertIn('/opt/tensorfold/bin/tf-dsv41-lanes',args)
                self.assertEqual(args[args.index('--context')+1],'1048576')
                self.assertEqual(args[args.index('--pool')+1],'8650752')


if __name__ == '__main__':
    unittest.main()
