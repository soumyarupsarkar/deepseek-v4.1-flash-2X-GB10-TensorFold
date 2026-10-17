"""1017 prompt fidelity and the stock view's exclusion of foreign overlays."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'deployment/scripts'))
import assets

class CheckpointTests(unittest.TestCase):
    def test_template_matches_pinned_reference_encoder(self):
        # A development-only dependency; the deployed server renders in Zig.
        try:
            from jinja2 import Environment
        except ImportError:
            self.skipTest('Optional Python reference check needs Jinja2; native prompt parity runs during image build')
        fixture=json.loads((SOURCE/'tests/publication/fixtures/checkpoint-1017-prompts.json').read_text())
        env=Environment()
        env.filters['tojson']=lambda value:json.dumps(value,ensure_ascii=False,separators=(', ', ': '))
        env.globals['raise_exception']=lambda message:(_ for _ in ()).throw(ValueError(message))
        template=env.from_string((SOURCE/'deployment/config/chat-template-1017.jinja').read_text())
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(template.render(messages=copy.deepcopy(case['messages']),**case['kwargs']),case['expected'])

    def test_stock_view_preserves_tensor_index_and_rejects_foreign_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for sub in ('stock-model','model'):(root/sub).mkdir()
            entries={'layers.0.test':{'dtype':'F32','shape':[1],'data_offsets':[0,4]}}
            assets.write_safetensors(root/'stock-model/model-00001.safetensors',json.dumps(entries).encode(),[b'\0'*4])
            index={'weight_map':{'layers.0.test':'model-00001.safetensors'}}
            (root/'stock-model/model.safetensors.index.json').write_text(json.dumps(index))
            specs={'model':{'files':[{'path':'model-00001.safetensors'},{'path':'model.safetensors.index.json'}]}}
            assets.model_view(root,specs)
            self.assertEqual(json.loads((root/'model/model.safetensors.index.json').read_text()),index)
            self.assertFalse((root/'model/zz_keys_overlay.safetensors').exists())
            self.assertEqual((root/'model/chat_template.jinja').read_bytes(),(assets.CONFIG/'chat-template-1017.jinja').read_bytes())
            (root/'model/zz_keys_overlay.safetensors').write_bytes(b'foreign checkpoint')
            with self.assertRaisesRegex(ValueError,'previous Keys overlay'):assets.model_view(root,specs)
            (root/'model/zz_keys_overlay.safetensors').unlink()
            (root/'model/unknown-overlay.safetensors').write_bytes((root/'stock-model/model-00001.safetensors').read_bytes())
            with self.assertRaisesRegex(ValueError,'Unexpected files'):assets.model_view(root,specs)

    def test_original_engram_shard_is_linked_without_rewriting_or_ignoring_bad_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'original';output=root/'engram';source.mkdir();output.mkdir()
            entries={'unrelated.weight':{'dtype':'F32','shape':[1],'data_offsets':[0,4]},
                     'layers.1.engram.embed.weight':{'dtype':'F8_E4M3','shape':[2,4],'data_offsets':[4,12]},
                     'layers.1.engram.embed.scale':{'dtype':'F8_E8M0','shape':[2,1],'data_offsets':[12,14]}}
            shard=source/'part.safetensors'
            assets.write_safetensors(shard,json.dumps(entries).encode(),[bytes(range(14))])
            tensors={k:{n:v[n] for n in ('dtype','shape')} for k,v in entries.items() if '.engram.embed.' in k}
            links={'engram-layer-01.safetensors':{'source':shard.name,'tensors':tensors}}
            index={k:shard.name for k in entries}
            pins={'engram/engram-layer-01.safetensors':{'bytes':shard.stat().st_size,'sha256':assets.sha(shard)}}
            assets.link_engram(source,output,index,links,pins)
            self.assertTrue(shard.samefile(output/'engram-layer-01.safetensors'))
            bad=copy.deepcopy(links);bad['engram-layer-01.safetensors']['tensors']['layers.1.engram.embed.weight']['shape']=[4,2]
            with self.assertRaisesRegex(ValueError,'layout differs'):assets.link_engram(source,output,index,bad,pins)

    def test_engram_serving_pins_are_the_pinned_original_bytes(self):
        config=SOURCE/'deployment/config'
        original={r['path']:r for r in json.loads((config/'assets.json').read_text())['engram']['files']}
        derived=json.loads((config/'derived-assets.json').read_text())
        for name,entry in json.loads((config/'engram-links.json').read_text()).items():
            source=original[entry['source']]
            self.assertEqual(derived['engram/'+name],{'bytes':source['size'],'sha256':source['sha256']})

if __name__=='__main__':unittest.main()
