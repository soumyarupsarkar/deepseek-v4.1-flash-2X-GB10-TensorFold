"""Portable recipe contracts; no SSH, Docker, model downloads or host mutations."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'deployment/scripts'))
import assets
import cli
import configuration as cfg
import runtime
import reuse


def example():
    return cfg.read(cfg.CONFIG/'cluster.example.json')


class ConfigurationTests(unittest.TestCase):
    def test_example_plan_has_no_external_side_effects(self):
        with patch('subprocess.run',side_effect=AssertionError('external command')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            result=cli.plan(cfg.validate(example()))
        self.assertEqual(result['profile']['parallel'],32)
        self.assertEqual(result['environment']['TF_DS_POOL_TOKENS'],'8650752')
        self.assertEqual(result['environment']['TENSORFOLD_SEED_MODE'],'random')

    def test_dedicated_data_paths_required(self):
        for path in ('/','/home/user','/etc/model','/tmp/../etc/model','relative','/srv/model:rw','/srv/a b'):
            with self.subTest(path=path):
                value=example();value['head']['data_root']=path
                with self.assertRaises(ValueError):cfg.validate(value)

    def test_remote_argument_injection_rejected(self):
        for target in ('-oProxyCommand=bad','user@host;command','user@host name','user@$(command)'):
            with self.subTest(target=target):
                value=example();value['worker']['ssh']=target
                with self.assertRaises(ValueError):cfg.validate(value)

    def test_lan_access_requires_explicit_choice(self):
        value=example();value['api']['bind']='0.0.0.0'
        with self.assertRaisesRegex(ValueError,'LAN bind'):cfg.validate(value)
        value['api']['allow_unauthenticated_lan']=True
        cfg.validate(value)

    def test_bad_and_conflicting_ports(self):
        for port in (True,0,80,65536,'8000',29581):
            value=example();value['api']['port']=port
            with self.subTest(port=port),self.assertRaises(ValueError):cfg.validate(value)

    def test_schema_boolean_is_not_a_version(self):
        value=example();value['schema']=True
        with self.assertRaises(ValueError):cfg.validate(value)

    def test_duplicate_rails_or_rank_addresses_rejected(self):
        value=example();value['head']['rails'][1]=copy.deepcopy(value['head']['rails'][0])
        with self.assertRaises(ValueError):cfg.validate(value)
        value=example();value['worker']['rails'][0]['address']=value['head']['rails'][0]['address']
        with self.assertRaises(ValueError):cfg.validate(value)

    def test_launch_preserves_qualified_budget_and_separates_rank_arguments(self):
        value=example();identity=str(uuid.uuid4())
        for host in ('head','worker'):
            rails=[dict(r,gid_index=3) for r in value[host]['rails']]
            args=cfg.launch_args(value,host,identity,'sha256:'+'a'*64,rails)
            env=dict(args[i+1].split('=',1) for i,a in enumerate(args[:-1]) if a=='-e')
            self.assertEqual(env['TF_DS_DECODE_ROWS'],'32')
            self.assertEqual(env['TF_DS_PREFILL_CHUNK'],'1024')
            self.assertEqual(env['TF_DS_POOL_TOKENS'],'8650752')
            self.assertEqual(env['TF_DS_MEM_FLOOR_GIB'],'2.5')
            self.assertEqual(env['TF_DS_KEEP_ENTRIES'],'32')
            self.assertEqual(env['TF_DS_KEEP_MARKS'],'2')
            self.assertEqual(env['NCCL_IB_GID_INDEX'],'3')
            self.assertEqual(hashlib.sha256(env['TF_DS_COST_MODEL_JSON'].encode()).hexdigest(),cfg.profile()['cost_model_sha256'])
            self.assertEqual(args[args.index('--master')+1],value['head']['rails'][0]['address'])
            self.assertEqual(args[args.index('--rank')+1],'0' if host=='head' else '1')
            self.assertEqual('--host' in args,host=='head')
            self.assertNotIn('HF_TOKEN',env)
            self.assertNotIn('--privileged',args)

    def test_gids_must_match(self):
        value=example();rails=[dict(r,gid_index=n) for n,r in enumerate(value['head']['rails'])]
        with self.assertRaisesRegex(ValueError,'GID'):cfg.launch_args(value,'head',str(uuid.uuid4()),'image',rails)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';self.identity=str(uuid.uuid4())

    def roots(self,init=True):
        return subprocess.run([sys.executable,'-B','-c',runtime.ROOTS],
            input=json.dumps(dict(root=str(self.root),id=self.identity,init=init,subdirs=cfg.SUBDIRS)),
            capture_output=True,text=True)

    def test_initialize_and_repeat_own_empty_root(self):
        self.assertEqual(self.roots().returncode,0)
        self.assertEqual(self.roots().returncode,0)
        self.assertEqual(self.roots(False).returncode,0)

    def test_nonempty_root_not_adopted(self):
        self.root.mkdir();(self.root/'keep').write_text('existing data')
        self.assertNotEqual(self.roots().returncode,0)
        self.assertFalse((self.root/'.spark-owned.json').exists())
        self.assertEqual((self.root/'keep').read_text(),'existing data')

    def test_wrong_owner_and_symlink_are_refused(self):
        self.assertEqual(self.roots().returncode,0)
        self.identity=str(uuid.uuid4())
        self.assertNotEqual(self.roots().returncode,0)
        alias=Path(self.temp.name)/'alias';alias.symlink_to(self.root,target_is_directory=True)
        self.root=alias
        self.assertNotEqual(self.roots().returncode,0)

    def test_config_drift_never_selects_other_hosts(self):
        value=example();state=Path(self.temp.name)/'state'
        runtime.atomic(state/'ownership.json',dict(deployment_id=self.identity,config_sha256=cfg.fingerprint(value)))
        self.assertEqual(runtime.Pair(value,state).ownership(),self.identity)
        value['worker']['ssh']='someone@else.example.invalid'
        with self.assertRaisesRegex(ValueError,'Configuration changed'):runtime.Pair(value,state).ownership()


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_relative_paths_cannot_escape(self):
        for value in ('','../file','/tmp/file','a/../../b','a//b'):
            with self.subTest(value=value),self.assertRaises(ValueError):assets.relative(value)

    def test_safetensors_extraction_is_byte_exact_and_resumable_when_finished(self):
        source=self.root/'source';source.mkdir();out=self.root/'out';out.mkdir()
        body=b'AAAABBBBBBBB'
        original={'discard':dict(dtype='U8',shape=[4],data_offsets=[0,4]),
                  'layers.1.engram.embed.weight':dict(dtype='U8',shape=[8],data_offsets=[4,12])}
        encoded=json.dumps(original,separators=(',',':')).encode();encoded+=b' '*(-len(encoded)%8)
        assets.write_safetensors(source/'shard.safetensors',encoded,[body])
        output={'layers.1.engram.embed.weight':dict(dtype='U8',shape=[8],data_offsets=[0,8])}
        target=json.dumps(output,separators=(',',':')).encode();target+=b' '*(-len(target)%8)
        import struct
        expected=struct.pack('<Q',len(target))+target+b'BBBBBBBB'
        layouts={'extracted.safetensors':dict(header=target.decode(),bytes=len(expected),sha256=hashlib.sha256(expected).hexdigest())}
        mapping={'layers.1.engram.embed.weight':'shard.safetensors'}
        assets.extract_engram(source,out,mapping,layouts)
        self.assertEqual((out/'extracted.safetensors').read_bytes(),expected)
        assets.extract_engram(source,out,mapping,layouts)
        self.assertEqual((source/'shard.safetensors').read_bytes()[-12:],body)

    def test_wrong_finished_file_not_overwritten(self):
        p=self.root/'keep.safetensors';p.write_bytes(b'existing')
        with self.assertRaises(ValueError):assets.write_safetensors(p,b'{}',[b'new'],dict(bytes=1,sha256='a'*64))
        self.assertEqual(p.read_bytes(),b'existing')

    def test_http_auth_is_not_forwarded_on_redirect(self):
        import urllib.request
        request=urllib.request.Request('https://example.invalid/asset')
        assets.authorization(request,'test-value')
        self.assertNotIn('Authorization',request.headers)
        self.assertEqual(request.unredirected_hdrs['Authorization'],'Bearer test-value')

    def test_remote_range_requires_partial_response_and_exact_length(self):
        class Response:
            status=200
            headers={}
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):raise AssertionError('Must refuse before reading an unbounded full response')
        spec=dict(repo='organization/model',revision='a'*40)
        with patch('urllib.request.urlopen',return_value=Response()):
            with self.assertRaisesRegex(ValueError,'bounded HTTP range'):assets.range_bytes(spec,'x',0,7)

    def test_manifest_check_rejects_extra_override_files(self):
        for sub in ('model','engram','vision-extra'):(self.root/sub).mkdir()
        (self.root/'model/zz-unexpected.safetensors').write_bytes(b'bad')
        p=subprocess.run([sys.executable,'-B','-c',assets.VERIFY],
            input=json.dumps(dict(root=str(self.root),manifest={},full=True,previous=None)),capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('inventory differs',p.stderr)

    def test_reuse_validates_pins_and_preserves_source_when_new_link_removed(self):
        source=self.root/'old';dest=self.root/'new';source.mkdir();dest.mkdir()
        original=source/'weight';original.write_bytes(b'checked weights')
        row=dict(source='weight',target='model/weight',bytes=original.stat().st_size,
                 sha256=hashlib.sha256(original.read_bytes()).hexdigest())
        def run():
            return subprocess.run([sys.executable,'-B','-c',reuse.IMPORT],input=json.dumps(
                dict(source=str(source),root=str(dest),files=[row])),capture_output=True,text=True)
        self.assertEqual(run().returncode,0)
        self.assertEqual(run().returncode,0)
        self.assertEqual(original.stat().st_ino,(dest/'model/weight').stat().st_ino)
        (dest/'model/weight').unlink()
        self.assertEqual(original.read_bytes(),b'checked weights')
        row['sha256']='0'*64
        self.assertNotEqual(run().returncode,0)
        self.assertFalse((dest/'model/weight').exists())

    def test_reuse_refuses_redirected_source_and_foreign_destination(self):
        source=self.root/'old';dest=self.root/'new';source.mkdir();dest.mkdir()
        original=source/'weight';original.write_bytes(b'a')
        row=dict(source='weight',target='weight',bytes=1,sha256=hashlib.sha256(b'a').hexdigest())
        (dest/'weight').write_bytes(b'keep')
        def run():
            return subprocess.run([sys.executable,'-B','-c',reuse.IMPORT],input=json.dumps(
                dict(source=str(source),root=str(dest),files=[row])),capture_output=True,text=True)
        self.assertNotEqual(run().returncode,0)
        self.assertEqual((dest/'weight').read_bytes(),b'keep')
        original.unlink();original.symlink_to(dest/'weight')
        self.assertNotEqual(run().returncode,0)

    def test_imported_prepared_cache_is_readonly_in_serving_container(self):
        value=example();rails=[dict(r,gid_index=3) for r in value['head']['rails']]
        args=cfg.launch_args(value,'head',str(uuid.uuid4()),'image',rails,prepared_readonly=True)
        self.assertIn(value['head']['data_root']+'/prepared:/prepared:ro',args)

    def test_prepared_import_requires_owned_destination_and_complete_footer(self):
        import struct
        old=self.root/'old';new=self.root/'new'
        (old/'prepared').mkdir(parents=True);(new/'prepared').mkdir(parents=True)
        identity=str(uuid.uuid4())
        runtime.atomic(new/'.spark-owned.json',dict(deployment_id=identity))
        cache=old/'prepared/rank0of2-fixture.bin'
        index=json.dumps([['tensor','uint8',[4],0,4]]).encode()
        cache.write_bytes(b'data'+index+struct.pack('<Q',4)+b'TFDSRK01');cache.chmod(0o444)
        payload=dict(source=str(old),root=str(new),rank=0,id='wrong')
        def run():
            return subprocess.run([sys.executable,'-B','-c',reuse.PREPARED],
                                  input=json.dumps(payload),capture_output=True,text=True)
        self.assertNotEqual(run().returncode,0)
        self.assertEqual(list((new/'prepared').iterdir()),[])
        payload['id']=identity
        result=run();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['sha256'],hashlib.sha256(cache.read_bytes()).hexdigest())
        self.assertEqual(cache.stat().st_mode&0o777,0o444)
        (new/'prepared'/cache.name).unlink()
        cache.chmod(0o644);cache.write_bytes(b'incomplete')
        self.assertNotEqual(run().returncode,0)
        self.assertEqual(list((new/'prepared').iterdir()),[])


class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name);self.value=example();self.value['allow_temporary_drm']=True
        self.identity=str(uuid.uuid4())
        runtime.atomic(self.state/'ownership.json',dict(deployment_id=self.identity,config_sha256=cfg.fingerprint(self.value)))
        self.pair=runtime.Pair(self.value,self.state)
        self.before=dict(boot_id='old-boot',modeset='N',fbdev='Y',display_manager='active',
                         modules=dict(nvidia_drm=True,nvidia_modeset=True))

    def test_old_boot_restoration_does_not_mutate_a_new_boot(self):
        runtime.atomic(self.state/'drm-worker.json',dict(deployment_id=self.identity,active=True,before=self.before))
        after=dict(self.before,boot_id='new-boot')
        with patch.object(self.pair,'idle'),patch.object(self.pair,'snapshot',return_value=after), \
             patch.object(self.pair,'sudo',side_effect=AssertionError('must not mutate new boot')):
            self.pair.restore_display('worker')
        self.assertFalse(cfg.read(self.state/'drm-worker.json')['active'])

    def test_different_new_boot_keeps_journal_for_review(self):
        runtime.atomic(self.state/'drm-worker.json',dict(deployment_id=self.identity,active=True,before=self.before))
        after=dict(self.before,boot_id='new-boot',fbdev='N')
        with patch.object(self.pair,'idle'),patch.object(self.pair,'snapshot',return_value=after), \
             patch.object(self.pair,'sudo',side_effect=AssertionError('must not mutate new boot')):
            with self.assertRaisesRegex(RuntimeError,'journal retained'):self.pair.restore_display('worker')
        self.assertTrue(cfg.read(self.state/'drm-worker.json')['active'])

    def test_journal_is_durable_before_first_display_change(self):
        before=dict(self.before);after=dict(before,modeset='Y',fbdev='N',display_manager='inactive')
        calls=[]
        def sudo(host,*args):
            saved=cfg.read(self.state/'drm-head.json')
            self.assertTrue(saved['active']);self.assertEqual(saved['before'],before)
            calls.append(args)
        with patch.object(self.pair,'roots'),patch.object(self.pair,'idle'), \
             patch.object(self.pair,'snapshot',side_effect=[before,after]),patch.object(self.pair,'sudo',side_effect=sudo):
            self.pair.apply_display('head')
        self.assertEqual(calls[0],('systemctl','stop','display-manager'))

    def test_failure_applying_display_attempts_restoration(self):
        with patch.object(self.pair,'roots'),patch.object(self.pair,'idle'), \
             patch.object(self.pair,'snapshot',return_value=self.before), \
             patch.object(self.pair,'sudo',side_effect=RuntimeError('module busy')), \
             patch.object(self.pair,'restore_display') as restore:
            with self.assertRaisesRegex(RuntimeError,'module busy'):self.pair.apply_display('head')
        restore.assert_called_once_with('head')

    def test_stop_cannot_remove_a_foreign_container(self):
        foreign=dict(Config={'Labels':{cfg.LABEL:str(uuid.uuid4())}},Id='foreign',State={'Running':True})
        with patch.object(self.pair,'stop_monitor'),patch.object(self.pair,'containers',return_value=[foreign]), \
             patch.object(self.pair,'docker',side_effect=AssertionError('foreign mutation')), \
             patch.object(self.pair,'restore_display') as restore:
            with self.assertRaisesRegex(RuntimeError,'ownership differs'):self.pair.stop()
        restore.assert_not_called()

    def test_container_lookup_uses_both_ownership_labels(self):
        with patch.object(self.pair,'docker',return_value=types.SimpleNamespace(stdout='')) as docker:
            self.assertEqual(self.pair.containers('worker'),[])
        args=docker.call_args.args
        filters=[args[i+1] for i,a in enumerate(args[:-1]) if a=='--filter']
        self.assertEqual(filters,['label='+cfg.LABEL+'='+self.identity,'label='+cfg.ROLE+'=inference'])

    def test_start_without_drm_choice_has_no_remote_side_effects(self):
        value=example();pair=runtime.Pair(value,self.state)
        with patch.object(pair,'run',side_effect=AssertionError('remote side effect')):
            with self.assertRaisesRegex(ValueError,'allow_temporary_drm'):pair.start()

    def test_monitor_failure_still_attempts_both_container_cleanups(self):
        with patch.object(self.pair,'stop_monitor',side_effect=RuntimeError('unit unavailable')), \
             patch.object(self.pair,'containers',return_value=[]) as containers, \
             patch.object(self.pair,'restore_display') as restore:
            with self.assertRaisesRegex(RuntimeError,'monitor: unit unavailable'):self.pair.stop()
        self.assertEqual([c.args[0] for c in containers.call_args_list],['worker','head'])
        restore.assert_not_called()

    def test_one_restore_failure_does_not_skip_other_host(self):
        def restore(host):
            if host=='worker':raise RuntimeError('worker offline')
        with patch.object(self.pair,'stop_monitor'),patch.object(self.pair,'containers',return_value=[]), \
             patch.object(self.pair,'restore_display',side_effect=restore) as restore_call:
            with self.assertRaisesRegex(RuntimeError,'Display restoration incomplete'):self.pair.stop()
        self.assertEqual([c.args[0] for c in restore_call.call_args_list],['worker','head'])

    def test_monitor_must_be_running_before_start_can_succeed(self):
        with patch.object(self.pair,'sudo'), \
             patch.object(self.pair,'monitor_properties',return_value={'ActiveState':'inactive','MainPID':'0'}):
            with self.assertRaisesRegex(RuntimeError,'monitor did not stay active'):self.pair.start_monitor()

    def test_partial_launch_failure_cleans_up_both_ranks(self):
        runtime.atomic(self.state/'build.json',dict(id='image',revision='qualified'))
        runtime.atomic(self.state/'precompile.json',dict(image='image'))
        def docker(host,*args,**kwargs):
            if args[0]=='image':return types.SimpleNamespace(stdout='[{"Id":"image"}]')
            if args[0]=='run' and host=='worker':return types.SimpleNamespace(stdout='worker-id')
            raise RuntimeError('head launch failed')
        with patch('runtime.source_revision',return_value='qualified'), \
             patch.object(self.pair,'containers',return_value=[]),patch.object(self.pair,'roots'), \
             patch.object(self.pair,'idle'),patch('assets.verify'),patch.object(self.pair,'docker',side_effect=docker), \
             patch.object(self.pair,'memory',return_value={'MemAvailable':120*2**30}), \
             patch.object(self.pair,'fabric',side_effect=lambda h:[dict(r,gid_index=3) for r in self.value[h]['rails']]), \
             patch.object(self.pair,'snapshot',return_value={'cards':{'card0':'nvidia'}}), \
             patch.object(self.pair,'run'),patch.object(self.pair,'apply_display'),patch.object(self.pair,'stop') as stop:
            with self.assertRaisesRegex(RuntimeError,'head launch failed'):self.pair.start()
        stop.assert_called_once_with()

    def test_changed_source_is_refused_before_remote_start_actions(self):
        runtime.atomic(self.state/'build.json',dict(id='image',revision='old'))
        with patch('runtime.source_revision',return_value='new'), \
             patch.object(self.pair,'run',side_effect=AssertionError('remote side effect')):
            with self.assertRaisesRegex(RuntimeError,'Source/profile differs'):self.pair.start()


if __name__=='__main__':unittest.main()
