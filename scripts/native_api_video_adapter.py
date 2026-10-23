#!/usr/bin/env python3
"""One-shot official MiniMax H3, Wan3 and qualified Seedance HTTP adapters."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from config_contract import ContractError, object_sha256, read_json_object
from video_adapter_common import (download_video, input_image_for_provider, key_color_for_provider,
                                  load_task_and_prompt, write_result)
from video_connections import file_hash, model_spec, validate_execution, validate_selection


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Bearer credentials stay at the pinned regional origin.


class TerminalTaskError(ContractError):
    pass


def api_json(url: str, key: str, *, method: str = 'GET', body: dict | None = None,
             headers: dict | None = None, timeout: float = 30) -> dict:
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if encoded is not None and len(encoded) > 64 * 1024 * 1024:
        raise ContractError('API 请求超过64MiB，未提交')
    req = urllib.request.Request(url, data=encoded, method=method,
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                 'Accept': 'application/json', **(headers or {})})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ContractError('供应商响应过大')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ContractError('供应商响应不是JSON对象')
            return result
    except urllib.error.HTTPError as exc:
        # Error bodies can echo prompts, signed URLs or credentials. Keep only status.
        raise ContractError(f'供应商 HTTP {exc.code}；未自动重试，请检查账号、额度或参数') from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ContractError('供应商网络或JSON响应异常；不会重新提交生成') from None


def origin(spec: dict, workspace_id: str | None = None) -> str:
    platform, region = spec['platform'], spec['region']
    if platform == 'minimax':
        return 'https://api.minimax.cn' if region == 'china' else 'https://api.minimax.io'
    if platform == 'bytedance' and region == 'china':
        return 'https://ark.cn-beijing.volces.com'
    if platform == 'alibaba':
        if not isinstance(workspace_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,62}', workspace_id):
            raise ContractError('Wan 3.0 需要有效 WorkspaceId，不能用任意 base URL 替代')
        location = 'cn-beijing' if region == 'china' else 'ap-southeast-1'
        return f'https://{workspace_id}.{location}.maas.aliyuncs.com'
    raise ContractError('不支持的供应商或地域')


def probe_metadata(spec: dict, key: str, workspace_id: str | None, request=api_json) -> dict:
    platform = spec['platform']
    if platform == 'minimax':
        url = origin(spec) + '/v2/query/video_generation?page_num=1&page_size=1'
    elif platform == 'alibaba':
        base = origin(spec, workspace_id) if spec['region'] == 'china' else 'https://dashscope-intl.aliyuncs.com'
        url = base + '/api/v1/models?model=wan3.0-video'
    else:
        return {'metadata_probe': 'unsupported', 'generation_unverified': True, 'balance': 'unknown'}
    value = request(url, key)
    if value.get('error') or value.get('code') or value.get('success') is False:
        raise ContractError('只读元数据查询失败；不能据此认定视频权限或余额可用')
    valid_shape = isinstance(value.get('items'), list) if platform == 'minimax' else (
        value.get('success') is True and isinstance(value.get('output', {}).get('models'), list))
    if not valid_shape:
        raise ContractError('元数据响应缺少成功证据；账号状态保持未知')
    # Discard all historical tasks/URLs; a successful read proves only metadata access.
    return {'metadata_probe': 'passed', 'generation_unverified': True, 'balance': 'unknown'}


def build_request(task: dict, prompt: dict, selection: dict) -> tuple[str, dict, dict]:
    spec = validate_selection(selection)
    provider_id = spec['provider_id']
    execution = task.get('provider_execution', {}).get(provider_id, {})
    duration = execution.get('duration_seconds', task.get('duration_seconds', 6))
    resolution = execution.get('resolution', spec['default_resolution'])
    if isinstance(duration, bool) or not isinstance(duration, int) or not spec['duration'][0] <= duration <= spec['duration'][1]:
        raise ContractError('时长不符合所选模型范围')
    if resolution not in spec['resolutions']:
        raise ContractError('分辨率不符合所选模型范围')
    image = input_image_for_provider(task, provider_id)
    image_limit = 20 if spec['platform'] == 'alibaba' else 30
    if image.stat().st_size > min(image_limit * 1024 * 1024, task.get('max_input_image_bytes', 25 * 1024 * 1024)):
        raise ContractError('参考图超过所选模型的输入体积限制')
    from PIL import Image
    with Image.open(image) as im:
        width, height = im.size
        mime = Image.MIME.get(im.format)
        if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
            raise ContractError('参考图须为 PNG、JPEG 或 WebP')
        # The workflow prepares an opaque plate; reject a direct alpha upload.
        if 'A' in im.getbands() and im.getchannel('A').getextrema()[0] < 255:
            raise ContractError('先将参考图铺到任务指定的纯色幕布，再提交生成')
        minimum, maximum, ratio = (256, 5760, 2.5) if spec['platform'] == 'minimax' else (240, 8000, 8)
        if min(width, height) < minimum or max(width, height) > maximum or max(width/height, height/width) > ratio:
            raise ContractError('参考图尺寸或比例不符合模型输入范围')
    encoded = f'data:{mime};base64,' + base64.b64encode(image.read_bytes()).decode('ascii')
    text = prompt['grid_video_prompt']
    if task.get('allow_key_background'):
        color = key_color_for_provider(task, provider_id)
        text += f'\nKeep all empty pixels and borders exactly flat {color} in EVERY frame. Fixed camera. No backdrop or checkerboard.'
    base = origin(spec, selection.get('workspace_id'))
    if spec['platform'] == 'minimax':
        if len(text) > 7000:
            raise ContractError('MiniMax H3 提示词超过7000字符')
        return base + '/v2/video_generation', {
            'model': spec['model'], 'content': [{'type': 'text', 'text': text},
                {'type': 'image_url', 'image_url': {'url': encoded}, 'role': 'first_frame'}],
            'duration': duration, 'resolution': resolution.upper(), 'ratio': 'adaptive'}, {}
    if spec['platform'] == 'alibaba':
        return base + '/api/v1/services/aigc/video-generation/video-synthesis', {
            'model': spec['model'], 'input': {'prompt': text, 'media': [{'type': 'first_frame', 'url': encoded}]},
            'parameters': {'duration': duration, 'resolution': resolution.upper(), 'ratio': 'adaptive', 'audio': False}}, {'X-DashScope-Async': 'enable'}
    # For authorized human portraits, the enrolled asset replaces the local photo.
    from video_connections import validate_subject
    validate_subject(task, spec | {'id': provider_id})
    asset = task.get('input_asset_uri')
    role = 'reference_image' if asset else 'first_frame'
    return base + '/api/v3/contents/generations/tasks', {
        'model': spec['model'], 'content': [{'type': 'text', 'text': text},
            {'type': 'image_url', 'image_url': {'url': asset or encoded}, 'role': role}],
        'duration': duration, 'resolution': resolution, 'ratio': 'adaptive', 'generate_audio': False}, {}


def request_id(value: dict, platform: str) -> str:
    candidate = value.get('task_id') if platform == 'minimax' else value.get('output', {}).get('task_id') if platform == 'alibaba' else value.get('id')
    if value.get('error') or value.get('code') or not isinstance(candidate, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', candidate):
        raise ContractError('供应商没有返回有效任务ID；提交结果未知，不自动重试')
    return candidate


def poll_result(value: dict, platform: str) -> tuple[str, str | None]:
    result = value.get('task', {}) if platform == 'minimax' else value.get('output', {}) if platform == 'alibaba' else value
    status = str(result.get('status', result.get('task_status', ''))).lower()
    if status == 'succeeded':
        url = result.get('content', {}).get('url') if platform == 'minimax' else result.get('video_url') if platform == 'alibaba' else result.get('content', {}).get('video_url')
        if not isinstance(url, str) or not url.startswith('https://'):
            raise ContractError('成功任务缺少有效HTTPS视频地址')
        return status, url
    if status in {'failed', 'cancelled', 'canceled', 'unknown', 'expired'}:
        raise TerminalTaskError(f'供应商任务终止：{status}；不会自动再次生成')
    if status not in {'queued', 'pending', 'running'}:
        raise ContractError('未知任务状态；保留任务ID，等待人工检查')
    return status, None


def run(task: dict, prompt: dict, selection: dict, key: str, progress: Path, *,
        resume_id: str | None = None, request=api_json, download=download_video,
        clock=time.monotonic, sleep=time.sleep) -> dict:
    spec = validate_selection(selection)
    url, body, headers = build_request(task, prompt, selection)
    binding = {'provider': spec['provider_id'], 'task_sha256': object_sha256(task),
               'input_sha256': file_hash(input_image_for_provider(task, spec['provider_id']))}
    prior = read_json_object(progress) if progress.exists() else None
    if prior and any(prior.get(k) != v for k, v in binding.items()):
        raise ContractError('远端进度不匹配当前任务，不能恢复或重新提交')
    if prior and not resume_id:
        raise ContractError('已有提交记录；请恢复同一任务，不得再次POST')
    if resume_id and (not prior or prior.get('request_id') != resume_id):
        raise ContractError('恢复ID与持久化任务ID不一致')
    deadline = clock() + task.get('timeout_seconds', 900)
    if resume_id:
        job_id = resume_id
    else:
        # Persist uncertainty before the non-idempotent POST. There is no POST retry.
        write_result(progress, {'version': 1, **binding, 'status': 'submitting'})
        response = request(url, key, method='POST', body=body, headers=headers)
        job_id = request_id(response, spec['platform'])
        write_result(progress, {'version': 1, **binding, 'status': 'submitted', 'request_id': job_id})
    base = origin(spec, selection.get('workspace_id'))
    poll_url = base + ('/v2/query/video_generation/' if spec['platform'] == 'minimax' else '/api/v1/tasks/' if spec['platform'] == 'alibaba' else '/api/v3/contents/generations/tasks/') + quote(job_id, safe='')
    interval = max(1, task.get('poll_interval_ms', 10000) / 1000)
    while clock() < deadline:
        value = request(poll_url, key, timeout=min(30, max(1, deadline - clock())))
        try:
            status, video_url = poll_result(value, spec['platform'])
        except TerminalTaskError:
            write_result(progress, {'version': 1, **binding, 'status': 'failed', 'request_id': job_id})
            raise
        print(f'{spec["provider_id"]}: {status} ({job_id})', file=sys.stderr, flush=True)
        if video_url:
            target = Path(task['output_directory']) / (spec['provider_id'] + '-' + job_id + '.mp4')
            if target.exists():
                raise ContractError('目标视频已存在，不覆盖现有产物')
            output = download(video_url, target, task.get('max_output_bytes', 200 * 1024 * 1024), timeout=min(120, max(1, deadline-clock())))
            write_result(progress, {'version': 1, **binding, 'status': 'succeeded', 'request_id': job_id})
            return {'status': 'succeeded', 'provider': spec['provider_id'], 'model': spec['model'],
                    'output': str(output), 'request_id': job_id, 'has_alpha': False,
                    'duration_seconds': body.get('duration', body.get('parameters', {}).get('duration'))}
        sleep(min(interval, max(0, deadline - clock())))
    raise ContractError('等待任务超时；任务ID已保留，恢复时仅查询原任务')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider-id', required=True)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--progress', type=Path, required=True)
    parser.add_argument('--resume-request-id')
    args = parser.parse_args()
    try:
        task, prompt = load_task_and_prompt(args.task)
        selection = read_json_object(Path(task['connection_file']))
        spec = validate_selection(selection)
        if args.provider_id != spec['provider_id']:
            raise ContractError('适配器与用户所选模型不一致')
        route = json.loads(os.environ.get('MOTION_VIDEO_ROUTE_JSON', '{}'))
        approval = os.environ.get('MOTION_VIDEO_APPROVAL')
        validate_execution(task, spec | {'id': args.provider_id}, route, Path(approval) if approval else None)
        key = os.environ.get(spec['key_env'], '')
        if not key:
            raise ContractError('未配置所选平台的 Key')
        result = run(task, prompt, selection, key, args.progress, resume_id=args.resume_request_id)
        write_result(args.output, result)
        return 0
    except (ContractError, OSError, ValueError, KeyError) as exc:
        progress = read_json_object(args.progress) if args.progress.exists() else {}
        write_result(args.output, {'status': 'failed', 'provider': args.provider_id,
                                  'error': str(exc), 'request_id': progress.get('request_id')})
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
