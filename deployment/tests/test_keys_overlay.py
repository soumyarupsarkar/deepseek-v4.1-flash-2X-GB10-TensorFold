"""Weight selection must preserve aliases, immutable caches and paired recovery."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from configuration import CONFIG, launch_args, profile, read
from runtime import Pair
from keys_overlay import selected, spec, verify, variant
from engine_health import ready


class OverlayTests(unittest.TestCase):
    def test_both_ranks_select_same_readonly_overlay_and_preserve_all_aliases(self):
        config=read(CONFIG/'cluster.example.json')
        for host in ('head','worker'):
            rails=[dict(r,gid_index=3) for r in config[host]['rails']]
            args={v:launch_args(config,host,'00000000-0000-4000-8000-000000000000',
                'sha256:test',rails,weight_variant=v) for v in ('stock','keys')}
            env={v:dict(a[i+1].split('=',1) for i,x in enumerate(a) if x=='-e') for v,a in args.items()}
            self.assertNotIn('TF_DS_WEIGHT_OVERLAY',env['stock'])
            self.assertEqual(env['keys'].pop('TF_DS_WEIGHT_OVERLAY'),'/weight-overlay')
            self.assertEqual(env['stock'],env['keys'])
            for v in args:
                self.assertIn(config[host]['data_root']+'/prepared:/prepared:ro',args[v])
            self.assertIn(config[host]['data_root']+'/overlays/keys-1017/prepared:/weight-overlay:ro',args['keys'])
            if host=='head':
                self.assertEqual(args['stock'][args['stock'].index('sha256:test'):],
                                 args['keys'][args['keys'].index('sha256:test'):])

    def test_health_requires_actual_overlay_loading_for_selected_profile(self):
        h=dict(status='ok',runtime_poisoned=False,warming=False,max_batch_size=32,max_model_len=1048576,
            structured_outputs=True,native=dict(rdma_failed=False,pool_tokens=8650752,
                context_tokens=1048576,stream_slots=32,weight_overlay_entries=0))
        self.assertTrue(ready(h,profile('stock')))
        self.assertFalse(ready(h,profile('keys')))
        h['native']['weight_overlay_entries']=78
        self.assertTrue(ready(h,profile('keys')))
        self.assertFalse(ready(h,profile('stock')))

    def test_selection_defaults_to_stock_but_does_not_accept_unknown_values(self):
        with tempfile.TemporaryDirectory() as d:
            p=Mock(state=Path(d))
            self.assertEqual(selected(p),'stock')
            (p.state/'variant.json').write_text(json.dumps({'variant':'keys'}))
            self.assertEqual(selected(p),'keys')
            with self.assertRaises(ValueError):variant('../keys')

    def test_overlay_receipt_cannot_move_to_another_image(self):
        with tempfile.TemporaryDirectory() as d:
            pair=Mock(state=Path(d))
            (pair.state/'keys-overlay.json').write_text(json.dumps(dict(status='passed',image='old')))
            with self.assertRaises(ValueError):verify(pair,'new')
            pair.run.assert_not_called()


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pair=Mock(state=Path(self.tmp.name))
        (self.pair.state/'build.json').write_text(json.dumps(dict(revision='source',id='image')))
        (self.pair.state/'variant.json').write_text(json.dumps(dict(variant='stock')))
        (self.pair.state/'launch.json').write_text(json.dumps(dict(variant='stock',containers={'head':'h','worker':'w'})))
        self.pair.containers.side_effect=lambda host:[dict(Id='h' if host=='head' else 'w',Image='image',State={'Running':True})]
        self.pair.get.return_value=dict(status='ok',runtime_poisoned=False,native={'rdma_failed':False},scheduler={})
        self.rev=patch('runtime.source_revision',return_value='source');self.rev.start();self.addCleanup(self.rev.stop)
        self.verify=patch('keys_overlay.verify',return_value={});self.verify.start();self.addCleanup(self.verify.stop)

    def test_switch_stops_pair_and_selects_keys(self):
        Pair.switch(self.pair,'keys')
        self.pair.stop.assert_called_once_with()
        self.pair.start.assert_called_once_with('keys')
        self.assertEqual(read(self.pair.state/'switch.json')['status'],'passed')

    def test_failed_start_restores_previous_variant(self):
        self.pair.start.side_effect=[RuntimeError('synthetic startup failure'),None]
        with self.assertRaisesRegex(RuntimeError,'synthetic'):Pair.switch(self.pair,'keys')
        self.assertEqual([x.args for x in self.pair.start.call_args_list],[('keys',),('stock',)])
        self.assertEqual(read(self.pair.state/'switch.json')['status'],'rolled-back')

    def test_busy_or_poisoned_pair_is_not_stopped(self):
        for field,value in [('scheduler',{'running':1}),('runtime_poisoned',True)]:
            with self.subTest(field=field):
                h=copy.deepcopy(self.pair.get.return_value);h[field]=value
                with patch.object(self.pair,'get',return_value=h):
                    with self.assertRaisesRegex(RuntimeError,'healthy idle'):Pair.switch(self.pair,'keys')
        self.pair.stop.assert_not_called();self.pair.start.assert_not_called()

    def test_unverified_overlay_does_not_stop_healthy_stock(self):
        with patch('keys_overlay.verify',side_effect=ValueError('changed weights')):
            with self.assertRaisesRegex(ValueError,'changed'):Pair.switch(self.pair,'keys')
        self.pair.stop.assert_not_called()

    def test_same_variant_is_noop(self):
        Pair.switch(self.pair,'stock')
        self.pair.stop.assert_not_called();self.pair.start.assert_not_called()


if __name__=='__main__':unittest.main()
