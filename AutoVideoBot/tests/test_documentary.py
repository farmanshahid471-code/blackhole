import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.script import parse_script_file, generate_script
from bot.shot_library import SHOTS, validate_scene


class FakeLLM:
    provider_name = 'fake'
    def chat(self, messages, **kwargs):
        assert 'accretion_disk_orbit' in messages[0]['content']
        return json.dumps({'title':'Test', 'scenes':[{'narration':'A distant star curves around the horizon.',
                    'shot':'accretion_disk_orbit','params':{'disk_tilt_deg':18},'duration_hint_s':4},
                    {'narration':'The horizon marks a boundary we cannot cross back.',
                    'shot':'core_cross_section_diagram','params':{'highlight':'event_horizon'}}]})


class DocumentaryTests(unittest.TestCase):
    def cfg(self):
        return Config({'visual':{'engine':'remotion'},'llm':{'scenes':{'target_seconds_per_scene':8}},
                       'video':{'aspect':'16x9','fps':24},'motion':{'preset':'auto'},
                       'timing':{'default_scene_seconds':6}})

    def test_library_validation(self):
        for i, shot in enumerate(SHOTS):
            sc={'shot':shot}
            validate_scene(sc,i)
            self.assertEqual(sc['shot'],shot)
        for bad in ({'shot':'invented'}, {'shot':'accretion_disk_orbit','params':{'disk_tilt_deg':90}},
                    {'shot':'outro','params':{'fake':1}},
                    {'shot':'outro','text_overlays':[{'t':-1,'text':'oops'}]}):
            with self.assertRaises(ValueError): validate_scene(bad,0)

    def test_director(self):
        output=generate_script(FakeLLM(),self.cfg(),topic='black holes',duration=16)
        self.assertTrue(output['narration_led'])
        self.assertEqual(output['scenes'][0]['shot'],'accretion_disk_orbit')
        self.assertEqual(output['scenes'][0]['params']['disk_tilt_deg'],18)
        self.assertEqual(output['scenes'][1]['params']['highlight'],'event_horizon')

    def test_json_file_and_pipeline_skip_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input.json'
            path.write_text(json.dumps({'title':'Test', 'voice':'en-US-ChristopherNeural',
                          'scenes':[{'narration':'Black holes are real.','shot':'title_card','params':{}},
                                    {'narration':'A second thought.','shot':'starfield_warp','params':{}}]}))
            data=parse_script_file(path)
            self.assertTrue(data['narration_led'])
            self.assertEqual(data['scenes'][1]['id'],'s02')
            p=Pipeline(self.cfg(),Project(Path(tmp),'project'))
            p.stage_script(script_file=path)
            with patch.object(p,'provider',side_effect=AssertionError('images should not load')):
                p.stage_images()
            self.assertEqual(p.scenes[1]['shot'],'starfield_warp')

    def test_silent_title_card_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'cards.json'
            p.write_text(json.dumps({'scenes':[{'shot':'title_card','title':'Gravity',
                         'text_overlays':[{'t':0,'text':'GRAVITY','style':'title_card'}],
                         'duration_hint_s':2}]}))
            data=parse_script_file(p)
            self.assertEqual(len(data['scenes']),1)
            self.assertEqual(data['scenes'][0]['shot'],'title_card')

    def test_invalid_director_output_fails(self):
        class Bad(FakeLLM):
            def chat(self,*a,**k): return '{"scenes":[{"narration":"A","shot":"invented"}]}'
        with self.assertRaisesRegex(ValueError,'unknown shot'):
            generate_script(Bad(),self.cfg(),topic='black hole')



class CaptionTests(unittest.TestCase):
    def test_absolute_words_drive_captions_and_karaoke(self):
        from bot.subtitles import build_srt, words_to_karaoke_ass
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'s01.json').write_text(json.dumps({'words':[{'w':'Gravity','s':0,'e':.4},
                                                           {'w':'bends.','s':.5,'e':.9}]}))
            scene={'id':'s01','narration':'Gravity bends.','start':2,'end':4,'duration':2,
                   'tempo':1,'speech_pad_before':.15,
                   'word_timings':[{'w':'Gravity','start':2.15,'end':2.55},
                                   {'w':'bends.','start':2.65,'end':3.05}]}
            cfg=Config({'subtitles':{'words_per_line':4,'max_chars_per_line':42}})
            cues=build_srt([scene],cfg,words_dir=folder)
            self.assertAlmostEqual(cues[0]['start'],2.15)
            path=words_to_karaoke_ass([scene],folder,folder/'karaoke.ass',{},play_w=1920,play_h=1080)
            self.assertIn(r'{\k',path.read_text())
            self.assertIn('0:00:02.15',path.read_text())

class SfxTests(unittest.TestCase):
    def test_effects_are_deterministic_and_scene_relative(self):
        from bot.sfx import plan_events
        cfg = Config({'audio': {'sfx': {'enabled': True}}})
        scenes = [{'id':'s01','shot':'title_card','start':0,'duration':2},
                  {'id':'s02','shot':'event_horizon_flythrough','start':2,'duration':4}]
        with tempfile.TemporaryDirectory() as temp:
            a = plan_events(scenes, cfg, Path(temp))
            self.assertEqual([e['kind'] for e in a], ['whoosh', 'rumble'])
            self.assertAlmostEqual(a[0]['at'], 1.75)
            original = a[0]['path'].read_bytes()
            a[0]['path'].unlink()
            self.assertEqual(original, plan_events(scenes,cfg,Path(temp))[0]['path'].read_bytes())
            scenes[1]['sfx'] = []
            self.assertEqual(plan_events(scenes,cfg,Path(temp)), [])
            scenes[1]['sfx'] = [{'kind':'whoosh','t':5}]
            with self.assertRaisesRegex(ValueError,'outside'):
                plan_events(scenes,cfg,Path(temp))


class RemoteTests(unittest.TestCase):
    def test_archive_excludes_credentials(self):
        import tarfile
        from bot.providers.render_vast import VastRemotionRenderer
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'VAST_API_KEY': 'test-key'}):
            p = Project(Path(temp), 'video').create()
            cfg = Config({'visual': {'vast': {'api_key_env':'VAST_API_KEY',
                                            'mode':'existing','instance_id':'42'}}})
            renderer = VastRemotionRenderer(cfg,p)
            archive=p.tmp_dir/'source.tar.gz'
            renderer._archive(archive)
            with tarfile.open(archive) as tar:
                names=tar.getnames()
            self.assertIn('src/index.ts',names)
            self.assertIn('shots.json',names)
            self.assertFalse(any('.env' in name or 'node_modules' in name or 'workspace' in name
                                 for name in names))

    def test_remote_failure_preserves_completed_clips_and_tears_down(self):
        import subprocess
        from bot.providers.render_vast import VastRemotionRenderer
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'VAST_API_KEY':'fake'}):
            p=Project(Path(temp),'video').create()
            cfg=Config({'visual':{'vast':{'mode':'existing','instance_id':'42',
                                          'api_key_env':'VAST_API_KEY'}}})
            r=VastRemotionRenderer(cfg,p)
            output=[p.scene_clip('s01'),p.scene_clip('s02')]
            scenes=[{'id':'s01','shot':'title_card','duration':1},
                    {'id':'s02','shot':'title_card','duration':1}]
            saved=[]
            def fake_ssh(command, **kwargs):
                if command.startswith('cat '):
                    return subprocess.CompletedProcess([],0,json.dumps({'s01':{'ok':True,'bytes':4},
                                            's02':{'ok':False,'error':'shader failed'}}),'')
                if 'node worker.cjs' in command:
                    return subprocess.CompletedProcess([],1,'','one render failed')
                return subprocess.CompletedProcess([],0,'','')
            def fake_scp(src,dst,**kwargs):
                if src.endswith('/clips/s01.mp4'):
                    Path(dst).write_bytes(b'clip')
            with patch.object(r,'_boot',side_effect=lambda: (setattr(r,'_remote','root@host'),
                                           setattr(r,'_port',22))), \
                 patch.object(r,'_ssh',side_effect=fake_ssh), \
                 patch.object(r,'_scp',side_effect=fake_scp), \
                 patch.object(r.vast,'teardown') as teardown:
                with self.assertRaisesRegex(RuntimeError,'s02'):
                    r.render_many(list(zip(scenes,output)),width=320,height=180,fps=12,
                                  completed=lambda scene,out:saved.append(scene['id']))
                teardown.assert_called_once()
            self.assertEqual(saved,['s01'])
            self.assertEqual(output[0].read_bytes(),b'clip')
            self.assertFalse(output[1].exists())

class ProvisionTests(unittest.TestCase):
    def test_search_instance_has_no_image_server_port_and_is_owned(self):
        from bot.providers.render_vast import VastRenderProvisioner
        with tempfile.TemporaryDirectory() as temp:
            cfg=Config({'image':{'vast':{'search':{'image':'node:22-bookworm','disk_gb':35}}}})
            p=Project(Path(temp),'video').create()
            provisioner=VastRenderProvisioner(cfg,p)
            sent=[]
            def api(method,url,body=None,**kwargs):
                sent.append((method,url,body))
                return {'new_contract':123}
            with patch.object(provisioner,'_api',side_effect=api):
                provisioner._create_instance({'id':77})
            self.assertEqual(sent[0][2]['runtype'],'ssh_direct')
            self.assertNotIn('env',sent[0][2])
            self.assertNotIn('bundle_id',sent[0][2])
            self.assertEqual(sent[0][1], '/asks/77/')
            self.assertTrue(provisioner._owns_instance)
            self.assertEqual(provisioner._instance_id,'123')

    def test_malformed_json_does_not_become_narration(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bad.json'
            p.write_text('{"scenes": [invalid]}')
            with self.assertRaisesRegex(ValueError,'Invalid JSON script'):
                parse_script_file(p)

if __name__ == "__main__":
    unittest.main()
