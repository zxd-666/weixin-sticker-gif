"""Offline contract/lifecycle checks: no provider calls, keychain writes or fees."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from config_contract import ContractError, read_json_object
from configure_video import authorize, select_model, write
from native_api_video_adapter import build_request, origin, poll_result, probe_metadata, run
from video_connections import MODELS, credential, discover, file_hash, model_spec, now, stamp, validate_execution, validate_subject


class VideoConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image.png'
        Image.new('RGB', (480, 480), '#00ff00').save(self.image)
        self.environment = patch.dict(os.environ, {'MINIMAX_API_KEY': 'test-key-not-real',
                                                   'DASHSCOPE_API_KEY': 'test-key-not-real',
                                                   'ARK_API_KEY': 'test-key-not-real'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def fixture(self, name='minimax-h3', region=None, subject='fictional'):
        region = region or MODELS[name]['regions'][0]
        result = select_model(name, region, self.root / name, subject, confirmed=True,
                              workspace_id='workspace-123' if name == 'wan3' else None)
        selection = result['selection']
        provider = next(p for p in read_json_object(Path(result['provider_template']))['providers']
                        if p['id'] == selection['provider_id'])
        task = {'connection_file': result['connection'], 'input_image': str(self.image),
                'output_directory': str(self.root / 'output'), 'subject': {'type': subject},
                'duration_seconds': 6, 'timeout_seconds': 10, 'poll_interval_ms': 1,
                'provider_execution': {provider['id']: {'duration_seconds': 6,
                    'resolution': selection['default_resolution']}}}
        return selection, provider, task, {'selected': provider}

    def approval(self, task, route, **overrides):
        task_file, route_file = self.root / 'task.json', self.root / 'route.json'
        write(task_file, task); write(route_file, route)
        options = dict(included=False, estimated=.5, maximum=1, currency='CNY',
                       price_source='https://official.example/pricing', confirmed=True, confirm_paid=True)
        options.update(overrides)
        output = self.root / 'approval.json'
        authorize(task_file, route_file, output, **options)
        return output

    def test_discovery_never_calls_generation_or_exposes_cached_tokens(self):
        auth = self.root / 'grok'
        auth.mkdir()
        write(auth / 'auth.json', {'account': {'expires_at': (now()+timedelta(hours=1)).isoformat(),
              'access_token': 'do-not-print', 'auth_mode': 'subscription'}})
        with patch.dict(os.environ, {'GROK_HOME': str(auth)}), patch('shutil.which', return_value='/bin/grok'):
            result = discover({'tools': [{'id': 'tool', 'available': True, 'capabilities': ['image-to-video']}]})
        self.assertFalse(result['generation_performed'])
        self.assertEqual(result['tools'][0]['account_status'], 'cached-login')
        self.assertEqual(result['tools'][0]['video_capability'], 'requires-live-confirmation')
        self.assertNotIn('do-not-print', json.dumps(result))
        self.assertNotIn('test-key-not-real', json.dumps(result))

    def test_selection_keeps_grok_and_disables_automatic_paid_fallback(self):
        selection, provider, _, _ = self.fixture('wan3')
        config = read_json_object(self.root / 'wan3' / 'selected-providers.json')
        self.assertEqual(config['routing']['fallback'], 'none')
        self.assertIn('grok-build-local', [p['id'] for p in config['providers']])
        self.assertEqual(provider['model'], 'wan3.0-video')
        self.assertNotIn('test-key-not-real', json.dumps(config))
        self.assertTrue(Path(provider['command'][1]).is_absolute())
        self.assertEqual(selection['workspace_id'], 'workspace-123')

    def test_keychain_access_failure_is_not_reported_as_missing_key(self):
        with patch.dict(os.environ, {'MINIMAX_API_KEY': ''}), \
                patch('video_connections.secure_keyring') as keyring:
            keyring.return_value.get_password.side_effect = RuntimeError('access denied')
            with self.assertRaisesRegex(ContractError, '凭据库当前不可读取'):
                credential('minimax-h3', 'china')
            keyring.return_value.get_password.side_effect = None
            keyring.return_value.get_password.return_value = None
            self.assertIsNone(credential('minimax-h3', 'china'))

    def test_selection_requires_confirmation_and_wan_workspace(self):
        for confirmed, workspace in [(False, 'valid'), (True, None), (True, '../evil')]:
            with self.subTest(confirmed=confirmed, workspace=workspace), self.assertRaises(ContractError):
                select_model('wan3', 'china', self.root/'bad', 'fictional',
                             confirmed=confirmed, workspace_id=workspace)

    def test_official_regional_origins(self):
        self.assertEqual(origin(model_spec('minimax-h3','china')), 'https://api.minimax.cn')
        self.assertEqual(origin(model_spec('minimax-h3','international')), 'https://api.minimax.io')
        self.assertEqual(origin(model_spec('wan3','international'), 'ws'),
                         'https://ws.ap-southeast-1.maas.aliyuncs.com')
        with self.assertRaises(ContractError):
            origin(model_spec('wan3','china'), 'evil.example/path')

    def test_minimax_h3_request_uses_v2_content_and_native_resolution(self):
        selection, _, task, _ = self.fixture()
        url, body, headers = build_request(task, {'grid_video_prompt': 'nod'}, selection)
        self.assertEqual(url, 'https://api.minimax.io/v2/video_generation')
        self.assertEqual(body['model'], 'MiniMax-H3')
        self.assertEqual(body['resolution'], '768P')
        self.assertEqual(body['content'][1]['role'], 'first_frame')
        self.assertTrue(body['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertEqual(headers, {})

    def test_wan3_request_uses_workspace_media_and_async_header(self):
        selection, _, task, _ = self.fixture('wan3','china')
        url, body, headers = build_request(task, {'grid_video_prompt': 'nod'}, selection)
        self.assertTrue(url.startswith('https://workspace-123.cn-beijing.maas.aliyuncs.com/'))
        self.assertEqual(body['input']['media'][0]['type'], 'first_frame')
        self.assertFalse(body['parameters']['audio'])
        self.assertEqual(headers, {'X-DashScope-Async': 'enable'})

    def test_image_mime_and_invalid_dimensions_or_resolution(self):
        selection, provider, task, _ = self.fixture()
        jpeg = self.root / 'image.jpg'; Image.new('RGB',(480,480)).save(jpeg)
        task['input_image'] = str(jpeg)
        self.assertTrue(build_request(task, {'grid_video_prompt':'nod'}, selection)[1]
                        ['content'][1]['image_url']['url'].startswith('data:image/jpeg;'))
        task['provider_execution'][provider['id']]['resolution'] = '720p'
        with self.assertRaises(ContractError): build_request(task, {'grid_video_prompt':'nod'}, selection)
        task['provider_execution'][provider['id']]['resolution'] = '768p'
        Image.new('RGB',(240,240)).save(jpeg)
        with self.assertRaises(ContractError): build_request(task, {'grid_video_prompt':'nod'}, selection)

    def test_fee_gate_binds_task_model_region_and_key(self):
        _, provider, task, route = self.fixture()
        with self.assertRaises(ContractError): validate_execution(task, provider, route, None)
        approval = self.approval(task, route)
        self.assertEqual(validate_execution(task, provider, route, approval)['billing'], 'paid')
        with patch.dict(os.environ, {'MINIMAX_API_KEY': 'changed-key'}), self.assertRaises(ContractError):
            validate_execution(task, provider, route, approval)
        mutated = copy.deepcopy(task); mutated['duration_seconds'] = 9
        with self.assertRaises(ContractError): validate_execution(mutated, provider, route, approval)
        changed_subject = copy.deepcopy(task); changed_subject['subject']['type'] = 'real-person'
        with self.assertRaisesRegex(ContractError, '素材类型'):
            validate_execution(changed_subject, provider, route, approval)
        bad = read_json_object(approval); bad['confirmed_at'] = (now()-timedelta(hours=2)).isoformat()
        write(approval, bad)
        with self.assertRaises(ContractError): validate_execution(task, provider, route, approval)

    def test_fee_gate_rejects_unknown_nonfinite_over_budget_and_api_free_claim(self):
        _, _, task, route = self.fixture()
        for options in [dict(confirm_paid=False), dict(estimated=float('nan')), dict(maximum=float('inf')),
                        dict(estimated=2,maximum=1), dict(price_source=''),
                        dict(included=True,confirm_paid=False)]:
            with self.subTest(options=options), self.assertRaises(ContractError):
                self.approval(task, route, **options)

    def test_grok_included_quota_requires_explicit_confirmation(self):
        _, provider, task, route = self.fixture('grok')
        auth = self.root / 'fake-grok'; auth.mkdir(); write(auth/'auth.json', {'account':'fake'})
        with patch.dict(os.environ, {'GROK_HOME': str(auth)}):
            route['selected']['region'] = None  # Real capability reports carry null for legacy Grok.
            approval = self.approval(task, route, included=True, confirm_paid=False)
            self.assertEqual(validate_execution(task, provider, route, approval)['billing'], 'included-quota')
            write(auth/'auth.json', {'account':'changed'})
            with self.assertRaises(ContractError): validate_execution(task, provider, route, approval)

    def test_seedance_real_person_requires_active_authorized_asset_bound_to_photo_and_account(self):
        selection, provider, task, _ = self.fixture('seedance-2-5', subject='real-person')
        with self.assertRaises(ContractError): validate_subject(task, provider)
        asset = {'uri':'asset://portrait123', 'verified_by_user':True, 'verified_at':stamp(),
                 'asset_status':'Active', 'authorization_status':'accepted',
                 'reference_mode_confirmed': True,
                 'valid_until':(now()+timedelta(hours=1)).isoformat(),
                 'connection_sha256': file_hash(Path(task['connection_file'])),
                 'source_sha256':file_hash(self.image)}
        task['subject']['seedance_asset'] = asset; task['input_asset_uri'] = asset['uri']
        validate_subject(task,provider)
        body = build_request(task,{'grid_video_prompt':'nod'},selection)[1]
        self.assertEqual(body['content'][1]['image_url']['url'],'asset://portrait123')
        self.assertEqual(body['content'][1]['role'],'reference_image')
        self.assertNotIn('base64',json.dumps(body))
        for field, value in [('asset_status','Processing'), ('authorization_status','pending'),
                             ('reference_mode_confirmed', False),
                             ('source_sha256','wrong'), ('connection_sha256','wrong'),
                             ('valid_until',(now()-timedelta(seconds=1)).isoformat())]:
            invalid = copy.deepcopy(task); invalid['subject']['seedance_asset'][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError): validate_subject(invalid,provider)

    def test_seedance_unknown_is_blocked_fictional_allowed(self):
        _, provider, task, _ = self.fixture('seedance-2-0',subject='unknown')
        with self.assertRaises(ContractError): validate_subject(task,provider)
        task['subject']['type']='fictional'; validate_subject(task,provider)

    def test_metadata_read_does_not_claim_generation_or_balance(self):
        requests=[]
        def mock(url,key,**kwargs):
            requests.append((url,kwargs)); return {'success':True,'output':{'models':[]}}
        result=probe_metadata(model_spec('wan3','china'),'fake','ws',mock)
        self.assertTrue(result['generation_unverified']); self.assertEqual(result['balance'],'unknown')
        self.assertEqual(requests[0][1],{}); self.assertIn('/models?',requests[0][0])
        with self.assertRaises(ContractError):
            probe_metadata(model_spec('minimax-h3','china'),'fake',None,lambda *a,**kw:{})

    def test_one_post_then_poll_success_for_minimax_and_wan(self):
        for name in ['minimax-h3','wan3']:
            with self.subTest(name=name):
                selection, _, task, _ = self.fixture(name)
                progress=self.root/(name+'.progress.json'); calls=[]
                def request(url,key,**kwargs):
                    calls.append(kwargs.get('method','GET'))
                    if kwargs.get('method')=='POST':
                        return {'task_id':'job-1'} if name=='minimax-h3' else {'output':{'task_id':'job-1'}}
                    return {'task':{'status':'succeeded','content':{'url':'https://cdn.example/video.mp4'}}} if name=='minimax-h3' else {'output':{'task_status':'SUCCEEDED','video_url':'https://cdn.example/video.mp4'}}
                result=run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=request,
                           download=lambda url,target,limit,**kw:target)
                self.assertEqual(calls,['POST','GET']); self.assertEqual(result['request_id'],'job-1')
                self.assertEqual(read_json_object(progress)['status'],'succeeded')
                with self.assertRaises(ContractError): run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=request)
                self.assertEqual(calls,['POST','GET'])

    def test_timeout_resume_queries_same_id_without_second_post(self):
        selection, _, task, _=self.fixture(); progress=self.root/'progress.json'; calls=[]
        task['timeout_seconds']=2; current=[0.0]
        def request(url,key,**kwargs):
            calls.append(kwargs.get('method','GET'))
            return {'task_id':'job-1'} if kwargs.get('method')=='POST' else {'task':{'status':'running'}}
        with self.assertRaises(ContractError):
            run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=request,
                clock=lambda:current[0],sleep=lambda seconds:current.__setitem__(0,current[0]+seconds))
        def completed(url,key,**kwargs):
            calls.append(kwargs.get('method','GET'))
            return {'task':{'status':'succeeded','content':{'url':'https://cdn.example/result.mp4'}}}
        run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,resume_id='job-1',request=completed,
            download=lambda url,target,limit,**kw:target)
        self.assertEqual(calls.count('POST'),1)

    def test_uncertain_post_is_persisted_and_never_blindly_retried(self):
        selection, _, task, _=self.fixture(); progress=self.root/'progress.json'; calls=[]
        def failure(*args,**kwargs): calls.append(1); raise ContractError('connection lost')
        with self.assertRaises(ContractError): run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=failure)
        self.assertEqual(read_json_object(progress)['status'],'submitting')
        with self.assertRaises(ContractError): run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=failure)
        self.assertEqual(len(calls),1)

    def test_terminal_failure_is_recorded_and_http_url_rejected(self):
        selection, _, task, _=self.fixture(); progress=self.root/'progress.json'
        def failure(url,key,**kw):
            return {'task_id':'job-1'} if kw.get('method')=='POST' else {'task':{'status':'failed'}}
        with self.assertRaises(ContractError): run(task,{'grid_video_prompt':'nod'},selection,'fake',progress,request=failure)
        self.assertEqual(read_json_object(progress)['status'],'failed')
        with self.assertRaises(ContractError): poll_result({'task':{'status':'succeeded','content':{'url':'http://bad'}}},'minimax')

    def test_prepare_accepts_h3_768p_and_wan_30s_with_full_duration_profile(self):
        for name,duration in [('minimax-h3',4),('wan3',30)]:
            selection,_,_,_=self.fixture(name)
            files={'layout':{'detected_layout':{'columns':1,'rows':1,'count':1,'confidence':.99}},
                   'prompts':{'detected_layout':{'columns':1,'rows':1,'count':1},'grid_video_prompt':'nod'},
                   'state':{},'tile-plan':{'tiles':[{'id':'01','motion':'nod'}]}}
            args=[]
            for flag,value in files.items():
                path=self.root/(flag+'.json');write(path,value);args += ['--'+flag,str(path)]
            work=self.root/(name+'-prepared')
            result=subprocess.run([sys.executable,str(ROOT/'scripts/prepare_workflow.py'),
                '--work-dir',str(work),'--image',str(self.image),'--connection',str(self.root/name/'connection.json'),
                '--duration-seconds',str(duration),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            task=read_json_object(work/'video-task.json')
            self.assertEqual(task['provider_chain'],[selection['provider_id']])
            self.assertEqual(task['provider_execution'][selection['provider_id']]['resolution'],selection['default_resolution'])
            self.assertEqual(task['duration_seconds'],duration)

    def test_grok_connection_can_use_an_isolated_leader_without_changing_global_login(self):
        from grok_build_video_adapter import grok_command
        from execute_video_route import child_environment
        _,provider,_,_=self.fixture('grok')
        chosen='/tmp/weixin-isolated-test.sock'
        env=child_environment(provider,{'GROK_LEADER_SOCKET':chosen,'ARK_API_KEY':'not-for-grok'})
        self.assertEqual(env['GROK_LEADER_SOCKET'],chosen)
        self.assertNotIn('ARK_API_KEY',env)
        command=grok_command('/bin/grok','test',self.root,self.root/'grok',env)
        self.assertEqual(command[command.index('--leader-socket')+1],chosen)

    def test_keychain_credentials_are_usable_by_capability_probe_without_env_export(self):
        from probe_video_capabilities import credentials_status
        selection, provider, _, _ = self.fixture()
        with patch.dict(os.environ, {'MINIMAX_API_KEY':''}), patch('video_connections.credential',return_value='keychain-only'):
            self.assertEqual(credentials_status(provider,selection),(True,[]))
            self.assertEqual(credentials_status(provider),(False,['MINIMAX_API_KEY']))

    def test_executor_blocks_before_claim_then_passes_only_selected_key(self):
        from config_contract import object_sha256
        from execute_video_route import execute_attempt
        from manage_job_state import create_state
        from route_video_provider import route
        selection, provider, task, _ = self.fixture()
        layout=self.root/'layout.json'; prompts=self.root/'prompts.json'; state=self.root/'state.json'
        write(layout,{'detected_layout':{'columns':1,'rows':1,'count':1,'confidence':.99}})
        write(prompts,{'detected_layout':{'columns':1,'rows':1,'count':1},'grid_video_prompt':'nod'})
        write(state,create_state(self.image,layout,None,'user-supplied'))
        task.update(version=1,operation='image-to-video',provider=provider['id'],allow_fallback=False,
                    layout_file=str(layout),prompt_file=str(prompts),approval_file=str(state),timeout_seconds=30,
                    poll_interval_ms=100)
        config=read_json_object(self.root/'minimax-h3'/'selected-providers.json')
        capabilities={'version':1,'config_sha256':object_sha256(config),
                      'providers':[dict(provider,available=True)],'local_processing':{}}
        report=route(config,capabilities,task)
        config_path=self.root/'providers.json';task_path=self.root/'task.json';output=self.root/'result.json'
        write(config_path,config);write(task_path,task)
        with patch('execute_video_route.subprocess.run') as network:
            with self.assertRaises(ContractError): execute_attempt(config_path,task_path,report,output,1)
            network.assert_not_called()
        self.assertFalse((self.root/'attempt-ledger.json').exists())
        approval=self.approval(task,report)
        captured=[]
        def completed(command,**kwargs):
            captured.append((command,kwargs['env']))
            raw=Path(task['output_directory']);raw.mkdir();video=raw/'mock.mp4';video.write_bytes(b'offline fixture')
            write(output,{'status':'succeeded','provider':provider['id'],'output':str(video)})
            return subprocess.CompletedProcess(command,0,b'',b'')
        with patch('execute_video_route.subprocess.run',side_effect=completed), patch(
            'execute_video_route.probe_video_alpha',return_value={'has_meaningful_alpha':True}):
            execute_attempt(config_path,task_path,report,output,1,execution_approval_path=approval)
        command,environment=captured[0]
        self.assertIn('--progress',command)
        self.assertEqual(environment['MINIMAX_API_KEY'],'test-key-not-real')
        self.assertNotIn('DASHSCOPE_API_KEY',environment)
        self.assertNotIn('ARK_API_KEY',environment)
        self.assertIn('MOTION_VIDEO_APPROVAL',environment)
        self.assertNotIn('test-key-not-real',output.read_text())

    def test_explicit_retry_archives_progress_but_resume_keeps_original_request(self):
        from attempt_ledger import claim_attempt, finish_attempt, progress_path_for
        report={'version':1,'attempts':[{'attempt':1,'id':'minimax-h3','driver':'command'}]}
        ledger=self.root/'ledger.json';output=self.root/'result.json'
        claim_attempt(ledger,report,1,output)
        progress=progress_path_for(ledger,1)
        write(progress,{'status':'failed','request_id':'previous-task'})
        finish_attempt(ledger,report,1,'failed')
        claim=claim_attempt(ledger,report,1,output,retry_approval_sha256='unique-user-approval')
        self.assertFalse(progress.exists())
        self.assertNotIn('request_id',claim['entry'])
        archives=list(self.root.glob('*.retry-*.json'))
        self.assertEqual(len(archives),1)
        self.assertEqual(read_json_object(archives[0])['request_id'],'previous-task')


if __name__=='__main__': unittest.main()
