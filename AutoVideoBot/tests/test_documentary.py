import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.script import parse_script_file, generate_script
from bot.shot_library import SHOTS, validate_scene, validate_sequence


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

    def test_vector_pilot_shots_are_reusable_in_scene_sequence(self):
        shots=['stellar_equilibrium','stellar_collapse','horizon_boundary']
        self.assertEqual([SHOTS[s]['family'] for s in shots],['wide','close','diagram'])
        scenes=[{'shot':s,'duration':8,'params':{}} for s in shots]
        validate_sequence(scenes)
        self.assertEqual([s['shot'] for s in scenes],shots)

    def test_vector_60_second_example_is_valid(self):
        from bot.shot_library import validate_sequence
        example=Path(__file__).resolve().parent.parent/'examples/vector-60s.json'
        data=parse_script_file(example)
        self.assertEqual(data['total_duration'],60)
        self.assertEqual(len(data['scenes']),6)
        self.assertEqual([(s['target_start'],s['target_end']) for s in data['scenes']],
                         [(i*10,(i+1)*10) for i in range(6)])
        validate_sequence(data['scenes'])

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

    def test_director_repairs_a_new_duplicate_in_second_repair(self):
        class DoubleRepair(FakeLLM):
            answers = [
                ['starfield_warp', 'accretion_disk_orbit', 'core_cross_section_diagram'],
                ['starfield_warp', 'core_cross_section_diagram', 'core_cross_section_diagram'],
                ['starfield_warp', 'core_cross_section_diagram', 'event_horizon_flythrough'],
            ]
            def __init__(self):
                self.calls = []
            def chat(self, messages, **kwargs):
                self.calls.append(messages)
                shots = self.answers[len(self.calls) - 1]
                return json.dumps({'title': 'Test', 'scenes': [
                    {'shot': name, 'narration': f'Scene {i} describes gravity and light.'}
                    for i, name in enumerate(shots)]})

        llm = DoubleRepair()
        out = generate_script(llm, self.cfg(), topic='black holes', duration=16)
        self.assertEqual(len(llm.calls), 3)
        self.assertIn('EVERY adjacent pair', llm.calls[2][-1]['content'])
        self.assertEqual([s['shot'] for s in out['scenes']], llm.answers[-1])
        validate_sequence(out['scenes'])

    def test_optional_bad_overlay_is_omitted_without_llm_retry(self):
        class BadOverlay(FakeLLM):
            def __init__(self): self.calls = 0
            def chat(self, *args, **kwargs):
                self.calls += 1
                return json.dumps({'scenes': [
                    {'shot': 'starfield_warp', 'narration': 'A distant star curves around the horizon.',
                     'text_overlays': [
                         {'text': 'invalid', 'style': 'invented'},
                         {'text': 'Gravity', 'style': 'lower_third', 't': 0}]},
                    {'shot': 'core_cross_section_diagram',
                     'narration': 'The dark horizon is a boundary around it.',
                     'text_overlays': 'not an array'},
                ]})
        llm = BadOverlay()
        out = generate_script(llm, self.cfg(), topic='black holes', duration=16)
        self.assertEqual(llm.calls, 1)
        self.assertEqual(out['scenes'][0]['text_overlays'],
                         [{'text': 'Gravity', 'style': 'lower_third', 't': 0}])
        self.assertEqual(out['scenes'][1]['text_overlays'], [])
        self.assertEqual(len(out['director_warnings']), 2)
        self.assertIn('scene 1: omitted', out['director_warnings'][0])
        validate_sequence(out['scenes'])
        with self.assertRaisesRegex(ValueError, 'invalid text overlay'):
            validate_scene({'shot': 'starfield_warp',
                            'text_overlays': [{'text': 'invalid', 'style': 'invented'}]}, 0)

    def test_bounded_repairs_keep_valid_repeated_visual_as_warned_draft(self):
        class Repeats(FakeLLM):
            def __init__(self): self.calls = 0
            def chat(self, *args, **kwargs):
                self.calls += 1
                return json.dumps({'scenes': [
                    {'shot': 'starfield_warp', 'narration': 'A distant star curves around the horizon.'},
                    {'shot': 'starfield_warp', 'narration': 'Starlight bends around the horizon.'},
                ]})
        llm = Repeats()
        out = generate_script(llm, self.cfg(), topic='black holes', duration=16)
        self.assertEqual(llm.calls, 3)
        self.assertIn('repeats', out['visual_variety_warnings'][0])
        self.assertEqual(out['scenes'][0]['shot'], out['scenes'][1]['shot'])
        self.assertTrue(out['narration_led'])

    def test_failed_variety_repairs_also_drop_bad_optional_overlays(self):
        class BadStoryboard(FakeLLM):
            def __init__(self): self.calls = 0
            def chat(self, *args, **kwargs):
                self.calls += 1
                return json.dumps({'scenes': [
                    {'shot': 'starfield_warp', 'narration': 'Gravity and light circle the horizon.',
                     'text_overlays': [{'text': 'bad', 't': -10}]},
                    {'shot': 'starfield_warp', 'narration': 'Starlight bends around the horizon.'},
                ]})
        llm = BadStoryboard()
        out = generate_script(llm, self.cfg(), topic='black holes', duration=16)
        self.assertEqual(llm.calls, 3)
        self.assertEqual(out['scenes'][0]['text_overlays'], [])
        self.assertTrue(out['director_warnings'])
        self.assertTrue(out['visual_variety_warnings'])

    def test_lenient_variety_never_hides_invalid_later_parameters(self):
        from bot.shot_library import validate_sequence
        scenes = [{'shot': 'starfield_warp'}, {'shot': 'starfield_warp'},
                  {'shot': 'spaghettification', 'params': {'stretch': 999}}]
        with self.assertRaisesRegex(ValueError, 'stretch'):
            validate_sequence(scenes, strict_variety=False)

    def test_director_remains_fail_closed_after_bounded_retries(self):
        class Bad(FakeLLM):
            def __init__(self): self.calls = 0
            def chat(self, *args, **kwargs):
                self.calls += 1
                return '{"scenes":[{"narration":"A","shot":"invented"}]}'
        llm = Bad()
        with self.assertRaisesRegex(ValueError, 'unknown shot'):
            generate_script(llm, self.cfg(), topic='black hole')
        self.assertEqual(llm.calls, 3)

    def test_invalid_director_output_fails(self):
        class Bad(FakeLLM):
            def chat(self,*a,**k): return '{"scenes":[{"narration":"A","shot":"invented"}]}'
        with self.assertRaisesRegex(ValueError,'unknown shot'):
            generate_script(Bad(),self.cfg(),topic='black hole')



class CaptionTests(unittest.TestCase):
    def test_karaoke_groups_do_not_overlap(self):
        from bot.subtitles import words_to_karaoke_ass
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            words=[{'w':w,'s':i*.3,'e':(i+1)*.3} for i,w in enumerate('one two three four five six seven eight'.split())]
            (folder/'s01.json').write_text(json.dumps({'words':words}))
            path=words_to_karaoke_ass([{'id':'s01','start':0,'end':3,'duration':3}], folder,
                                      folder/'out.ass', {}, play_w=1280, play_h=720)
            events=[line for line in path.read_text().splitlines() if line.startswith('Dialogue:')]
            self.assertEqual(len(events),2)
            self.assertEqual(events[0].split(',')[2],'0:00:01.19')
            self.assertEqual(events[1].split(',')[1],'0:00:01.20')

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
            with patch.object(r,'healthcheck',return_value='mocked preflight'), \
                 patch.object(r,'_boot',side_effect=lambda: (setattr(r,'_remote','root@host'),
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

class WindowsSCPTests(unittest.TestCase):
    def test_vast_render_scp_uses_relative_local_names(self):
        import subprocess
        from bot.providers.render_vast import VastRemotionRenderer
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'VAST_API_KEY': 'fake'}):
            cfg = Config({'visual': {'vast': {'api_key_env': 'VAST_API_KEY',
                                             'mode': 'existing', 'instance_id': '1'}}})
            p = Project(Path(temp), 'video').create()
            renderer = VastRemotionRenderer(cfg, p)
            renderer._remote, renderer._port = 'root@host', 12345
            renderer.vast._scp_exe = '/fake/scp.exe'
            source = p.tmp_dir / 'source.tar.gz'
            with patch('bot.providers.render_vast.subprocess.run',
                       return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
                renderer._scp(str(source), 'root@host:/workspace/source.tar.gz')
                self.assertEqual(run.call_args.args[0][-2:], ['source.tar.gz', 'root@host:/workspace/source.tar.gz'])
                self.assertEqual(run.call_args.kwargs['cwd'], str(source.parent))
                dest = p.tmp_dir / 'clip.mp4'
                renderer._scp('root@host:/workspace/clip.mp4', str(dest))
                self.assertEqual(run.call_args.args[0][-2:], ['root@host:/workspace/clip.mp4', 'clip.mp4'])
                self.assertEqual(run.call_args.kwargs['cwd'], str(dest.parent))


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
